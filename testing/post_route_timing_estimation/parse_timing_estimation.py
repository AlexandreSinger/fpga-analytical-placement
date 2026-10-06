#!/usr/bin/env python3
"""
Parse the results of the post-routing timing estimation experiment.

For every circuit in every suite, this compares the post-routing timing
estimate made by the AP flow from a flat placement (the "estimate" task)
against the actual timing after routing that same placement (the "routed"
task), and produces:
    - results/timing_estimation_results.csv: One row per circuit with the
      routed and estimated CPD, sTNS, and wirelength, and the accuracy of
      the estimated path delays and criticalities.
    - results/cpd_tns_wirelength_comparison.png: Estimated vs. routed CPD,
      sTNS, and wirelength.
    - results/path_crit_accuracy.png: The accuracy of the estimated path
      delays and connection criticalities of each circuit.
    - results/circuits/<suite>_<circuit>.png (with --per_circuit_plots):
      Scatter plots of the estimated vs. routed path delays (colored by the
      routed criticality of their endpoint) and connection criticalities of
      each circuit.

The CPD, sTNS, and wirelength are parsed from the VPR logs. The routed
wirelength is the total wirelength of the routing; the estimated wirelength
is the AP flow's post-routing wire usage estimate of the flat placement. Both
are in tiles. The path delays and criticalities are computed from the timing
graph echo files:
    - Routed:    timing_graph.analysis.echo
    - Estimated: timing_graph.ap_post_routing_estimate.echo
Both are over the same atom-level timing graph, so they are compared node by
node. This is verified before comparing.

Path delays are the setup data arrival times at the timing endpoints (SINK
nodes), per clock domain pair. Their accuracy is also reported separately for
critical endpoints (routed criticality > 0.8) and non-critical endpoints, since
the router trades delay for routability on non-critical connections, which the
estimate does not model. Connection criticalities are the setup
criticalities of the sinks of routed connections, computed the same way as VPR
(relaxed criticality). Connections driven by constant generators and
connections to clock pins are not routed through the general routing network
and are not compared.
"""

import argparse
import csv
import math
import os
import re
import sys
import zlib
from array import array
from collections import defaultdict
from multiprocessing import Pool

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # pylint: disable=wrong-import-position
import numpy as np  # pylint: disable=wrong-import-position

# pylint: disable-next=wrong-import-position
from collect_flat_placements import (
    find_circuit_dirs,
    find_run_dir,
    find_suites,
    read_task_config_jobs,
    task_dir,
)

ROUTED_ECHO = "timing_graph.analysis.echo"
ESTIMATE_ECHO = "timing_graph.ap_post_routing_estimate.echo"

NODE_TYPE_CODES = {"SOURCE": 0, "SINK": 1, "IPIN": 2, "OPIN": 3, "CPIN": 4}
SINK = NODE_TYPE_CODES["SINK"]
IPIN = NODE_TYPE_CODES["IPIN"]
CPIN = NODE_TYPE_CODES["CPIN"]

# Connections with a routed criticality above this are considered critical.
CRITICAL_THRESHOLD = 0.8


# ---------------------------------------------------------------------------
# Finding the runs.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Parsing the VPR logs.
# ---------------------------------------------------------------------------


def parse_log_value(log_file, pattern):
    """Return the first float captured by the pattern in the log file, or NaN."""
    if not os.path.isfile(log_file):
        return math.nan
    regex = re.compile(pattern)
    with open(log_file, "r", encoding="utf-8", errors="replace") as log:
        for line in log:
            match = regex.search(line)
            if match:
                return float(match.group(1))
    return math.nan


def parse_routed_log(common_dir):
    """
    Parse the routed CPD and sTNS (in ns) and the routed wirelength (in tiles)
    from the routed task's VPR log.
    """
    log_file = os.path.join(common_dir, "vpr.out")
    return (
        parse_log_value(log_file, r"Final critical path delay \(least slack\): (\S+) ns"),
        parse_log_value(log_file, r"Final setup Total Negative Slack \(sTNS\): (\S+) ns"),
        parse_log_value(log_file, r"Total wirelength: (\d+), average net length"),
    )


def parse_estimate_log(common_dir):
    """
    Parse the estimated CPD and sTNS (in ns) and the estimated wirelength (in
    tiles) from the estimate task's VPR log. The first estimated wirelength in
    the log is the one of the read-in flat placement.
    """
    log_file = os.path.join(common_dir, "vpr.out")
    return (
        parse_log_value(log_file, r"Placement estimated CPD: (\S+) ns"),
        parse_log_value(log_file, r"Placement estimated sTNS: (\S+) ns"),
        parse_log_value(log_file, r"Placement estimated wirelength: (\S+)"),
    )


# ---------------------------------------------------------------------------
# Parsing the timing graph echo files.
# ---------------------------------------------------------------------------


class TimingEcho:  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """The parts of a Tatum timing graph echo file needed for the comparison."""

    def __init__(self):
        # Node id -> node type code (see NODE_TYPE_CODES).
        self.node_types = array("b")
        # Source and sink nodes of the enabled interconnect edges.
        self.interconnect_src = array("i")
        self.interconnect_sink = array("i")
        # Nodes which are constant generators.
        self.constant_generators = set()
        # (SINK node, launch domain, capture domain) -> setup data arrival time.
        self.endpoint_arrival = {}
        # (launch domain, capture domain) -> max required time / worst slack
        # over the timing endpoints (SINK nodes).
        self.max_required = {}
        self.worst_slack = {}
        # Node -> list of ((launch domain, capture domain), setup slack), for
        # SINK and IPIN nodes.
        self.slacks = defaultdict(list)
        # Checksum of the timing graph section, to verify that two echo files
        # are over the same timing graph.
        self.graph_checksum = 0

    def routed_connection_sinks(self):
        """
        Get the sink nodes of the interconnect edges which are routed through
        the general routing network (i.e. not driven by a constant generator
        and not connected to a clock pin).
        """
        sinks = set()
        for src, sink in zip(self.interconnect_src, self.interconnect_sink):
            if src in self.constant_generators or self.node_types[sink] == CPIN:
                continue
            sinks.add(sink)
        return sinks

    def setup_criticality(self, node):
        """
        Compute the setup criticality of the given node, the same way as VPR
        (see calc_relaxed_criticality in vpr/src/timing/timing_util.cpp).
        Returns None if the node has no slacks.
        """
        crit = None
        for domain_pair, slack in self.slacks.get(node, ()):
            if domain_pair not in self.max_required or domain_pair not in self.worst_slack:
                continue
            req = self.max_required[domain_pair]
            if self.worst_slack[domain_pair] < 0:
                shift = -self.worst_slack[domain_pair]
                slack += shift
                req += shift
            if req > 0:
                tag_crit = 1.0 - slack / req
            elif req == 0 and slack == 0:
                tag_crit = 1.0
            else:
                continue
            tag_crit = min(1.0, max(0.0, tag_crit))
            crit = tag_crit if crit is None else max(crit, tag_crit)
        return crit


def _parse_timing_graph_line(echo, line, edge):
    """Parse a line of the timing_graph section. edge holds the current edge record."""
    stripped = line.strip()
    if stripped.startswith("node:"):
        edge["kind"] = "node"
    elif stripped.startswith("edge:"):
        edge["kind"] = "edge"
    elif stripped.startswith("type:"):
        value = stripped.split()[1]
        if edge["kind"] == "node":
            echo.node_types.append(NODE_TYPE_CODES.get(value, -1))
        else:
            edge["type"] = value
    elif stripped.startswith("src_node:"):
        edge["src"] = int(stripped.split()[1])
    elif stripped.startswith("sink_node:"):
        edge["sink"] = int(stripped.split()[1])
    elif stripped.startswith("disabled:"):
        if edge["type"] == "INTERCONNECT" and stripped.split()[1] == "false":
            echo.interconnect_src.append(edge["src"])
            echo.interconnect_sink.append(edge["sink"])


def _parse_analysis_result_line(echo, line):
    """Parse a setup tag or slack line of the analysis_result section."""
    tokens = line.split()
    # Format: type: <type> node: <id> launch_domain: <id> capture_domain: <id> time|slack: <value>
    if len(tokens) < 10 or tokens[2] != "node:" or not tokens[1].startswith("SETUP"):
        return
    tag_type = tokens[1]
    node = int(tokens[3])
    value = float(tokens[9])
    if not math.isfinite(value):
        # Skip tags which do not correspond to timing paths (e.g. the tags
        # of constant generators have infinite arrival times).
        return
    node_type = echo.node_types[node]
    domain_pair = (int(tokens[5]), int(tokens[7]))
    if tag_type == "SETUP_DATA_ARRIVAL":
        if node_type == SINK:
            echo.endpoint_arrival[(node, domain_pair[0], domain_pair[1])] = value
    elif tag_type == "SETUP_DATA_REQUIRED":
        if node_type == SINK:
            echo.max_required[domain_pair] = max(
                echo.max_required.get(domain_pair, -math.inf), value
            )
    elif tag_type == "SETUP_SLACK":
        if node_type == SINK:
            echo.worst_slack[domain_pair] = min(echo.worst_slack.get(domain_pair, math.inf), value)
        if node_type in (SINK, IPIN):
            echo.slacks[node].append((domain_pair, value))


def parse_timing_echo(filename):
    """Parse the parts of a timing graph echo file needed for the comparison."""
    echo = TimingEcho()
    section = None
    edge = {"kind": None, "type": None, "src": -1, "sink": -1}
    with open(filename, "r", encoding="utf-8") as echo_file:
        for line in echo_file:
            # Section headers are not indented.
            if not line.startswith(" "):
                if line.strip():
                    section = line.strip().rstrip(":")
                continue
            if section == "timing_graph":
                echo.graph_checksum = zlib.crc32(line.encode(), echo.graph_checksum)
                _parse_timing_graph_line(echo, line, edge)
            elif section == "timing_constraints":
                if "CONSTANT_GENERATOR" in line:
                    echo.constant_generators.add(int(line.split("node:")[1].split()[0]))
            elif section == "analysis_result":
                _parse_analysis_result_line(echo, line)
    return echo


# ---------------------------------------------------------------------------
# Comparing a circuit.
# ---------------------------------------------------------------------------


def pair_stats(pairs, prefix):
    """Accuracy statistics of (routed, estimated) pairs."""
    stats = {f"{prefix}_count": len(pairs)}
    if len(pairs) == 0:
        return stats
    routed, estimated = pairs[:, 0], pairs[:, 1]
    stats[f"{prefix}_pearson_r"] = (
        float(np.corrcoef(routed, estimated)[0, 1]) if len(pairs) > 1 else math.nan
    )
    stats[f"{prefix}_mean_abs_error"] = float(np.mean(np.abs(estimated - routed)))
    nonzero = routed > 0
    if np.any(nonzero):
        ratio = estimated[nonzero] / routed[nonzero]
        stats[f"{prefix}_median_ratio"] = float(np.median(ratio))
        stats[f"{prefix}_mean_abs_pct_error"] = float(np.mean(np.abs(ratio - 1.0)) * 100.0)
    return stats


def endpoint_path_pairs(routed, estimated):
    """
    Get the (routed, estimated) path delays of the timing endpoints: the setup
    arrival times at the SINK nodes (in ns), per clock domain pair. Also get
    the routed criticality of the endpoint of each pair, which is 0 for
    endpoints without a criticality.
    """
    endpoint_crits = {}
    path_pairs = []
    path_crits = []
    for key, arrival in routed.endpoint_arrival.items():
        if key not in estimated.endpoint_arrival:
            continue
        node = key[0]
        if node not in endpoint_crits:
            endpoint_crits[node] = routed.setup_criticality(node) or 0.0
        path_pairs.append((arrival * 1e9, estimated.endpoint_arrival[key] * 1e9))
        path_crits.append(endpoint_crits[node])
    return np.array(path_pairs).reshape(-1, 2), np.array(path_crits)


def compare_circuit(job):
    """
    Compare the routed and estimated timing of one circuit. Returns the row
    of results, and if they are needed for per-circuit plots, the (routed,
    estimated) path delay pairs, the routed criticality of the endpoint of
    each path delay pair, and the (routed, estimated) criticality pairs.
    """
    suite, arch, circuit, routed_dir, estimate_dir, keep_pairs = job
    row = {"suite": suite, "arch": arch, "circuit": os.path.splitext(circuit)[0]}
    row["routed_cpd_ns"], row["routed_stns_ns"], row["routed_wirelength"] = parse_routed_log(
        routed_dir
    )
    row["estimated_cpd_ns"], row["estimated_stns_ns"], row["estimated_wirelength"] = (
        parse_estimate_log(estimate_dir)
    )

    routed_echo_file = os.path.join(routed_dir, ROUTED_ECHO)
    estimate_echo_file = os.path.join(estimate_dir, ESTIMATE_ECHO)
    if not os.path.isfile(routed_echo_file) or not os.path.isfile(estimate_echo_file):
        row["error"] = "missing echo file"
        return row, None

    routed = parse_timing_echo(routed_echo_file)
    estimated = parse_timing_echo(estimate_echo_file)
    if (
        routed.graph_checksum != estimated.graph_checksum
        or routed.node_types != estimated.node_types
    ):
        row["error"] = "timing graphs do not match"
        return row, None

    path_pairs, path_crits = endpoint_path_pairs(routed, estimated)
    path_is_critical = path_crits > CRITICAL_THRESHOLD

    # Criticalities of the sinks of routed connections.
    crit_pairs = []
    for node in sorted(routed.routed_connection_sinks()):
        routed_crit = routed.setup_criticality(node)
        estimated_crit = estimated.setup_criticality(node)
        if routed_crit is not None and estimated_crit is not None:
            crit_pairs.append((routed_crit, estimated_crit))
    crit_pairs = np.array(crit_pairs).reshape(-1, 2)

    row.update(pair_stats(path_pairs, "path"))
    row.update(pair_stats(path_pairs[path_is_critical], "path_critical"))
    row.update(pair_stats(path_pairs[~path_is_critical], "path_noncritical"))
    row.update(pair_stats(crit_pairs, "crit"))
    critical = crit_pairs[crit_pairs[:, 0] > CRITICAL_THRESHOLD] if len(crit_pairs) else crit_pairs
    row["crit_critical_count"] = len(critical)
    if len(critical) > 0:
        row["crit_critical_mean_abs_error"] = float(
            np.mean(np.abs(critical[:, 1] - critical[:, 0]))
        )

    if keep_pairs:
        return row, (path_pairs, path_crits, crit_pairs)
    return row, None


# ---------------------------------------------------------------------------
# Output.
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "suite",
    "arch",
    "circuit",
    "routed_cpd_ns",
    "estimated_cpd_ns",
    "routed_stns_ns",
    "estimated_stns_ns",
    "routed_wirelength",
    "estimated_wirelength",
    "path_count",
    "path_pearson_r",
    "path_median_ratio",
    "path_mean_abs_pct_error",
    "path_mean_abs_error",
    "path_critical_count",
    "path_critical_median_ratio",
    "path_critical_mean_abs_pct_error",
    "path_noncritical_count",
    "path_noncritical_median_ratio",
    "path_noncritical_mean_abs_pct_error",
    "crit_count",
    "crit_pearson_r",
    "crit_mean_abs_error",
    "crit_critical_count",
    "crit_critical_mean_abs_error",
    "error",
]


def write_csv(rows, filename):
    """Write the results of every circuit to a CSV file."""
    with open(filename, "w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _finite(value):
    return value is not None and isinstance(value, float) and math.isfinite(value)


def _geomean(values):
    values = [v for v in values if _finite(v) and v > 0]
    return math.exp(sum(math.log(v) for v in values) / len(values)) if values else math.nan


def _ratio(row, estimated_key, routed_key):
    """The estimated / routed ratio of a value of a row, or NaN if it cannot be computed."""
    estimated, routed = row.get(estimated_key), row.get(routed_key)
    if not _finite(estimated) or not _finite(routed) or routed == 0:
        return math.nan
    return estimated / routed


def print_summary(rows):
    """Print a table of the results and the geomean of the estimate ratios per suite."""
    print(
        f"{'suite':<12} {'circuit':<26} {'CPD r/e (ns)':>17} {'sTNS r/e (ns)':>25} {'WL e/r':>7} "
        f"{'path r':>7} {'path med':>8} {'crit med':>8} {'ncrit med':>9} {'path %err':>9} "
        f"{'crit r':>7} {'crit MAE':>8}"
    )

    def fmt(value, spec):
        return format(value, spec) if _finite(value) else "-"

    for row in rows:
        print(
            f"{row['suite']:<12} {row['circuit']:<26} "
            f"{fmt(row['routed_cpd_ns'], '8.3f')}/{fmt(row['estimated_cpd_ns'], '<8.3f')} "
            f"{fmt(row['routed_stns_ns'], '12.1f')}/{fmt(row['estimated_stns_ns'], '<12.1f')} "
            f"{fmt(_ratio(row, 'estimated_wirelength', 'routed_wirelength'), '7.3f')} "
            f"{fmt(row.get('path_pearson_r'), '7.3f')} {fmt(row.get('path_median_ratio'), '8.3f')} "
            f"{fmt(row.get('path_critical_median_ratio'), '8.3f')} "
            f"{fmt(row.get('path_noncritical_median_ratio'), '9.3f')} "
            f"{fmt(row.get('path_mean_abs_pct_error'), '9.1f')} "
            f"{fmt(row.get('crit_pearson_r'), '7.3f')} {fmt(row.get('crit_mean_abs_error'), '8.4f')}"
            + (f"  ERROR: {row['error']}" if row.get("error") else "")
        )

    print("\nGeomean of estimated / routed:")
    for suite in sorted({row["suite"] for row in rows}):
        suite_rows = [row for row in rows if row["suite"] == suite]
        cpd = _geomean([_ratio(r, "estimated_cpd_ns", "routed_cpd_ns") for r in suite_rows])
        tns = _geomean([_ratio(r, "estimated_stns_ns", "routed_stns_ns") for r in suite_rows])
        wl = _geomean([_ratio(r, "estimated_wirelength", "routed_wirelength") for r in suite_rows])
        print(f"\t{suite:<12} CPD: {cpd:.3f}  sTNS: {tns:.3f}  Wirelength: {wl:.3f}")


def _suite_colors(rows):
    suites = sorted({row["suite"] for row in rows})
    palette = ["#2a6fdb", "#e8743b", "#19a979", "#945ecf", "#ed4a7b"]
    return {suite: palette[i % len(palette)] for i, suite in enumerate(suites)}


def _scatter_with_labels(ax, rows, colors, routed_key, estimated_key, negate):
    """Log-log scatter of estimated vs. routed values, one point per circuit."""
    all_values = []
    for suite, color in colors.items():
        xs, ys, labels = [], [], []
        for row in rows:
            routed, estimated = row[routed_key], row[estimated_key]
            if row["suite"] != suite or not _finite(routed) or not _finite(estimated):
                continue
            if negate:
                routed, estimated = -routed, -estimated
            if routed <= 0 or estimated <= 0:
                continue
            xs.append(routed)
            ys.append(estimated)
            labels.append(row["circuit"])
        ax.scatter(xs, ys, s=25, color=color, label=suite, zorder=3)
        for x, y, label in zip(xs, ys, labels):
            ax.annotate(label, (x, y), fontsize=6, xytext=(3, 3), textcoords="offset points")
        all_values += xs + ys
    if all_values:
        lo, hi = min(all_values) / 1.3, max(all_values) * 1.3
        ax.plot([lo, hi], [lo, hi], color="#555555", linewidth=1, linestyle="--", label="y = x")
        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_aspect("equal")
    ax.grid(True, which="both", linewidth=0.3)
    ax.legend(fontsize=8)


def plot_cpd_tns_wirelength(rows, filename):
    """Plot the estimated vs. routed CPD, sTNS, and wirelength of every circuit."""
    colors = _suite_colors(rows)
    fig, axes = plt.subplots(1, 3, figsize=(19.5, 6.5))
    _scatter_with_labels(axes[0], rows, colors, "routed_cpd_ns", "estimated_cpd_ns", negate=False)
    axes[0].set_xlabel("Routed CPD (ns)")
    axes[0].set_ylabel("Estimated CPD (ns)")
    axes[0].set_title("Critical Path Delay")
    _scatter_with_labels(axes[1], rows, colors, "routed_stns_ns", "estimated_stns_ns", negate=True)
    axes[1].set_xlabel("Routed -sTNS (ns)")
    axes[1].set_ylabel("Estimated -sTNS (ns)")
    axes[1].set_title("Setup Total Negative Slack")
    _scatter_with_labels(
        axes[2], rows, colors, "routed_wirelength", "estimated_wirelength", negate=False
    )
    axes[2].set_xlabel("Routed wirelength (tiles)")
    axes[2].set_ylabel("Estimated wirelength (tiles)")
    axes[2].set_title("Wirelength")
    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    plt.close(fig)


def plot_accuracy(rows, filename):
    """Bar charts of the path delay and criticality accuracy of every circuit."""
    colors = _suite_colors(rows)
    rows = [row for row in rows if not row.get("error")]
    if not rows:
        return
    labels = [row["circuit"] for row in rows]
    bar_colors = [colors[row["suite"]] for row in rows]
    panels = [
        ("path_median_ratio", "Path delay: median estimated / routed", 1.0),
        ("path_mean_abs_pct_error", "Path delay: mean abs. % error", None),
        (
            "path_critical_median_ratio",
            f"Path delay (critical endpoints, routed crit > {CRITICAL_THRESHOLD}): "
            "median estimated / routed",
            1.0,
        ),
        (
            "path_noncritical_median_ratio",
            f"Path delay (non-critical endpoints, routed crit <= {CRITICAL_THRESHOLD}): "
            "median estimated / routed",
            1.0,
        ),
        ("crit_mean_abs_error", "Criticality: mean abs. error (all connections)", None),
        (
            "crit_critical_mean_abs_error",
            f"Criticality: mean abs. error (routed crit > {CRITICAL_THRESHOLD})",
            None,
        ),
    ]
    fig, axes = plt.subplots(
        len(panels), 1, figsize=(max(8, 0.35 * len(rows) + 2), 3 * len(panels))
    )
    for ax, (key, title, reference) in zip(axes, panels):
        values = [row.get(key, math.nan) for row in rows]
        values = [v if _finite(v) else 0.0 for v in values]
        ax.bar(range(len(rows)), values, color=bar_colors)
        if reference is not None:
            ax.axhline(reference, color="#555555", linewidth=1, linestyle="--")
            lo = min(values + [reference])
            ax.set_ylim(min(0.8, lo * 0.98), max(values + [reference]) * 1.02)
        ax.set_title(title, fontsize=10)
        ax.set_xticks(range(len(rows)))
        ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=7)
        ax.grid(True, axis="y", linewidth=0.3)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in colors.values()]
    axes[0].legend(handles, list(colors.keys()), fontsize=8)
    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    plt.close(fig)


def _plot_identity_axes(ax, pairs, title, unit):
    """Draw the y = x line and set up square axes covering the given pairs."""
    lo = min(0.0, float(pairs.min()))
    hi = float(pairs.max()) * 1.05
    ax.plot([lo, hi], [lo, hi], color="#555555", linewidth=1, linestyle="--")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal")
    ax.set_xlabel(f"Routed{unit}")
    ax.set_ylabel(f"Estimated{unit}")
    ax.set_title(title)
    ax.grid(True, linewidth=0.3)


def plot_circuit(row, path_pairs, path_crits, crit_pairs, filename):
    """
    Scatter plots of the estimated vs. routed path delays and criticalities of
    a circuit. The path delays are colored by the routed criticality of their
    endpoint, with the most critical drawn on top.
    """
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    name = f"{row['suite']} / {row['circuit']}"
    if len(path_pairs) > 0:
        order = np.argsort(path_crits, kind="stable")
        points = axes[0].scatter(
            path_pairs[order, 0],
            path_pairs[order, 1],
            c=path_crits[order],
            cmap="viridis",
            vmin=0.0,
            vmax=1.0,
            s=3,
            alpha=0.5,
            linewidths=0,
            rasterized=True,
        )
        fig.colorbar(
            points, ax=axes[0], fraction=0.046, pad=0.04, label="Routed endpoint criticality"
        )
        _plot_identity_axes(axes[0], path_pairs, f"{name}: Endpoint path delay", " (ns)")
    if len(crit_pairs) > 0:
        axes[1].scatter(
            crit_pairs[:, 0], crit_pairs[:, 1], s=3, alpha=0.25, linewidths=0, rasterized=True
        )
        _plot_identity_axes(axes[1], crit_pairs, f"{name}: Connection criticality", "")
    fig.tight_layout()
    fig.savefig(filename, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------


def collect_jobs(base_dir, suites, args):
    """Find the routed and estimate run directories of every circuit."""
    jobs = []
    for suite in suites:
        routed_task_dir = task_dir(base_dir, suite, "routed")
        estimate_task_dir = task_dir(base_dir, suite, "estimate")
        routed_run = find_run_dir(routed_task_dir, args.routed_run)
        estimate_run = find_run_dir(estimate_task_dir, args.estimate_run)
        if routed_run is None or estimate_run is None:
            print(f"{suite}: skipping, missing a run of the routed or estimate task")
            continue
        print(f"{suite}: routed {routed_run}, estimate {estimate_run}")
        # Only the circuits in the tasks' configs are parsed; any other
        # directories in the runs are ignored.
        config_jobs = read_task_config_jobs(routed_task_dir) | read_task_config_jobs(
            estimate_task_dir
        )
        routed_dirs = find_circuit_dirs(routed_run, config_jobs)
        estimate_dirs = find_circuit_dirs(estimate_run, config_jobs)
        for key in sorted(config_jobs):
            if routed_dirs[key] is None or estimate_dirs[key] is None:
                print(f"\tskipping {key[1]}: not in both runs")
                continue
            jobs.append(
                (
                    suite,
                    key[0],
                    key[1],
                    routed_dirs[key],
                    estimate_dirs[key],
                    args.per_circuit_plots,
                )
            )
    return jobs


def main():
    """Main entry point."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(
        description="Parse the results of the post-routing timing estimation experiment."
    )
    parser.add_argument("--suites", nargs="+", default=None, help="Suites to parse (default: all).")
    parser.add_argument(
        "--routed_run", default=None, help="Run of the routed tasks (default: latest)."
    )
    parser.add_argument(
        "--estimate_run", default=None, help="Run of the estimate tasks (default: latest)."
    )
    parser.add_argument(
        "--output_dir",
        default=os.path.join(base_dir, "results"),
        help="Directory to write the results to (default: results).",
    )
    parser.add_argument(
        "--per_circuit_plots",
        action="store_true",
        help="Also write scatter plots of the path delays and criticalities of each circuit.",
    )
    parser.add_argument(
        "-j",
        type=int,
        default=1,
        help="Number of circuits to parse in parallel. Parsing a large circuit's "
        "echo files can use several GB of memory (default: 1).",
    )
    args = parser.parse_args()

    suites = args.suites if args.suites is not None else find_suites(base_dir)
    jobs = collect_jobs(base_dir, suites, args)
    if not jobs:
        sys.exit("No circuits to parse.")

    os.makedirs(args.output_dir, exist_ok=True)
    if args.per_circuit_plots:
        os.makedirs(os.path.join(args.output_dir, "circuits"), exist_ok=True)

    rows = []
    with Pool(max(1, args.j)) as pool:
        for row, circuit_data in pool.imap(compare_circuit, jobs):
            print(f"\tparsed {row['suite']} / {row['circuit']}", flush=True)
            rows.append(row)
            if args.per_circuit_plots and circuit_data is not None:
                plot_circuit(
                    row,
                    *circuit_data,
                    os.path.join(
                        args.output_dir, "circuits", f"{row['suite']}_{row['circuit']}.png"
                    ),
                )

    print()
    print_summary(rows)
    write_csv(rows, os.path.join(args.output_dir, "timing_estimation_results.csv"))
    plot_cpd_tns_wirelength(
        rows, os.path.join(args.output_dir, "cpd_tns_wirelength_comparison.png")
    )
    plot_accuracy(rows, os.path.join(args.output_dir, "path_crit_accuracy.png"))
    print(f"\nResults written to {args.output_dir}")


if __name__ == "__main__":
    main()

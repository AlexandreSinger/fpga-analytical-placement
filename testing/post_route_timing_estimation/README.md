# Post-Routing Timing Estimation

Measures how accurately the AP flow's post-routing timing estimate (made from
a flat placement) predicts the timing of the design after routing.

For every circuit, the final flat placement of a full AP run (after detailed
placement) is read back into the AP flow, which estimates the post-routing
timing of that exact placement. The estimate is compared against the timing of
the routed design.

## Suites

Each suite contains two tasks over the same circuits, devices and channel
widths:

- `<suite>/<suite>_routed`: Runs the AP flow, routes, and analyzes the design. Writes
  the final flat placement (`final.fplace`), the routed timing graph
  (`timing_graph.analysis.echo`), and the routed wire usage of each net
  (`wire_usage.routed.echo`).
- `<suite>/<suite>_estimate`: Reads in the final flat placement of the routed task
  (global placement is skipped) and writes the estimated timing graph
  (`timing_graph.ap_post_routing_estimate.echo`) and the estimated wire usage
  of each net (`wire_usage.ap_post_routing_estimate.echo`). The estimated CPD and sTNS
  are printed in the VPR log ("Placement estimated CPD/sTNS"), along with the
  estimated wirelength ("Placement estimated wirelength").

NOTE: Every task must have a unique directory name. `run_vtr_task.py` names a
task after its directory (not its path), and when several tasks with the same
name are run together their run directories collide (e.g. the jobs and parse
results of one task are written into the run directory of the other).

| Suite         | Circuits                                         |
|---------------|--------------------------------------------------|
| `mcnc`        | The 20 MCNC circuits (`k6_frac_N10_40nm.xml`, fixed `mcnc_small/medium/large` devices) |
| `vtr_largest` | The 8 largest VTR circuits (same as `vtr_largest_ap`) |
| `koios`       | The Koios circuits (same as `koios_ap`)          |
| `titan_quick` | The Titan circuits of the `ap_titan` regression test (titan_quick, without gaussianblur) |

The `mcnc` suite is small enough to run on a local machine in a few minutes.
It is meant for quickly testing the experiment (e.g. after changing VPR or
these scripts), not for measuring the accuracy of the estimate, since the
circuits are very small.

The `titan_quick` tasks use the same device widths and router options as the
`ap_titan` regression test (`vtr_reg_nightly_test7`), but with timing analysis
turned on (that test is wirelength driven). The Titan benchmarks must be
downloaded into the VTR tree (`make get_titan_benchmarks`).

Only the needed timing graph and wire usage echo files are written (using
`--echo_files`), since `--echo_file on` writes many very large files.

NOTE: This requires a VPR build with the `--echo_files` option, the AP
post-routing timing estimate, and the wire usage echo files.

## Running

All commands are run from this directory.

1. Run the routed tasks:
   ```sh
   source VTR_PATH/.venv/bin/activate
   VTR_PATH/vtr_flow/scripts/run_vtr_task.py -l routed_task_list.txt -j <N>
   ```

2. Copy the final flat placements of the latest routed runs into the estimate
   tasks (`<suite>/<suite>_estimate/flat_placements/<circuit>.fplace`):
   ```sh
   ./collect_flat_placements.py
   ```

3. Run the estimate tasks:
   ```sh
   VTR_PATH/vtr_flow/scripts/run_vtr_task.py -l estimate_task_list.txt -j <N>
   ```

4. Parse the results:
   ```sh
   ./parse_timing_estimation.py [--per_circuit_plots] [-j <N>]
   ```

By default the latest runs of each task are used; use `--run` (collection) or
`--routed_run` / `--estimate_run` (parsing) to select specific runs.

### Running a single suite

Each suite can be run on its own. Pass the task directly to `run_vtr_task.py`
(instead of a task list) and use `--suites` with the scripts. For example, to
run only `mcnc` (a quick local test):

```sh
VTR_PATH/vtr_flow/scripts/run_vtr_task.py mcnc/mcnc_routed -j <N>
./collect_flat_placements.py --suites mcnc
VTR_PATH/vtr_flow/scripts/run_vtr_task.py mcnc/mcnc_estimate -j <N>
./parse_timing_estimation.py --suites mcnc --per_circuit_plots
```

`--suites` takes one or more suite names. Without it, the scripts process every
suite; when parsing, suites without a run of both tasks are skipped.

Only the architectures and circuits listed in a task's config are collected and
parsed; any other directories in its run directories are ignored.

## Results

`parse_timing_estimation.py` writes to `results/`:

- `timing_estimation_results.csv`: One row per circuit, with:
  - The routed and estimated CPD and sTNS.
  - The routed wirelength ("Total wirelength" after routing) and the estimated
    post-routing wire usage of the flat placement, both in tiles.
  - Path delay accuracy: the setup arrival time at every timing endpoint, per
    clock domain pair (Pearson r, median estimated / routed, mean absolute %
    error). The median ratio and % error are also reported separately for
    critical endpoints (routed criticality > 0.8) and non-critical endpoints.
  - Criticality accuracy: the setup criticality of the sink of every routed
    connection, computed the same way as VPR (Pearson r, mean absolute error
    over all connections and over the critical connections, i.e. routed
    criticality > 0.8).
  - Per-net wire usage accuracy, over the nets which are both estimated and
    routed (`wl_net_*`: Pearson r, median estimated / routed, mean absolute %
    error). The median error is also split into two factors:
    - `wl_net_bb_median_ratio`: estimated tile HPWL / placed tile HPWL. The
      error of the flat placement's bounding box (e.g. blocks moving during
      legalization, or blocks in large tiles).
    - `wl_net_crossing_median_ratio`: placed tile HPWL * crossing / routed
      wire usage. The error of the crossing count (routing detours).
  - The number of nets and the wire usage of each category of net: `matched`
    (estimated and routed), `spurious` (estimated, but absorbed by clustering),
    `missed_absorbed` (estimated as absorbed into a tile, but routed), and
    `missed_other` (routed, but not estimated for another reason, e.g.
    estimated as global).
- `cpd_tns_wirelength_comparison.png`: Estimated vs. routed CPD, sTNS, and
  wirelength of every circuit.
- `path_crit_accuracy.png`: The path delay, criticality, and per-net wire
  usage accuracy of every circuit.
- `circuits/timing/<suite>_<circuit>.png` (with `--per_circuit_plots`): Scatter plots
  of the estimated vs. routed path delays and criticalities of each circuit.
  The path delays are colored by the routed criticality of their endpoint, with
  the most critical endpoints drawn on top.
- `circuits/wire_usage/<suite>_<circuit>.png` (with `--per_circuit_plots`):
  Per-net plots of the estimated vs. routed wire usage (colored by the number
  of placed tiles the net connects, with the totals of each category of net),
  the estimated / routed ratio vs. the number of placed tiles, the estimated vs.
  placed tile HPWL (bounding box error), and the placed HPWL * crossing /
  routed ratio vs. the number of placed tiles (crossing count error).

The nets of the two wire usage echo files are joined by name (AP nets and
clustered nets are both named after their atom net). The wire usage is
compared even when the timing echo files are missing.

A summary table and the geomean of the estimated / routed CPD, sTNS, and
wirelength of each suite are also printed.

Connections driven by constant generators and connections to clock pins are not
routed through the general routing network, so they are not compared.

NOTE: Parsing the echo files of a large circuit can use several GB of memory
(about 150 MB for stereovision2, and about 3 GB for the largest Koios
circuits). The Titan circuits are larger still, so parse `titan_quick` with a
low `-j`.

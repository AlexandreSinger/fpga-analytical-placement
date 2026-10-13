# Legality Estimation

Runs the global placer of the AP flow on its own (`--global_place`) and reports
the legality estimate of the global placement, to debug and evaluate the
legality estimator (`vpr/src/analytical_place/common/gp_solution_legality_estimation.cpp`,
see `notes/legality-estimation`).

The flat placements used by `post_route_timing_estimation` are legal, so they
only show that the estimator does not report false positives. Global placements
are not legal, so they test whether the estimator finds the violations, which
rules they are charged to, and which tiles they are in.

## Suites

Each suite contains two tasks over the same circuits, devices and router
options:

- `<suite>/<suite>_gp`: Runs only global placement (`--global_place`). The
  legality estimate of the global placement is printed in the VPR log
  ("Legality Estimate Summary"), along with the post-global placement
  wirelength / CPD / sTNS estimates. The per-tile penalty and tile pin demand
  are written to `legality.ap_estimate.echo`, and the global placement is
  written to `gp.fplace` (`--write_post_gp_flat_place`).
- `<suite>/<suite>_reestimate`: Reads in the global placement written by the gp
  task (`--global_place --read_flat_place`), which skips the global placer and
  only estimates the legality of the placement. This is useful for quickly
  testing changes to the legality estimator on the same global placements,
  without re-running global placement (which takes a long time on the larger
  suites).

NOTE: Every task must have a unique directory name. `run_vtr_task.py` names a
task after its directory (not its path), and when several tasks with the same
name are run together their run directories collide.

| Suite         | Circuits                                         |
|---------------|--------------------------------------------------|
| `mcnc`        | The 20 MCNC circuits (`k6_frac_N10_40nm.xml`, fixed `mcnc_small/medium/large` devices) |
| `vtr_largest` | The 8 largest VTR circuits (same as `vtr_largest_ap`) |
| `koios`       | The Koios circuits (same as `koios_ap`)          |
| `titan_quick` | The Titan circuits of the `ap_titan` regression test (titan_quick, without gaussianblur) |
| `titanium_quick` | The Titanium circuits of the `titanium_s10_quick_qor` regression test (16 circuits which run in under around 2 hours), on their Stratix 10 devices from the `titanium_s10_ap` test suite |
| `artix_7`     | The 8 VTR circuits of the `artix_7_ap` test suite (`7series_BRAM_DSP_carry.xml`, fixed Artix-7-like devices, channel width 190) |

The circuits, devices, channel widths and router options are the same as the
`post_route_timing_estimation` suites. The router options matter even though
nothing is routed: the timing-driven global placer uses a place delay model
built from the router lookahead.

The `mcnc` suite is small enough to run on a local machine in a few minutes. It
is meant for quickly testing the experiment, not for drawing conclusions about
the legality estimator. The Titan and Titanium benchmarks must be downloaded into
the VTR tree (`make get_titan_benchmarks`). The Artix-7 circuits are read from
`/shared/singera8/7series_blifs` (the same as the `artix_7_ap` test suite).

NOTE: This requires a VPR build with:
- `--global_place` and `--write_post_gp_flat_place` (VTR PR #3899), including
  the `vpr_ap_global_place.txt` parse config and
  `pass_requirements_ap_global_place.txt` pass requirements used by the tasks;
- the legality estimator and its echo file (`legality.ap_estimate.echo`).

## Running

All commands are run from this directory.

1. Run the gp tasks:
   ```sh
   source VTR_PATH/.venv/bin/activate
   VTR_PATH/vtr_flow/scripts/run_vtr_task.py -l gp_task_list.txt -j <N>
   ```

2. Parse the results:
   ```sh
   ./parse_legality_estimation.py [--worst_tiles <N>] [-j <N>]
   ```

To re-estimate the legality of the same global placements (e.g. after changing
the estimator):

3. Copy the global placements of the latest gp runs into the re-estimate tasks
   (`<suite>/<suite>_reestimate/flat_placements/<circuit>.fplace`):
   ```sh
   ./collect_gp_placements.py
   ```

4. Run the re-estimate tasks and parse them:
   ```sh
   VTR_PATH/vtr_flow/scripts/run_vtr_task.py -l reestimate_task_list.txt -j <N>
   ./parse_legality_estimation.py --task reestimate
   ```

Without changes to the estimator, the re-estimate must match the estimate made
during global placement. To verify that (e.g. that the global placement is
written and read back without losing information), parse the gp task and
compare it against the re-estimate task:
```sh
./parse_legality_estimation.py --check_reestimate
```
Any circuit whose legality values differ is reported with
`REESTIMATE MISMATCH`. NOTE: flat placement files store single-precision
positions, while the global placer works in double precision. A block placed
within float rounding of a tile boundary can change tiles when it is read back,
which causes a small, benign mismatch.

By default the latest runs of each task are used; use `--run` (collection and
parsing) or `--reestimate_run` (with `--check_reestimate`) to select specific
runs.

### Running a single suite

Each suite can be run on its own. Pass the task directly to `run_vtr_task.py`
(instead of a task list) and use `--suites` with the scripts. For example, to
run only `mcnc` (a quick local test):

```sh
VTR_PATH/vtr_flow/scripts/run_vtr_task.py mcnc/mcnc_gp -j <N>
./parse_legality_estimation.py --suites mcnc --worst_tiles 5
```

## Results

`parse_legality_estimation.py` writes to `results/`:

- `legality_estimation_results.csv`: One row per circuit, with:
  - The VPR status (`success` if the log says "VPR succeeded").
  - The legality estimate: the pins in violation (raw and normalized by the
    number of connected pins), and the pins in violation of each rule
    (`legality_rule_<name>_pins`).
  - The chains whose relative placement is checked (`legality_num_chains`) and
    how many of them are broken (`legality_broken_chains`).
  - The sanity counters: primitives placed off the device, evicted primitives
    with no compatible tile, and molecules split across tiles. The global
    placer places each molecule as one block, and the partial legalizer keeps
    blocks within the device, so the off-device and split counts should be
    zero; a non-zero count of evicted primitives
    with no compatible tile means some primitive cannot legally go anywhere,
    which is a bug in the estimator (or an architecture it does not support).
  - The post-global placement wirelength, CPD and sTNS estimates.
  - The run time of the global placer, of the AP flow (and its max RSS), and of
    VPR.
  - `reestimate_mismatch` (with `--check_reestimate`): the legality values
    which differ between the two tasks.
  - `error`: missing logs / echo files, a failed VPR run, or a disagreement
    between the per tile type penalty in the log and the echo file.
- `legality_tile_types.csv`: One row per (circuit, tile type), aggregated from
  the echo file:
  - The number of occupied tiles and of tiles with a violation, the number of
    primitives and connected pins placed in them, and the pins in violation
    (total and per rule, `rule_<name>`).
  - For each class of tile pin (`in_regular`, `in_global`, `in_clock`, `out`):
    the number of occupied tiles whose demand is over the capacity
    (`*_over_cap`), and the largest demand / capacity ratio (`*_max_ratio`).
    The demand counts every primitive placed in the tile (before any
    evictions), so it shows how overloaded the global placement is, not what
    remains after the estimator's evictions.

A table of the legality estimate of each circuit is also printed (with the worst
tiles of each circuit from the VPR log when `--worst_tiles` is given), followed
by, per suite, the geomean normalized score over the circuits with a non-zero
score and the share of the pins in violation charged to each rule, and, per
suite and tile type, the pins in violation of each rule and the tile pin
demand.

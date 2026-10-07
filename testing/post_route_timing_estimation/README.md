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
  the final flat placement (`final.fplace`) and the routed timing graph
  (`timing_graph.analysis.echo`).
- `<suite>/<suite>_estimate`: Reads in the final flat placement of the routed task
  (global placement is skipped) and writes the estimated timing graph
  (`timing_graph.ap_post_routing_estimate.echo`). The estimated CPD and sTNS
  are printed in the VPR log ("Placement estimated CPD/sTNS"), along with the
  estimated wirelength ("Placement estimated wirelength").

NOTE: Every task must have a unique directory name. `run_vtr_task.py` names a
task after its directory (not its path), and when several tasks with the same
name are run together their run directories collide (e.g. the jobs and parse
results of one task are written into the run directory of the other).

| Suite         | Circuits                                         |
|---------------|--------------------------------------------------|
| `vtr_largest` | The 8 largest VTR circuits (same as `vtr_largest_ap`) |
| `koios`       | The Koios circuits (same as `koios_ap`)          |
| `titan_quick` | The Titan circuits of the `ap_titan` regression test (titan_quick, without gaussianblur) |

The `titan_quick` tasks use the same device widths and router options as the
`ap_titan` regression test (`vtr_reg_nightly_test7`), but with timing analysis
turned on (that test is wirelength driven). The Titan benchmarks must be
downloaded into the VTR tree (`make get_titan_benchmarks`).

Only the needed timing graph echo files are written (using
`--echo_files`), since `--echo_file on` writes many very large files.

NOTE: This requires a VPR build with the `--echo_files` option and the AP
post-routing timing estimate.

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
run only `vtr_largest`:

```sh
VTR_PATH/vtr_flow/scripts/run_vtr_task.py vtr_largest/vtr_largest_routed -j <N>
./collect_flat_placements.py --suites vtr_largest
VTR_PATH/vtr_flow/scripts/run_vtr_task.py vtr_largest/vtr_largest_estimate -j <N>
./parse_timing_estimation.py --suites vtr_largest
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
- `cpd_tns_wirelength_comparison.png`: Estimated vs. routed CPD, sTNS, and
  wirelength of every circuit.
- `path_crit_accuracy.png`: The path delay and criticality accuracy of every
  circuit.
- `circuits/<suite>_<circuit>.png` (with `--per_circuit_plots`): Scatter plots
  of the estimated vs. routed path delays and criticalities of each circuit.
  The path delays are colored by the routed criticality of their endpoint, with
  the most critical endpoints drawn on top.

A summary table and the geomean of the estimated / routed CPD, sTNS, and
wirelength of each suite are also printed.

Connections driven by constant generators and connections to clock pins are not
routed through the general routing network, so they are not compared.

NOTE: Parsing the echo files of a large circuit can use several GB of memory
(about 150 MB for stereovision2, and about 3 GB for the largest Koios
circuits). The Titan circuits are larger still, so parse `titan_quick` with a
low `-j`.

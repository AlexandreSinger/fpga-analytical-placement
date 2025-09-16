#!/usr/bin/env python

import os
import sys
import shutil
import re
import csv
from dataclasses import dataclass
from pathlib import Path

from enum import Enum

from subprocess import Popen, PIPE, TimeoutExpired
from multiprocessing import Pool

import argparse

@dataclass
class BenchmarkCircuit:
    unique_name: str
    circuit_source_file: Path
    arch_file: Path
    device: str
    route_chan_width: int
    is_verilog: bool
    sdc_file: Path = None

@dataclass
class Benchmark:
    name: str
    benchmark_circuits: list[BenchmarkCircuit]

    def verify(self):
        circuit_names = set()
        for circuit in self.benchmark_circuits:
            assert(circuit.unique_name not in circuit_names)
            assert(circuit.circuit_source_file.exists())
            assert(circuit.arch_file.exists())
            assert(circuit.arch_file.suffix == ".xml")
            assert(circuit.route_chan_width > 0)
            if circuit.is_verilog:
                assert(circuit.circuit_source_file.suffix == ".v")
            else:
                assert(circuit.circuit_source_file.suffix == ".blif")
            if circuit.sdc_file is not None:
                assert(circuit.sdc_file.suffix == ".sdc")

class VTRBenchmark(Benchmark):
    def __init__(self, vtr_base_dir: Path):
        self.name = "vtr_largest"

        circuits_dir = Path(os.path.dirname(os.path.abspath(__file__))).joinpath("benchmarks").joinpath("vtr_largest")
        arch_file = vtr_base_dir.joinpath("vtr_flow").joinpath("arch").joinpath("timing").joinpath("k6_frac_N10_frac_chain_mem32K_40nm.xml")

        circuit_data = [
            ("stereovision0.blif", "vtr_medium",      66),
            ("arm_core.blif",      "vtr_medium",      148),
            ("stereovision1.blif", "vtr_medium",      100),
            ("LU8PEEng.blif",      "vtr_large",       118),
            ("bgm.blif",           "vtr_large",       110),
            ("stereovision2.blif", "vtr_extra_large", 114),
            ("mcml.blif",          "vtr_extra_large", 170),
            ("LU32PEEng.blif",     "vtr_extra_large", 146),
        ]

        self.benchmark_circuits = []
        for data in circuit_data:
            self.benchmark_circuits.append(
                BenchmarkCircuit(unique_name=data[0][:-5],
                                 circuit_source_file=circuits_dir.joinpath(data[0]),
                                 arch_file=arch_file,
                                 sdc_file=circuits_dir.joinpath(data[0][:-5] + ".sdc"),
                                 device=data[1],
                                 route_chan_width=data[2],
                                 is_verilog=False)
            )


class TitanQuickBenchmark(Benchmark):
    def __init__(self, vtr_base_dir: Path):
        self.name = "titan_quick"

        circuits_dir = vtr_base_dir.joinpath("vtr_flow").joinpath("benchmarks").joinpath("titan_blif").joinpath("titan23").joinpath("stratixiv")
        sdc_dir = circuits_dir
        arch_file = vtr_base_dir.joinpath("vtr_flow").joinpath("arch").joinpath("titan").joinpath("stratixiv_arch.timing.xml")

        circuit_data = [
            ("sparcT1_core_stratixiv_arch_timing.blif",  "titan_extra_small"),
            ("SLAM_spheric_stratixiv_arch_timing.blif",  "titan_extra_small"),
            ("stereo_vision_stratixiv_arch_timing.blif", "titan_small"),
            ("cholesky_mc_stratixiv_arch_timing.blif",   "titan_small"),
            ("neuron_stratixiv_arch_timing.blif",        "titan_small"),
            ("segmentation_stratixiv_arch_timing.blif",  "titan_small"),
            ("dart_stratixiv_arch_timing.blif",          "titan_small"),
            ("denoise_stratixiv_arch_timing.blif",       "titan_small"),
            ("sparcT2_core_stratixiv_arch_timing.blif",  "titan_small"),
            ("stap_qrd_stratixiv_arch_timing.blif",      "titan_medium"),
            ("cholesky_bdti_stratixiv_arch_timing.blif", "titan_medium"),
            ("des90_stratixiv_arch_timing.blif",         "titan_medium"),
            ("mes_noc_stratixiv_arch_timing.blif",       "titan_medium"),
            ("openCV_stratixiv_arch_timing.blif",        "titan_medium"),
            ("LU_Network_stratixiv_arch_timing.blif",    "titan_medium"),
            ("minres_stratixiv_arch_timing.blif",        "titan_medium"),
            ("bitcoin_miner_stratixiv_arch_timing.blif", "titan_medium"),
            ("bitonic_mesh_stratixiv_arch_timing.blif",  "titan_large"),
            ("gsm_switch_stratixiv_arch_timing.blif",    "titan_large"),
            ("sparcT1_chip2_stratixiv_arch_timing.blif", "titan_large"),
            ("directrf_stratixiv_arch_timing.blif",      "titan_large"),
            ("LU230_stratixiv_arch_timing.blif",         "titan_extra_large"),
            ("gaussianblur_stratixiv_arch_timing.blif",  "titan_extra_large"),
        ]

        self.benchmark_circuits = []
        for data in circuit_data:
            self.benchmark_circuits.append(
                BenchmarkCircuit(unique_name=data[0][:-5],
                                 circuit_source_file=circuits_dir.joinpath(data[0]),
                                 arch_file=arch_file,
                                 device=data[1],
                                 route_chan_width=300,
                                 is_verilog=False)
            )


class GenPlacementType(Enum):
    CENTROID = 0
    AP = 1
    RANDOM = 2


class RunPlacementType(Enum):
    VARIANCE = 0
    EQUILIBRIUM_EST = 1


def run_vpr(args,
            timeout: float) -> bool:
    process = Popen(args,
                    stdout=PIPE,
                    stderr=PIPE)

    if timeout == 0.0:
        timeout = None

    circuit_timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=None)
    except TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        circuit_timed_out = True

    with open("vpr.out", "w") as f:
        f.write(stdout.decode())
        f.close()

    with open("vpr_err.out", "w") as f:
        f.write(stderr.decode())
        f.close()

    return not circuit_timed_out

    if not circuit_timed_out:
        print(f"{circuit.unique_name} is done!")
    else:
        print(f"{circuit.unique_name} timed out after {timeout} seconds!")


def gen_test_placements_for_circuit(thread_args):
    circuit: BenchmarkCircuit = thread_args[0]
    circuit_temp_dir: Path = thread_args[1]
    circuit_result_dir: Path = thread_args[2]
    placement_type: GenPlacementType = thread_args[3]
    vpr_executable: Path = thread_args[4]

    assert(circuit_temp_dir.exists())
    assert(circuit_result_dir.exists())
    assert(vpr_executable.exists())

    assert(circuit.circuit_source_file.suffix == ".blif")

    init_place_file = circuit_result_dir.joinpath(f"{circuit.unique_name}_init.place")
    final_place_file = circuit_result_dir.joinpath(f"{circuit.unique_name}_final.place")

    net_file = circuit_result_dir.joinpath(f"{circuit.unique_name}.net")

    # Run VTR in the temp directory
    os.chdir(circuit_temp_dir)

    args = [vpr_executable]

    args.extend([
        circuit.arch_file,
        circuit.circuit_source_file,
        "--write_initial_place_file", str(init_place_file),
        "--place_file", str(final_place_file),
        "--net_file", str(net_file),
        "--device", circuit.device,
        "--route_chan_width", str(circuit.route_chan_width),
        ])

    if circuit.sdc_file is not None:
        args.extend(["--sdc_file", str(circuit.sdc_file)])

    if placement_type == GenPlacementType.CENTROID:
        args.extend([
            "--pack",
            "--place",
        ])
    elif placement_type == GenPlacementType.AP:
        args.extend([
            "--analytical_place",
        ])
    else:
        assert(False)

    run_success = run_vpr(args, 0.0)
    if run_success:
        print(f"{circuit.unique_name} is done!")
    else:
        print(f"{circuit.unique_name} timed out after {timeout} seconds!")


def gen_test_placements_for_benchmark(benchmark: Benchmark,
                                      result_dir: Path,
                                      temp_dir: Path,
                                      vtr_base_dir: Path,
                                      num_threads: int):
    benchmark.verify()
    assert(result_dir.exists())
    assert(temp_dir.exists())

    benchmark_result_dir = result_dir.joinpath(benchmark.name)
    assert(not benchmark_result_dir.exists())
    os.mkdir(benchmark_result_dir)

    benchmark_temp_dir = temp_dir.joinpath(benchmark.name)
    if benchmark_temp_dir.exists():
        shutil.rmtree(benchmark_temp_dir)
    os.mkdir(benchmark_temp_dir)

    centroid_place_result_dir = benchmark_result_dir.joinpath("centroid")
    os.mkdir(centroid_place_result_dir)
    centroid_place_temp_dir = benchmark_temp_dir.joinpath("centroid")
    os.mkdir(centroid_place_temp_dir)

    ap_result_dir = benchmark_result_dir.joinpath("ap")
    os.mkdir(ap_result_dir)
    ap_temp_dir = benchmark_temp_dir.joinpath("ap")
    os.mkdir(ap_temp_dir)

    vpr_executable = vtr_base_dir.joinpath("vpr").joinpath("vpr")

    thread_args = []
    for circuit in benchmark.benchmark_circuits:
        circuit_centroid_temp_dir = centroid_place_temp_dir.joinpath(circuit.unique_name)
        os.mkdir(circuit_centroid_temp_dir)
        thread_args.append([
            circuit,
            circuit_centroid_temp_dir,
            centroid_place_result_dir,
            GenPlacementType.CENTROID,
            vpr_executable,
        ])

        circuit_ap_temp_dir = ap_temp_dir.joinpath(circuit.unique_name)
        os.mkdir(circuit_ap_temp_dir)
        thread_args.append([
            circuit,
            circuit_ap_temp_dir,
            ap_result_dir,
            GenPlacementType.AP,
            vpr_executable,
        ])

    pool = Pool(num_threads)
    pool.map(gen_test_placements_for_circuit, thread_args)
    pool.close()

def run_placement(thread_args):
    circuit: BenchmarkCircuit = thread_args[0]
    circuit_temp_dir: Path = thread_args[1]
    circuit_place_file: Path = thread_args[2]
    circuit_net_file: Path = thread_args[3]
    run_placement_type: RunPlacementType = thread_args[4]
    vpr_executable: Path = thread_args[5]

    assert(circuit_temp_dir.exists())
    assert(circuit_place_file.exists())
    assert(circuit_place_file.suffix == ".place")
    assert(vpr_executable.exists())

    assert(circuit.circuit_source_file.suffix == ".blif")

    os.chdir(circuit_temp_dir)

    args = [vpr_executable]

    args.extend([
        circuit.arch_file,
        circuit.circuit_source_file,
        "--place",
        "--net_file", str(circuit_net_file),
        "--read_initial_place_file", str(circuit_place_file),
        "--device", circuit.device,
        "--route_chan_width", str(circuit.route_chan_width),
        ])

    if circuit.sdc_file is not None:
        args.extend(["--sdc_file", str(circuit.sdc_file)])

    if run_placement_type == RunPlacementType.VARIANCE:
        args.extend([
            "--anneal_auto_init_t_estimator", "cost_variance",
        ])
    elif run_placement_type == RunPlacementType.EQUILIBRIUM_EST:
        args.extend([
            "--anneal_auto_init_t_estimator", "equilibrium",
        ])

    run_success = run_vpr(args, 0.0)
    if run_success:
        print(f"{circuit.unique_name} is done!")
    else:
        print(f"{circuit.unique_name} timed out after {timeout} seconds!")


def get_next_run_name(base_dir: Path) -> str:
    pattern = re.compile(r"^run(\d+)$")
    max_num = 0
    for entry in os.listdir(base_dir):
        full_path = os.path.join(base_dir, entry)
        if os.path.isdir(full_path):
            match = pattern.match(entry)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num
    return f"run{max_num+1:03d}"


def run_test_placements_for_benchmark(benchmark: Benchmark,
                                      run_place_type: RunPlacementType,
                                      placements_dir: Path,
                                      results_dir: Path,
                                      run_dir: Path,
                                      vtr_base_dir: Path,
                                      num_threads: int):

    print(f"Running test placements for {benchmark.name} with the {run_place_type.name} estimator...")

    assert(run_dir.exists())

    centroid_placements_dir = placements_dir.joinpath(benchmark.name).joinpath("centroid")
    ap_placements_dir = placements_dir.joinpath(benchmark.name).joinpath("ap")
    
    vpr_executable = vtr_base_dir.joinpath("vpr").joinpath("vpr")

    run_place_type_name = ""
    if run_place_type == RunPlacementType.VARIANCE:
        run_place_type_name = "variance"
    elif run_place_type == RunPlacementType.EQUILIBRIUM_EST:
        run_place_type_name = "equilibriumest"

    thread_args = []
    for circuit in benchmark.benchmark_circuits:
        circuit_run_dir = run_dir.joinpath(circuit.unique_name)
        assert(not circuit_run_dir.exists())
        os.mkdir(circuit_run_dir)

        for place_qual in ["init", "final"]:
            centroid_run_dir = circuit_run_dir.joinpath(f"centroid_{place_qual}_{run_place_type_name}")
            assert(not centroid_run_dir.exists())
            os.mkdir(centroid_run_dir)
            thread_args.append([
                circuit,
                centroid_run_dir,
                centroid_placements_dir.joinpath(f"{circuit.unique_name}_{place_qual}.place"),
                centroid_placements_dir.joinpath(f"{circuit.unique_name}.net"),
                run_place_type,
                vpr_executable,
            ])

            ap_run_dir = circuit_run_dir.joinpath(f"ap_{place_qual}_{run_place_type_name}")
            assert(not ap_run_dir.exists())
            os.mkdir(ap_run_dir)
            thread_args.append([
                circuit,
                ap_run_dir,
                ap_placements_dir.joinpath(f"{circuit.unique_name}_{place_qual}.place"),
                ap_placements_dir.joinpath(f"{circuit.unique_name}.net"),
                run_place_type,
                vpr_executable,
            ])

    pool = Pool(num_threads)
    pool.map(run_placement, thread_args)
    pool.close()

    print("Parsing results...")


    # Parse the results into a CSV file.
    # | circuit name | estimator | centroid / ap | init / final | init_t | iter 1 cost ratio | init_wl | final_wl | init_cpd | final_cpd |
    data = [
        ['circuit_name', 'estimator', 'init_placer_type', 'place_quality',
         'init_t', 'iter_one_cost_ratio',
         'init_wl', 'final_wl', 'init_cpd', 'final_cpd', 'place_runtime']
    ]
    for circuit in benchmark.benchmark_circuits:
        for place_qual in ["init", "final"]:
            for init_placer_type in ["centroid", "ap"]:
                data_row = [circuit.unique_name,
                            run_place_type_name,
                            init_placer_type,
                            place_qual]

                vpr_out_file = run_dir.joinpath(f"{circuit.unique_name}").joinpath(f"{init_placer_type}_{place_qual}_{run_place_type_name}").joinpath("vpr.out")

                init_t = -1
                cost_ratio = -1
                init_wl = -1
                final_wl = -1
                init_cpd = -1
                final_cpd = -1
                place_time = -1
                first_line_pattern = re.compile(r"^\s*1\s+\S+\s+(\S+)\s+(\S+)(\s+\S+){11}\s*$")
                init_wl_pattern = re.compile(r"Initial placement BB estimate of wirelength:\s*(\S+)")
                final_wl_pattern = re.compile(r"BB estimate of min-dist \(placement\) wire length:\s*(\S+)")
                init_cpd_pattern = re.compile(r"Initial placement estimated Critical Path Delay \(CPD\):\s*(\S+)\s+ns")
                final_cpd_pattern = re.compile(r"Placement estimated critical path delay \(least slack\):\s*(\S+)\s+ns")
                place_time_pattern = re.compile(r"# Placement took (\S+) seconds")
                with open(vpr_out_file, "r") as f:
                    for line in f:
                        first_line_match = first_line_pattern.search(line)
                        if first_line_match:
                            init_t = float(first_line_match.group(1))
                            cost_ratio = float(first_line_match.group(2))
                            continue
                        init_wl_match = init_wl_pattern.search(line)
                        if init_wl_match:
                            init_wl = float(init_wl_match.group(1))
                            continue
                        final_wl_match = final_wl_pattern.search(line)
                        if final_wl_match:
                            final_wl = float(final_wl_match.group(1))
                            continue
                        init_cpd_match = init_cpd_pattern.search(line)
                        if init_cpd_match:
                            init_cpd = float(init_cpd_match.group(1))
                            continue
                        final_cpd_match = final_cpd_pattern.search(line)
                        if final_cpd_match:
                            final_cpd = float(final_cpd_match.group(1))
                            continue
                        place_time_match = place_time_pattern.search(line)
                        if place_time_match:
                            place_time = float(place_time_match.group(1))
                            continue


                # Collect the data into a row in CSV file
                data_row.extend([
                    init_t,
                    cost_ratio,
                    init_wl,
                    final_wl,
                    init_cpd,
                    final_cpd,
                    place_time,
                ])
                data.append(data_row)

    csv_file_path = run_dir.joinpath("results.csv")
    with open(csv_file_path, 'w', newline='') as file:
        writer = csv.writer(file)

        writer.writerows(data)

def command_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=None,
        description="Script for testing initial temperature estimation.",
        epilog="",
    )

    parser.add_argument(
        "-j",
        default=1,
        type=int,
        metavar="NUM_PROC",
    )

    return parser

if __name__ == "__main__":
    args = command_parser().parse_args(sys.argv[1:])

    vtr_base_dir = Path.home().joinpath("vtr-verilog-to-routing")

    benchmarks_to_run = [
        VTRBenchmark(vtr_base_dir),
        TitanQuickBenchmark(vtr_base_dir),
    ]

    result_dir = Path(os.path.dirname(os.path.abspath(__file__))).joinpath("placements")
    if not result_dir.exists():
        os.mkdir(result_dir)

    temp_dir = Path(os.path.dirname(os.path.abspath(__file__))).joinpath("temp")
    if not temp_dir.exists():
        os.mkdir(temp_dir)

    for benchmark in benchmarks_to_run:
        benchmark_result_dir = result_dir.joinpath(benchmark.name)
        if benchmark_result_dir.exists():
            should_regenerate = input(f"Benchmark placements already exist for {benchmark.name}. Do you want to regenerate them (y/n): ")
            if should_regenerate != 'y':
                print("Skipping regenerating placements.")
                continue
            shutil.rmtree(benchmark_result_dir)

    for benchmark in benchmarks_to_run:
        benchmark_result_dir = result_dir.joinpath(benchmark.name)
        if benchmark_result_dir.exists():
            continue
        # TODO: We can extract way more parallelism by collecting the thread
        #       args at a high level.
        gen_test_placements_for_benchmark(benchmark,
                                          result_dir,
                                          temp_dir,
                                          vtr_base_dir,
                                          args.j)

    run_dir = Path(os.path.dirname(os.path.abspath(__file__))).joinpath("runs")
    if not run_dir.exists():
        os.mkdir(run_dir)

    for benchmark in benchmarks_to_run:
        benchmark_run_dir = run_dir.joinpath(benchmark.name)
        if not benchmark_run_dir.exists():
            os.mkdir(benchmark_run_dir)
        run_name = get_next_run_name(benchmark_run_dir)
        current_run_dir = benchmark_run_dir.joinpath(run_name)
        assert(not current_run_dir.exists())
        os.mkdir(current_run_dir)

        # TODO: We can extract way more parralelism by collecting the thread
        #       args at a high level.
        equilibrium_run_dir = current_run_dir.joinpath("equilibrium")
        os.mkdir(equilibrium_run_dir)
        run_test_placements_for_benchmark(benchmark,
                                          RunPlacementType.EQUILIBRIUM_EST,
                                          result_dir,
                                          None,
                                          equilibrium_run_dir,
                                          vtr_base_dir,
                                          args.j)

        variance_run_dir = current_run_dir.joinpath("variance")
        os.mkdir(variance_run_dir)
        run_test_placements_for_benchmark(benchmark,
                                          RunPlacementType.VARIANCE,
                                          result_dir,
                                          None,
                                          variance_run_dir,
                                          vtr_base_dir,
                                          args.j)

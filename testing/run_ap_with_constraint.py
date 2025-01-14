#!/usr/bin/python3

# This script run vpr with fixed io constraints.

import argparse
import os
import re
import shutil
import subprocess
import sys
from multiprocessing import Pool

# This function parses arguments of this python script
def command_parser():
    parser = argparse.ArgumentParser(description="parse arguments for fix io script")
    parser.add_argument("test_suite_name", help="name of the one test suite being run")
    default_vtr_path = os.path.join(os.path.expanduser("~"), "vtr-verilog-to-routing")
    parser.add_argument("-vtr_path", default=default_vtr_path, type=str, help="path of root directory for VTR")
    default_test_cases_path = os.path.join(os.getcwd(), "tests")
    parser.add_argument("-test_cases_path", default=default_test_cases_path, type=str, help="path to intermediate files of the testcases")
    default_runs_path = os.path.join(os.getcwd(), "ap_runs")
    parser.add_argument("-runs_path", default=default_runs_path, type=str, help="path to where to store the run results.")
    parser.add_argument("-route_chan_width", default=-1, type=int, help="routing channel width to use for all circuits. -1 does a min channel width route.")
    parser.add_argument("-run_simulated_annealing", action="store_true", help="This flag tells the script to use the unmodified constraint file where all pins are constrained, it is used to test performence of simulated annealing placer")
    parser.add_argument("-j", default=1, type=int, metavar="NUM_PROC")

    return parser

# Helper method to get the device name out of the config file.
def get_device_name(config_path, circuit):
    device_pattern = r'--device\s+"([^"]+)"'
    with open(config_path, 'r') as config:
        for line in config:
            if "circuit_constraint_list_add" not in line:
                continue
            if circuit not in line:
                continue
            if "device" not in line:
                continue
            match = re.search(r'device\s*=\s*(.*)\s*\)', line)
            if match:
                return match.group(1)
        for line in config:
            match = re.search(device_pattern, line)
            if match:
                return match.group(1)
    return None

# Helper method to get the circuit's route channel width out of the config file.
def get_route_channel_width(config_path, circuit):
    route_chan_width_pattern = r'--route_chan_width\s+"([^"]+)"'
    with open(config_path, 'r') as config:
        for line in config:
            if "circuit_constraint_list_add" not in line:
                continue
            if circuit not in line:
                continue
            if "route_chan_width" not in line:
                continue
            match = re.search(r'route_chan_width\s*=\s*(.*)\s*\)', line)
            if match:
                return match.group(1)
        for line in config:
            match = re.search(route_chan_width_pattern, line)
            if match:
                return match.group(1)
    return None

# Helper method to extract the run number from the given run directory name.
# For example "run003" would return 3.
def extract_run_number(run):
    if run is None:
        return None
    match = re.match(r"run(\d+)", run)
    if match:
        return int(match.group(1))
    else:
        return None

def run_vpr(thread_args):
    # Parse the thread arguments
    working_dir = thread_args[0]
    vtr_dir = thread_args[1]
    arch = thread_args[2]
    circuit_blif = thread_args[3]
    constraint_file = thread_args[4]
    device_name = thread_args[5]
    route_chan_width = thread_args[6]
    circuit_name = thread_args[7]
    is_ap = thread_args[8]

    # Change directory to the working directory
    os.chdir(working_dir)

    run_list = [os.path.join(vtr_dir, "vpr", "vpr"), \
                             arch, \
                             circuit_blif, \
                             "--read_vpr_constraints", constraint_file]
    if is_ap:
        run_list.append("--analytical_place")
    else:
        run_list.append("--pack")
        run_list.append("--place")
    run_list.append("--route")

    if device_name is not None:
        run_list.append("--device")
        run_list.append(device_name)
    if route_chan_width is not None:
        run_list.append("--route_chan_width")
        run_list.append(str(route_chan_width))

    try:
        process = subprocess.Popen(run_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        print(f"\t{circuit_name} ({'AP' if is_ap else 'NO AP'}) run completed.")
        returncode = process.returncode
        if returncode != 0:
            print(f"Circuit run exited with error code {returncode}")
            print(f"Error message: {stderr.decode()}")

        with open("vpr.out", "w") as f:
            f.write(stdout.decode())
            f.close()

        with open("vpr_err.out", "w") as f:
            f.write(stderr.decode())
            f.close()

    except Exception as e:
        print(f"Program crashed with exception: {e}")


# This is the main function of the python script
def run_test_main(args):
    # parse arguments
    args = command_parser().parse_args(args)

    # check if test suite and test directory exist. 
    test_path = os.path.join(args.test_cases_path, args.test_suite_name)
    if(not os.path.isdir(test_path)):
        print(f"Error: {test_path} does not exists!")
        return False

    print(f"Running AP flow using intermediate files located at: {test_path}")

    # Get the config file
    config_path = os.path.join(test_path, args.test_suite_name + "_config.txt")

    ap_run_base_dir = os.path.join(args.runs_path, args.test_suite_name)
    os.makedirs(ap_run_base_dir, exist_ok=True)
    runs = [d for d in os.listdir(ap_run_base_dir) if os.path.isdir(os.path.join(ap_run_base_dir, d)) and d.startswith("run")]
    last_run_num = 0
    if len(runs) is not 0:
        last_run = sorted(runs)[-1]
        last_run_num = extract_run_number(last_run)
        if last_run_num is None:
            last_run_num = 0
    run_num = last_run_num + 1
    run_name = "run{:03d}".format(run_num)
    run_dir = os.path.join(ap_run_base_dir, run_name)
    os.makedirs(run_dir, exist_ok=True)
    print(f"Saving run information to: {run_dir}")

    # iterate through arch then circuit and call vpr on it
    # results are in tests/arch/circuit/common/ap_run
    thread_args = []
    for arch in os.listdir(test_path):
        arch_dir_path = os.path.join(test_path, arch)
        if not os.path.isdir(arch_dir_path):
            continue
        for circuit in os.listdir(arch_dir_path):
            if circuit == "constraints":
                continue
            circuit_dir_path = os.path.join(arch_dir_path, circuit, "common")
            ap_run_dir = os.path.join(run_dir, "ap", arch, circuit, "common")
            no_ap_run_dir = os.path.join(run_dir, "no_ap", arch, circuit, "common")
            os.makedirs(ap_run_dir)
            os.makedirs(no_ap_run_dir)
            # This part is for handling the two scenarios where test name could be .v or .blif
            circuit_name = circuit[:-2]
            pre_vpr_str = ""
            if(circuit[-13:]==".pre-vpr.blif"):
                circuit_name = circuit[:-13]
                pre_vpr_str = ".pre-vpr"
            constraint_file_name = "io_constraint.xml"
            if args.run_simulated_annealing:
                constraint_file_name = "constraint.xml"
            device_name = get_device_name(config_path, circuit);
            route_chan_width = get_route_channel_width(config_path, circuit)
            if args.route_chan_width > 0:
                route_chan_width = args.route_chan_width
            thread_args.append([ap_run_dir,
                                args.vtr_path,
                                os.path.join(circuit_dir_path, arch),
                                os.path.join(circuit_dir_path, circuit_name + ".pre-vpr.blif"),
                                os.path.join(circuit_dir_path, constraint_file_name),
                                device_name,
                                route_chan_width,
                                circuit_name,
                                True])
            """
            thread_args.append([no_ap_run_dir,
                                args.vtr_path,
                                os.path.join(circuit_dir_path, arch),
                                os.path.join(circuit_dir_path, circuit_name + ".pre-vpr.blif"),
                                os.path.join(circuit_dir_path, constraint_file_name),
                                device_name,
                                args.route_chan_width,
                                circuit_name,
                                False])
            """
    pool = Pool(args.j)
    pool.map(run_vpr, thread_args)
    pool.close()

    return True

if __name__ == "__main__":
    success = run_test_main(sys.argv[1:])
    if not success:
        sys.exit(-1)

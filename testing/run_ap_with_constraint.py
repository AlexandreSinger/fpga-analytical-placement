#!/usr/bin/python3

# This script run vpr with fixed io constraints.

import argparse
import os
import re
import shutil
import subprocess
import sys

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
    parser.add_argument("-chan_width", default=100, type=int, help="largest chan width required for tests in this test suite")
    parser.add_argument("-run_simulated_annealing", action="store_true", help="This flag tells the script to use the unmodified constraint file where all pins are constrained, it is used to test performence of simulated annealing placer")

    return parser

# Helper method to get the device name out of the config file.
def get_device_name(config_path):
    device_pattern = r'--device\s+"([^"]+)"'
    with open(config_path, 'r') as config:
        for line in config:
            match = re.search(device_pattern, line)
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
    for arch in os.listdir(test_path):
        arch_dir_path = os.path.join(test_path, arch)
        if not os.path.isdir(arch_dir_path):
            continue
        for circuit in os.listdir(arch_dir_path):
            circuit_dir_path = os.path.join(arch_dir_path, circuit, "common")
            ap_run_dir = os.path.join(run_dir, arch, circuit, "common")
            os.makedirs(ap_run_dir)
            script_path = os.getcwd();
            os.chdir(ap_run_dir)
            # This part is for handling the two scenarios where test name could be .v or .blif
            circuit_name = circuit[:-2]
            pre_vpr_str = ""
            if(circuit[-13:]==".pre-vpr.blif"):
                circuit_name = circuit[:-13]
                pre_vpr_str = ".pre-vpr"
            constraint_file_name = "io_constraint.xml"
            if args.run_simulated_annealing:
                constraint_file_name = "constraint.xml"
            run_list = [os.path.join(args.vtr_path, "vpr", "vpr"), \
                                     os.path.join(circuit_dir_path, arch), \
                                     os.path.join(circuit_dir_path, circuit_name + ".pre-vpr.blif"), \
                                     "--analytical_place", \
                                     "--route_chan_width", str(args.chan_width), \
                                     "--read_vpr_constraints", os.path.join(circuit_dir_path, constraint_file_name)]
            device_name = get_device_name(config_path);
            if device_name is not None:
                run_list.append("--device")
                run_list.append(device_name)
            try:
                process = subprocess.Popen(run_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout, stderr = process.communicate()
                print(f"\t{circuit} run completed.")
                returncode = process.returncode
                if returncode != 0:
                    print(f"Circuit run exited with error code {returncode}")
                    print(f"Error message: {stderr.decode()}")
            except Exception as e:
                print(f"Program crashed with exception: {e}")
            with open(os.path.join(ap_run_dir, "vpr_stdout.log"), "a") as vpr_log_file:
                vpr_log_file.write(" ".join(run_list))
            os.chdir(script_path)

    return True

if __name__ == "__main__":
    success = run_test_main(sys.argv[1:])
    if not success:
        sys.exit(-1)

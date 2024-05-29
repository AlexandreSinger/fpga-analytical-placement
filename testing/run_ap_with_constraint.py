#!/usr/bin/python3

# This script run vpr with fixed io constraints.

import argparse
import os
import shutil
import subprocess
import sys

# This function parses arguments of this python script
def command_parser():
    parser = argparse.ArgumentParser(description="parse arguments for fix io script")
    parser.add_argument("test_suite_name", help="name of the one test suite being run")
    default_vtr_path = os.path.join(os.path.expanduser("~"), "vtr-verilog-to-routing-ap")
    parser.add_argument("-vtr_path", default=default_vtr_path, type=str, help="path of root directory for VTR")
    default_test_cases_path = os.path.join(os.getcwd(), "tests")
    parser.add_argument("-test_cases_path", default=default_test_cases_path, type=str, help="path of to intermediate files of the testcases")
    parser.add_argument("-chan_width", default=100, type=int, help="largest chan width required for tests in this test suite")

    return parser
    
# This is the main function of the python script
def run_test_main(args):
    # parse arguments
    args = command_parser().parse_args(args)

    # check if test suite and test directory exist. 
    test_path = os.path.join(args.test_cases_path, args.test_suite_name)
    if(not os.path.isdir(test_path)):
        print(test_path, " does not exists!")

    # iterate through arch then circuit and call vpr on it
    # results are in tests/arch/circuit/common/ap_run
    for arch in os.listdir(test_path):
        arch_dir_path = os.path.join(test_path, arch)
        for circuit in os.listdir(arch_dir_path):
            circuit_dir_path = os.path.join(arch_dir_path, circuit, "common")
            ap_run_dir = os.path.join(circuit_dir_path, "ap_dir")
            os.makedirs(ap_run_dir, exist_ok=True)
            script_path = os.getcwd();
            os.chdir(ap_run_dir)
            # This part is for handling the two scenarios where test name could be .v or .blif
            circuit_name = circuit[:-2]
            pre_vpr_str = ""
            if(circuit[-13:]==".pre-vpr.blif"):
                circuit_name = circuit[:-13]
                pre_vpr_str = ".pre-vtr"
            print("circuit_name: "+circuit_name)
            print("pre_vpr_str: "+pre_vpr_str)
            result = subprocess.run([os.path.join(args.vtr_path, "vpr", "vpr"), \
                                     os.path.join(circuit_dir_path, arch), \
                                     os.path.join(circuit_dir_path, circuit_name + ".pre-vpr.blif"), \
                                     "--net_file", os.path.join(circuit_dir_path, circuit_name + pre_vpr_str+".net"), \
                                     "--place_file", os.path.join(circuit_dir_path, circuit_name + pre_vpr_str+".place"), \
                                     "--route_chan_width", str(args.chan_width), \
                                     "--read_vpr_constraints", os.path.join(circuit_dir_path, "io_constraint.xml")], \
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print(result.stdout.decode('unicode_escape'))
            if(result.returncode != 0):
                print("vpr failed: ", result.stderr)
                return
            os.chdir(script_path)

if __name__ == "__main__":
    run_test_main(sys.argv[1:])

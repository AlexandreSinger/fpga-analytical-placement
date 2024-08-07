#!/usr/bin/python3

# This script is used to collect all the HPWL information
# Given a test cases patha and a test suite name, the script collect information from that directory and form a hpwls.csv file

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys

# This function parses arguments of this python script
def command_parser():
    parser = argparse.ArgumentParser(description="parse arguments for fix io script")
    parser.add_argument("test_suite_name", help="name of the one test suite being run")
    default_test_cases_path = os.path.join(os.getcwd(), "tests")
    parser.add_argument("-test_cases_path", default=default_test_cases_path, type=str, help="path of to intermediate files of the testcases")
    default_runs_path = os.path.join(os.getcwd(), "ap_runs")
    parser.add_argument("-runs_path", default=default_runs_path, type=str, help="path to where to store the run results.")
    default_output_file=os.path.join(os.getcwd(), "hpwls.csv")
    parser.add_argument("-output_file", default=default_output_file, type=str, help="path of to output file")
    parser.add_argument("-run_simulated_annealing", action="store_true", help="This flag tells the script that it is parsing output generated by simulated annealing placer")

    return parser
    
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
        print(test_path, " does not exists!")

    output_file = open(args.output_file, "w")
    writer = csv.writer(output_file)

    ap_run_base_dir = os.path.join(args.runs_path, args.test_suite_name)
    os.makedirs(ap_run_base_dir, exist_ok=True)
    runs = [d for d in os.listdir(ap_run_base_dir) if os.path.isdir(os.path.join(ap_run_base_dir, d)) and d.startswith("run")]
    last_run_num = 0
    if len(runs) is not 0:
        last_run = sorted(runs)[-1]
        last_run_num = extract_run_number(last_run)
        if last_run_num is None:
            last_run_num = 0
    run_name = "run{:03d}".format(last_run_num)
    run_dir = os.path.join(ap_run_base_dir, run_name)

    for arch in os.listdir(test_path):
        arch_dir_path = os.path.join(test_path, arch)
        for circuit in os.listdir(arch_dir_path):
            circuit_dir_path = os.path.join(arch_dir_path, circuit, "common")
            ap_run_dir = os.path.join(run_dir, arch, circuit, "common")
            result_file_path = os.path.join(ap_run_dir, "vpr_stdout.log")
            writer.writerow([arch, circuit, run_name])
            if not args.run_simulated_annealing:
                HPWL = []
                PLHPWL = []
                result_file = open(result_file_path, "r")
                for line in result_file:
                    line_list = line.split()
                    if len(line_list) == 2 and line_list[0] == "HPWL:":
                        HPWL.append(line_list[1])
                    elif len(line_list) == 3 and line_list[0] == "Post-Legalized":
                        PLHPWL.append(line_list[2])
                writer.writerow(HPWL)
                writer.writerow(PLHPWL)
            else:
                HPWL = []
                result_file = open(result_file_path, "r")
                for line in result_file:
                    line_list = line.split()
                    if len(line_list) == 4 and line_list[0] == "simulated":
                        HPWL.append(line_list[-1])
                writer.writerow(HPWL)


if __name__ == "__main__":
    run_test_main(sys.argv[1:])

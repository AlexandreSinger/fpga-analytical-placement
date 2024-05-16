#!/usr/bin/python3

# This script generates and stores intermediate files used while running VTR, such as .blif, .place, etc.

import argparse
import os
import shutil
import subprocess
import sys

# This function parses arguments of this python script
def command_parser():
    parser = argparse.ArgumentParser(description="parse arguments for fix io script")
    parser.add_argument("test_suite_name", help="name of the one test suite being run")
    default_vtr_path = os.path.join(os.path.expanduser("~"), "vtr-verilog-to-routing")
    parser.add_argument("-vtr_path", default=default_vtr_path, type=str, help="path of root directory for VTR")
    default_output_path = os.path.join(os.getcwd(), "tests")
    parser.add_argument("-output_path", default=default_output_path, type=str, help="path of the output directory")
    parser.add_argument("-save_tmp", action="store_true", help="do not remove the tmp dir at then end of the script")
    return parser

# This function moves files from tmp to output
def move_files(test_suite_output_path, tmp_path):
    # run001 is the output vtr task generats runing the first time
    for item in os.listdir(os.path.join(tmp_path, "run001")):
        item_path = os.path.join(tmp_path, "run001", item)
        if(os.path.isdir(item_path) and item.endswith(".xml")):
            shutil.move(item_path, test_suite_output_path)
    
# This is the main function of the python script
def run_test_main(args):
    # parse arguments
    args = command_parser().parse_args(args)

    # if output for test suite exists, stop; if not, create that directory. 
    test_suite_output_path = os.path.join(args.output_path, args.test_suite_name)
    if(not os.path.isdir(test_suite_output_path)):
        os.makedirs(test_suite_output_path)
    else: 
        print(args.test_suite_name + "'s output already exists!")
        return

    # Remove tmp directory if exists, then create tmp directory
    # Tmp directory is needed to make vtr task and the script's output structure compatiable
    tmp_path = os.path.join(os.getcwd(), "tmp")
    if(os.path.isdir(tmp_path)):
        shutil.rmtree(tmp_path)
    os.makedirs(tmp_path)

    # Check if config file for test suite exists
    test_suite_config_file_path = os.path.join(os.getcwd(), "configs", args.test_suite_name + "_config.txt")
    if (not os.path.isfile(test_suite_config_file_path)):
        print("Config file for test suite " + args.test_suite_name + " does not exist! The config file name should be in the form <test_suite_name>_config.txt.")
        return

    # Copy config file to tmp
    tmp_config_dir_path = os.path.join(tmp_path, "config")
    os.makedirs(tmp_config_dir_path)
    tmp_config_file_path = os.path.join(tmp_config_dir_path, "config.txt")
    shutil.copy(test_suite_config_file_path, tmp_config_file_path)

    # Run vtr task on the test suite
    vtr_task_path = "vtr_flow/scripts/run_vtr_task.py"
    result = subprocess.run([os.path.join(args.vtr_path, vtr_task_path), tmp_path], \
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if(result.returncode != 0):
        print("run_vtr_task failed: ", result.stderr)
        return

    # Move files from tmp to output
    move_files(test_suite_output_path, tmp_path)

    # Remove tmp unless save_tmp is enabled
    if(not args.save_tmp):
        shutil.rmtree(tmp_path)

if __name__ == "__main__":
    run_test_main(sys.argv[1:])

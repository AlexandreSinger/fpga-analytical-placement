#!/usr/bin/python3

# This script generates and stores intermediate files used while running VTR, such as .blif, .place, etc.

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

# This function parses arguments of this python script
def command_parser():
    parser = argparse.ArgumentParser(description="parse arguments for fix io script")
    parser.add_argument("test_suite_name", help="name of the one test suite being run")
    default_vtr_path = os.path.join(os.path.expanduser("~"), "vtr-verilog-to-routing")
    parser.add_argument("-vtr_path", default=default_vtr_path, type=str, help="path of root directory for VTR")
    default_output_path = os.path.join(os.getcwd(), "tests")
    parser.add_argument("-output_path", default=default_output_path, type=str, help="path of the output directory")
    parser.add_argument("-save_tmp", action="store_true", help="do not remove the tmp dir at then end of the script")
    default_configs_path = os.path.join(os.getcwd(), "configs") 
    parser.add_argument("-configs_path", default=default_configs_path, type=str, help="path of the config files directory")
    parser.add_argument(
        "-j",
        "-p",
        default=1,
        type=int,
        metavar="NUM_PROC",
        help="How many processors to use for execution.",
    )
    return parser

# This function moves files from tmp to output
def move_files(test_suite_output_path, tmp_path):
    # run001 is the output vtr task generates running the first time
    for item in os.listdir(os.path.join(tmp_path, "run001")):
        item_path = os.path.join(tmp_path, "run001", item)
        if(os.path.isdir(item_path) and item.endswith(".xml")):
            shutil.move(item_path, test_suite_output_path)
    
# This is the main function of the python script
def get_intermediate_files(args):
    # parse arguments
    args = command_parser().parse_args(args)

    # Get the location the temperary files will be generated into.
    #   <output_path>/<test_suite_name>
    test_suite_output_path = os.path.join(args.output_path, args.test_suite_name)
    print(f"Generating intermediate files into {test_suite_output_path}.");

    # Get the file path to the config file.
    #   <config_path>/<test_suite_name>_config.txt
    test_suite_config_file_path = os.path.join(args.configs_path, args.test_suite_name + "_config.txt")

    # if output for test suite exists, stop.
    if (os.path.isdir(test_suite_output_path)):
        print(f"{args.test_suite_name}'s output already exists! Skipping generating intermediate files.")
        return True

    # Check if config file for test suite exists
    if (not os.path.isfile(test_suite_config_file_path)):
        print(f"Error: Config file for test suite {args.test_suite_name} does not exist! The config file name should be in the form <test_suite_name>_config.txt.")
        return False

    print(f"Using config file: {test_suite_config_file_path}")

    # Make the directory
    os.makedirs(test_suite_output_path)

    # Create a temporary directory.
    tmp_path = tempfile.mkdtemp()

    # Copy config file to tmp
    tmp_config_dir_path = os.path.join(tmp_path, "config")
    os.makedirs(tmp_config_dir_path)
    tmp_config_file_path = os.path.join(tmp_config_dir_path, "config.txt")
    shutil.copy(test_suite_config_file_path, tmp_config_file_path)

    # Run vtr task on the test suite
    vtr_task_path = "vtr_flow/scripts/run_vtr_task.py"
    vtr_task_command = [os.path.join(args.vtr_path, vtr_task_path), tmp_path, "-j"+str(args.j)]
    print(f"Running VTR task with the following command: {vtr_task_command}")
    result = subprocess.run(vtr_task_command, stdout=None, stderr=subprocess.PIPE)

    # Move files from tmp to output
    print(f"Moving temporary files from {tmp_path} to {test_suite_output_path}")
    move_files(test_suite_output_path, tmp_path)

    # Copy the config file into the output path, this can be useful.
    shutil.copy(test_suite_config_file_path, test_suite_output_path);

    # Remove tmp unless save_tmp is enabled
    if(args.save_tmp):
        print(f"Saving temporary directory. Directory located at {tmp_path}")
    else:
        print(f"Removing temp directory")
        shutil.rmtree(tmp_path)

    # If running the task failed, raise an error.
    if(result.returncode != 0):
        print("Error: run_vtr_task failed: ", result.stderr)
        return False

    print(f"Successfully generated intermediate files into {test_suite_output_path}")
    return True

if __name__ == "__main__":
    success = get_intermediate_files(sys.argv[1:])
    if not success:
        sys.exit(-1)

#!/usr/bin/python3

# This script runs get_intermediate_files.py, generate_fix_io.py, and run_ap_with_constraint.py in sequence.

import argparse
import os
import subprocess
import sys

def command_parser():
    parser = argparse.ArgumentParser(description="parse arguments for fix io script")
    parser.add_argument("test_suite_name", help="name of the one test suite being run")
    parser.add_argument(
        "-j",
        "-p",
        default=1,
        type=int,
        metavar="NUM_PROC",
        help="How many processors to use for execution.",
    )

    return parser

def run_test_main(args):
    # parse arguments
    args = command_parser().parse_args(args)
    pwd = os.getcwd()

    print("==== Getting intermediate files ===")
    result = subprocess.run([os.path.join(pwd, "get_intermediate_files.py"), args.test_suite_name, "-j" + str(args.j)], \
                            stdout=None, stderr=subprocess.PIPE)
    if(result.returncode != 0):
        print("get_intermediate_files failed.")
        if result.stderr:
            print("get_intermediate_files failed: ", result.stderr)
        return
    print("")

    print("====== Generating fixed IOs =======")
    result = subprocess.run([os.path.join(pwd, "generate_fix_io.py"), args.test_suite_name], \
                            stdout=None, stderr=subprocess.PIPE)
    if(result.returncode != 0):
        print("generate_fix_io failed: ", result.stderr)
        return
    print("")

    print("=========== Running AP ============")
    result = subprocess.run([os.path.join(pwd, "run_ap_with_constraint.py"), args.test_suite_name, "-j" + str(args.j)], \
                            stdout=None, stderr=subprocess.PIPE)
    if(result.returncode != 0):
        print("run_ap_with_constraint failed: ", result.stderr)
        return


if __name__ == "__main__":
    run_test_main(sys.argv[1:])

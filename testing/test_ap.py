#!/usr/bin/python3

# This script runs get_intermediate_file.py, generate_fix_io.py, and run_ap_with_constraint.py in sequence. 

import argparse
import os
import subprocess
import sys

def command_parser():
    parser = argparse.ArgumentParser(description="parse arguments for fix io script")
    parser.add_argument("test_suite_name", help="name of the one test suite being run")

    return parser

def run_test_main(args):
    # parse arguments
    args = command_parser().parse_args(args)
    pwd = os.getcwd()
    result = subprocess.run([os.path.join(pwd, "get_intermediate_file.py"), args.test_suite_name], \
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(result.stdout.decode('unicode_escape'))
    if(result.returncode != 0):
        print("get_intermediate_file failed: ", result.stderr)
        return
    
    result = subprocess.run([os.path.join(pwd, "generate_fix_io.py"), args.test_suite_name], \
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(result.stdout.decode('unicode_escape'))
    if(result.returncode != 0):
        print("generate_fix_io failed: ", result.stderr)
        return
    
    result = subprocess.run([os.path.join(pwd, "run_ap_with_constraint.py"), args.test_suite_name], \
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(result.stdout.decode('unicode_escape'))
    if(result.returncode != 0):
        print("run_ap_with_constraint failed: ", result.stderr)
        return


if __name__ == "__main__":
    run_test_main(sys.argv[1:])

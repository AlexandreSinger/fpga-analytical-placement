#!/usr/bin/python3

import sys
import argparse
import os
import subprocess
import glob

def parse_args(args):
    parser = argparse.ArgumentParser(description="parse arguments for fix io script")
    parser.add_argument("test_case_name")
    parser.add_argument("arch_desc_name")
    parser.add_argument("task_name")
    default_vtr_path = os.path.expanduser("~") + "/vtr-verilog-to-routing"
    parser.add_argument("-vtr_path", default = default_vtr_path, type = str)
    return parser

def run_test_main(args):
    args = parse_args(args).parse_args(args)
    result_run_dir = glob.glob(os.getcwd()+"/run*/")
    if len(result_run_dir) == 0:
        if(not os.path.isdir("./config")):
            print("missing config or run### dir")
            return
        result = subprocess.run([os.path.join(args.vtr_path, "vtr_flow/scripts/run_vtr_task.py"), "./"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if(result.returncode != 0):
            print("run_vtr_task failed: ", result.stderr)
    result_run_dir = glob.glob(os.getcwd()+"/run*/")
    result_dir = os.path.join(os.path.join(result_run_dir[0], args.arch_desc_name), args.test_case_name)
    if(os.path.isdir(result_dir)):
        print(result_dir)
    else:
        print("testcase architecture pair does not exist!")

if __name__ == "__main__":
    run_test_main(sys.argv[1:])

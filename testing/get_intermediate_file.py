#!/usr/bin/python3

import sys
import argparse
import os
import subprocess
import glob
import shutil

def parse_args(args):
    parser = argparse.ArgumentParser(description="parse arguments for fix io script")
    parser.add_argument("test_suite_name")
    default_vtr_path = os.path.expanduser("~") + "/vtr-verilog-to-routing"
    parser.add_argument("-vtr_path", default = default_vtr_path, type = str)
    default_output_path = os.getcwd()+"/tests"
    parser.add_argument("-output_path", default = default_output_path, type = str)
    return parser

def run_test_main(args):
    args = parse_args(args).parse_args(args)
    if(not os.path.isdir(args.output_path + "/" + args.test_suite_name)):
        os.makedirs(args.output_path + "/" + args.test_suite_name)
    os.makedirs(os.getcwd()+"/tmp/")
    if(not os.path.isfile(os.getcwd()+"/configs/"+args.test_suite_name+"_config.txt")):
        print("config file for test suite " + args.test_suite_name + " does not exist!")
        return
    os.makedirs(os.getcwd()+"/tmp/config")
    shutil.copy(os.getcwd()+"/configs/"+args.test_suite_name+"_config.txt", os.getcwd()+"/tmp/config/config.txt")
    os.chdir(os.getcwd()+"/tmp/")
    result = subprocess.run([os.path.join(args.vtr_path, "vtr_flow/scripts/run_vtr_task.py"), "./"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if(result.returncode != 0):
        print("run_vtr_task failed: ", result.stderr)
    os.chdir("../")
    for item in os.listdir(os.getcwd()+"/tmp/run001"):
        item_path = os.path.join(os.getcwd()+"/tmp/run001", item)
        if(os.path.isdir(item_path) and item.endswith(".xml")):
            shutil.move(item_path, args.output_path + "/" + args.test_suite_name)
    shutil.rmtree(os.getcwd()+"/tmp")

if __name__ == "__main__":
    run_test_main(sys.argv[1:])

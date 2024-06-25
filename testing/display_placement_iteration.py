#!/usr/bin/python3

# animate placement iteration

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import time

# This function parses arguments of this python script
def command_parser():
    parser = argparse.ArgumentParser(description="parse arguments for display placement iteration script")
    parser.add_argument("file_path", help="name of the one test suite being run")

    return parser
    

# This is the main function of the python script
def run_test_main(args):
    # parse arguments
    args = command_parser().parse_args(args)

    within_draw = False
    file = open(args.file_path, "rb");
    data = file.read()
    text = data.decode('utf-8', errors='ignore')  # Ignore decoding errors

    # Process decoded text
    lines = text.splitlines()
    for line in lines:
        if line == "unicode_art start":
            within_draw = True
            os.system("clear")
            continue
        if line == "unicode_art end":
            within_draw = False
            time.sleep(0.05)  
        if within_draw:
            print(line)

if __name__ == "__main__":
    run_test_main(sys.argv[1:])

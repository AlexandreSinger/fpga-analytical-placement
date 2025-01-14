# Need some way to generate the tasks. It can be very annoying to make these tasks, so created a script to automate making the task.
# Decided against this idea. Leaving the code just in case. This is really not needed. Better to fix the run task method.

import os
import sys
import argparse

def command_parser(prog=None):
    parser = argparse.ArgumentParser(prog=prog, description="Generate a task for the AP flow.", epilog="")

    parser.add_argument("test_suite_name", help="name of the test suite being turned into a task")

    default_task_dir = os.path.join(os.getcwd(), "tasks")
    parser.add_argument("-task_dir", default=default_task_dir, type=str, help="path to the target directory to generate the task into.")

    return parser

def gen_task_main(arg_list, prog=None):
    args = command_parser(prog).parse_args(arg_list)
    print(f"Generating the task for {args.test_suite_name}")
    print(f"Task will be generated into {args.task_dir}")

    # Change directory into the task directory.
    if (not os.path.isdir(args.task_dir)):
        print(f"Error: {args.task_dir} is not a directory.")
        return False
    os.chdir(args.task_dir)

if __name__ == "__main__":
    gen_task_main(sys.argv[1:])

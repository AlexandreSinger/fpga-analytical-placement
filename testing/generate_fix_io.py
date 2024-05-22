#!/usr/bin/python3

# this script is used to modify the constaint files so that only the input and output blocks are kept. the constraint file create is used as initial states for the analytical placer.

import argparse
import os
import shutil
import sys
import xml.etree.ElementTree as ET

# This function parses arguments of this python script
def command_parser():
    parser = argparse.ArgumentParser(description="parse arguments for fix io script")
    parser.add_argument("test_suite_name", help="name of the one test suite being run")
    default_output_path = os.path.join(os.getcwd(), "fix_io")
    parser.add_argument("-output_path", default=default_output_path, type=str, help="path of the output directory")
    default_input_path = os.path.join(os.getcwd(), "tests")
    parser.add_argument("-input_path", default=default_input_path, type=str, help="path of the input directory")
    return parser

# the pre-vpr.blif file's input and output section is stored in two sets for constraint file atom name matching. Input is kept if the name matches exactly; Output is kept if and only if the name of atom in constraint file's first four chars are "out:" and the name comes after matches blif output section name exactly. 
def modify_constraint(blif_path, constraint_input_path, constraint_output_path):
    blif_file = open(blif_path, "r")
    out_set = set()
    in_set = set()
    is_input = False
    is_output = False
    for line in blif_file:
        line = line.strip()
        if line.startswith(".inputs") or is_input:
            in_set.update(line.split())
            if line.endswith("\\"):
                is_input = True
            else:
                is_input = False
        if line.startswith(".outputs") or is_output:
            out_set.update(line.split())
            if line.endswith("\\"):
                is_output = True
            else:
                is_output = False
                break
    in_set.discard(".inputs")
    out_set.discard(".outputs")
    in_set.discard("\\")
    out_set.discard("\\")

    shutil.copyfile(constraint_input_path, constraint_output_path)

    tree = ET.parse(constraint_output_path)
    root = tree.getroot()
    partition_list = root.find('partition_list')
    for partition in partition_list.findall('partition'):
        atom_kept = False
        for atom in partition.findall('add_atom'):
            atom_name = atom.get('name_pattern')
            if atom_name in in_set:
                atom_kept = True
            elif atom_name.startswith('out:') and atom_name[4:] in out_set:
                atom_kept = True
            else:
                partition.remove(atom)
        if not atom_kept:
            partition_list.remove(partition)
    ET.ElementTree(root).write(constraint_output_path)	

# This is the main function of the python script
def run_test_main(args):
    # parse arguments
    args = command_parser().parse_args(args)

    # if input for test suite does not exist, raise an error
    test_suite_input_path = os.path.join(args.input_path, args.test_suite_name)
    if(not os.path.isdir(test_suite_input_path)):
        print("Input path is invalid or it does not contain test suite " + args.test_suite_name + "!")
        return

    # if output dir does not exist, create it; if exists, raise an error
    test_suite_output_path = os.path.join(args.output_path, args.test_suite_name)
    if(not os.path.isdir(test_suite_output_path)):
        os.makedirs(test_suite_output_path)
    else:
        print("Output exists for " + args.test_suite_name + "!")
        return

    # Iterate through combination of target and circuit pair and create corresponding pair in the output directory. The constraints files are then modified in each iteration.
    for arch in os.listdir(test_suite_input_path):
        input_arch_dir_path = os.path.join(test_suite_input_path, arch)
        output_arch_dir_path = os.path.join(test_suite_output_path, arch)
        os.makedirs(output_arch_dir_path)
        for circuit in os.listdir(input_arch_dir_path):
            input_circuit_dir_path = os.path.join(input_arch_dir_path, circuit)
            output_circuit_dir_path = os.path.join(output_arch_dir_path, circuit)
            os.makedirs(output_circuit_dir_path)
            common_path = os.path.join(input_circuit_dir_path, "common")
            blif_path = os.path.join(common_path, circuit[:-2]+".pre-vpr.blif")
            constraint_input_path = os.path.join(common_path, circuit[:-2]+"_constraint.xml")
            constraint_output_path = os.path.join(output_circuit_dir_path, circuit[:-2]+"_constraint.xml")
            if(not os.path.isfile(blif_path)):
                print("Files missing for "+arch+" "+circuit+"!")
                return
            modify_constraint(blif_path, constraint_input_path, constraint_output_path)
 
if __name__ == "__main__":
    run_test_main(sys.argv[1:])


import argparse
import csv
import os
import re
import shutil
import subprocess
import sys

# Helper method to generate a parser for the command line interface.
def command_parser(prog=None):
    description = "Iteratively runs vtr, feeding back the flat placement into the packer"
    parser = argparse.ArgumentParser(
            prog=prog,
            description=description,
            epilog="",
    )

    default_vtr_dir = os.path.expanduser("~") + "/vtr-verilog-to-routing"
    parser.add_argument(
            "-vtr_dir",
            default=default_vtr_dir,
            type=str,
            metavar="VTR_DIR",
    )

    default_configs_dir = os.path.join(os.getcwd(), "configs")
    parser.add_argument(
            "-configs_dir",
            default=default_configs_dir,
            type=str,
            metavar="CONFIGS_DIR",
    )
    
    return parser

# The first pass will run the circuit to generate all of the temporary files
# required by VPR as well as the first flat placement file.
def run_first_pass(config_file_path, output_dir_path, vtr_dir_path):
    # Create a directory in the output directory for the first pass
    first_pass_dir = os.path.join(output_dir_path, "first_pass")
    os.makedirs(first_pass_dir)

    # Copy the config file into the first pass folder
    first_pass_config_dir = os.path.join(first_pass_dir, "config")
    os.makedirs(first_pass_config_dir)
    first_pass_config_file_path = os.path.join(first_pass_config_dir, "config.txt")
    shutil.copy(config_file_path, first_pass_config_file_path)

    # Run the vtr task
    run_vtr_task_path = os.path.join(vtr_dir_path, "vtr_flow/scripts/run_vtr_task.py")
    vtr_task_command = [run_vtr_task_path,
                        first_pass_dir]
    print(f"Running VTR task with the following command: {vtr_task_command}")
    result = subprocess.run(vtr_task_command, stdout=None, stderr=subprocess.PIPE)

    # If running the task failed, raise an error.
    if(result.returncode != 0):
        print("Error: run_vtr_task failed: ", result.stderr)
        return False

    return True

# Collects common files which will be used for future iterations to run. This
# includes the VPR command to run, the flat placement file, the architecture
# file, and the architecture file.
def collect_common_files(output_dir_path, common_files_dir_path):
    # FIXME: This may need to be updated to handle multiple circuits.

    # Get the root directory of the first pass which has all the files we want.
    #   Get the first pass run directory.
    first_pass_run_dir = os.path.join(output_dir_path, "first_pass", "run001")
    #   Get all of the sub directories in this folder.
    run_dir_sub_dirs = [ f.path for f in os.scandir(first_pass_run_dir) if f.is_dir() ]
    if (len(run_dir_sub_dirs) != 1):
        print("Error: folder structure of the first pass is not consistent (assumed to have 1 architecture.")
        return False
    #   Assuming there is only 1 architecture, there is only one folder. Get the
    #   sub-directories of this folder.
    arch_dir_sub_dirs = [ f.path for f in os.scandir(run_dir_sub_dirs[0]) if f.is_dir() ]
    if (len(arch_dir_sub_dirs) != 1):
        print("Error: folder structure of the first pass is not consistent (assumed to have 1 circuit).")
        return False
    #   Assuming there is only 1 circuit, there should only be one folder. Get
    #   the root directory from here.
    first_pass_root_dir = os.path.join(arch_dir_sub_dirs[0], "common")

    # Create the common files directory
    os.makedirs(common_files_dir_path)

    # Get the VPR command
    first_pass_vpr_out_file_path = os.path.join(first_pass_root_dir, "vpr.out")
    vpr_command = ""
    with open(first_pass_vpr_out_file_path) as f:
        vpr_command = f.readline().strip('\n')

    # Get the xml file from the command
    arch_file = ""
    arch_match = re.search(r'\S+\.xml', vpr_command)
    if arch_match:
        arch_file = arch_match.group()
    else:
        print("Error: unable to find architecture file in vpr command.")
        return False
    # Copy the architecture file over to the common files directory
    first_pass_arch_file_path = os.path.join(first_pass_root_dir, arch_file)
    shutil.copy(first_pass_arch_file_path, common_files_dir_path)
    # Update the compile command to point to the common files directory now.
    common_files_arch_file_path = os.path.join(common_files_dir_path, arch_file)
    vpr_command = re.sub(r'\S+\.xml', common_files_arch_file_path, vpr_command, count=1)

    # Get the blif file from the command
    blif_file = ""
    blif_match = re.search(r'\S+\.blif', vpr_command)
    if blif_match:
        blif_file = blif_match.group()
    else:
        print("Error: unable to find blif file in vpr command.")
        return False
    # Copy the architecture file over to the common files directory
    first_pass_blif_file_path = os.path.join(first_pass_root_dir, blif_file)
    shutil.copy(first_pass_blif_file_path, common_files_dir_path)
    # Update the compile command to point to the common files directory now.
    common_files_blif_file_path = os.path.join(common_files_dir_path, blif_file)
    vpr_command = re.sub(r'\S+\.blif', common_files_blif_file_path, vpr_command, count=1)

    # Get the flat placement file
    fp_file = ""
    fp_match = re.search(r'\S+\.fplace', vpr_command)
    if fp_match:
        fp_file = fp_match.group()
    else:
        print("Error: unable to find fplace file in vpr command.")
        return False
    # Copt the fplace file over to the common files directory with new name
    first_pass_fplace_file_path = os.path.join(first_pass_root_dir, fp_file)
    common_files_fplace_file_path = os.path.join(common_files_dir_path, "iter0.fplace")
    shutil.copy(first_pass_fplace_file_path, common_files_fplace_file_path)
    # Remove the "--write_flate_place" option from the command to make it easier to work with.
    vpr_command = re.sub(r'--write_flat_place \S+', '', vpr_command)

    # Clean up any extra spaces that might be left behind
    vpr_command = re.sub(r'\s+', ' ', vpr_command).strip()

    # Write the VPR command as a txt file
    vpr_command_file_path = os.path.join(common_files_dir_path, "vpr_command.txt")
    with open(vpr_command_file_path, "w") as file:
        file.write(vpr_command)

    # Get the log file for the first pass. Used later for parsing.
    first_pass_log_file = os.path.join(first_pass_root_dir, "vpr_stdout.log")
    common_files_first_pass_log_file = os.path.join(common_files_dir_path, "first_pass_vpr_stdout.log")
    shutil.copy(first_pass_log_file, common_files_first_pass_log_file)

    return True

# Run a single iteration VPR command. This uses the command provided by the
# common files directory.
def run_single_iter(iter_num, common_files_dir_path):
    # Get the VPR command to run
    vpr_command_file_path = os.path.join(common_files_dir_path, "vpr_command.txt")
    vpr_command = ""
    with open(vpr_command_file_path) as f:
        vpr_command = f.readline().strip('\n')

    # Get the fplace file to read/write and add to the VPR command
    read_fplace_file_path = os.path.join(common_files_dir_path, f"iter{iter_num - 1}.fplace")
    write_fplace_file_path = os.path.join(common_files_dir_path, f"iter{iter_num}.fplace")
    vpr_command += f" --read_flat_place {read_fplace_file_path} --write_flat_place {write_fplace_file_path}"

    # Make a directory to store the temporary files
    iter_run_dir_path = os.path.join(common_files_dir_path, "..", f"iter{iter_num}")
    os.makedirs(iter_run_dir_path)
    os.chdir(iter_run_dir_path)

    # Run the vtr task
    print(f"Running VPR with the following command: {vpr_command}")
    result = subprocess.run(vpr_command, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # If running the task failed, raise an error.
    if(result.returncode != 0):
        print("Error: run_vtr_task failed: ", result.stderr)
        return False

    return True

# Parse a single log file for the given regex pattern. This is not a very
# efficient way to do this, but this should not be called often enough to cause
# a problem.
def parse_log_file(log_file_path, regex_pattern):
    with open(log_file_path, 'r') as file:
        for line in file:
            match = re.search(regex_pattern, line)
            if match:
                return match.group(1)
    # If a piece of data cannot be found, return -1
    return -1

# Parse a single iteration's log file for all the information we are looking for.
def parse_single_iter(iter_log_file_path, iter_num):
    return [iter_num,
            parse_log_file(iter_log_file_path, r"\s*Packing took (.*) seconds"),
            parse_log_file(iter_log_file_path, r"Device Utilization: (.*) \(target"),
            parse_log_file(iter_log_file_path, r"Total wirelength:\s*(\d+),"),
            parse_log_file(iter_log_file_path, r"Final critical path delay \(least slack\): (.*) ns")
            ]

# Parse the per-iteration results into a csv file.
def parse_iter_results(output_dir_path, per_iter_qor_csv_file_path, total_num_iterations):
    qor_data = [['iter_num', 'pack_time(s)', 'device_util', 'total_wl', 'CPD(ns)']]

    first_pass_log_file = os.path.join(output_dir_path, "common_files", "first_pass_vpr_stdout.log")
    qor_data.append(parse_single_iter(first_pass_log_file, 0))

    for iter_num in range(total_num_iterations):
        iter_log_file_path = os.path.join(output_dir_path, f"iter{iter_num + 1}", "vpr_stdout.log")
        iter_qor_data = parse_single_iter(iter_log_file_path, iter_num + 1)
        qor_data.append(iter_qor_data)

    with open(per_iter_qor_csv_file_path, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerows(qor_data)

    return True

# Main function to run the vtr iteratively, feeding back the flat placement into
# the packer.
def run_vtr_feedback(arg_list, prog=None):
    # Load the arguments
    args = command_parser(prog).parse_args(arg_list)

    # Check if an output directory already exists
    output_dir_path = os.path.join(os.getcwd(), "output")
    if (os.path.isdir(output_dir_path)):
        print(f"Output directory already exists: {output_dir_path}")
        response = input("Do you want to remove it? [Y/n]")
        if (response != "Y"):
            print("Exiting script, save the output directory and run again.")
            return
        shutil.rmtree(output_dir_path)

    # Run the first pass to generate the files needed to run VPR and the first
    # (default) flat placement file.
    success = run_first_pass(os.path.join(args.configs_dir, "alu4_config.txt"),
                             output_dir_path,
                             args.vtr_dir)
    if not success:
        print("Error: Failed to run first pass.")
        return

    # Collect common files in a convenient folder.
    common_files_dir_path = os.path.join(output_dir_path, "common_files")
    success = collect_common_files(output_dir_path, common_files_dir_path)
    if not success:
        print("Error: Failed to collect common files.")
        return

    # Run the iterations
    total_num_iterations = 3
    for iter_num in range(total_num_iterations):
        success = run_single_iter(iter_num + 1, common_files_dir_path)
        if not success:
            print(f"Error: Iteration {iter_num + 1} failed.")
            return

    # Parse QoR data to a CSV file
    per_iter_qor_csv_file_path = os.path.join(output_dir_path, "per_iter_qor.csv")
    success = parse_iter_results(output_dir_path, per_iter_qor_csv_file_path, total_num_iterations)
    if not success:
        print(f"Error: Failed to parse per iteration QoR data.")
        return

if __name__ == "__main__":
    run_vtr_feedback(sys.argv[1:])


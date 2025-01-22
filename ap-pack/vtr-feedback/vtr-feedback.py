
import argparse
import csv
import glob
import math
from multiprocessing import Pool
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

    parser.add_argument(
            "test_suite_name",
            help="Name of the test suite being run, given by a configuration file",
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

    parser.add_argument(
            "-num_iter",
            default=3,
            type=int,
            metavar="NUM_ITER",
    )

    # Number of threads to use to run the circuits in parallel.
    parser.add_argument(
            "-j",
            default=1,
            type=int,
            metavar="NUM_PROC"
    )
    
    return parser

"""
Cleans the given run directory by removing everything in the folder except for
the vpr_stdout.log file. This saves storage space since over many iterations
we will quickly run out of space due to the unnnecessary .net, .place, and
.route files generated.
"""
def clean_run_dir(run_dir_path):
    # Collect all the files in the directory into a list
    files_to_remove = glob.glob(os.path.join(run_dir_path, '*'))

    # Remove the log file from this list
    log_file_path = os.path.join(run_dir_path, "vpr_stdout.log")
    files_to_remove.remove(log_file_path)

    # Remove all of the files in the list
    for file in files_to_remove:
        os.remove(file)

# The first pass will run the circuit to generate all of the temporary files
# required by VPR as well as the first flat placement file.
def run_first_pass(config_file_path, output_dir_path, vtr_dir_path, num_proc):
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
                        first_pass_dir,
                        f"-j{num_proc}"]
    print(f"Running VTR task with the following command: {vtr_task_command}")
    result = subprocess.run(vtr_task_command, stdout=None, stderr=subprocess.PIPE)

    # If running the task failed, raise an error.
    if(result.returncode != 0):
        print("Error: run_vtr_task failed: ", result.stderr)
        return False

    return True

# Collect the common files for a single circuit.
def collect_common_files_for_circuit(circuit_first_pass_root_dir,
                                     circuit_common_files_target_dir):
    # Create the common files directory
    os.makedirs(circuit_common_files_target_dir)

    # Get the VPR command
    first_pass_vpr_out_file_path = os.path.join(circuit_first_pass_root_dir, "vpr.out")
    vpr_command = ""
    with open(first_pass_vpr_out_file_path) as f:
        vpr_command = f.readline().strip('\n')

    # Get the xml file from the command
    # FIXME: We do not need to get the xml file for every single circuit. For
    #        now it is fine to keep.
    arch_file = ""
    arch_match = re.search(r'\S+\.xml', vpr_command)
    if arch_match:
        arch_file = arch_match.group()
    else:
        print("Error: unable to find architecture file in vpr command.")
        return False
    # Copy the architecture file over to the common files directory
    first_pass_arch_file_path = os.path.join(circuit_first_pass_root_dir, arch_file)
    shutil.copy(first_pass_arch_file_path, circuit_common_files_target_dir)
    # Update the compile command to point to the common files directory now.
    common_files_arch_file_path = os.path.join(circuit_common_files_target_dir, arch_file)
    vpr_command = re.sub(r'\S+\.xml', common_files_arch_file_path, vpr_command, count=1)

    # Get the blif file from the command
    blif_file = ""
    blif_match = re.search(r'\s(\S+\.blif)\s', vpr_command)
    if blif_match:
        blif_file = blif_match.group()
        blif_file = blif_file.strip()
    else:
        print("Error: unable to find blif file in vpr command.")
        return False
    # Copy the architecture file over to the common files directory
    first_pass_blif_file_path = os.path.join(circuit_first_pass_root_dir, blif_file)
    shutil.copy(first_pass_blif_file_path, circuit_common_files_target_dir)
    # Update the compile command to point to the common files directory now.
    common_files_blif_file_path = os.path.join(circuit_common_files_target_dir, blif_file)
    vpr_command = re.sub(r'\s(\S+\.blif)\s', " " + common_files_blif_file_path + " ", vpr_command, count=1)

    # Get the flat placement file
    fp_file = ""
    fp_match = re.search(r'\S+\.fplace', vpr_command)
    if fp_match:
        fp_file = fp_match.group()
    else:
        print("Error: unable to find fplace file in vpr command.")
        return False
    # Copt the fplace file over to the common files directory with new name
    first_pass_fplace_file_path = os.path.join(circuit_first_pass_root_dir, fp_file)
    common_files_fplace_file_path = os.path.join(circuit_common_files_target_dir, "iter0.fplace")
    shutil.copy(first_pass_fplace_file_path, common_files_fplace_file_path)
    # Remove the "--write_flate_place" option from the command to make it easier to work with.
    vpr_command = re.sub(r'--write_flat_place \S+', '', vpr_command)

    # Clean up any extra spaces that might be left behind
    vpr_command = re.sub(r'\s+', ' ', vpr_command).strip()

    # Write the VPR command as a txt file
    vpr_command_file_path = os.path.join(circuit_common_files_target_dir, "vpr_command.txt")
    with open(vpr_command_file_path, "w") as file:
        file.write(vpr_command)

    # Get the log file for the first pass. Used later for parsing.
    first_pass_log_file = os.path.join(circuit_first_pass_root_dir, "vpr_stdout.log")
    common_files_first_pass_log_file = os.path.join(circuit_common_files_target_dir, "first_pass_vpr_stdout.log")
    shutil.copy(first_pass_log_file, common_files_first_pass_log_file)

    # Clean the root dir to safe space
    clean_run_dir(circuit_first_pass_root_dir)

    return True


# Collects common files which will be used for future iterations to run. This
# includes the VPR command to run, the flat placement file, the architecture
# file, and the architecture file.
def collect_common_files(output_dir_path, common_files_dir_path):
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

    # Create the common files directory
    os.makedirs(common_files_dir_path)

    # For each circuit, collect common files.
    for circuit_dir in arch_dir_sub_dirs:
        circuit_name = os.path.basename(circuit_dir)
        circuit_first_pass_root_dir = os.path.join(circuit_dir, "common")
        circuit_common_files_target_dir = os.path.join(common_files_dir_path, circuit_name)
        success = collect_common_files_for_circuit(circuit_first_pass_root_dir, circuit_common_files_target_dir)
        if not success:
            print(f"Error: Unable to collect common files for circuit: {circuit_name}")
            return False

    return True

"""
Run a single iteration for a circuit. This method is multithreaded so many
circuits can be run at the same time.
Arguments:
    iter_num
    circuit_iter_run_dir_path
    circuit_common_files_target_dir
"""
def run_circuit_single_iter(thread_args):
    # Parse the arguments
    iter_num = thread_args[0]
    circuit_iter_run_dir_path = thread_args[1]
    circuit_common_files_dir_path = thread_args[2]

    # Get the VPR command to run
    vpr_command_file_path = os.path.join(circuit_common_files_dir_path, "vpr_command.txt")
    vpr_command = ""
    with open(vpr_command_file_path) as f:
        vpr_command = f.readline().strip('\n')

    # Get the fplace file to read/write and add to the VPR command
    read_fplace_file_path = os.path.join(circuit_common_files_dir_path, f"iter{iter_num - 1}.fplace")
    write_fplace_file_path = os.path.join(circuit_common_files_dir_path, f"iter{iter_num}.fplace")
    vpr_command += f" --read_flat_place {read_fplace_file_path} --write_flat_place {write_fplace_file_path}"

    # Make a directory to store the temporary files
    os.chdir(circuit_iter_run_dir_path)

    # Run the vtr task
    # print(f"Running VPR with the following command: {vpr_command}")
    result = subprocess.run(vpr_command, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # If running the task failed, raise an error.
    if(result.returncode != 0):
        print("Error: run_vtr_task failed: ", result.stderr)
        return False

    # Print a message to signify that the run was successful.
    circuit_name = os.path.basename(circuit_iter_run_dir_path)
    print(f"Iteration {iter_num} of circuit {circuit_name} completed.")

    # Clean the run directory to save space.
    clean_run_dir(circuit_iter_run_dir_path)

    return True

# Run a single iteration VPR command. This uses the command provided by the
# common files directory.
def run_single_iter(iter_num, common_files_dir_path, num_proc):
    # Get the directory for this iteration.
    iter_run_dir_path = os.path.join(common_files_dir_path, "..", f"iter{iter_num}")

    # Collect the arguments required to run each circuit for one iteration.
    circuit_common_files_dir_paths = [ f.path for f in os.scandir(common_files_dir_path) if f.is_dir() ]
    thread_args = []
    for circuit_common_files_dir_path in circuit_common_files_dir_paths:
        circuit_name = os.path.basename(circuit_common_files_dir_path)
        circuit_iter_run_dir_path = os.path.join(iter_run_dir_path, circuit_name)
        os.makedirs(circuit_iter_run_dir_path)
        thread_args.append([iter_num,
                            circuit_iter_run_dir_path,
                            circuit_common_files_dir_path])

    # Dispatch a threadpool to run the circuits in parallel.
    with Pool(num_proc) as p:
        results = p.map(run_circuit_single_iter, thread_args)
        # If any of the circuits failed, return false here.
        if False in results:
            print(f"Error: One of the circuits failed.")
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
            parse_log_file(iter_log_file_path, r"Final critical path delay \(least slack\): (.*) ns"),
            parse_log_file(iter_log_file_path, r"Percent of clusters with reconstruction errors: (.*)"),
            parse_log_file(iter_log_file_path, r"Percent of atoms misplaced from the flat placement: (.*)"),
            parse_log_file(iter_log_file_path, r"Average atom displacement of initial placement from flat placement: (.*)")
            ]

# Parse the results of a single iteration run of a circuit into a csv file.
def parse_circuit_iter_results(output_dir_path,
                               circuit_name,
                               circuit_per_iter_qor_csv_file_path,
                               total_num_iterations):
    # Create the header of the CSV file.
    qor_data = [['iter_num', 'pack_time(s)', 'device_util', 'total_wl', 'CPD(ns)', 'percent_cluster_errors', 'percent_atoms_displaced', 'average_atom_displacement']]
    # Get the log file for the first pass for this circuit.
    first_pass_log_file = os.path.join(output_dir_path,
                                       "common_files",
                                       circuit_name,
                                       "first_pass_vpr_stdout.log")
    # Parse the first iteration
    qor_data.append(parse_single_iter(first_pass_log_file, 0))

    # Parse the other iterations
    for iter_num in range(total_num_iterations):
        iter_log_file_path = os.path.join(output_dir_path,
                                          f"iter{iter_num + 1}",
                                          circuit_name,
                                          "vpr_stdout.log")
        iter_qor_data = parse_single_iter(iter_log_file_path, iter_num + 1)
        qor_data.append(iter_qor_data)

    # Write the parsed results into the CSV file
    with open(circuit_per_iter_qor_csv_file_path, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerows(qor_data)

    return True

"""
Calculate the geomean and average results over all of the given csv files.
Assumes that they are all the same shape (same number of cols and rows).
Will save the results to csv files located in per_iter_qor_dir_path.
"""
def calc_gmean_and_avg_results(qor_csv_files,
                               per_iter_qor_dir_path):
    # Use the first csv file to get the number of rows (number of iterators)
    # and the header (which has the number of cols).
    headers = []
    num_rows = 0
    with open(qor_csv_files[0]) as f:
        csv_reader = csv.reader(f)
        # Remove the headers and store them to variable
        headers = next(csv_reader, None)
        for row in csv_reader:
            num_rows += 1

    # Create 2D arrays to hold important values
    sum = [[0 for x in range(len(headers))] for y in range(num_rows)]
    log_sum = [[0 for x in range(len(headers))] for y in range(num_rows)]
    total_valid = [[0 for x in range(len(headers))] for y in range(num_rows)]
    total_log_valid = [[0 for x in range(len(headers))] for y in range(num_rows)]

    # Go through the CSV files and accumulate important values
    for qor_csv_file in qor_csv_files:
        with open(qor_csv_file) as f:
            csv_reader = csv.reader(f)
            next(csv_reader)
            for row_idx, row in enumerate(csv_reader):
                for idx, val in enumerate(row):
                    if val == '-1':
                        continue
                    fp_val = float(val)
                    if fp_val != 0:
                        log_sum[row_idx][idx] += math.log(fp_val)
                        total_log_valid[row_idx][idx] += 1
                    sum[row_idx][idx] += fp_val
                    total_valid[row_idx][idx] += 1

    # Get the file paths to the output csv files.
    gmean_per_ter_qor_csv_file_path = os.path.join(per_iter_qor_dir_path, "gmean_per_iter_qor.csv")
    avg_per_ter_qor_csv_file_path = os.path.join(per_iter_qor_dir_path, "avg_per_iter_qor.csv")

    # Compute the average and geomean over all circuits
    avg_data = sum
    gmean_data = log_sum
    for row_idx in range(len(gmean_data)):
        for col_idx in range(len(gmean_data[row_idx])):
            num_valid = total_valid[row_idx][col_idx]
            num_log_valid = total_log_valid[row_idx][col_idx]
            avg = -1
            if num_valid != 0:
                avg = sum[row_idx][col_idx] / float(num_valid)
            gmean = -1
            if num_log_valid != 0:
                gmean = math.exp(log_sum[row_idx][col_idx] / float(num_log_valid))
            avg_data[row_idx][col_idx] = avg
            gmean_data[row_idx][col_idx] = gmean
    # Prepend the header (should match).
    avg_data = [headers] + avg_data
    gmean_data = [headers] + gmean_data

    # Write the data to the csv files.
    with open(gmean_per_ter_qor_csv_file_path, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerows(gmean_data)
    with open(avg_per_ter_qor_csv_file_path, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerows(avg_data)

# Parse the per-iteration results into csv files.
def parse_iter_results(output_dir_path, per_iter_qor_dir_path, total_num_iterations):
    # Create a directory to hold the per iter qor data.
    os.makedirs(per_iter_qor_dir_path)

    # Parse the QoR results for each circuit and collect the CSV files for each
    # circuit.
    # TODO: It would be better if we created a text file listing all of the
    #       circuit names which is stored in common files.
    qor_csv_files = []
    common_files_dir_path = os.path.join(output_dir_path, "common_files")
    circuit_common_files_dir_paths = [ f.path for f in os.scandir(common_files_dir_path) if f.is_dir() ]
    for circuit_common_files_dir_path in circuit_common_files_dir_paths:
        circuit_name = os.path.basename(circuit_common_files_dir_path)
        circuit_per_iter_qor_dir_path = os.path.join(per_iter_qor_dir_path,
                                                     circuit_name)
        os.makedirs(circuit_per_iter_qor_dir_path)
        circuit_per_iter_qor_csv_file_path = os.path.join(circuit_per_iter_qor_dir_path,
                                                          "per_iter_qor.csv")
        success = parse_circuit_iter_results(output_dir_path,
                                             circuit_name,
                                             circuit_per_iter_qor_csv_file_path,
                                             total_num_iterations)
        if not success:
            print(f"Error: Failed to parse the results for circuit: {circuit_name}")
            return False
        qor_csv_files.append(circuit_per_iter_qor_csv_file_path)

    # Calculate the geoemean and average of all the circuit results.
    calc_gmean_and_avg_results(qor_csv_files, per_iter_qor_dir_path)

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
    test_suite_config_name = args.test_suite_name + "_config.txt"
    success = run_first_pass(os.path.join(args.configs_dir, test_suite_config_name),
                             output_dir_path,
                             args.vtr_dir,
                             args.j)
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
    total_num_iterations = args.num_iter
    for iter_num in range(total_num_iterations):
        success = run_single_iter(iter_num + 1, common_files_dir_path, args.j)
        if not success:
            print(f"Error: Iteration {iter_num + 1} failed.")
            return

    # Parse QoR data to a CSV file
    per_iter_qor_dir_path = os.path.join(output_dir_path, "per_iter_qor")
    success = parse_iter_results(output_dir_path, per_iter_qor_dir_path, total_num_iterations)
    if not success:
        print(f"Error: Failed to parse per iteration QoR data.")
        return

if __name__ == "__main__":
    run_vtr_feedback(sys.argv[1:])


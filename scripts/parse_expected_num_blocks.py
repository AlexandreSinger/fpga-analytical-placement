
import os
import argparse
import re

def get_folder_names(directory_path):
    """
    Returns a list of folder names within the specified directory.
    """
    folder_names = []
    for item in os.listdir(directory_path):
        item_path = os.path.join(directory_path, item)
        if os.path.isdir(item_path):
            folder_names.append(item)
    return folder_names

def parse_expected_blocks(ap_mass_report_file):
    expected_num_blocks = {}
    with open(ap_mass_report_file, 'r') as f:
        lines = f.readlines()

    start_parsing = False
    for line in lines:
        stripped_line = line.strip()
        if "Expected number of logical blocks:" in stripped_line:
            start_parsing = True
            continue
        if "Expected block utilization:" in stripped_line:
            break

        if not start_parsing:
            continue

        if ':' in stripped_line:
            parts = stripped_line.split(':', 1) # Split only on the first colon
            key = parts[0].strip()
            value_str = parts[1].strip()
            # Check if the key is one of the expected block types and value is a digit
            if key and value_str.isdigit():
                assert key not in expected_num_blocks
                expected_num_blocks[key] = int(value_str)
    return expected_num_blocks

def parse_actual_num_blocks(vpr_out_file):
    actual_num_blocks = {}
    with open(vpr_out_file, 'r') as f:
        lines = f.readlines()

    start_parsing = False
    for line in lines:
        stripped_line = line
        if "Final Clustering Statistics:" in stripped_line:
            start_parsing = True
            continue
        if not start_parsing:
            continue

        parts = re.split(r'\s{2,}', line.strip())

        if len(parts) >= 2:
            block_type = parts[0].strip()
            num_blocks_str = parts[1].strip()
            if block_type and num_blocks_str.isdigit():
                assert block_type not in actual_num_blocks
                actual_num_blocks[block_type] = int(num_blocks_str)
        else:
            break

    return actual_num_blocks

def get_logical_block_types(vpr_out_file):
    actual_num_blocks = parse_actual_num_blocks(vpr_out_file)
    logical_block_types = list(actual_num_blocks.keys())
    logical_block_types.sort()
    return logical_block_types



parser = argparse.ArgumentParser()
parser.add_argument("run_folder_dir")
args = parser.parse_args()
run_folder_dir = args.run_folder_dir

archs = get_folder_names(run_folder_dir)

assert len(archs) == 1

arch_folder_dir = os.path.join(run_folder_dir, archs[0])

circuits = get_folder_names(arch_folder_dir)
assert len(circuits) != 0

logical_block_types = get_logical_block_types(os.path.join(arch_folder_dir, circuits[0], 'common', 'vpr.out'))

print('circuit', end=', ')
for logical_block_type in logical_block_types:
    print(f"{logical_block_type}_expected", end=', ')
    print(f"{logical_block_type}_actual", end=', ')
    print(f"{logical_block_type}_error", end=', ')
print()

for circuit in circuits:
    circuit_common_dir = os.path.join(arch_folder_dir, circuit, 'common')
    ap_mass_report = os.path.join(circuit_common_dir, 'ap_mass.rpt')
    assert os.path.isfile(ap_mass_report)
    expected_num_blocks = parse_expected_blocks(ap_mass_report)
    vpr_out_file = os.path.join(circuit_common_dir, 'vpr.out')
    actual_num_blocks = parse_actual_num_blocks(vpr_out_file)
    print(circuit, end=', ')
    for logical_block_type in logical_block_types:
        expected_blocks = 0
        if logical_block_type in expected_num_blocks:
            expected_blocks = expected_num_blocks[logical_block_type]
        actual_blocks = 0
        if logical_block_type in actual_num_blocks:
            actual_blocks = actual_num_blocks[logical_block_type]
        print(expected_blocks, end=', ')
        print(actual_blocks, end=', ')
        if actual_blocks != 0:
            print(abs(expected_blocks - actual_blocks) / actual_blocks, end=', ')
        else:
            print(0, end=', ')
    print()

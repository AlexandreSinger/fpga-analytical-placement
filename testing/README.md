# get_intermediate_file.py manual
Step 1. Move a run### directory or run_vtr_task's config directory into the directory containing the script.

Step 2. `./fix_io.py circuit.v arch_desc.xml task_name`. If the run### exists, script prints the path to the directory containing all intermediate files. If the run### does not exist, run_vtr_task.py is called to run task named task_name and prints the path. 

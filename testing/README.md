# get_intermediate_file.py manual
Before running the script, create `<test_suite_name>_config.txt` for the corresponding test suite under the `configs` directory. An example config file would be `~/vtr-verilog-to-routing/vtr_flow/tasks/regression_tests/vtr_reg_basic/basic_no_timing/config/config.txt`. The config file contains lists of architecture description and test files, and more. 
```sh
./get_intermediate_file.py <test_suite_name> -vtr_path ~/vtr_verilog_to_routing -output_path ./tests
```
After running the commend, the output can be found in `./test/<test_suite_name>`.

# fix_io.py manual
Before running the script, add "vpr_args["write_vpr_constraints"] = os.path.join(temp_dir, os.path.basename(args.circuit_file)[:-2]+"_constraint.xml")" after line 557 of run_vtr_flow.py and then run get_intermediate_file.py.
```sh
./fix_io.py <test_suite_name> -output_path ./tests -input_path ./fix_io
```
After running the script, the output can be found in `./fix_io/<test_suite_name>`.

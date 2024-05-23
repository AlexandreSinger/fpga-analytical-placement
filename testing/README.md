# get_intermediate_file.py manual
Before running the script, create `<test_suite_name>_config.txt` for the corresponding test suite under the `configs` directory. An example config file would be `~/vtr-verilog-to-routing/vtr_flow/tasks/regression_tests/vtr_reg_basic/basic_no_timing/config/config.txt`. The config file contains lists of architecture description and test files, and more. 
```sh
./get_intermediate_file.py <test_suite_name> -vtr_path ~/vtr_verilog_to_routing -output_path ./tests
```
After running the commend, the output can be found in `./test/<test_suite_name>`.

# generate_fix_io.py manual
Before running the script, append `--write_vpr_constraints constraint.xml` after `script_params_common = ` and then run get_intermediate_file.py.
```sh
./generate_fix_io.py <test_suite_name> -input_path ./tests -output_path ./fix_io
```
After running the script, the output can be found in `./fix_io/<test_suite_name>`.

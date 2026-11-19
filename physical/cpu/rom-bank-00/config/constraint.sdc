create_clock -name core_clock -period 10.000 [get_ports sys_clk]
set_input_delay 3.0 -clock core_clock [get_ports {address[*]}]
set_output_delay 5.0 -clock core_clock [get_ports {data[*]}]
set_load 0.03 [all_outputs]

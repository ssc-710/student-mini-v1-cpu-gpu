set clk_period 10.000
create_clock -name core_clock -period $clk_period [get_ports clk_i]
# OpenSTA supports collection filters but not Synopsys remove_from_collection.
set data_inputs [get_ports -filter "direction == input && name != clk_i" *]
set_input_delay 0.5 -clock core_clock $data_inputs
set_output_delay 0.5 -clock core_clock [all_outputs]

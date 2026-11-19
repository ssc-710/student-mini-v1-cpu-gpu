set_io_pin_constraint -pin_names [concat [get_ports sys_clk] [get_ports {address[*]}] [get_ports {data[*]}]] -region bottom:*

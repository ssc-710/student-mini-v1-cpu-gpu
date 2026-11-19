# Hardened quadrant blocks at their quadrant origins.
place_macro -macro_name {vortex_physical_top_q0_inst} -location {15.640 15.640} -orientation R0 -exact
place_macro -macro_name {vortex_physical_top_q1_inst} -location {3753.600 15.640} -orientation R0 -exact
place_macro -macro_name {vortex_physical_top_q2_inst} -location {15.640 3753.600} -orientation R0 -exact
place_macro -macro_name {vortex_physical_top_q3_inst} -location {3753.600 3753.600} -orientation R0 -exact
cut_rows -halo_width_x 2 -halo_width_y 2

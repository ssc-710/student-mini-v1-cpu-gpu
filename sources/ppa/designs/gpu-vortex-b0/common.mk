export PLATFORM = sky130hd
export DESIGN_NAME = vortex_physical_top
$(if $(GPU_PROJECT),,$(error GPU_PROJECT must bind one frozen Vortex profile))
$(if $(GPU_BLACKBOXES),,$(error GPU_BLACKBOXES must bind generated macro declarations))

include $(COURSE_ROOT)/ppa/designs/gpu-vortex-b0/macro-inputs-banked.mk
export VERILOG_FILES = \
  $(GPU_PROJECT) \
  $(GPU_BLACKBOXES) \
  $(COURSE_ROOT)/shared/rtl/vortex_banked_large_sram_wrappers.sv \
  $(COURSE_ROOT)/shared/rtl/vortex_command_adapter.sv \
  $(COURSE_ROOT)/shared/rtl/vortex_memory_adapter.sv \
  $(COURSE_ROOT)/shared/rtl/vortex_physical_top.sv
export VERILOG_FILES_BLACKBOX = $(GPU_BLACKBOXES)
export SYNTH_BLACKBOXES = vortex_dp_80x64_w4 \
  vortex_sp_32x256_w1 vortex_sp_32x512_w4 vortex_sp_32x1024_w4 \
  vortex_sp_64x128_w8 vortex_sp_128x128_w16
export SDC_FILE = $(COURSE_ROOT)/ppa/common/constraint.sdc
export PRE_PDN_TCL = $(COURSE_ROOT)/ppa/openram/connect_openram_power.tcl
export PLACE_DENSITY = 0.25
# Full parameterized Vortex synthesis contains legitimate distributed
# scheduler/register arrays up to 9,952 bits after the large SRAM shapes have
# been replaced by the audited banked OpenRAM macros.  Keep the guard just
# above that measured maximum so an accidental large inferred SRAM still
# fails before placement.
export SYNTH_MEMORY_MAX_BITS = 10000
export SKIP_CTS_REPAIR_TIMING = 1
export SKIP_INCREMENTAL_REPAIR = 1
export PWR_NETS_VOLTAGES =
export GND_NETS_VOLTAGES =

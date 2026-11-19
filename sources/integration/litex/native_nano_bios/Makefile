# Use the locked upstream BIOS, without registering historical course hooks.
# Prerequisites expand when their rule is read: changing OBJECTS after including
# the course Makefile cannot remove its already registered dependencies.
include ../include/generated/variables.mak
override BIOS_DIRECTORY := $(SOC_DIRECTORY)/software/bios
UPSTREAM_BIOS_DIRECTORY := $(BIOS_DIRECTORY)
include $(UPSTREAM_BIOS_DIRECTORY)/Makefile
COURSE_MINI_ENTRY_OBJECTS ?= student_mini_native_session.o
OBJECTS += $(COURSE_MINI_ENTRY_OBJECTS) student_mini_native_nano.o operator_scalar.o
bios.elf: $(COURSE_MINI_ENTRY_OBJECTS) student_mini_native_nano.o operator_scalar.o
CFLAGS += -ffp-contract=off -fno-fast-math -I$(UPSTREAM_BIOS_DIRECTORY) -I$(COURSE_NATIVE_IMAGE_DIR) -I$(COURSE_ROOT)/software/include
VPATH = $(COURSE_ROOT)/integration/litex/native_nano_bios:$(COURSE_ROOT)/software:$(UPSTREAM_BIOS_DIRECTORY):$(UPSTREAM_BIOS_DIRECTORY)/cmds:$(CPU_DIRECTORY)

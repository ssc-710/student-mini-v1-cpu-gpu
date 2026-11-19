# One immutable ROM contains both the baseline and native Nano programs.
COURSE_MINI_ENTRY_OBJECTS := student_mini_baseline_entry.o student_mini_scalar.o student_mini_native_entry.o
include $(COURSE_ROOT)/integration/litex/native_nano_bios/Makefile
CFLAGS += -DCOURSE_MINI_BASELINE_RECORD_COUNT=$(COURSE_MINI_BASELINE_RECORD_COUNT) -DCOURSE_NATIVE_BASE_OFFSET=$(COURSE_NATIVE_BASE_OFFSET)
VPATH := $(COURSE_ROOT)/integration/litex/combined_mini_bios:$(VPATH)

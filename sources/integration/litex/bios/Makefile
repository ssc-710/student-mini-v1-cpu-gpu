include ../include/generated/variables.mak
include $(SOC_DIRECTORY)/software/common.mak

UPSTREAM_BIOS_DIRECTORY := $(SOC_DIRECTORY)/software/bios
CFLAGS += -I$(UPSTREAM_BIOS_DIRECTORY)

COURSE_PROMOTION_CANDIDATE ?=
CPU_RUNTIME_CANDIDATES := CPU-P1-R1-fixed-runtime CPU-P2-R1-fixed-merge-runtime CPU-P3-R1-rv32-packed-int8
CPU_ALGORITHM_CANDIDATES := CPU-P1-A1-stream-topk-mla CPU-P2-A1-radix16-canonical CPU-P3-A1-expert-group-empty-skip
CPU_MICROARCH_CANDIDATES := CPU-P1-M1-page-cache-double-buffer CPU-P2-M1-split-double-buffer CPU-P3-M1-weight-stationary-blocking
CPU_PHYSICAL_CANDIDATES := CPU-P1-P1-low-power-physical CPU-P2-P1-low-power-physical CPU-P3-P1-low-power-physical
ifneq ($(COURSE_PROMOTION_CANDIDATE),)
ifneq ($(filter $(COURSE_PROMOTION_CANDIDATE),$(CPU_RUNTIME_CANDIDATES)),)
CFLAGS += -DCOURSE_PROMOTION_RUNTIME_INLINE=1 \
	-DCOURSE_PROMOTION_CANDIDATE_ID=\"$(COURSE_PROMOTION_CANDIDATE)\"
ifeq ($(COURSE_PROMOTION_CANDIDATE),CPU-P3-R1-rv32-packed-int8)
CFLAGS += -DCOURSE_PROMOTION_PACKED_INT8=1
endif
else ifneq ($(filter $(COURSE_PROMOTION_CANDIDATE),$(CPU_ALGORITHM_CANDIDATES)),)
CFLAGS += -DCOURSE_PROMOTION_RUNTIME_INLINE=1 \
	-DCOURSE_PROMOTION_CANDIDATE_ID=\"$(COURSE_PROMOTION_CANDIDATE)\"
ifeq ($(COURSE_PROMOTION_CANDIDATE),CPU-P1-A1-stream-topk-mla)
CFLAGS += -DCOURSE_PROMOTION_P1_STREAM_TOPK=1
else ifeq ($(COURSE_PROMOTION_CANDIDATE),CPU-P2-A1-radix16-canonical)
CFLAGS += -DCOURSE_PROMOTION_P2_RADIX16_CANONICAL=1
else ifeq ($(COURSE_PROMOTION_CANDIDATE),CPU-P3-A1-expert-group-empty-skip)
CFLAGS += -DCOURSE_PROMOTION_P3_EXPERT_GROUP_SKIP=1
endif
else ifneq ($(filter $(COURSE_PROMOTION_CANDIDATE),$(CPU_MICROARCH_CANDIDATES)),)
CFLAGS += -DCOURSE_PROMOTION_RUNTIME_INLINE=1 \
	-DCOURSE_PROMOTION_CANDIDATE_ID=\"$(COURSE_PROMOTION_CANDIDATE)\"
ifeq ($(COURSE_PROMOTION_CANDIDATE),CPU-P1-M1-page-cache-double-buffer)
CFLAGS += -DCOURSE_PROMOTION_P1_STREAM_TOPK=1 \
	-DCOURSE_PROMOTION_P1_PAGE_CACHE_DOUBLE_BUFFER=1
else ifeq ($(COURSE_PROMOTION_CANDIDATE),CPU-P2-M1-split-double-buffer)
CFLAGS += -DCOURSE_PROMOTION_P2_RADIX16_CANONICAL=1 \
	-DCOURSE_PROMOTION_P2_SPLIT_DOUBLE_BUFFER=1
else ifeq ($(COURSE_PROMOTION_CANDIDATE),CPU-P3-M1-weight-stationary-blocking)
CFLAGS += -DCOURSE_PROMOTION_P3_EXPERT_GROUP_SKIP=1 \
	-DCOURSE_PROMOTION_P3_WEIGHT_STATIONARY_BLOCKING=1
endif
else ifneq ($(filter $(COURSE_PROMOTION_CANDIDATE),$(CPU_PHYSICAL_CANDIDATES)),)
CFLAGS += -DCOURSE_PROMOTION_RUNTIME_INLINE=1 \
	-DCOURSE_PROMOTION_CANDIDATE_ID=\"$(COURSE_PROMOTION_CANDIDATE)\"
ifeq ($(COURSE_PROMOTION_CANDIDATE),CPU-P1-P1-low-power-physical)
CFLAGS += -DCOURSE_PROMOTION_P1_STREAM_TOPK=1 \
	-DCOURSE_PROMOTION_P1_PAGE_CACHE_DOUBLE_BUFFER=1
else ifeq ($(COURSE_PROMOTION_CANDIDATE),CPU-P2-P1-low-power-physical)
CFLAGS += -DCOURSE_PROMOTION_P2_RADIX16_CANONICAL=1 \
	-DCOURSE_PROMOTION_P2_SPLIT_DOUBLE_BUFFER=1
else ifeq ($(COURSE_PROMOTION_CANDIDATE),CPU-P3-P1-low-power-physical)
CFLAGS += -DCOURSE_PROMOTION_P3_EXPERT_GROUP_SKIP=1 \
	-DCOURSE_PROMOTION_P3_WEIGHT_STATIONARY_BLOCKING=1
endif
else
$(error unsupported CPU promotion candidate $(COURSE_PROMOTION_CANDIDATE))
endif
endif

OBJECTS = boot-helper.o boot.o helpers.o cmd_bios.o cmd_mem.o cmd_boot.o \
	cmd_i2c.o cmd_spiflash.o cmd_litedram.o cmd_liteeth.o cmd_litesdcard.o \
	cmd_litesata.o sim_debug.o main.o nano_control_smoke.o nano_session.o \
	cpu_operator_b0.o operator_scalar.o crt0.o

ifeq ($(COURSE_STUDENT_MINI),1)
OBJECTS += student_mini_session.o student_mini_scalar.o
endif

ifneq "$(or $(BIOS_CONSOLE_NO_AUTOCOMPLETE),$(BIOS_CONSOLE_LITE))" ""
CFLAGS += -DBIOS_CONSOLE_NO_AUTOCOMPLETE
else
OBJECTS += complete.o
endif

ifdef BIOS_CONSOLE_NO_HISTORY
CFLAGS += -DBIOS_CONSOLE_NO_HISTORY
endif
ifdef BIOS_CONSOLE_DISABLE
CFLAGS += -DBIOS_CONSOLE_DISABLE
endif
ifdef BIOS_CONSOLE_LITE
CFLAGS += -DBIOS_CONSOLE_LITE
OBJECTS += readline_simple.o
else
OBJECTS += readline.o
endif

ifeq ($(CPU), zynq7000)
LSCRIPT = linker-zynq.ld
else ifeq ($(CPU), zynqmp)
LSCRIPT = linker-zynqmp.ld
else
LSCRIPT = linker.ld
endif

all: bios.bin
	$(PYTHON) -m litex.soc.software.memusage bios.elf $(CURDIR)/../include/generated/regions.ld $(TRIPLE)

%.bin: %.elf
	$(OBJCOPY) -O binary $< $@
ifneq ($(OS),Windows_NT)
	chmod -x $@
endif
ifeq ($(CPUENDIANNESS),little)
	$(PYTHON) -m litex.soc.software.crcfbigen $@ --little
else
	$(PYTHON) -m litex.soc.software.crcfbigen $@
endif

bios.elf: $(UPSTREAM_BIOS_DIRECTORY)/$(LSCRIPT) $(OBJECTS)

vpath %.a $(PACKAGES:%=../%)

%.elf: crt0.o $(LIBS:%=%.a)
	$(CC) $(LDFLAGS) -T $(UPSTREAM_BIOS_DIRECTORY)/$(LSCRIPT) -N -o $@ \
		$(OBJECTS) $(PACKAGES:%=-L../%) -Wl,--start-group \
		$(LIBS:lib%=-l%) -Wl,--end-group -Wl,--gc-sections -Wl,-Map,$@.map

ifneq ($(OS),Windows_NT)
	chmod -x $@
endif

-include $(OBJECTS:.o=.d)

VPATH = $(BIOS_DIRECTORY):$(BIOS_DIRECTORY)/../../../software:$(UPSTREAM_BIOS_DIRECTORY):$(UPSTREAM_BIOS_DIRECTORY)/cmds:$(CPU_DIRECTORY)

%.o: %.c
	$(compile)
%.o: %.S
	$(assemble)

clean:
	$(RM) $(OBJECTS) bios.elf bios.bin .*~ *~

.PHONY: all clean

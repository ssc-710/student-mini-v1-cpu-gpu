// SPDX-License-Identifier: Apache-2.0
#ifndef OPEN_SOC_AI_ACCELERATOR_H_
#define OPEN_SOC_AI_ACCELERATOR_H_

#include <stdint.h>

#define ACCEL_BASE 0x40000000u
#define ACCEL_CONTROL (*(volatile uint32_t *)(ACCEL_BASE + 0x00u))
#define ACCEL_OPCODE (*(volatile uint32_t *)(ACCEL_BASE + 0x04u))
#define ACCEL_DESCRIPTOR (*(volatile uint32_t *)(ACCEL_BASE + 0x08u))
#define ACCEL_IRQ_CLEAR (*(volatile uint32_t *)(ACCEL_BASE + 0x0cu))
#define ACCEL_RESULT_STATUS (*(volatile uint32_t *)(ACCEL_BASE + 0x10u))
#define ACCEL_CYCLES_LO (*(volatile uint32_t *)(ACCEL_BASE + 0x14u))
#define ACCEL_CYCLES_HI (*(volatile uint32_t *)(ACCEL_BASE + 0x18u))

enum accelerator_opcode { ACCEL_PREFILL=1, ACCEL_DECODE=2, ACCEL_MOE=3, ACCEL_BLOCK=4 };

struct __attribute__((packed, aligned(16))) accelerator_descriptor {
  uint32_t header, batch, q_tokens, kv_tokens;
  uint32_t q_addr, kv_addr, page_addr, length_addr;
  uint32_t aux0_addr, aux1_addr, weight_addr, scale_addr;
  uint32_t output_addr, scratch_addr, config, reserved;
};

static inline void accelerator_start(enum accelerator_opcode opcode, const struct accelerator_descriptor *desc) {
  ACCEL_OPCODE=(uint32_t)opcode; ACCEL_DESCRIPTOR=(uint32_t)(uintptr_t)desc; ACCEL_CONTROL=1u;
}
static inline int accelerator_busy(void){return (ACCEL_CONTROL&1u)!=0u;}
static inline int accelerator_done(void){return (ACCEL_CONTROL&2u)!=0u;}
static inline uint64_t accelerator_cycles(void){uint32_t lo=ACCEL_CYCLES_LO,hi=ACCEL_CYCLES_HI;return ((uint64_t)hi<<32)|lo;}
static inline void accelerator_clear_irq(void){ACCEL_IRQ_CLEAR=1u;}

#endif

// SPDX-License-Identifier: Apache-2.0
#ifndef OPEN_SOC_AI_ACCELERATOR_LITEX_H_
#define OPEN_SOC_AI_ACCELERATOR_LITEX_H_

#include <stdint.h>
#include <generated/mem.h>

#include "accelerator.h"

/* ACCELERATOR_BASE is emitted by LiteX from the named Wishbone region. */
#define LITEX_ACCEL_REG(offset) (*(volatile uint32_t *)(ACCELERATOR_BASE + (offset)))

static inline void litex_accelerator_start(
    enum accelerator_opcode opcode,
    const struct accelerator_descriptor *descriptor) {
  LITEX_ACCEL_REG(0x04u) = (uint32_t)opcode;
  LITEX_ACCEL_REG(0x08u) = (uint32_t)(uintptr_t)descriptor;
  LITEX_ACCEL_REG(0x00u) = 1u;
}

static inline int litex_accelerator_busy(void) { return (LITEX_ACCEL_REG(0x00u) & 1u) != 0u; }
static inline int litex_accelerator_done(void) { return (LITEX_ACCEL_REG(0x00u) & 2u) != 0u; }
static inline uint32_t litex_accelerator_status(void) { return LITEX_ACCEL_REG(0x10u); }

static inline uint64_t litex_accelerator_cycles(void) {
  /* Low read latches the hardware snapshot; high completes the same snapshot. */
  uint32_t low = LITEX_ACCEL_REG(0x14u);
  uint32_t high = LITEX_ACCEL_REG(0x18u);
  return ((uint64_t)high << 32) | low;
}

static inline void litex_accelerator_clear_irq(void) { LITEX_ACCEL_REG(0x0cu) = 1u; }

#endif

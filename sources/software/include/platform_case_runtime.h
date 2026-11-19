// SPDX-License-Identifier: Apache-2.0
// Portable descriptor validation shared by VexRiscv C and Vortex CUDA B0.
#ifndef COURSE_PLATFORM_CASE_RUNTIME_H
#define COURSE_PLATFORM_CASE_RUNTIME_H

#include "platform_case_table_generated.h"

#define COURSE_STATUS_OK 0u
#define COURSE_STATUS_BAD_DESCRIPTOR 1u
#define COURSE_STATUS_BAD_LENGTH 2u
#define COURSE_STATUS_BAD_PAGE 3u
#define COURSE_STATUS_BUS_ERROR 4u
#define COURSE_STATUS_NUMERIC_ERROR 5u

#define COURSE_CASE_ZERO_PRIMARY       (1u << 0)
#define COURSE_CASE_BAD_OPCODE         (1u << 1)
#define COURSE_CASE_NONSTANDARD_PAGE   (1u << 2)
#define COURSE_CASE_SHORT_PAGE_TABLE   (1u << 3)
#define COURSE_CASE_INVALID_PAGE       (1u << 4)
#define COURSE_CASE_DMA_FAULT          (1u << 5)
#define COURSE_CASE_INVALID_SPLIT      (1u << 6)
#define COURSE_CASE_SPLIT_GT_LENGTH    (1u << 7)
#define COURSE_CASE_INVALID_EXPERT     (1u << 8)
#define COURSE_CASE_INVALID_SCALE      (1u << 9)

#if defined(__CUDACC__)
#define COURSE_HD __host__ __device__
#else
#define COURSE_HD
#endif

COURSE_HD static unsigned course_platform_validate_case(
    const course_platform_case_t *item
) {
    const unsigned flags = item->scenario_flags;
    if (item->operator_id == 1u) {
        if (flags & COURSE_CASE_ZERO_PRIMARY) return COURSE_STATUS_BAD_LENGTH;
        if (flags & (COURSE_CASE_BAD_OPCODE | COURSE_CASE_NONSTANDARD_PAGE))
            return COURSE_STATUS_BAD_DESCRIPTOR;
        if (flags & (COURSE_CASE_SHORT_PAGE_TABLE | COURSE_CASE_INVALID_PAGE))
            return COURSE_STATUS_BAD_PAGE;
    } else if (item->operator_id == 2u) {
        if (flags & (COURSE_CASE_ZERO_PRIMARY | COURSE_CASE_SPLIT_GT_LENGTH))
            return COURSE_STATUS_BAD_LENGTH;
        if (flags & (COURSE_CASE_INVALID_SPLIT | COURSE_CASE_NONSTANDARD_PAGE))
            return COURSE_STATUS_BAD_DESCRIPTOR;
        if (flags & (COURSE_CASE_SHORT_PAGE_TABLE | COURSE_CASE_INVALID_PAGE))
            return COURSE_STATUS_BAD_PAGE;
    } else if (item->operator_id == 3u) {
        if (flags & (
            COURSE_CASE_ZERO_PRIMARY | COURSE_CASE_BAD_OPCODE |
            COURSE_CASE_INVALID_EXPERT
        )) return COURSE_STATUS_BAD_DESCRIPTOR;
        if (flags & COURSE_CASE_INVALID_SCALE) return COURSE_STATUS_NUMERIC_ERROR;
    } else {
        return COURSE_STATUS_BAD_DESCRIPTOR;
    }
    if (flags & COURSE_CASE_DMA_FAULT) return COURSE_STATUS_BUS_ERROR;
    return COURSE_STATUS_OK;
}

#undef COURSE_HD
#endif

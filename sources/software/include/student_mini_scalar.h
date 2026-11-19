// SPDX-License-Identifier: Apache-2.0
#ifndef STUDENT_MINI_SCALAR_H
#define STUDENT_MINI_SCALAR_H
#include <stdint.h>
// Input-only wire record: 32 little-endian words, then fixed INT8 tensors.
// No golden values or expected status are present in the executable input.
#define STUDENT_MINI_RECORD_BYTES 1936u
typedef struct {
    uint32_t status, count, selected_count;
    uint16_t output[32];
    uint8_t selected[8];
    int32_t primitive;
} student_mini_result;
void student_mini_execute(const uint8_t *record, student_mini_result *result);
#endif

// SPDX-License-Identifier: Apache-2.0
#include <generated/mem.h>
// Only this translation unit's model image is relocated past baseline inputs.
#undef MAIN_RAM_BASE
#define MAIN_RAM_BASE (0x40000000u + COURSE_NATIVE_BASE_OFFSET)
#include "student_mini_native_session_v2.c"

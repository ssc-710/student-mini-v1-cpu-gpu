// SPDX-License-Identifier: Apache-2.0
// The loader's block count is transport metadata, not the baseline case count.
#include <generated/soc.h>
#undef COURSE_STUDENT_MINI_COUNT
#define COURSE_STUDENT_MINI_COUNT COURSE_MINI_BASELINE_RECORD_COUNT
#include "../bios/student_mini_session.c"

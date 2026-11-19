#include "student_mini_native_nano.h"
#include "operator_scalar.h"

/*
 * RV32-oriented two-output blocking candidate.  Four-output blocking keeps
 * eight projection accumulators live and can force spills on a small integer
 * register file.  This variant limits that live set to four while retaining
 * row-major x reuse.  It is deliberately a separate symbol for ablation.
 */
static int8_t p3_pair_requant_q6(int64_t value) {
    uint64_t mag = value < 0 ? (uint64_t)(-value) : (uint64_t)value;
    uint64_t q = mag >> 16, r = mag & 65535u;
    q += r > 32768u || (r == 32768u && (q & 1u));
    return value < 0 ? (q >= 128u ? -128 : -(int8_t)q)
                     : (q >= 127u ? 127 : (int8_t)q);
}

int p3_native_candidate_pair(void *user, unsigned expert, const int8_t *x,
                             float input_scale, const mini_native_model *m,
                             uint16_t *out) {
    (void)user;
    if (expert > 2) return -1;
    const unsigned shared = expert == 2;
    const unsigned gate = shared ? MINI_SHARED_GATE : MINI_GATE;
    const unsigned up = shared ? MINI_SHARED_UP : MINI_UP;
    const unsigned down = shared ? MINI_SHARED_DOWN : MINI_DOWN;
    const unsigned offset = shared ? 0 : expert * 256;
    const int8_t *gw = m->weight[gate] + offset;
    const int8_t *uw = m->weight[up] + offset;
    const int8_t *dw = m->weight[down] + offset;
    const float gs = input_scale * m->scale[gate];
    const float us = input_scale * m->scale[up];
    const float ds = 0x1p-6f * m->scale[down];
    int8_t intermediate[16];

    for (unsigned j = 0; j < 16; j += 2) {
        int32_t g0 = 0, g1 = 0, u0 = 0, u1 = 0;
        const int8_t *gp = gw + j, *up = uw + j;
        for (unsigned k = 0; k < 16; ++k, gp += 16, up += 16) {
            const int32_t a = x[k];
            g0 += a * gp[0]; g1 += a * gp[1];
            u0 += a * up[0]; u1 += a * up[1];
        }
        int16_t gq0, gq1, uq0, uq1;
        if (course_int32_scale_to_q5_11(g0, gs, &gq0) ||
            course_int32_scale_to_q5_11(g1, gs, &gq1) ||
            course_int32_scale_to_q5_11(u0, us, &uq0) ||
            course_int32_scale_to_q5_11(u1, us, &uq1)) return -2;
        intermediate[j] = p3_pair_requant_q6((int64_t)course_silu_q11(gq0) * uq0);
        intermediate[j + 1] = p3_pair_requant_q6((int64_t)course_silu_q11(gq1) * uq1);
    }

    for (unsigned j = 0; j < 16; j += 2) {
        int32_t a0 = 0, a1 = 0;
        const int8_t *dp = dw + j;
        for (unsigned k = 0; k < 16; ++k, dp += 16) {
            const int32_t v = intermediate[k];
            a0 += v * dp[0]; a1 += v * dp[1];
        }
        out[j] = course_bf16_rne_bits((float)a0 * ds);
        out[j + 1] = course_bf16_rne_bits((float)a1 * ds);
    }
    return 0;
}

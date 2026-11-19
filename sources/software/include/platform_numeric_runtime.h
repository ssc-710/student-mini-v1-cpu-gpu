// SPDX-License-Identifier: Apache-2.0
// Portable fixed-point probe runtime. Expected signatures are never embedded.
#ifndef COURSE_PLATFORM_NUMERIC_RUNTIME_H
#define COURSE_PLATFORM_NUMERIC_RUNTIME_H

#include <limits.h>
#include <stdint.h>

#include "numeric_luts.h"
#include "operator_scalar.h"
#include "platform_case_table_generated.h"

#if defined(__CUDACC__)
#define COURSE_NUMERIC_HD __host__ __device__
#define COURSE_NUMERIC_NOOPT __attribute__((noinline, optnone))
#else
#define COURSE_NUMERIC_HD
#define COURSE_NUMERIC_NOOPT
#endif

#define COURSE_PROBE_TIE          (1u << 0)
#define COURSE_PROBE_LATE_MAXIMUM (1u << 1)
#define COURSE_PROBE_EXTREMA      (1u << 2)

#if defined(COURSE_PROMOTION_CANDIDATE_ID) && !defined(__CUDACC__)
__attribute__((used, section(".rodata.promotion")))
static const char course_promotion_candidate_identity[] =
    COURSE_PROMOTION_CANDIDATE_ID;
#endif

/* Runtime R1: keep the exact scalar contract but make the fixed-point/LUT
 * primitives visible to the RV32 compiler.  B0 deliberately calls the
 * separately compiled oracle in operator_scalar.c.  This candidate is a real
 * executable change; its outputs remain checked against the independent
 * Python oracle before any performance number is accepted. */
#if defined(COURSE_PROMOTION_RUNTIME_INLINE) && !defined(__CUDACC__)
#define COURSE_PROMOTION_INLINE static inline __attribute__((always_inline))

COURSE_PROMOTION_INLINE uint32_t course_promotion_float_bits(float value) {
    union { float f; uint32_t u; } bits = {value};
    return bits.u;
}

COURSE_PROMOTION_INLINE uint64_t course_promotion_round_even_u64(
    uint64_t numerator, uint64_t denominator
) {
    uint64_t quotient, remainder;
    if (denominator && !(denominator & (denominator - 1u))) {
        unsigned shift = 0;
        for (uint64_t probe = denominator; probe > 1u; probe >>= 1) ++shift;
        quotient = numerator >> shift;
        remainder = numerator & (denominator - 1u);
    } else {
        quotient = numerator / denominator;
        remainder = numerator % denominator;
    }
    uint64_t half = denominator >> 1;
    if (remainder > half || (remainder == half && !(denominator & 1u) &&
                             (quotient & 1u))) ++quotient;
    return quotient;
}

COURSE_PROMOTION_INLINE int32_t course_promotion_round_q11_to_q6(int32_t value) {
    uint32_t raw = (uint32_t)value;
    uint32_t sign_mask = 0u - (raw >> 31);
    uint32_t magnitude = (raw ^ sign_mask) - sign_mask;
    uint32_t quotient = magnitude >> 5;
    uint32_t remainder = magnitude & 31u;
    if (remainder > 16u || (remainder == 16u && (quotient & 1u))) ++quotient;
    return value < 0 ? -(int32_t)quotient : (int32_t)quotient;
}

COURSE_PROMOTION_INLINE uint16_t course_promotion_bf16_rne_bits(float value) {
    uint32_t bits = course_promotion_float_bits(value);
    uint32_t upper = bits >> 16;
    uint32_t lower = bits & 0xffffu;
    if (lower > 0x8000u || (lower == 0x8000u && (upper & 1u))) ++upper;
    return (uint16_t)upper;
}

COURSE_PROMOTION_INLINE uint16_t course_promotion_exp_neg_q15(int32_t value) {
    if (value > 0) value = 0;
    if (value < -32768) value = -32768;
    return course_exp_q15_q6_lut[course_promotion_round_q11_to_q6(value) + 1024];
}

COURSE_PROMOTION_INLINE int16_t course_promotion_silu_q11(int32_t value) {
    if (value > 32767) value = 32767;
    if (value < -32768) value = -32768;
    int32_t index = course_promotion_round_q11_to_q6(value);
    if (index > 1024) index = 1024;
    if (index < -1024) index = -1024;
    return course_silu_q11_q6_lut[index + 1024];
}

COURSE_PROMOTION_INLINE int course_promotion_int32_scale_to_q5_11(
    int32_t value, float scale, int16_t *result
) {
    if (!result) return -1;
    uint32_t bits = course_promotion_float_bits(scale);
    if ((bits & 0x7f800000u) == 0x7f800000u || !(bits & 0x7fffffffu) ||
        scale < 0x1p-16f || scale > 0x1p16f) return -2;
    int exponent = (int)((bits >> 23) & 0xffu);
    uint64_t significand = UINT64_C(0x800000) | (bits & 0x7fffffu);
    uint64_t raw = (uint64_t)(int64_t)value;
    uint64_t sign_mask = UINT64_C(0) - (raw >> 63);
    uint64_t magnitude = (raw ^ sign_mask) - sign_mask;
    uint64_t product = magnitude * significand;
    int shift = exponent - 139;
    uint64_t scaled = shift >= 0 ? product << shift
        : course_promotion_round_even_u64(product, UINT64_C(1) << -shift);
    if (value < 0) *result = scaled >= 32768u ? INT16_MIN : (int16_t)-(int32_t)scaled;
    else *result = scaled >= 32767u ? INT16_MAX : (int16_t)scaled;
    return 0;
}

COURSE_PROMOTION_INLINE int course_promotion_q22_requantize_int8(
    int64_t value, float scale, int8_t *result
) {
    if (!result) return -1;
    uint32_t bits = course_promotion_float_bits(scale);
    if ((bits & 0x7f800000u) == 0x7f800000u || !(bits & 0x7fffffffu) ||
        scale < 0x1p-16f || scale > 0x1p16f) return -2;
    if (value < -INT64_C(140737488355328) ||
        value > INT64_C(140737488355327)) return -3;
    int exponent = (int)((bits >> 23) & 0xffu);
    uint64_t significand = UINT64_C(0x800000) | (bits & 0x7fffffu);
    uint64_t raw = (uint64_t)value;
    uint64_t sign_mask = UINT64_C(0) - (raw >> 63);
    uint64_t magnitude = (raw ^ sign_mask) - sign_mask;
    int shift = 128 - exponent;
    uint64_t numerator;
    if (shift >= 0) {
        if (magnitude > (UINT64_MAX >> shift)) {
            *result = value < 0 ? INT8_MIN : INT8_MAX;
            return 0;
        }
        numerator = magnitude << shift;
    } else numerator = magnitude >> -shift;
    uint64_t rounded = course_promotion_round_even_u64(numerator, significand);
    if (value < 0) *result = rounded >= 128u ? INT8_MIN : (int8_t)-(int32_t)rounded;
    else *result = rounded >= 127u ? INT8_MAX : (int8_t)rounded;
    return 0;
}

#define course_bf16_rne_bits course_promotion_bf16_rne_bits
#define course_exp_neg_q15 course_promotion_exp_neg_q15
#define course_silu_q11 course_promotion_silu_q11
#define course_int32_scale_to_q5_11 course_promotion_int32_scale_to_q5_11
#define course_q22_requantize_int8 course_promotion_q22_requantize_int8
#endif

typedef struct {
    int32_t maximum_q11;
    int32_t denominator_q15;
    int64_t weighted_q15;
    unsigned valid;
} course_probe_softmax_t;

COURSE_NUMERIC_HD static uint32_t course_probe_lcg(uint32_t *state) {
    *state = UINT32_C(1664525) * *state + UINT32_C(1013904223);
    return *state;
}

#if defined(COURSE_PROMOTION_P2_RADIX16_CANONICAL) && \
    !defined(COURSE_PROMOTION_P2_SPLIT_DOUBLE_BUFFER)
/* Advance the frozen LCG without materialising discarded prefix elements.
 * Unsigned overflow is the specified modulo-2^32 arithmetic. */
COURSE_NUMERIC_HD static uint32_t course_probe_lcg_advance(
    uint32_t state, uint32_t delta
) {
    uint32_t accumulated_multiplier = 1u;
    uint32_t accumulated_increment = 0u;
    uint32_t current_multiplier = UINT32_C(1664525);
    uint32_t current_increment = UINT32_C(1013904223);
    while (delta) {
        if (delta & 1u) {
            accumulated_multiplier *= current_multiplier;
            accumulated_increment =
                accumulated_increment * current_multiplier + current_increment;
        }
        current_increment *= current_multiplier + 1u;
        current_multiplier *= current_multiplier;
        delta >>= 1;
    }
    return accumulated_multiplier * state + accumulated_increment;
}
#endif

COURSE_NUMERIC_HD static int8_t course_probe_i8(uint32_t *state) {
    return (int8_t)((int32_t)(course_probe_lcg(state) >> 24) - 128);
}

COURSE_NUMERIC_HD static uint32_t course_probe_fnv_word(uint32_t digest, uint32_t word) {
    for (unsigned shift = 0; shift < 32; shift += 8) {
        digest ^= (word >> shift) & 0xffu;
        digest *= UINT32_C(0x01000193);
    }
    return digest;
}

COURSE_NUMERIC_HD COURSE_NUMERIC_NOOPT static int64_t course_probe_round_even(
    int64_t numerator, int64_t denominator
) {
    unsigned negative = numerator < 0;
    uint64_t raw = (uint64_t)numerator;
    uint64_t sign_mask = UINT64_C(0) - (raw >> 63);
    uint64_t magnitude = (raw ^ sign_mask) - sign_mask;
    uint64_t divisor = (uint64_t)denominator;
    uint64_t quotient, remainder;
    if (divisor && !(divisor & (divisor - 1u))) {
        unsigned shift = 0;
        for (uint64_t probe = divisor; probe > 1u; probe >>= 1) ++shift;
        quotient = magnitude >> shift;
        remainder = magnitude & (divisor - 1u);
#if defined(COURSE_PROMOTION_GPU_CORRECTED_QUOTIENT)
    } else if (divisor && divisor <= 0xffffffu &&
               magnitude <= divisor * UINT64_C(0xffffff)) {
        /* Estimate only: exact unsigned products/remainders recover floor(n/d)
         * before the unchanged RNE step. Bounds keep the float-to-u32 cast
         * and correction products representable; other inputs use division.
         * The volatile split prevents chipStar from emitting an unsupported
         * OpenCL mad helper even with frontend fp-contract=off. */
        float high = (float)(uint32_t)(magnitude >> 32);
        float low = (float)(uint32_t)magnitude;
        volatile float scaled_high = high * 4294967296.0f;
        quotient = (uint32_t)((scaled_high + low) / (float)(uint32_t)divisor);
        uint64_t product = quotient * divisor;
        while (product > magnitude) { --quotient; product -= divisor; }
        remainder = magnitude - product;
        while (remainder >= divisor) { ++quotient; remainder -= divisor; }
#endif
    } else {
        quotient = magnitude / divisor;
        remainder = magnitude % divisor;
    }
    uint64_t twice = remainder * 2u;
    if (twice > divisor || (twice == divisor && (quotient & 1u))) ++quotient;
    return negative ? -(int64_t)quotient : (int64_t)quotient;
}

COURSE_NUMERIC_HD static void course_probe_softmax_update(
    course_probe_softmax_t *state, int32_t score, int8_t value
) {
    if (!state->valid) {
        state->valid = 1;
        state->maximum_q11 = score;
        state->denominator_q15 = 32768;
        state->weighted_q15 = (int64_t)value * 32768;
        return;
    }
    int32_t maximum = score > state->maximum_q11 ? score : state->maximum_q11;
    int32_t old_scale = course_exp_neg_q15(state->maximum_q11 - maximum);
    int32_t new_scale = course_exp_neg_q15(score - maximum);
    state->denominator_q15 = (int32_t)course_probe_round_even(
        (int64_t)state->denominator_q15 * old_scale, 32768
    ) + new_scale;
    state->weighted_q15 = course_probe_round_even(
        state->weighted_q15 * old_scale, 32768
    ) + (int64_t)value * new_scale;
    state->maximum_q11 = maximum;
}

COURSE_NUMERIC_HD static void course_probe_softmax_merge_into(
    course_probe_softmax_t *left, const course_probe_softmax_t *right
) {
    if (!right->valid) return;
    if (!left->valid) {
        *left = *right;
        return;
    }
    int32_t maximum = left->maximum_q11 > right->maximum_q11
        ? left->maximum_q11 : right->maximum_q11;
    int32_t left_scale = course_exp_neg_q15(left->maximum_q11 - maximum);
    int32_t right_scale = course_exp_neg_q15(right->maximum_q11 - maximum);
    int32_t denominator = (int32_t)course_probe_round_even(
        (int64_t)left->denominator_q15 * left_scale, 32768
    ) + (int32_t)course_probe_round_even(
        (int64_t)right->denominator_q15 * right_scale, 32768
    );
    int64_t weighted = course_probe_round_even(
        left->weighted_q15 * left_scale, 32768
    ) + course_probe_round_even(right->weighted_q15 * right_scale, 32768);
    left->valid = 1;
    left->maximum_q11 = maximum;
    left->denominator_q15 = denominator;
    left->weighted_q15 = weighted;
}

COURSE_NUMERIC_HD static uint16_t course_probe_softmax_bf16(
    course_probe_softmax_t state
) {
    int64_t q16 = course_probe_round_even(
        state.weighted_q15 << 16, state.denominator_q15
    );
    /* The quotient is bounded by the INT8 value range, so Q16 fits INT32.
       Narrow explicitly to avoid pulling a 64-bit-to-float helper into RV32. */
    return course_bf16_rne_bits((float)(int32_t)q16 / 65536.0f);
}

COURSE_NUMERIC_HD static uint32_t course_probe_p1(
    const course_platform_case_t *item
) {
    unsigned visible = item->extent1 < 1u ? 1u : item->extent1;
    if (visible > 65u) visible = 65u;
    unsigned topk = item->extent2 ? item->extent2 : 1u;
    if (topk > visible) topk = visible;
    if (topk > 32u) topk = 32u;
    uint32_t rng = item->numeric_probe_seed;
    uint8_t selected[32];
#ifdef COURSE_PROMOTION_P1_STREAM_TOPK
    int32_t selected_scores[32];
#ifdef COURSE_PROMOTION_P1_PAGE_CACHE_DOUBLE_BUFFER
    /* Keep the selected value beside its score.  The A1 implementation keeps
     * a whole-page value array and later performs sparse random reads; this
     * two-bank selected window is the M1 page-local cache boundary. */
    int8_t selected_values[32];
#else
    int8_t values[65];
#endif
    unsigned selected_count = 0u;
#else
    int8_t values[65];
    int32_t scores[65];
#endif
    for (unsigned token = 0; token < visible; ++token) {
        int32_t score;
        if (item->numeric_probe_flags & COURSE_PROBE_TIE) {
            score = 0;
        } else {
            score = (int32_t)((course_probe_lcg(&rng) >> 16) & 0x7ffu) - 1024;
            score *= 16;
            if ((item->numeric_probe_flags & COURSE_PROBE_LATE_MAXIMUM) &&
                token + 1u == visible) score = 32767;
            if (item->numeric_probe_flags & COURSE_PROBE_EXTREMA)
                score = (token & 1u) ? -32768 : 32767;
        }
        int8_t value = course_probe_i8(&rng);
#ifdef COURSE_PROMOTION_P1_STREAM_TOPK
        unsigned position = 0u;
        while (position < selected_count &&
               (selected_scores[position] > score ||
                (selected_scores[position] == score && selected[position] < token)))
            ++position;
        if (position < topk) {
            unsigned limit = selected_count < topk ? selected_count : topk - 1u;
            for (unsigned move = limit; move > position; --move) {
                selected[move] = selected[move - 1u];
                selected_scores[move] = selected_scores[move - 1u];
#ifdef COURSE_PROMOTION_P1_PAGE_CACHE_DOUBLE_BUFFER
                selected_values[move] = selected_values[move - 1u];
#endif
            }
            selected[position] = (uint8_t)token;
            selected_scores[position] = score;
#ifdef COURSE_PROMOTION_P1_PAGE_CACHE_DOUBLE_BUFFER
            selected_values[position] = value;
#endif
            if (selected_count < topk) ++selected_count;
        }
#else
        values[token] = value;
        scores[token] = score;
#endif
#if defined(COURSE_PROMOTION_P1_STREAM_TOPK) && \
    !defined(COURSE_PROMOTION_P1_PAGE_CACHE_DOUBLE_BUFFER)
        values[token] = value;
#endif
    }
#ifndef COURSE_PROMOTION_P1_STREAM_TOPK
    for (unsigned rank = 0; rank < topk; ++rank) {
        unsigned best = visible;
        for (unsigned token = 0; token < visible; ++token) {
            unsigned used = 0;
            for (unsigned prior = 0; prior < rank; ++prior)
                if (selected[prior] == token) used = 1;
            if (!used && (best == visible || scores[token] > scores[best] ||
                (scores[token] == scores[best] && token < best))) best = token;
        }
        selected[rank] = (uint8_t)best;
    }
#endif
    course_probe_softmax_t state = {0};
    for (unsigned rank = 0; rank < topk; ++rank) {
#ifndef COURSE_PROMOTION_P1_PAGE_CACHE_DOUBLE_BUFFER
        unsigned token = selected[rank];
#endif
#ifdef COURSE_PROMOTION_P1_STREAM_TOPK
#ifdef COURSE_PROMOTION_P1_PAGE_CACHE_DOUBLE_BUFFER
        course_probe_softmax_update(
            &state, selected_scores[rank], selected_values[rank]
        );
#else
        course_probe_softmax_update(&state, selected_scores[rank], values[token]);
#endif
#else
        course_probe_softmax_update(&state, scores[token], values[token]);
#endif
    }
    uint32_t digest = UINT32_C(0x811c9dc5);
    digest = course_probe_fnv_word(digest, 1u);
    digest = course_probe_fnv_word(digest, visible);
    digest = course_probe_fnv_word(digest, topk);
    for (unsigned rank = 0; rank < topk; ++rank)
        digest = course_probe_fnv_word(digest, selected[rank]);
    digest = course_probe_fnv_word(digest, (uint32_t)state.maximum_q11);
    digest = course_probe_fnv_word(digest, (uint32_t)state.denominator_q15);
    digest = course_probe_fnv_word(digest, (uint32_t)state.weighted_q15);
    return course_probe_fnv_word(digest, course_probe_softmax_bf16(state));
}

COURSE_NUMERIC_HD static uint32_t course_probe_p2(
    const course_platform_case_t *item
) {
    unsigned length = item->extent0 < 1u ? 1u : item->extent0;
    if (length > 512u) length = 512u;
    uint32_t digest = UINT32_C(0x811c9dc5);
    digest = course_probe_fnv_word(digest, 2u);
    digest = course_probe_fnv_word(digest, length);
    unsigned mask = item->numeric_probe_aux;
    for (unsigned bit = 0; bit < 4; ++bit) {
        if (!(mask & (1u << bit))) continue;
        unsigned splits = 1u << bit;
        if (splits > length) splits = length;
        unsigned span = (length + splits - 1u) / splits;
        course_probe_softmax_t merged = {0};
#ifdef COURSE_PROMOTION_P2_SPLIT_DOUBLE_BUFFER
        /* The next contiguous split starts at the exact LCG state left by the
         * current split.  Carry it in the alternate buffer instead of running
         * logarithmic jump-ahead arithmetic for every descriptor. */
        uint32_t next_split_rng = item->numeric_probe_seed;
#endif
        for (unsigned split = 0; split < splits; ++split) {
            unsigned begin = split * span;
            if (begin > length) begin = length;
            unsigned end = begin + span;
            if (end > length) end = length;
            digest = course_probe_fnv_word(digest, begin);
            digest = course_probe_fnv_word(digest, end);
            course_probe_softmax_t partial = {0};
            // Regenerate the deterministic stream for each split instead of
            // materialising 512 scores and values in per-work-item local
            // memory.  This keeps the exact numeric order/signature while
            // fitting the Vortex kernel stack.
            uint32_t rng = item->numeric_probe_seed;
#ifdef COURSE_PROMOTION_P2_SPLIT_DOUBLE_BUFFER
            rng = next_split_rng;
            unsigned token_start = begin;
#elif defined(COURSE_PROMOTION_P2_RADIX16_CANONICAL)
            rng = course_probe_lcg_advance(rng, 2u * begin);
            unsigned token_start = begin;
#else
            unsigned token_start = 0u;
#endif
            for (unsigned token = token_start; token < end; ++token) {
                int32_t score =
                    (int32_t)((course_probe_lcg(&rng) >> 16) & 0x7ffu) - 1024;
                score *= 16;
                if ((item->numeric_probe_flags & COURSE_PROBE_LATE_MAXIMUM) &&
                    token + 1u == length) score = 32767;
                if (item->numeric_probe_flags & COURSE_PROBE_EXTREMA)
                    score = (token & 1u) ? -32768 : 32767;
                int8_t value = course_probe_i8(&rng);
#if defined(COURSE_PROMOTION_P2_RADIX16_CANONICAL) || \
    defined(COURSE_PROMOTION_P2_SPLIT_DOUBLE_BUFFER)
                course_probe_softmax_update(&partial, score, value);
#else
                if (token >= begin)
                    course_probe_softmax_update(&partial, score, value);
#endif
            }
#ifdef COURSE_PROMOTION_P2_SPLIT_DOUBLE_BUFFER
            next_split_rng = rng;
#endif
            // Avoid the invalid-left early-return path on Vortex.  The first
            // canonical split is definitionally the initial merged state;
            // later splits use the exact same rescaled merge operation.
            if (split == 0u) merged = partial;
            else course_probe_softmax_merge_into(&merged, &partial);
        }
        digest = course_probe_fnv_word(digest, (uint32_t)merged.maximum_q11);
        digest = course_probe_fnv_word(digest, (uint32_t)merged.denominator_q15);
        digest = course_probe_fnv_word(digest, (uint32_t)merged.weighted_q15);
        digest = course_probe_fnv_word(digest, course_probe_softmax_bf16(merged));
    }
    return digest;
}

COURSE_NUMERIC_HD static uint32_t course_probe_p3(
    const course_platform_case_t *item
) {
    unsigned rows = item->extent0 < 1u ? 1u : item->extent0;
    if (rows > 8u) rows = 8u;
    unsigned width = item->extent1 < 1u ? 1u : item->extent1;
    if (width > 64u) width = 64u;
    uint32_t rng = item->numeric_probe_seed;
    uint32_t digest = UINT32_C(0x811c9dc5);
    digest = course_probe_fnv_word(digest, 3u);
    digest = course_probe_fnv_word(digest, rows);
    digest = course_probe_fnv_word(digest, width);
    for (unsigned row = 0; row < rows; ++row) {
        int32_t gate_acc = 0, up_acc = 0;
#ifdef COURSE_PROMOTION_P3_WEIGHT_STATIONARY_BLOCKING
        unsigned column = 0u;
#define COURSE_P3_STATIONARY_ACCUMULATE_ONE() do { \
            int32_t activation = course_probe_i8(&rng); \
            int32_t gate_weight = (int32_t)course_probe_i8(&rng); \
            int32_t up_weight = (int32_t)course_probe_i8(&rng); \
            gate_acc += activation * gate_weight; \
            up_acc += activation * up_weight; \
        } while (0)
        /* Eight columns form the frozen same-expert weight-stationary block;
         * the second block is prepared while the first block accumulates. */
        for (; column + 8u <= width; column += 8u) {
            COURSE_P3_STATIONARY_ACCUMULATE_ONE();
            COURSE_P3_STATIONARY_ACCUMULATE_ONE();
            COURSE_P3_STATIONARY_ACCUMULATE_ONE();
            COURSE_P3_STATIONARY_ACCUMULATE_ONE();
            COURSE_P3_STATIONARY_ACCUMULATE_ONE();
            COURSE_P3_STATIONARY_ACCUMULATE_ONE();
            COURSE_P3_STATIONARY_ACCUMULATE_ONE();
            COURSE_P3_STATIONARY_ACCUMULATE_ONE();
        }
        for (; column < width; ++column)
            COURSE_P3_STATIONARY_ACCUMULATE_ONE();
#undef COURSE_P3_STATIONARY_ACCUMULATE_ONE
#elif defined(COURSE_PROMOTION_P3_EXPERT_GROUP_SKIP)
        unsigned column = 0u;
#define COURSE_P3_GROUP_ACCUMULATE_ONE() do { \
            int32_t activation = course_probe_i8(&rng); \
            gate_acc += activation * (int32_t)course_probe_i8(&rng); \
            up_acc += activation * (int32_t)course_probe_i8(&rng); \
        } while (0)
        for (; column + 4u <= width; column += 4u) {
            COURSE_P3_GROUP_ACCUMULATE_ONE();
            COURSE_P3_GROUP_ACCUMULATE_ONE();
            COURSE_P3_GROUP_ACCUMULATE_ONE();
            COURSE_P3_GROUP_ACCUMULATE_ONE();
        }
        for (; column < width; ++column) COURSE_P3_GROUP_ACCUMULATE_ONE();
#undef COURSE_P3_GROUP_ACCUMULATE_ONE
#else
        for (unsigned column = 0; column < width; ++column) {
            int32_t activation = course_probe_i8(&rng);
            gate_acc += activation * (int32_t)course_probe_i8(&rng);
            up_acc += activation * (int32_t)course_probe_i8(&rng);
        }
#endif
        int16_t gate_q11 = 0, up_q11 = 0;
        int8_t intermediate = 0;
        (void)course_int32_scale_to_q5_11(gate_acc, 0x1p-12f, &gate_q11);
        (void)course_int32_scale_to_q5_11(up_acc, 0x1p-12f, &up_q11);
        int16_t silu = course_silu_q11(gate_q11);
        (void)course_q22_requantize_int8(
            (int64_t)silu * up_q11, 1.0f, &intermediate
        );
        int32_t down_acc = (int32_t)intermediate * course_probe_i8(&rng);
        digest = course_probe_fnv_word(digest, (uint32_t)gate_acc);
        digest = course_probe_fnv_word(digest, (uint32_t)up_acc);
        digest = course_probe_fnv_word(digest, (uint32_t)(int32_t)gate_q11);
        digest = course_probe_fnv_word(digest, (uint32_t)(int32_t)up_q11);
        digest = course_probe_fnv_word(digest, (uint32_t)(int32_t)silu);
        digest = course_probe_fnv_word(digest, (uint32_t)(int32_t)intermediate);
        digest = course_probe_fnv_word(digest, (uint32_t)down_acc);
        digest = course_probe_fnv_word(
            digest, course_bf16_rne_bits((float)down_acc * 0x1p-8f)
        );
    }
    return digest;
}

COURSE_NUMERIC_HD static int course_platform_numeric_signature(
    const course_platform_case_t *item, uint32_t *signature
) {
    if (!item || !signature || item->expected_status != 0u || item->trace_only)
        return -1;
    if (item->operator_id == 1u) *signature = course_probe_p1(item);
    else if (item->operator_id == 2u) *signature = course_probe_p2(item);
    else if (item->operator_id == 3u) *signature = course_probe_p3(item);
    else return -2;
    return 0;
}

COURSE_NUMERIC_HD static uint32_t course_probe_rotate_left(
    uint32_t value, unsigned shift
) {
    shift &= 31u;
    return shift ? (value << shift) | (value >> (32u - shift)) : value;
}

COURSE_NUMERIC_HD static inline int course_platform_numeric_signature_seed(
    const course_platform_case_t *item, uint32_t runtime_seed,
    uint32_t *signature
) {
    if (!item) return -1;
    course_platform_case_t seeded = *item;
    seeded.numeric_probe_seed ^= course_probe_rotate_left(
        item->seed ^ runtime_seed, item->numeric_probe_seed_rotation
    );
    seeded.seed = runtime_seed;
    return course_platform_numeric_signature(&seeded, signature);
}

#undef COURSE_NUMERIC_HD
#if defined(COURSE_PROMOTION_RUNTIME_INLINE) && !defined(__CUDACC__)
#undef COURSE_PROMOTION_INLINE
#undef course_bf16_rne_bits
#undef course_exp_neg_q15
#undef course_silu_q11
#undef course_int32_scale_to_q5_11
#undef course_q22_requantize_int8
#endif
#endif

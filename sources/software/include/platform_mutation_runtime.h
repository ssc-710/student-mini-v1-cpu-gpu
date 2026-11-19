// SPDX-License-Identifier: Apache-2.0
// Eight portable mutation-killing probes. Expected signatures live host-side.
#ifndef COURSE_PLATFORM_MUTATION_RUNTIME_H
#define COURSE_PLATFORM_MUTATION_RUNTIME_H

#include <stdint.h>

#include "platform_numeric_runtime.h"

#if defined(__CUDACC__)
#define COURSE_MUTATION_HD __host__ __device__
#else
#define COURSE_MUTATION_HD
#endif

#define COURSE_PLATFORM_MUTATION_COUNT 8u

static const char *const course_platform_mutation_names[] = {
    "causal-bottom-right",
    "stable-topk-tie",
    "padding-isolation",
    "split-rescale-not-average",
    "first-tile-weight-switch",
    "int8-saturate-not-wrap",
    "stalled-payload-stable",
    "error-stops-new-dma",
};

COURSE_MUTATION_HD static uint32_t course_mutation_causal(void) {
    uint32_t digest = UINT32_C(0x811c9dc5);
    const unsigned q_len = 3u, kv_len = 6u;
    digest = course_probe_fnv_word(digest, q_len);
    digest = course_probe_fnv_word(digest, kv_len);
    for (unsigned q_pos = 0; q_pos < q_len; ++q_pos) {
        unsigned limit = q_pos + 1u + kv_len - q_len;
        if (limit > kv_len) limit = kv_len;
        digest = course_probe_fnv_word(digest, limit);
    }
    return digest;
}

COURSE_MUTATION_HD static uint32_t course_mutation_topk(void) {
    const uint32_t ids[4] = {3u, 1u, 2u, 0u};
    const int32_t scores[4] = {77, 77, 77, 77};
    uint8_t used[4] = {0};
    uint32_t digest = UINT32_C(0x811c9dc5);
    for (unsigned rank = 0; rank < 4u; ++rank) {
        unsigned best = 4u;
        for (unsigned index = 0; index < 4u; ++index) {
            if (!used[index] && (best == 4u || scores[index] > scores[best] ||
                (scores[index] == scores[best] && ids[index] < ids[best]))) best = index;
        }
        used[best] = 1u;
        digest = course_probe_fnv_word(digest, ids[best]);
    }
    return digest;
}

COURSE_MUTATION_HD static uint32_t course_mutation_padding(void) {
    const uint32_t pages[3] = {3u, 0u, 7u};
    const unsigned kv_len = 5u, page_size = 4u;
    uint32_t digest = UINT32_C(0x811c9dc5);
    digest = course_probe_fnv_word(digest, kv_len);
    digest = course_probe_fnv_word(digest, page_size);
    for (unsigned token = 0; token < kv_len; ++token) {
        uint32_t address = pages[token / page_size] * page_size + token % page_size;
        digest = course_probe_fnv_word(digest, address);
    }
    return digest;
}

COURSE_MUTATION_HD static uint32_t course_mutation_split(void) {
    course_probe_softmax_t left = {0}, right = {0};
    course_probe_softmax_update(&left, -32768, -100);
    course_probe_softmax_update(&right, 512, 100);
    course_probe_softmax_t merged = left;
    course_probe_softmax_merge_into(&merged, &right);
    int64_t wrong_average = (left.weighted_q15 + right.weighted_q15) / 2;
    uint32_t digest = UINT32_C(0x811c9dc5);
    digest = course_probe_fnv_word(digest, (uint32_t)merged.maximum_q11);
    digest = course_probe_fnv_word(digest, (uint32_t)merged.denominator_q15);
    digest = course_probe_fnv_word(digest, (uint32_t)merged.weighted_q15);
    return course_probe_fnv_word(digest, (uint32_t)wrong_average);
}

COURSE_MUTATION_HD static uint32_t course_mutation_switch(void) {
    const uint32_t experts[3] = {3u, 3u, 7u};
    uint32_t digest = UINT32_C(0x811c9dc5);
    for (unsigned index = 0; index < 3u; ++index)
        digest = course_probe_fnv_word(digest, experts[index]);
    for (unsigned index = 0; index < 3u; ++index) {
        uint32_t weight_switch = index == 0u || experts[index] != experts[index - 1u];
        digest = course_probe_fnv_word(digest, weight_switch);
    }
    return digest;
}

COURSE_MUTATION_HD static uint32_t course_mutation_saturate(void) {
    int8_t positive = 0, negative = 0;
    (void)course_q22_requantize_int8(INT64_C(1) << 40, 1.0f, &positive);
    (void)course_q22_requantize_int8(-(INT64_C(1) << 40), 1.0f, &negative);
    uint32_t digest = UINT32_C(0x811c9dc5);
    digest = course_probe_fnv_word(digest, (uint32_t)(int32_t)positive);
    return course_probe_fnv_word(digest, (uint32_t)(int32_t)negative);
}

COURSE_MUTATION_HD static uint32_t course_mutation_stall(void) {
    const uint32_t payload = UINT32_C(0x12345678);
    uint32_t digest = UINT32_C(0x811c9dc5);
    digest = course_probe_fnv_word(digest, 17u);
    for (unsigned cycle = 0; cycle < 17u; ++cycle)
        digest = course_probe_fnv_word(digest, payload);
    return course_probe_fnv_word(digest, 1u);
}

COURSE_MUTATION_HD static uint32_t course_mutation_error_dma(void) {
    uint32_t digest = UINT32_C(0x811c9dc5);
    digest = course_probe_fnv_word(digest, 1u);
    for (unsigned cycle = 0; cycle < 8u; ++cycle)
        digest = course_probe_fnv_word(digest, 0u);
    return digest;
}

COURSE_MUTATION_HD static uint32_t course_platform_mutation_signature(
    unsigned index
) {
    switch (index) {
        case 0: return course_mutation_causal();
        case 1: return course_mutation_topk();
        case 2: return course_mutation_padding();
        case 3: return course_mutation_split();
        case 4: return course_mutation_switch();
        case 5: return course_mutation_saturate();
        case 6: return course_mutation_stall();
        case 7: return course_mutation_error_dma();
        default: return 0u;
    }
}

#undef COURSE_MUTATION_HD
#endif

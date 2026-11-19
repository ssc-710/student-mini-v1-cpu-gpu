// SPDX-License-Identifier: Apache-2.0
#ifndef STUDENT_MINI_NATIVE_NANO_H
#define STUDENT_MINI_NATIVE_NANO_H
#include <stdint.h>

// Order is explicit; deployment code maps named image segments to these IDs.
enum mini_tensor {
    MINI_EMBEDDING, MINI_LM_HEAD, MINI_FINAL_NORM, MINI_ATTN_NORM, MINI_MOE_NORM,
    MINI_Q_NOPE, MINI_Q_PE, MINI_INDEX_Q, MINI_CKV, MINI_KPE, MINI_INDEX_K,
    MINI_ATTN_OUT, MINI_ROUTER, MINI_GATE, MINI_UP, MINI_DOWN,
    MINI_SHARED_GATE, MINI_SHARED_UP, MINI_SHARED_DOWN, MINI_TENSOR_COUNT
};
typedef struct {
    const int8_t *weight[MINI_TENSOR_COUNT];
    float scale[MINI_TENSOR_COUNT];
} mini_native_model;

// All tensors are complete arrays, never checksums. Hardware backends must
// execute these calls on their named target; NULL callbacks mean scalar C only.
typedef int (*mini_attention_fn)(void *user, unsigned prefill, unsigned rows,
    unsigned length, const int8_t *query, const int8_t *keys,
    const int8_t *index_query, const int8_t *index_keys,
    float score_scale, float index_scale, float value_scale, uint16_t *output);
typedef int (*mini_expert_fn)(void *user, unsigned expert, const int8_t *input,
    float input_scale, const mini_native_model *model, uint16_t *output);
typedef struct {
    void *user;
    mini_attention_fn attention;
    mini_expert_fn expert;
    void (*step_complete)(void *user, unsigned step, uint32_t token);
} mini_native_backend;
typedef struct {
    float cache[32][12], index_cache[32][8];
    float hidden[32][16], normalized[32][16], queries[32][12], index_queries[32][8];
    int8_t ki[32][12], iki[32][8], qi[32][12], iqi[32][8];
    uint16_t attended[32][8];
} mini_native_workspace;
typedef struct {
    unsigned count, p1_calls, p2_calls, p3_calls;
    uint32_t tokens[12];
    uint16_t final_hidden[12][16];
    uint16_t logits[12][256];
    // Caller owns placement. RV32 firmware puts this in SDRAM, not the 8 KiB stack.
    mini_native_workspace workspace;
} mini_native_result;

int mini_native_scalar_attention(void *, unsigned, unsigned, unsigned,
    const int8_t *, const int8_t *, const int8_t *, const int8_t *,
    float, float, float, uint16_t *);
int mini_native_scalar_expert(void *, unsigned, const int8_t *, float,
    const mini_native_model *, uint16_t *);
int mini_native_generate(const mini_native_model *, const uint32_t *, unsigned,
    const mini_native_backend *, mini_native_result *);
#endif

#ifndef OPEN_SOC_AI_LABS_OPERATOR_SCALAR_H
#define OPEN_SOC_AI_LABS_OPERATOR_SCALAR_H

#include <stddef.h>
#include <stdint.h>

#if defined(__CUDACC__)
#define COURSE_OPERATOR_HD __host__ __device__
#else
#define COURSE_OPERATOR_HD
#endif

typedef struct {
    float max_score;
    float denominator;
    float numerator;
} course_softmax_state_t;

/* Bit-exact integer primitives shared with the RTL oracle. */
COURSE_OPERATOR_HD uint16_t course_bf16_rne_bits(float value);
COURSE_OPERATOR_HD uint16_t course_exp_neg_q15(int32_t delta_q5_11);
COURSE_OPERATOR_HD int16_t course_silu_q11(int32_t value_q5_11);
COURSE_OPERATOR_HD int course_int32_scale_to_q5_11(
    int32_t value, float scale, int16_t *result
);
COURSE_OPERATOR_HD int course_q22_requantize_int8(
    int64_t value_q22, float scale, int8_t *result
);

/* Sort key: score descending, then token id ascending. */
int course_stable_topk(const float *scores, const uint32_t *token_ids,
                       size_t count, size_t k, uint32_t *selected_ids);

/* Merge local (m, d, o) states with max-score re-scaling. */
int course_merge_softmax(const course_softmax_state_t *states, size_t count,
                         course_softmax_state_t *merged, float *output);

/* Scalar reference for gate/up -> SiLU*up -> INT8 RNE/saturate -> down. */
int course_w8a8_expert(const int8_t *x, size_t input_dim,
                       const int8_t *gate_weights, const int8_t *up_weights,
                       size_t intermediate_dim, const int8_t *down_weights,
                       size_t output_dim, float scale_a, float gate_scale,
                       float up_scale, float intermediate_scale,
                       float down_scale, float route_weight, float *output);

#undef COURSE_OPERATOR_HD

#endif

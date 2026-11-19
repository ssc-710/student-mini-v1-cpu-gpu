#include "include/operator_scalar.h"
#include "include/numeric_luts.h"

#include <limits.h>
#include <stdint.h>

static int finite_float(float value) {
    union { float f; uint32_t u; } bits = {.f = value};
    return (bits.u & 0x7f800000u) != 0x7f800000u;
}

static int finite_positive(float value) {
    return finite_float(value) && value > 0.0f;
}

static int contract_scale(float value) {
    return finite_positive(value) && value >= 0x1p-16f && value <= 0x1p16f;
}

static uint32_t float_bits(float value) {
    union { float f; uint32_t u; } bits = {.f = value};
    return bits.u;
}

static uint64_t round_divide_even_u64(uint64_t numerator, uint64_t denominator) {
    uint64_t quotient = numerator / denominator;
    uint64_t remainder = numerator % denominator;
    uint64_t half = denominator >> 1;
    if (remainder > half || (remainder == half && (denominator & 1u) == 0u &&
                             (quotient & 1u))) {
        ++quotient;
    }
    return quotient;
}

static int32_t round_q11_to_q6(int32_t value) {
    uint32_t magnitude = value < 0 ? (uint32_t)(-(int64_t)value) : (uint32_t)value;
    uint32_t quotient = magnitude >> 5;
    uint32_t remainder = magnitude & 31u;
    if (remainder > 16u || (remainder == 16u && (quotient & 1u))) ++quotient;
    return value < 0 ? -(int32_t)quotient : (int32_t)quotient;
}

uint16_t course_bf16_rne_bits(float value) {
    uint32_t bits = float_bits(value);
    uint32_t upper = bits >> 16;
    uint32_t lower = bits & 0xffffu;
    if (lower > 0x8000u || (lower == 0x8000u && (upper & 1u))) ++upper;
    return (uint16_t)upper;
}

uint16_t course_exp_neg_q15(int32_t delta_q5_11) {
    if (delta_q5_11 > 0) delta_q5_11 = 0;
    if (delta_q5_11 < -32768) delta_q5_11 = -32768;
    int32_t index_q6 = round_q11_to_q6(delta_q5_11);
    return course_exp_q15_q6_lut[index_q6 + 1024];
}

int16_t course_silu_q11(int32_t value_q5_11) {
    if (value_q5_11 > 32767) value_q5_11 = 32767;
    if (value_q5_11 < -32768) value_q5_11 = -32768;
    int32_t index_q6 = round_q11_to_q6(value_q5_11);
    if (index_q6 > 1024) index_q6 = 1024;
    if (index_q6 < -1024) index_q6 = -1024;
    return course_silu_q11_q6_lut[index_q6 + 1024];
}

int course_int32_scale_to_q5_11(int32_t value, float scale, int16_t *result) {
    if (!result) return -1;
    if (!contract_scale(scale)) return -2;
    uint32_t bits = float_bits(scale);
    int exponent = (int)((bits >> 23) & 0xffu);
    uint64_t significand = UINT64_C(0x800000) | (bits & 0x7fffffu);
    uint64_t magnitude = value < 0 ? (uint64_t)(-(int64_t)value) : (uint64_t)value;
    uint64_t product = magnitude * significand;
    int shift = exponent - 139;
    uint64_t scaled = shift >= 0
        ? product << shift
        : round_divide_even_u64(product, UINT64_C(1) << -shift);
    if (value < 0) {
        *result = scaled >= 32768u ? INT16_MIN : (int16_t)-(int32_t)scaled;
    } else {
        *result = scaled >= 32767u ? INT16_MAX : (int16_t)scaled;
    }
    return 0;
}

int course_q22_requantize_int8(int64_t value_q22, float scale, int8_t *result) {
    if (!result) return -1;
    if (!contract_scale(scale)) return -2;
    if (value_q22 < -INT64_C(140737488355328) ||
        value_q22 > INT64_C(140737488355327)) return -3;
    uint32_t bits = float_bits(scale);
    int exponent = (int)((bits >> 23) & 0xffu);
    uint64_t significand = UINT64_C(0x800000) | (bits & 0x7fffffu);
    uint64_t magnitude = value_q22 < 0
        ? (uint64_t)(-value_q22) : (uint64_t)value_q22;
    int shift = 128 - exponent;
    uint64_t numerator;
    if (shift >= 0) {
        if (magnitude > (UINT64_MAX >> shift)) {
            *result = value_q22 < 0 ? INT8_MIN : INT8_MAX;
            return 0;
        }
        numerator = magnitude << shift;
    } else {
        numerator = magnitude >> -shift;
    }
    uint64_t rounded = round_divide_even_u64(numerator, significand);
    if (value_q22 < 0) {
        *result = rounded >= 128u ? INT8_MIN : (int8_t)-(int32_t)rounded;
    } else {
        *result = rounded >= 127u ? INT8_MAX : (int8_t)rounded;
    }
    return 0;
}

static float exp_approx(float value) {
    /* Range-reduced (1+x/256)^256.  Scalar-C is a portable system oracle;
       the bit-exact Q1.15 implementation remains in the RTL oracle. */
    if (value < -16.0f) value = -16.0f;
    if (value > 16.0f) value = 16.0f;
    float result = 1.0f + value / 256.0f;
    for (int i = 0; i < 8; ++i) result *= result;
    return result;
}

static int8_t rne_saturate_i8(float value) {
    if (value >= 127.0f) return 127;
    if (value <= -128.0f) return -128;
    int32_t whole = (int32_t)value;
    float fraction = value - (float)whole;
    if (fraction > 0.5f || (fraction == 0.5f && (whole & 1))) ++whole;
    if (fraction < -0.5f || (fraction == -0.5f && (whole & 1))) --whole;
    return (int8_t)whole;
}

int course_stable_topk(const float *scores, const uint32_t *token_ids,
                       size_t count, size_t k, uint32_t *selected_ids) {
    if (!scores || !token_ids || !selected_ids || k == 0 || k > count) return -1;
    uint8_t used[count];
    for (size_t i = 0; i < count; ++i) used[i] = 0;
    for (size_t rank = 0; rank < k; ++rank) {
        size_t best = count;
        for (size_t i = 0; i < count; ++i) {
            if (used[i] || !finite_float(scores[i])) continue;
            if (best == count || scores[i] > scores[best] ||
                (scores[i] == scores[best] && token_ids[i] < token_ids[best])) {
                best = i;
            }
        }
        if (best == count) {
            return -3;
        }
        used[best] = 1;
        selected_ids[rank] = token_ids[best];
    }
    return 0;
}

int course_merge_softmax(const course_softmax_state_t *states, size_t count,
                         course_softmax_state_t *merged, float *output) {
    if (!states || !merged || !output || count == 0) return -1;
    float maximum = -3.402823466e+38F;
    for (size_t i = 0; i < count; ++i) {
        if (!finite_float(states[i].max_score) || states[i].denominator < 0.0f ||
            !finite_float(states[i].denominator) || !finite_float(states[i].numerator)) return -2;
        if (states[i].max_score > maximum) maximum = states[i].max_score;
    }
    float denominator = 0.0f;
    float numerator = 0.0f;
    for (size_t i = 0; i < count; ++i) {
        float factor = exp_approx(states[i].max_score - maximum);
        denominator += states[i].denominator * factor;
        numerator += states[i].numerator * factor;
    }
    if (!(denominator > 0.0f) || !finite_float(denominator) || !finite_float(numerator)) return -3;
    merged->max_score = maximum;
    merged->denominator = denominator;
    merged->numerator = numerator;
    *output = numerator / denominator;
    return finite_float(*output) ? 0 : -4;
}

int course_w8a8_expert(const int8_t *x, size_t input_dim,
                       const int8_t *gate_weights, const int8_t *up_weights,
                       size_t intermediate_dim, const int8_t *down_weights,
                       size_t output_dim, float scale_a, float gate_scale,
                       float up_scale, float intermediate_scale,
                       float down_scale, float route_weight, float *output) {
    if (!x || !gate_weights || !up_weights || !down_weights || !output ||
        input_dim == 0 || intermediate_dim == 0 || output_dim == 0) return -1;
    if (!finite_positive(scale_a) || !finite_positive(gate_scale) ||
        !finite_positive(up_scale) || !finite_positive(intermediate_scale) ||
        !finite_positive(down_scale) || !finite_float(route_weight) ||
        route_weight < 0.0f || route_weight > 1.0f) return -2;
    int8_t hidden[intermediate_dim];
    for (size_t row = 0; row < intermediate_dim; ++row) {
        int32_t gate_acc = 0;
        int32_t up_acc = 0;
        for (size_t col = 0; col < input_dim; ++col) {
            gate_acc += (int32_t)x[col] * gate_weights[row * input_dim + col];
            up_acc += (int32_t)x[col] * up_weights[row * input_dim + col];
        }
        float gate = gate_acc * scale_a * gate_scale;
        float up = up_acc * scale_a * up_scale;
        float silu = gate / (1.0f + exp_approx(-gate));
        hidden[row] = rne_saturate_i8((silu * up) / intermediate_scale);
    }
    for (size_t row = 0; row < output_dim; ++row) {
        int32_t acc = 0;
        for (size_t col = 0; col < intermediate_dim; ++col) {
            acc += (int32_t)hidden[col] * down_weights[row * intermediate_dim + col];
        }
        output[row] = acc * intermediate_scale * down_scale * route_weight;
    }
    return 0;
}

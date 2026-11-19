#include <cuda_runtime.h>

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "../../software/include/numeric_luts.h"

__device__ static const uint16_t *gpu_exp_lut_device;
__device__ static const int16_t *gpu_silu_lut_device;

#ifdef COURSE_PROMOTION_RUNTIME_INLINE
#define COURSE_GPU_FIXED_ATTR __attribute__((always_inline)) inline
#ifdef COURSE_PROMOTION_CANDIDATE_ID
__device__ __attribute__((used)) static volatile const char course_promotion_candidate_identity[] =
    COURSE_PROMOTION_CANDIDATE_ID;
#define COURSE_GPU_CANDIDATE_GUARD() do { \
    if (course_promotion_candidate_identity[0] == '\0') return; \
} while (0)
#endif
#else
#define COURSE_GPU_FIXED_ATTR __attribute__((noinline, optnone))
#define COURSE_GPU_CANDIDATE_GUARD() do { } while (0)
#endif

// chipStar's optimized SPIR-V can materialize these C++ overloads before the
// RV32 archive link. Define them in the device module so O2 never depends on
// an unresolved host/libstdc++ symbol.
__device__ __attribute__((used, always_inline)) inline short abs(short value) {
    return value < 0 ? (short)-value : value;
}
__device__ __attribute__((used, always_inline)) inline int abs(int value) {
    return value < 0 ? -value : value;
}
__device__ __attribute__((used, always_inline)) inline long abs(long value) {
    return value < 0 ? -value : value;
}
__device__ __attribute__((used, noinline, optnone)) long popcount(long value) {
    unsigned long bits = (unsigned long)value;
    bits = bits - ((bits >> 1) & 0x55555555ul);
    bits = (bits & 0x33333333ul) + ((bits >> 2) & 0x33333333ul);
    bits = (bits + (bits >> 4)) & 0x0f0f0f0ful;
    bits += bits >> 8;
    bits += bits >> 16;
    return (long)(bits & 0x3ful);
}

__host__ __device__ static uint32_t gpu_float_bits(float value) {
    union { float f; uint32_t u; } bits = {value};
    return bits.u;
}

// LLVM's SPIR-V optimizer otherwise folds the usual signed-magnitude idiom
// into OpenCL.std s_abs.  The locked chipStar runtime then asks for abs(long)
// and abs(int) from its separate device library before Vortex's final RV32
// link can see our compatibility archive.  Keep just this two-instruction
// boundary opaque; the surrounding promotion primitives remain inlinable.
__host__ __device__ __attribute__((noinline, optnone)) static uint32_t
gpu_signed_magnitude_i32(int32_t value) {
    uint32_t raw = (uint32_t)value;
    uint32_t sign_mask = 0u - (raw >> 31);
    return (raw ^ sign_mask) - sign_mask;
}

__host__ __device__ __attribute__((noinline, optnone)) static uint64_t
gpu_signed_magnitude_i64(int64_t value) {
    uint64_t raw = (uint64_t)value;
    uint64_t sign_mask = UINT64_C(0) - (raw >> 63);
    return (raw ^ sign_mask) - sign_mask;
}

__host__ __device__ COURSE_GPU_FIXED_ATTR static uint64_t gpu_round_even_u64(
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

__host__ __device__ COURSE_GPU_FIXED_ATTR static int32_t gpu_round_q11_to_q6(int32_t value) {
    uint32_t magnitude = gpu_signed_magnitude_i32(value);
    uint32_t quotient = magnitude >> 5;
    uint32_t remainder = magnitude & 31u;
    if (remainder > 16u || (remainder == 16u && (quotient & 1u))) ++quotient;
    return value < 0 ? -(int32_t)quotient : (int32_t)quotient;
}

__host__ __device__ uint16_t course_gpu_bf16_rne_bits(float value) {
    uint32_t bits = gpu_float_bits(value);
    uint32_t upper = bits >> 16;
    uint32_t lower = bits & 0xffffu;
    if (lower > 0x8000u || (lower == 0x8000u && (upper & 1u))) ++upper;
    return (uint16_t)upper;
}

__host__ __device__ uint16_t course_gpu_exp_neg_q15(int32_t delta_q5_11) {
    if (delta_q5_11 > 0) delta_q5_11 = 0;
    if (delta_q5_11 < -32768) delta_q5_11 = -32768;
    int32_t index = gpu_round_q11_to_q6(delta_q5_11) + 1024;
#if defined(__HIP_DEVICE_COMPILE__) || defined(__CUDA_ARCH__)
    return gpu_exp_lut_device[index];
#else
    return course_exp_q15_q6_lut[index];
#endif
}

__host__ __device__ int16_t course_gpu_silu_q11(int32_t value_q5_11) {
    if (value_q5_11 > 32767) value_q5_11 = 32767;
    if (value_q5_11 < -32768) value_q5_11 = -32768;
    int32_t index = gpu_round_q11_to_q6(value_q5_11);
    if (index > 1024) index = 1024;
    if (index < -1024) index = -1024;
#if defined(__HIP_DEVICE_COMPILE__) || defined(__CUDA_ARCH__)
    return gpu_silu_lut_device[index + 1024];
#else
    return course_silu_q11_q6_lut[index + 1024];
#endif
}

__host__ __device__ COURSE_GPU_FIXED_ATTR int course_gpu_int32_scale_to_q5_11(
    int32_t value, float scale, int16_t *result
) {
    if (!result) return -1;
    uint32_t bits = gpu_float_bits(scale);
    if ((bits & 0x7f800000u) == 0x7f800000u || !(bits & 0x7fffffffu) ||
        scale < 0x1p-16f || scale > 0x1p16f) return -2;
    int exponent = (int)((bits >> 23) & 0xffu);
    uint64_t significand = UINT64_C(0x800000) | (bits & 0x7fffffu);
    uint64_t magnitude = gpu_signed_magnitude_i64((int64_t)value);
    uint64_t product = magnitude * significand;
    int shift = exponent - 139;
    uint64_t scaled = shift >= 0 ? product << shift
        : gpu_round_even_u64(product, UINT64_C(1) << -shift);
    if (value < 0) *result = scaled >= 32768u ? INT16_MIN : (int16_t)-(int32_t)scaled;
    else *result = scaled >= 32767u ? INT16_MAX : (int16_t)scaled;
    return 0;
}

__host__ __device__ COURSE_GPU_FIXED_ATTR int course_gpu_q22_requantize_int8(
    int64_t value_q22, float scale, int8_t *result
) {
    if (!result) return -1;
    uint32_t bits = gpu_float_bits(scale);
    if ((bits & 0x7f800000u) == 0x7f800000u || !(bits & 0x7fffffffu) ||
        scale < 0x1p-16f || scale > 0x1p16f) return -2;
    if (value_q22 < -INT64_C(140737488355328) ||
        value_q22 > INT64_C(140737488355327)) return -3;
    int exponent = (int)((bits >> 23) & 0xffu);
    uint64_t significand = UINT64_C(0x800000) | (bits & 0x7fffffu);
    uint64_t magnitude = gpu_signed_magnitude_i64(value_q22);
    int shift = 128 - exponent;
    uint64_t numerator;
    if (shift >= 0) {
        if (magnitude > (UINT64_MAX >> shift)) {
            *result = value_q22 < 0 ? INT8_MIN : INT8_MAX;
            return 0;
        }
        numerator = magnitude << shift;
    } else numerator = magnitude >> -shift;
    uint64_t rounded = gpu_round_even_u64(numerator, significand);
    if (value_q22 < 0) *result = rounded >= 128u ? INT8_MIN : (int8_t)-(int32_t)rounded;
    else *result = rounded >= 127u ? INT8_MAX : (int8_t)rounded;
    return 0;
}

#define course_bf16_rne_bits course_gpu_bf16_rne_bits
#define course_exp_neg_q15 course_gpu_exp_neg_q15
#define course_silu_q11 course_gpu_silu_q11
#define course_int32_scale_to_q5_11 course_gpu_int32_scale_to_q5_11
#define course_q22_requantize_int8 course_gpu_q22_requantize_int8
#include "../../software/include/platform_case_runtime.h"
#include "../../software/include/platform_numeric_runtime.h"
#include "../../software/include/platform_mutation_runtime.h"

// Do not DMA course_platform_case_t directly: its leading host pointer is 64-bit
// while Vortex device pointers are 32-bit, so the remaining fields would have
// different offsets.  This pointer-free wire record has an identical ABI on
// both sides of the chipStar boundary.
struct GpuCaseInput {
    uint32_t seed, extent0, extent1, extent2, extent3, numeric_probe_seed;
    uint32_t runtime_seed;
    uint16_t scenario_flags;
    uint8_t operator_id, expected_status, required_seams, trace_only;
    uint8_t numeric_probe_flags, numeric_probe_aux, numeric_probe_seed_rotation;
    uint8_t seeded;
};
struct GpuCaseOutput { uint32_t actual_status, numeric_status, signature; };

#define DEFINE_PLATFORM_OPERATOR_KERNEL(KERNEL_NAME, OPERATOR_ID, PROBE_FN) \
__global__ void KERNEL_NAME( \
    const uint16_t *exp_lut, const int16_t *silu_lut, \
    const GpuCaseInput *inputs, GpuCaseOutput *outputs, uint32_t count, \
    uint32_t *mutation_signatures \
) { \
    if (threadIdx.x) return; \
    COURSE_GPU_CANDIDATE_GUARD(); \
    gpu_exp_lut_device = exp_lut; \
    gpu_silu_lut_device = silu_lut; \
    uint32_t index = blockIdx.x; \
    if (index >= count) { \
        uint32_t mutation = index - count; \
        if (mutation < COURSE_PLATFORM_MUTATION_COUNT) \
            mutation_signatures[mutation] = course_platform_mutation_signature(mutation); \
        return; \
    } \
    const GpuCaseInput *wire = &inputs[index]; \
    course_platform_case_t item = { \
        0, wire->operator_id, wire->expected_status, wire->required_seams, \
        wire->trace_only, wire->scenario_flags, wire->seed, wire->extent0, \
        wire->extent1, wire->extent2, wire->extent3, \
        wire->numeric_probe_seed, wire->numeric_probe_flags, \
        wire->numeric_probe_aux, wire->numeric_probe_seed_rotation \
    }; \
    outputs[index].actual_status = course_platform_validate_case(&item); \
    outputs[index].signature = 0; \
    outputs[index].numeric_status = 0; \
    if ((item.required_seams & 2u) && item.operator_id == OPERATOR_ID) { \
        if (item.expected_status != 0u || item.trace_only) { \
            outputs[index].numeric_status = (uint32_t)-1; \
        } else { \
            if (wire->seeded) { \
                item.numeric_probe_seed ^= course_probe_rotate_left( \
                    item.seed ^ wire->runtime_seed, item.numeric_probe_seed_rotation); \
                item.seed = wire->runtime_seed; \
            } \
            outputs[index].signature = PROBE_FN(&item); \
        } \
    } \
}

DEFINE_PLATFORM_OPERATOR_KERNEL(platform_p1_kernel, 1u, course_probe_p1)
DEFINE_PLATFORM_OPERATOR_KERNEL(platform_p2_kernel, 2u, course_probe_p2)
DEFINE_PLATFORM_OPERATOR_KERNEL(platform_p3_kernel, 3u, course_probe_p3)
#undef DEFINE_PLATFORM_OPERATOR_KERNEL
#undef COURSE_GPU_CANDIDATE_GUARD

__global__ void platform_mutation_kernel(
    const uint16_t *exp_lut, const int16_t *silu_lut, uint32_t *signatures
) {
    if (blockIdx.x || threadIdx.x) return;
    gpu_exp_lut_device = exp_lut;
    gpu_silu_lut_device = silu_lut;
    for (uint32_t index = 0; index < COURSE_PLATFORM_MUTATION_COUNT; ++index)
        signatures[index] = course_platform_mutation_signature(index);
}

static void check(cudaError_t status, const char *what) {
    if (status != cudaSuccess) {
        fprintf(stderr, "%s failed: %s\n", what, cudaGetErrorString(status));
        exit(2);
    }
}

template <typename T> static T *device_copy(const T *source, size_t count) {
    T *device = NULL;
    check(cudaMalloc(&device, sizeof(T) * count), "cudaMalloc");
    check(cudaMemcpy(device, source, sizeof(T) * count, cudaMemcpyHostToDevice), "cudaMemcpy H2D");
    return device;
}

int main(int argc, char **argv) {
    const uint32_t total = COURSE_PLATFORM_CASE_COUNT
        + 3u * (COURSE_PUBLIC_SEED_COUNT + COURSE_HIDDEN_SEED_COUNT);
    uint32_t start = argc > 1 ? (uint32_t)strtoul(argv[1], NULL, 0) : 0u;
    uint32_t run_count = argc > 2 ? (uint32_t)strtoul(argv[2], NULL, 0) : total;
    uint32_t include_mutations = argc > 3 ? (uint32_t)strtoul(argv[3], NULL, 0) : 1u;
    uint32_t emit_terminal = argc > 4 ? (uint32_t)strtoul(argv[4], NULL, 0) : 1u;
    uint32_t operator_mode = argc > 5 ? (uint32_t)strtoul(argv[5], NULL, 0) : 1u;
    if (start > total || run_count > total - start) {
        fprintf(stderr, "invalid platform slice start=%u count=%u total=%u\n",
                start, run_count, total);
        return 4;
    }
    GpuCaseInput *inputs = (GpuCaseInput *)calloc(total, sizeof(*inputs));
    GpuCaseOutput *outputs = (GpuCaseOutput *)calloc(total, sizeof(*outputs));
    uint32_t cursor = 0, first_numeric[3] = {0}, found[3] = {0};
    #define COPY_CASE_TO_WIRE(dst, src) do { \
        (dst).seed = (src).seed; (dst).extent0 = (src).extent0; \
        (dst).extent1 = (src).extent1; (dst).extent2 = (src).extent2; \
        (dst).extent3 = (src).extent3; \
        (dst).numeric_probe_seed = (src).numeric_probe_seed; \
        (dst).scenario_flags = (src).scenario_flags; \
        (dst).operator_id = (src).operator_id; \
        (dst).expected_status = (src).expected_status; \
        (dst).required_seams = (src).required_seams; \
        (dst).trace_only = (src).trace_only; \
        (dst).numeric_probe_flags = (src).numeric_probe_flags; \
        (dst).numeric_probe_aux = (src).numeric_probe_aux; \
        (dst).numeric_probe_seed_rotation = (src).numeric_probe_seed_rotation; \
    } while (0)
    for (uint32_t index = 0; index < COURSE_PLATFORM_CASE_COUNT; ++index) {
        COPY_CASE_TO_WIRE(inputs[cursor], course_platform_cases[index]);
        ++cursor;
        uint32_t op = course_platform_cases[index].operator_id - 1u;
        if (op < 3u && !found[op] && (course_platform_cases[index].required_seams & 2u)) {
            first_numeric[op] = index; found[op] = 1u;
        }
    }
    for (uint32_t op = 0; op < 3u; ++op) {
        for (uint32_t ordinal = 0; ordinal < COURSE_PUBLIC_SEED_COUNT; ++ordinal) {
            COPY_CASE_TO_WIRE(inputs[cursor], course_platform_cases[first_numeric[op]]);
            inputs[cursor].runtime_seed = course_public_seeds[ordinal];
            inputs[cursor++].seeded = 1u;
        }
        for (uint32_t ordinal = 0; ordinal < COURSE_HIDDEN_SEED_COUNT; ++ordinal) {
            COPY_CASE_TO_WIRE(inputs[cursor], course_platform_cases[first_numeric[op]]);
            inputs[cursor].runtime_seed = course_hidden_seeds[op][ordinal];
            inputs[cursor++].seeded = 1u;
        }
    }
    #undef COPY_CASE_TO_WIRE
    for (uint32_t index = start; index < start + run_count; ++index) {
        if (inputs[index].operator_id != operator_mode) {
            fprintf(stderr, "mixed/wrong operator slice index=%u actual=%u requested=%u\n",
                    index, inputs[index].operator_id, operator_mode);
            return 4;
        }
    }
    uint16_t *device_exp = device_copy(course_exp_q15_q6_lut, 1025);
    int16_t *device_silu = device_copy(course_silu_q11_q6_lut, 2049);
    uint32_t allocation_count = run_count ? run_count : 1u;
    const GpuCaseInput *slice = run_count ? inputs + start : inputs + total - 1u;
    GpuCaseInput *device_inputs = device_copy(slice, allocation_count);
    GpuCaseOutput *device_outputs = NULL;
    uint32_t *device_mutations = NULL;
    check(cudaMalloc(&device_outputs, sizeof(*outputs) * allocation_count), "allocate outputs");
    check(cudaMalloc(&device_mutations, sizeof(uint32_t) * COURSE_PLATFORM_MUTATION_COUNT), "allocate mutations");
    uint32_t failures = 0;
    // The current Vortex command processor can retire one large launch, but a
    // second launch in the same process may be accepted without execution.
    // Put all records and mutation probes in one grid so evidence comes from a
    // single real device command rather than host-side fallback/replay.
    uint32_t mutation_count = include_mutations ? COURSE_PLATFORM_MUTATION_COUNT : 0u;
    if (operator_mode == 1u)
        platform_p1_kernel<<<run_count + mutation_count, 1>>>(
            device_exp, device_silu, device_inputs, device_outputs, run_count,
            device_mutations);
    else if (operator_mode == 2u)
        platform_p2_kernel<<<run_count + mutation_count, 1>>>(
            device_exp, device_silu, device_inputs, device_outputs, run_count,
            device_mutations);
    else if (operator_mode == 3u)
        platform_p3_kernel<<<run_count + mutation_count, 1>>>(
            device_exp, device_silu, device_inputs, device_outputs, run_count,
            device_mutations);
    else {
        fprintf(stderr, "invalid operator mode %u\n", operator_mode);
        return 4;
    }
    check(cudaGetLastError(), "launch combined platform workload");
    check(cudaDeviceSynchronize(), "synchronize combined platform workload");
    if (run_count)
        check(cudaMemcpy(outputs, device_outputs, sizeof(*outputs) * run_count,
                         cudaMemcpyDeviceToHost), "read platform records");
    for (uint32_t local = 0; local < run_count; ++local) {
        uint32_t index = start + local;
        const GpuCaseInput *item = &inputs[index];
        if (outputs[local].actual_status != item->expected_status ||
            outputs[local].numeric_status) ++failures;
        printf("GPU_PLATFORM_RESULT index=%u op=%u status=%u numeric_status=%u signature=%08x\n",
               index, item->operator_id, outputs[local].actual_status,
               outputs[local].numeric_status, outputs[local].signature);
    }
    fflush(stdout);
    uint32_t mutations[COURSE_PLATFORM_MUTATION_COUNT];
    if (include_mutations) {
        check(cudaMemcpy(mutations, device_mutations, sizeof(mutations), cudaMemcpyDeviceToHost), "read mutations");
        for (uint32_t index = 0; index < COURSE_PLATFORM_MUTATION_COUNT; ++index)
            printf("GPU_PLATFORM_MUTATION index=%u signature=%08x\n", index, mutations[index]);
    }
    if (emit_terminal)
        printf("GPU_PLATFORM_FULL %s records=%u mutations=%u manifest_sha256=%s\n",
               failures ? "FAIL" : "PASS", total, COURSE_PLATFORM_MUTATION_COUNT,
               COURSE_CASE_MANIFEST_SHA256);
    return failures ? 3 : 0;
}

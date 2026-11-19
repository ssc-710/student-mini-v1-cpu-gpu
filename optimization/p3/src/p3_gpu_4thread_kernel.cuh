#ifndef P3_GPU_4THREAD_KERNEL_CUH
#define P3_GPU_4THREAD_KERNEL_CUH

#include <stdint.h>

#if defined(__CUDACC__)
#define P3_4T_HD __host__ __device__
#define P3_4T_DEVICE __device__
#else
#define P3_4T_HD
#endif

enum p3_4thread_error {
    P3_4T_ERROR_NONE = 0u,
    P3_4T_ERROR_LAUNCH = 1u << 0,
    P3_4T_ERROR_DESCRIPTOR = 1u << 1,
    P3_4T_ERROR_NUMERIC = 1u << 2,
};

/* Fixed native-Nano contract: intermediate scale is exactly 2^-6. */
P3_4T_HD static int8_t p3_4thread_requant_q6(int64_t value) {
    uint64_t magnitude = value < 0 ? (uint64_t)(-value) : (uint64_t)value;
    uint64_t quotient = magnitude >> 16;
    uint64_t remainder = magnitude & UINT64_C(65535);
    quotient += remainder > UINT64_C(32768) ||
                (remainder == UINT64_C(32768) && (quotient & 1u));
    if (value < 0)
        return quotient >= 128u ? (int8_t)-128 : (int8_t)-(int32_t)quotient;
    return quotient >= 127u ? (int8_t)127 : (int8_t)quotient;
}

P3_4T_HD static unsigned p3_4thread_baseline_columns(
    unsigned tid, const int8_t *x, const int8_t *gate, const int8_t *up,
    float gate_scale, float up_scale, int8_t *intermediate
) {
    unsigned error = P3_4T_ERROR_NONE;
    const unsigned first = tid * 4u;
    for (unsigned lane = 0; lane < 4u; ++lane) {
        const unsigned column = first + lane;
        int32_t gate_acc = 0, up_acc = 0;
        for (unsigned k = 0; k < 16u; ++k) {
            gate_acc += (int32_t)x[k] * gate[k * 16u + column];
            up_acc += (int32_t)x[k] * up[k * 16u + column];
        }
        int16_t gate_q11 = 0, up_q11 = 0;
        if (course_int32_scale_to_q5_11(gate_acc, gate_scale, &gate_q11) ||
            course_int32_scale_to_q5_11(up_acc, up_scale, &up_q11)) {
            error |= P3_4T_ERROR_NUMERIC;
            intermediate[column] = 0;
        } else {
            intermediate[column] = p3_4thread_requant_q6(
                (int64_t)course_silu_q11(gate_q11) * up_q11);
        }
    }
    return error;
}

P3_4T_HD static unsigned p3_4thread_candidate_columns(
    unsigned tid, const int8_t *x, const int8_t *gate, const int8_t *up,
    float gate_scale, float up_scale, int8_t *intermediate
) {
    const unsigned first = tid * 4u;
    int32_t gate_acc[4] = {0, 0, 0, 0};
    int32_t up_acc[4] = {0, 0, 0, 0};
    for (unsigned k = 0; k < 16u; ++k) {
        const int32_t activation = x[k];
        const unsigned row = k * 16u + first;
        for (unsigned lane = 0; lane < 4u; ++lane) {
            gate_acc[lane] += activation * gate[row + lane];
            up_acc[lane] += activation * up[row + lane];
        }
    }
    unsigned error = P3_4T_ERROR_NONE;
    for (unsigned lane = 0; lane < 4u; ++lane) {
        int16_t gate_q11 = 0, up_q11 = 0;
        if (course_int32_scale_to_q5_11(gate_acc[lane], gate_scale, &gate_q11) ||
            course_int32_scale_to_q5_11(up_acc[lane], up_scale, &up_q11)) {
            error |= P3_4T_ERROR_NUMERIC;
            intermediate[first + lane] = 0;
        } else {
            intermediate[first + lane] = p3_4thread_requant_q6(
                (int64_t)course_silu_q11(gate_q11) * up_q11);
        }
    }
    return error;
}

P3_4T_HD static void p3_4thread_down_columns(
    unsigned tid, const int8_t *intermediate, const int8_t *down,
    float down_scale, uint16_t *out
) {
    const unsigned first = tid * 4u;
    int32_t acc[4] = {0, 0, 0, 0};
    for (unsigned k = 0; k < 16u; ++k) {
        const int32_t activation = intermediate[k];
        const unsigned row = k * 16u + first;
        for (unsigned lane = 0; lane < 4u; ++lane)
            acc[lane] += activation * down[row + lane];
    }
    for (unsigned lane = 0; lane < 4u; ++lane)
        out[first + lane] = course_bf16_rne_bits(
            (float)acc[lane] * (0x1p-6f * down_scale));
}

/* Sequential phase emulator for host differential testing of the cooperative ABI. */
P3_4T_HD static unsigned p3_4thread_host_reference(
    int candidate, const int8_t *x, const int8_t *gate, const int8_t *up,
    const int8_t *down, float gate_scale, float up_scale, float down_scale,
    uint16_t *out
) {
    int8_t intermediate[16];
    unsigned error = P3_4T_ERROR_NONE;
    for (unsigned tid = 0; tid < 4u; ++tid)
        error |= candidate
            ? p3_4thread_candidate_columns(tid, x, gate, up, gate_scale, up_scale,
                                           intermediate)
            : p3_4thread_baseline_columns(tid, x, gate, up, gate_scale, up_scale,
                                          intermediate);
    if (error != P3_4T_ERROR_NONE) return error;
    for (unsigned tid = 0; tid < 4u; ++tid)
        p3_4thread_down_columns(tid, intermediate, down, down_scale, out);
    return P3_4T_ERROR_NONE;
}

#if defined(__CUDACC__)
template <bool Candidate>
__global__ void p3_gpu_4thread_kernel(
    const int8_t *x, const int8_t *gate_all, const int8_t *up_all,
    const int8_t *down_all, unsigned expert, unsigned experts,
    float gate_scale, float up_scale, float down_scale, uint16_t *out,
    unsigned *status, unsigned *completed
) {
    __shared__ volatile int8_t intermediate0, intermediate1, intermediate2, intermediate3;
    __shared__ volatile int8_t intermediate4, intermediate5, intermediate6, intermediate7;
    __shared__ volatile int8_t intermediate8, intermediate9, intermediate10, intermediate11;
    __shared__ volatile int8_t intermediate12, intermediate13, intermediate14, intermediate15;
    __shared__ unsigned error_mask;
    __shared__ unsigned stop;
    __shared__ volatile unsigned lane_error0, lane_error1, lane_error2, lane_error3;
    const unsigned tid = threadIdx.x;
    const bool publish = tid == 0u;

    if (publish) {
        error_mask = P3_4T_ERROR_NONE;
        stop = 0u;
        lane_error0 = lane_error1 = lane_error2 = lane_error3 = P3_4T_ERROR_NONE;
        if (blockIdx.x != 0u || gridDim.x != 1u || blockDim.x != 4u)
            error_mask |= P3_4T_ERROR_LAUNCH;
        if (expert >= experts || !x || !gate_all || !up_all || !down_all ||
            !out || !status || !completed)
            error_mask |= P3_4T_ERROR_DESCRIPTOR;
        stop = error_mask != P3_4T_ERROR_NONE;
    }
    __syncthreads();

    if (!stop && tid < 4u) {
        const unsigned offset = expert * 256u;
        int8_t lane_values[16];
        const unsigned lane_result = Candidate
            ? p3_4thread_candidate_columns(tid, x, gate_all + offset,
                                           up_all + offset, gate_scale, up_scale,
                                           lane_values)
            : p3_4thread_baseline_columns(tid, x, gate_all + offset,
                                          up_all + offset, gate_scale, up_scale,
                                          lane_values);
        if (tid == 0u) {
            lane_error0 = lane_result;
            intermediate0 = lane_values[0]; intermediate1 = lane_values[1];
            intermediate2 = lane_values[2]; intermediate3 = lane_values[3];
        } else if (tid == 1u) {
            lane_error1 = lane_result;
            intermediate4 = lane_values[4]; intermediate5 = lane_values[5];
            intermediate6 = lane_values[6]; intermediate7 = lane_values[7];
        } else if (tid == 2u) {
            lane_error2 = lane_result;
            intermediate8 = lane_values[8]; intermediate9 = lane_values[9];
            intermediate10 = lane_values[10]; intermediate11 = lane_values[11];
        } else {
            lane_error3 = lane_result;
            intermediate12 = lane_values[12]; intermediate13 = lane_values[13];
            intermediate14 = lane_values[14]; intermediate15 = lane_values[15];
        }
    }
    __syncthreads();

    if (publish) {
        error_mask |= lane_error0 | lane_error1 | lane_error2 | lane_error3;
        stop = error_mask != P3_4T_ERROR_NONE;
    }
    __syncthreads();

    if (!stop && tid < 4u) {
        const unsigned offset = expert * 256u;
        int8_t snapshot[16];
        snapshot[0] = intermediate0; snapshot[1] = intermediate1;
        snapshot[2] = intermediate2; snapshot[3] = intermediate3;
        snapshot[4] = intermediate4; snapshot[5] = intermediate5;
        snapshot[6] = intermediate6; snapshot[7] = intermediate7;
        snapshot[8] = intermediate8; snapshot[9] = intermediate9;
        snapshot[10] = intermediate10; snapshot[11] = intermediate11;
        snapshot[12] = intermediate12; snapshot[13] = intermediate13;
        snapshot[14] = intermediate14; snapshot[15] = intermediate15;
        p3_4thread_down_columns(tid, snapshot, down_all + offset,
                                down_scale, out);
    }
    __syncthreads();

    if (publish) {
        if (status) *status = error_mask;
        if (completed) *completed = stop ? 0u : 1u;
    }
    __syncthreads();
}
#endif

#undef P3_4T_HD
#if defined(__CUDACC__)
#undef P3_4T_DEVICE
#endif

#endif

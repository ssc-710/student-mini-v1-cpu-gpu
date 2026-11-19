#ifndef P3_GPU_CYCLE_PROFILE_H
#define P3_GPU_CYCLE_PROFILE_H

#include <stdint.h>

#define P3_CYCLE_PROFILE_ABI_VERSION 1u
#define P3_CYCLE_PROFILE_COMMIT_MAGIC 0x50334331u

typedef struct {
    uint32_t abi_version;
    uint32_t routed_calls;
    uint32_t shared_calls;
    uint32_t failed_calls;
    uint32_t routed_cycles_lo;
    uint32_t routed_cycles_hi;
    uint32_t shared_cycles_lo;
    uint32_t shared_cycles_hi;
    uint32_t empty_cycles_lo;
    uint32_t empty_cycles_hi;
    uint32_t commit_magic;
} p3_cycle_profile;

#ifdef __cplusplus
static_assert(sizeof(p3_cycle_profile) == 44, "p3 cycle profile ABI changed");
#else
_Static_assert(sizeof(p3_cycle_profile) == 44, "p3 cycle profile ABI changed");
#endif

static inline uint64_t p3_profile_join(uint32_t lo, uint32_t hi) {
    return ((uint64_t)hi << 32) | lo;
}

#endif

// Device-scope SPV_KHR_shader_clock implementation for the Vortex RV32 target.
#include <stdint.h>
#include "vx_intrinsics.h"

uint64_t clock_read_device() {
    return vx_rdcycle_sync();
}

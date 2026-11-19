#include "student_mini_native_nano.h"
#include "operator_scalar.h"

typedef struct { uint32_t significand; int shift; } p3_hoist_scale_ctx;

static int p3_hoist_scale_prepare(float scale, p3_hoist_scale_ctx *ctx) {
    union { float f; uint32_t u; } bits = { .f = scale };
    if (!(scale >= 0x1p-16f && scale <= 0x1p16f) ||
        (bits.u & 0x7f800000u) == 0x7f800000u) return -2;
    ctx->significand = 0x800000u | (bits.u & 0x7fffffu);
    ctx->shift = (int)((bits.u >> 23) & 0xffu) - 139;
    return 0;
}

static int16_t p3_hoist_signed_sat(int32_t value, uint64_t scaled) {
    if (value < 0)
        return scaled >= 32768u ? INT16_MIN : (int16_t)-(int32_t)scaled;
    return scaled >= 32767u ? INT16_MAX : (int16_t)scaled;
}

__attribute__((noinline)) static void p3_hoist_scale_apply4(
        const int32_t value[4], const p3_hoist_scale_ctx *ctx, int16_t result[4]) {
    if (ctx->shift >= 0) {
        unsigned shift = (unsigned)ctx->shift;
        for (unsigned lane=0; lane<4; ++lane) {
            uint64_t magnitude = value[lane] < 0
                ? (uint64_t)(-(int64_t)value[lane]) : (uint64_t)value[lane];
            uint64_t scaled = magnitude * ctx->significand << shift;
            result[lane] = p3_hoist_signed_sat(value[lane], scaled);
        }
    } else {
        unsigned shift = (unsigned)-ctx->shift;
        uint64_t mask = (UINT64_C(1) << shift) - 1u;
        uint64_t half = UINT64_C(1) << (shift - 1u);
        for (unsigned lane=0; lane<4; ++lane) {
            uint64_t magnitude = value[lane] < 0
                ? (uint64_t)(-(int64_t)value[lane]) : (uint64_t)value[lane];
            uint64_t product = magnitude * ctx->significand;
            uint64_t q = product >> shift;
            uint64_t r = product & mask;
            uint64_t scaled = q + (r > half || (r == half && (q & 1u)));
            result[lane] = p3_hoist_signed_sat(value[lane], scaled);
        }
    }
}

static int8_t p3_hoist_requant_q6(int64_t value) {
    uint64_t mag=value<0 ? (uint64_t)(-value) : (uint64_t)value;
    uint64_t q=mag>>16, r=mag&65535u;
    q += r>32768u || (r==32768u && (q&1u));
    return value<0 ? (q>=128u ? -128 : -(int8_t)q) : (q>=127u ? 127 : (int8_t)q);
}

int p3_native_candidate_ctx_hoist(void *user,unsigned expert,const int8_t *x,float input_scale,
                                  const mini_native_model *m,uint16_t *out) {
    (void)user;
    if (expert>2) return -1;
    unsigned gate=expert==2 ? MINI_SHARED_GATE : MINI_GATE;
    unsigned up=expert==2 ? MINI_SHARED_UP : MINI_UP;
    unsigned down=expert==2 ? MINI_SHARED_DOWN : MINI_DOWN;
    unsigned offset=expert==2 ? 0 : expert*256;
    float gs=input_scale*m->scale[gate], us=input_scale*m->scale[up];
    p3_hoist_scale_ctx gc,uc;
    if (p3_hoist_scale_prepare(gs,&gc) || p3_hoist_scale_prepare(us,&uc)) return -2;
    float ds=0x1p-6f*m->scale[down];
    int8_t intermediate[16];
    for (unsigned j=0;j<16;j+=4) {
        int32_t ga[4]={0},ua[4]={0};
        for (unsigned k=0;k<16;++k) {
            int32_t a=x[k]; unsigned w=offset+k*16+j;
            for (unsigned lane=0;lane<4;++lane) {
                ga[lane]+=a*m->weight[gate][w+lane];
                ua[lane]+=a*m->weight[up][w+lane];
            }
        }
        int16_t g[4],u[4];
        p3_hoist_scale_apply4(ga,&gc,g); p3_hoist_scale_apply4(ua,&uc,u);
        for (unsigned lane=0;lane<4;++lane)
            intermediate[j+lane]=p3_hoist_requant_q6((int64_t)course_silu_q11(g[lane])*u[lane]);
    }
    for (unsigned j=0;j<16;j+=4) {
        int32_t acc[4]={0};
        for (unsigned k=0;k<16;++k)
            for (unsigned lane=0;lane<4;++lane)
                acc[lane]+=(int32_t)intermediate[k]*m->weight[down][offset+k*16+j+lane];
        for (unsigned lane=0;lane<4;++lane)
            out[j+lane]=course_bf16_rne_bits((float)acc[lane]*ds);
    }
    return 0;
}

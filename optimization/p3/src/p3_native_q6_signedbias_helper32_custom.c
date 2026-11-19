typedef struct { uint32_t significand; int shift; } p3_scale_ctx;

static int p3_scale_prepare(float scale, p3_scale_ctx *ctx) {
    union { float f; uint32_t u; } bits = { .f = scale };
    if (!(scale >= 0x1p-16f && scale <= 0x1p16f) ||
        (bits.u & 0x7f800000u) == 0x7f800000u) return -2;
    ctx->significand = 0x800000u | (bits.u & 0x7fffffu);
    ctx->shift = (int)((bits.u >> 23) & 0xffu) - 139;
    __asm__ volatile (".option push\n.option norvc\nj 1f\n.space 36\n1:\n.option pop" ::: "memory");
    return 0;
}

__attribute__((always_inline)) static inline void p3_scale_apply2(const int32_t value[2],
        const p3_scale_ctx *ctx, int16_t result[2]) {
    const uint32_t packed=ctx->significand | (((uint32_t)ctx->shift & 63u)<<24);
    { int32_t scaled;
      __asm__ volatile (".insn r 0x0b, 0, 0x2a, %0, %1, %2" : "=r"(scaled) : "r"(value[0]), "r"(packed));
      result[0]=(int16_t)scaled; }
    { int32_t scaled;
      __asm__ volatile (".insn r 0x0b, 0, 0x2a, %0, %1, %2" : "=r"(scaled) : "r"(value[1]), "r"(packed));
      result[1]=(int16_t)scaled; }
}

__attribute__((aligned(16),noinline)) static int8_t p3_ctx_requant_q6(int32_t value) {
    __asm__ volatile (".option push\n.option norvc\nj 1f\n.space 28\n1:\n.option pop" ::: "memory");
    int32_t q=(value+32767+(int32_t)(((uint32_t)value>>16)&1u))>>16;
    return q>127 ? 127 : (q < -128 ? -128 : (int8_t)q);
}

__attribute__((aligned(16))) int p3_native_candidate_ctx(void *user,unsigned expert,const int8_t *x,float input_scale,
                            const mini_native_model *m,uint16_t *out) {
    (void)user;
    if (expert>2) return -1;
    unsigned gate=expert==2 ? MINI_SHARED_GATE : MINI_GATE;
    unsigned up=expert==2 ? MINI_SHARED_UP : MINI_UP;
    unsigned down=expert==2 ? MINI_SHARED_DOWN : MINI_DOWN;
    unsigned offset=expert==2 ? 0 : expert*256;
    float gs=input_scale*m->scale[gate], us=input_scale*m->scale[up];
    p3_scale_ctx gc,uc;
    if (p3_scale_prepare(gs,&gc) || p3_scale_prepare(us,&uc)) return -2;
    float ds=0x1p-6f*m->scale[down];
    int8_t intermediate[16];
    for (unsigned j=0;j<16;j+=2) {
        int32_t g0=0,g1=0,u0=0,u1=0;
        const int8_t *gw=m->weight[gate]+offset+j,*uw=m->weight[up]+offset+j;
        for (unsigned k=0;k<16;++k) {
            int32_t v=x[k];
            g0+=v*gw[0];g1+=v*gw[1];u0+=v*uw[0];u1+=v*uw[1];
            gw+=16;uw+=16;
        }
        int32_t ga[2]={g0,g1},ua[2]={u0,u1};int16_t g[2],u[2];
        p3_scale_apply2(ga,&gc,g);p3_scale_apply2(ua,&uc,u);
        intermediate[j]=p3_ctx_requant_q6((int32_t)course_silu_q11(g[0])*u[0]);
        intermediate[j+1]=p3_ctx_requant_q6((int32_t)course_silu_q11(g[1])*u[1]);
    }
    for (unsigned j=0;j<16;j+=4) {
        int32_t a0=0,a1=0,a2=0,a3=0;const int8_t *dw=m->weight[down]+offset+j;
        for (unsigned k=0;k<16;++k) {
            int32_t v=intermediate[k];a0+=v*dw[0];a1+=v*dw[1];a2+=v*dw[2];a3+=v*dw[3];dw+=16;
        }
        out[j+0]=course_bf16_rne_bits((float)a0*ds);
        out[j+1]=course_bf16_rne_bits((float)a1*ds);
        out[j+2]=course_bf16_rne_bits((float)a2*ds);
        out[j+3]=course_bf16_rne_bits((float)a3*ds);
    }
    __asm__ volatile (".option push\n.option norvc\nj 1f\n.space 36\n1:\n.option pop" ::: "memory");
    return 0;
}


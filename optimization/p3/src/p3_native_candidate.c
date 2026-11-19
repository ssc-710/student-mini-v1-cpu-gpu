#include "student_mini_native_nano.h"
#include "operator_scalar.h"

/* Private INT16*INT16 domain: |value|<=2^30. Q22 / 2^-6 is Q16. */
static int8_t p3_requant_q6(int64_t value) {
    uint64_t mag=value<0 ? (uint64_t)(-value) : (uint64_t)value;
    uint64_t q=mag>>16, r=mag&65535u;
    q+=(r>32768u || (r==32768u && (q&1u)));
    return value<0 ? (q>=128u ? -128 : -(int8_t)q) : (q>=127u ? 127 : (int8_t)q);
}

int p3_native_candidate(void *user,unsigned expert,const int8_t *x,float input_scale,
                        const mini_native_model *m,uint16_t *out) {
    (void)user;
    if(expert>2)return -1;
    unsigned gate=expert==2 ? MINI_SHARED_GATE : MINI_GATE;
    unsigned up=expert==2 ? MINI_SHARED_UP : MINI_UP;
    unsigned down=expert==2 ? MINI_SHARED_DOWN : MINI_DOWN;
    unsigned offset=expert==2 ? 0 : expert*256;
    float gs=input_scale*m->scale[gate],us=input_scale*m->scale[up];
    int8_t intermediate[16];
    for(unsigned j=0;j<16;j+=4) {
        int32_t ga[4]={0},ua[4]={0};
        for(unsigned k=0;k<16;++k) {
            int32_t a=x[k];unsigned w=offset+k*16+j;
            for(unsigned lane=0;lane<4;++lane) {
                ga[lane]+=a*m->weight[gate][w+lane];
                ua[lane]+=a*m->weight[up][w+lane];
            }
        }
        for(unsigned lane=0;lane<4;++lane) {
            int16_t g,u;
            if(course_int32_scale_to_q5_11(ga[lane],gs,&g) ||
               course_int32_scale_to_q5_11(ua[lane],us,&u))return -2;
            intermediate[j+lane]=p3_requant_q6((int64_t)course_silu_q11(g)*u);
        }
    }
    for(unsigned j=0;j<16;j+=4) {
        int32_t acc[4]={0};
        for(unsigned k=0;k<16;++k)
            for(unsigned lane=0;lane<4;++lane)
                acc[lane]+=(int32_t)intermediate[k]*m->weight[down][offset+k*16+j+lane];
        for(unsigned lane=0;lane<4;++lane)
            out[j+lane]=course_bf16_rne_bits((float)acc[lane]*(0x1p-6f*m->scale[down]));
    }
    return 0;
}

#ifdef P3_TEST_PRIMITIVE
int p3_test_requant(int64_t value){return p3_requant_q6(value);}
#endif

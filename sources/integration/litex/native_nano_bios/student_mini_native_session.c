// SPDX-License-Identifier: Apache-2.0
#include <stdint.h>
#include <stdio.h>
#include <generated/mem.h>
#include <generated/csr.h>
#include "init.h"
#include "student_mini_native_nano.h"
#include "student_mini_native_image.h"

static uint64_t counter(unsigned instructions) {
    uint32_t hi,lo,again;
    do {
        if(instructions) {
            __asm__ volatile("csrr %0, minstreth":"=r"(hi));
            __asm__ volatile("csrr %0, minstret":"=r"(lo));
            __asm__ volatile("csrr %0, minstreth":"=r"(again));
        } else {
            __asm__ volatile("csrr %0, mcycleh":"=r"(hi));
            __asm__ volatile("csrr %0, mcycle":"=r"(lo));
            __asm__ volatile("csrr %0, mcycleh":"=r"(again));
        }
    } while(hi!=again);
    return ((uint64_t)hi<<32)|lo;
}
static void print64(uint64_t n) { printf("%lu:%lu",(unsigned long)(n>>32),(unsigned long)n); }
typedef struct { uint64_t start, step[12], op_cycles[3]; } timings;
static void step_done(void *user,unsigned step,uint32_t token) {
    (void)token;
    timings *t=user;
    t->step[step]=counter(0)-t->start;
}
static int attention(void *user,unsigned prefill,unsigned rows,unsigned length,
    const int8_t *q,const int8_t *k,const int8_t *iq,const int8_t *ik,
    float ss,float is,float vs,uint16_t *out) {
    uint64_t begin=counter(0);
    int code=mini_native_scalar_attention(0,prefill,rows,length,q,k,iq,ik,ss,is,vs,out);
    ((timings *)user)->op_cycles[prefill?0:1]+=counter(0)-begin;
    return code;
}
static int expert(void *user,unsigned id,const int8_t *x,float s,const mini_native_model *m,uint16_t *out) {
    uint64_t begin=counter(0);
    int code=mini_native_scalar_expert(0,id,x,s,m,out);
    ((timings *)user)->op_cycles[2]+=counter(0)-begin;
    return code;
}

#define TENSOR_MAP(X) \
 X(EMBEDDING,EMBEDDING) X(LM_HEAD,LM_HEAD) X(FINAL_NORM,FINAL_NORM) \
 X(ATTN_NORM,ATTENTION_NORM) X(MOE_NORM,MOE_NORM) \
 X(Q_NOPE,ATTENTION_Q_NOPE) X(Q_PE,ATTENTION_Q_PE) X(INDEX_Q,ATTENTION_INDEX_Q) \
 X(CKV,ATTENTION_CKV) X(KPE,ATTENTION_KPE) X(INDEX_K,ATTENTION_INDEX_K) \
 X(ATTN_OUT,ATTENTION_OUT) X(ROUTER,ROUTER) X(GATE,GATE) X(UP,UP) X(DOWN,DOWN) \
 X(SHARED_GATE,SHARED_GATE) X(SHARED_UP,SHARED_UP) X(SHARED_DOWN,SHARED_DOWN)

static void student_mini_native_session(void) {
    uint8_t *image=(uint8_t *)MAIN_RAM_BASE;
    mini_native_model model;
    const float *scales=(const float *)(image+COURSE_NANO_SEGMENT_SCALES_FP32_OFFSET);
#define LOAD(ID,NAME) model.weight[MINI_##ID]=(const int8_t *)(image+COURSE_NANO_SEGMENT_WEIGHT_##NAME##_OFFSET); model.scale[MINI_##ID]=scales[COURSE_NANO_SCALE_##NAME##_INDEX];
    TENSOR_MAP(LOAD)
#undef LOAD
    mini_native_result *result=(mini_native_result *)(image+COURSE_NANO_SEGMENT_OPERATOR_SCRATCH_OFFSET);
    timings timer={0};
    mini_native_backend backend={&timer,attention,expert,step_done};
    printf("STUDENT_NATIVE_CPU_BEGIN prompt_tokens=%u max_tokens=12\n",COURSE_NANO_PROMPT_TOKENS);
    cpu_traffic_reset_write(1);cpu_traffic_reset_write(0);
    uint64_t inst=counter(1);timer.start=counter(0);
    int status=mini_native_generate(&model,(const uint32_t *)(image+COURSE_NANO_SEGMENT_PROMPT_TOKENS_U32_OFFSET),COURSE_NANO_PROMPT_TOKENS,&backend,result);
    uint64_t cycles=counter(0)-timer.start,instructions=counter(1)-inst;
    cpu_traffic_capture_write(1);cpu_traffic_capture_write(0);
    uint64_t ibus=cpu_traffic_ibus_bytes_read(),dbus=cpu_traffic_dbus_bytes_read(),dma=cpu_traffic_dma_bytes_read();
    printf("STUDENT_NATIVE_CPU status=%d count=%u cycles=",status,result->count);print64(cycles);
    printf(" instructions=");print64(instructions);
    printf(" ibus_bytes=");print64(ibus);printf(" dbus_bytes=");print64(dbus);printf(" dma_bytes=");print64(dma);printf("\n");
    if(status || result->count>12) return;
    uint32_t *generated=(uint32_t *)(image+COURSE_NANO_SEGMENT_GENERATED_TOKENS_U32_OFFSET);
    for(unsigned step=0;step<result->count;++step) {
        generated[step]=result->tokens[step];
        printf("STUDENT_NATIVE_TOKEN step=%u token=%lu elapsed_cycles=",step,(unsigned long)generated[step]);print64(timer.step[step]);
        printf(" hidden=");
        for(unsigned j=0;j<16;++j) printf("%s%04x",j?",":"",result->final_hidden[step][j]);
        printf(" logits=");
        for(unsigned j=0;j<256;++j) printf("%s%04x",j?",":"",result->logits[step][j]);
        printf("\n");
    }
    for(unsigned op=0;op<3;++op) { printf("STUDENT_NATIVE_OPERATOR op=%u cycles=",op+1);print64(timer.op_cycles[op]);printf("\n"); }
    printf("STUDENT_NATIVE_CPU_COMPLETE count=%u p1=%u p2=%u p3=%u\n",result->count,result->p1_calls,result->p2_calls,result->p3_calls);
}
define_init_func(student_mini_native_session);

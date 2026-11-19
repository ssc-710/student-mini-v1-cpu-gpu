// SPDX-License-Identifier: Apache-2.0
// Native one-layer autoregressive model. No answer/intent/position table.
// Compile without fast-math or FP contraction: binary32 boundaries are the ABI.
#include "include/student_mini_native_nano.h"
#include "include/operator_scalar.h"
#include <string.h>

static float bf(uint16_t x) {
    union { uint32_t u; float f; } v = {.u=(uint32_t)x << 16};
    return v.f;
}
static float rounded(float x) { return bf(course_bf16_rne_bits(x)); }
static float clamp(float x) { return x < 0x1p-16f ? 0x1p-16f : x > 0x1p16f ? 0x1p16f : x; }
static int32_t rne_float(float x) {
    int32_t q=(int32_t)x;
    if(x < (float)q) --q;
    float r=x-(float)q;
    return q+(r>0.5f || (r==0.5f && (q&1)));
}
static int64_t rne_div(int64_t n, int64_t d) {
    uint64_t a=n<0 ? (uint64_t)(-(n+1))+1u : (uint64_t)n;
    uint64_t q=a/(uint64_t)d, r=a%(uint64_t)d;
    if(r*2u>(uint64_t)d || (r*2u==(uint64_t)d && (q&1u))) ++q;
    return n<0 ? -(int64_t)q : (int64_t)q;
}
static float quantize(const float *x, unsigned n, int8_t *out) {
    float peak=0;
    for(unsigned i=0;i<n;++i) { float a=x[i]<0 ? -x[i] : x[i]; if(a>peak) peak=a; }
    float s=peak ? clamp(peak/127.0f) : 1.0f;
    for(unsigned i=0;i<n;++i) {
        int32_t q=rne_float(x[i]/s);
        out[i]=(int8_t)(q < -128 ? -128 : q > 127 ? 127 : q);
    }
    return s;
}
static void matmul(const mini_native_model *m, unsigned id, const float *x,
                   unsigned in, unsigned out, unsigned transpose, float *y) {
    int8_t a[16];
    float s=quantize(x,in,a)*m->scale[id];
    for(unsigned j=0;j<out;++j) {
        int32_t acc=0;
        for(unsigned k=0;k<in;++k)
            acc+=(int32_t)a[k]*m->weight[id][transpose ? j*in+k : k*out+j];
        y[j]=rounded((float)acc*s);
    }
}
static void norm(const mini_native_model *m, unsigned id, const float *x, float *y) {
    float sum=0;
    for(unsigned j=0;j<16;++j) sum+=x[j]*x[j];
    float target=sum/16.0f+0.000001f, root=target>1.0f ? target : 1.0f;
    for(unsigned j=0;j<12;++j) root=0.5f*(root+target/root);
    for(unsigned j=0;j<16;++j) y[j]=rounded((x[j]/root)*((float)m->weight[id][j]*m->scale[id]));
}
static void rope(float *x, unsigned position) {
    for(unsigned pair=0;pair<2;++pair) {
        float a=(float)position*(pair ? 0.01f : 1.0f);
        while(a>3.14159265358979323846f) a-=6.28318530717958647692f;
        float a2=a*a;
        float s=-0.0000000250521084f;
        s=0.0000027557319224f+a2*s; s=-0.0001984126984127f+a2*s;
        s=0.0083333333333333f+a2*s; s=-0.1666666666666667f+a2*s;
        s=a*(1.0f+a2*s);
        float c=0.0000000020876757f;
        c=-0.0000002755731922f+a2*c; c=0.0000248015873016f+a2*c;
        c=-0.0013888888888889f+a2*c; c=0.0416666666666667f+a2*c;
        c=-0.5f+a2*c; c=1.0f+a2*c;
        float even=x[2*pair], odd=x[2*pair+1];
        x[2*pair]=rounded(even*c-odd*s); x[2*pair+1]=rounded(even*s+odd*c);
    }
}

int mini_native_scalar_attention(void *user, unsigned prefill, unsigned rows,
    unsigned length, const int8_t *query, const int8_t *keys,
    const int8_t *iq, const int8_t *ik, float score_scale, float index_scale,
    float value_scale, uint16_t *output) {
    (void)user;
    if(!rows || rows>length || length>32) return -1;
    for(unsigned row=0;row<rows;++row) {
        unsigned visible=length-rows+row+1, ids[32], count=visible;
        int16_t scores[32];
        for(unsigned t=0;t<visible;++t) {
            ids[t]=t;
            int32_t a=0;
            for(unsigned j=0;j<8;++j) a+=(int32_t)iq[row*8+j]*ik[t*8+j];
            if(course_int32_scale_to_q5_11(a,index_scale,&scores[t])) return -2;
        }
        if(prefill) {
            for(unsigned i=0;i<visible;++i) for(unsigned j=i+1;j<visible;++j)
                if(scores[ids[j]]>scores[ids[i]] || (scores[ids[j]]==scores[ids[i]] && ids[j]<ids[i])) {
                    unsigned tmp=ids[i]; ids[i]=ids[j]; ids[j]=tmp;
                }
            if(count>4) count=4;
        }
        int32_t maximum=0, denominator=0;
        int64_t numerator[8]={0};
        for(unsigned t=0;t<count;++t) {
            int32_t a=0; unsigned token=ids[t]; int16_t score;
            for(unsigned j=0;j<12;++j) a+=(int32_t)query[row*12+j]*keys[token*12+j];
            if(course_int32_scale_to_q5_11(a,score_scale,&score)) return -2;
            if(!t) {
                maximum=score; denominator=32768;
                for(unsigned j=0;j<8;++j) numerator[j]=(int32_t)keys[token*12+j]*32768;
            } else {
                int32_t next=maximum>score ? maximum : score;
                int32_t old=course_exp_neg_q15(maximum-next), added=course_exp_neg_q15(score-next);
                denominator=(int32_t)rne_div((int64_t)denominator*old,32768)+added;
                for(unsigned j=0;j<8;++j) numerator[j]=rne_div(numerator[j]*old,32768)+(int32_t)keys[token*12+j]*added;
                maximum=next;
            }
        }
        for(unsigned j=0;j<8;++j) {
            int32_t q=(int32_t)rne_div(numerator[j]*65536,denominator);
            output[row*8+j]=course_bf16_rne_bits(((float)q/65536.0f)*value_scale);
        }
    }
    return 0;
}

int mini_native_scalar_expert(void *user, unsigned expert, const int8_t *x,
    float input_scale, const mini_native_model *m, uint16_t *out) {
    (void)user;
    if(expert>2) return -1;
    unsigned gate=expert==2 ? MINI_SHARED_GATE : MINI_GATE;
    unsigned up=expert==2 ? MINI_SHARED_UP : MINI_UP;
    unsigned down=expert==2 ? MINI_SHARED_DOWN : MINI_DOWN;
    unsigned offset=expert==2 ? 0 : expert*256;
    int8_t intermediate[16];
    for(unsigned j=0;j<16;++j) {
        int32_t ga=0, ua=0; int16_t g,u;
        for(unsigned k=0;k<16;++k) {
            ga+=(int32_t)x[k]*m->weight[gate][offset+k*16+j];
            ua+=(int32_t)x[k]*m->weight[up][offset+k*16+j];
        }
        if(course_int32_scale_to_q5_11(ga,input_scale*m->scale[gate],&g) ||
           course_int32_scale_to_q5_11(ua,input_scale*m->scale[up],&u) ||
           course_q22_requantize_int8((int64_t)course_silu_q11(g)*u,0x1p-6f,&intermediate[j])) return -2;
    }
    for(unsigned j=0;j<16;++j) {
        int32_t acc=0;
        for(unsigned k=0;k<16;++k) acc+=(int32_t)intermediate[k]*m->weight[down][offset+k*16+j];
        out[j]=course_bf16_rne_bits((float)acc*(0x1p-6f*m->scale[down]));
    }
    return 0;
}

int mini_native_generate(const mini_native_model *m, const uint32_t *prompt,
    unsigned prompt_count, const mini_native_backend *backend, mini_native_result *result) {
    if(!m || !prompt || !result || !prompt_count || prompt_count+12>32) return -1;
    for(unsigned i=0;i<MINI_TENSOR_COUNT;++i)
        if(!m->weight[i] || !(m->scale[i]>=0x1p-16f && m->scale[i]<=0x1p16f)) return -1;
    for(unsigned i=0;i<prompt_count;++i) if(prompt[i]>=256) return -1;
    if(backend && (!backend->attention || !backend->expert)) return -1;
    mini_attention_fn attention=backend ? backend->attention : mini_native_scalar_attention;
    mini_expert_fn expert_fn=backend ? backend->expert : mini_native_scalar_expert;
    void *user=backend ? backend->user : 0;
    memset(result,0,sizeof(*result));
    float (*cache)[12]=result->workspace.cache, (*index_cache)[8]=result->workspace.index_cache;
    float (*hidden)[16]=result->workspace.hidden, (*normalized)[16]=result->workspace.normalized;
    float (*queries)[12]=result->workspace.queries, (*index_queries)[8]=result->workspace.index_queries;
    int8_t (*ki)[12]=result->workspace.ki, (*iki)[8]=result->workspace.iki;
    int8_t (*qi)[12]=result->workspace.qi, (*iqi)[8]=result->workspace.iqi;
    uint16_t (*attended)[8]=result->workspace.attended;
    unsigned length=0;
    for(unsigned step=0;step<12;++step) {
        unsigned rows=step ? 1 : prompt_count, start=length;
        length+=rows;
        for(unsigned row=0;row<rows;++row) {
            unsigned token=step ? result->tokens[step-1] : prompt[row];
            for(unsigned j=0;j<16;++j) hidden[row][j]=rounded((float)m->weight[MINI_EMBEDDING][token*16+j]*m->scale[MINI_EMBEDDING]);
            norm(m,MINI_ATTN_NORM,hidden[row],normalized[row]);
            matmul(m,MINI_CKV,normalized[row],16,8,0,cache[start+row]);
            matmul(m,MINI_KPE,normalized[row],16,4,0,cache[start+row]+8);
            rope(cache[start+row]+8,start+row);
            matmul(m,MINI_INDEX_K,normalized[row],16,8,0,index_cache[start+row]);
            matmul(m,MINI_Q_NOPE,normalized[row],16,8,0,queries[row]);
            matmul(m,MINI_Q_PE,normalized[row],16,4,0,queries[row]+8);
            rope(queries[row]+8,start+row);
            matmul(m,MINI_INDEX_Q,normalized[row],16,8,0,index_queries[row]);
        }
        float ks=quantize(&cache[0][0],length*12,&ki[0][0]);
        float iks=quantize(&index_cache[0][0],length*8,&iki[0][0]);
        float qs=quantize(&queries[0][0],rows*12,&qi[0][0]);
        float iqs=quantize(&index_queries[0][0],rows*8,&iqi[0][0]);
        float score=clamp((qs*ks)/3.4641016151377544f), index=clamp(iqs*iks);
        if(attention(user,step==0,rows,length,&qi[0][0],&ki[0][0],&iqi[0][0],&iki[0][0],score,index,ks,&attended[0][0])) return -2;
        if(step) ++result->p2_calls; else ++result->p1_calls;
        for(unsigned row=0;row<rows;++row) {
            float value[8], projected[16], router[2]; int8_t activation[16]; uint16_t routed[16], shared[16];
            for(unsigned j=0;j<8;++j) value[j]=bf(attended[row][j]);
            matmul(m,MINI_ATTN_OUT,value,8,16,0,projected);
            for(unsigned j=0;j<16;++j) hidden[row][j]=rounded(hidden[row][j]+projected[j]);
            norm(m,MINI_MOE_NORM,hidden[row],normalized[row]);
            matmul(m,MINI_ROUTER,normalized[row],16,2,0,router);
            unsigned expert=router[1]>router[0] ? 1 : 0;
            float s=quantize(normalized[row],16,activation);
            if(expert_fn(user,expert,activation,s,m,routed) || expert_fn(user,2,activation,s,m,shared)) return -3;
            result->p3_calls+=2;
            for(unsigned j=0;j<16;++j) hidden[row][j]=rounded(hidden[row][j]+(bf(routed[j])+bf(shared[j])));
        }
        float final[16], logits[256];
        norm(m,MINI_FINAL_NORM,hidden[rows-1],final);
        matmul(m,MINI_LM_HEAD,final,16,256,1,logits);
        unsigned best=0;
        for(unsigned j=0;j<16;++j) result->final_hidden[step][j]=course_bf16_rne_bits(final[j]);
        for(unsigned j=0;j<256;++j) {
            result->logits[step][j]=course_bf16_rne_bits(logits[j]);
            if(logits[j]>logits[best]) best=j;
        }
        result->tokens[result->count++]=best;
        if(backend && backend->step_complete) backend->step_complete(user,step,best);
        if(best==4) break;
    }
    return 0;
}

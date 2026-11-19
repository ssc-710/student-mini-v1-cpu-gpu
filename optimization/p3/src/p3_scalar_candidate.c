// SPDX-License-Identifier: Apache-2.0
// Conservative, serial full-vector B0. Host execution is preflight only.
#include "student_mini_scalar.h"
#include "operator_scalar.h"
#include <string.h>

static uint32_t word(const uint8_t *p, unsigned i) {
    p+=4*i;
    return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);
}
static float real(const uint8_t *p,unsigned i) {
    union {uint32_t u;float f;} v={.u=word(p,i)};
    return v.f;
}
static int valid_scale(float f) { return f>=0x1p-16f && f<=0x1p16f; }
static int64_t rne(int64_t n,int64_t d) {
    uint64_t m=n<0 ? (uint64_t)(-(n+1))+1u : (uint64_t)n;
    uint64_t q=m/(uint64_t)d,r=m%(uint64_t)d;
    if (r*2u>(uint64_t)d || (r*2u==(uint64_t)d && (q&1u))) ++q;
    return n<0 ? -(int64_t)q : (int64_t)q;
}
typedef struct {int32_t max,sum;int64_t value[8];unsigned valid;} state;
static void update(state *s,int32_t score,const int8_t *v) {
    if (!s->valid) {
        s->valid=1;s->max=score;s->sum=32768;
        for(unsigned j=0;j<8;++j)s->value[j]=(int32_t)v[j]*32768;
        return;
    }
    int32_t m=s->max>score?s->max:score;
    int32_t a=course_exp_neg_q15(s->max-m),b=course_exp_neg_q15(score-m);
    s->sum=(int32_t)rne((int64_t)s->sum*a,32768)+b;
    for(unsigned j=0;j<8;++j)s->value[j]=rne(s->value[j]*a,32768)+(int32_t)v[j]*b;
    s->max=m;
}
static void merge(state *a,const state *b) {
    if(!b->valid)return;
    if(!a->valid){*a=*b;return;}
    int32_t m=a->max>b->max?a->max:b->max;
    int32_t x=course_exp_neg_q15(a->max-m),y=course_exp_neg_q15(b->max-m);
    a->sum=(int32_t)(rne((int64_t)a->sum*x,32768)+rne((int64_t)b->sum*y,32768));
    for(unsigned j=0;j<8;++j)a->value[j]=rne(a->value[j]*x,32768)+rne(b->value[j]*y,32768);
    a->max=m;
}
static int32_t dot(const int8_t *a,const int8_t *b,unsigned n) {
    int32_t sum=0;
    for(unsigned j=0;j<n;++j)sum+=(int32_t)a[j]*b[j];
    return sum;
}
void student_mini_execute(const uint8_t *p,student_mini_result *r) {
    memset(r,0,sizeof(*r));
    unsigned op=word(p,1),rows=word(p,4),n=word(p,5),k=word(p,6),splits=word(p,7);
    const int8_t *x=(const int8_t *)(p+128),*keys=x+32,*v=keys+96,*iq=v+64,*ik=iq+16;
    const int8_t *gate=ik+64,*up=gate+512,*down=up+512;
    if(word(p,0)!=0x31494e4d || op<1 || op>3){r->status=1;return;}
    if(op<3) {
        if(!rows || rows>2 || !n || n>8){r->status=2;return;}
        if((word(p,10)!=1 && word(p,10)!=4) || (op==1 && (!k || k>4)) ||
           (op==2 && splits!=1 && splits!=2 && splits!=4)){r->status=1;return;}
        if(op==2 && splits>n){r->status=2;return;}
        if(!valid_scale(real(p,21)) || !valid_scale(real(p,22))){r->status=4;return;}
    } else {
        if(!rows || rows>2 || word(p,8)!=16 || word(p,9)!=16){r->status=1;return;}
        for(unsigned i=0;i<rows;++i)if(word(p,14+i)>=2){r->status=1;return;}
        for(unsigned i=16;i<=20;++i)if(!valid_scale(real(p,i))){r->status=4;return;}
    }
    // Bus-fault injection belongs to the target adapter, never to this kernel.
    // 6 means unavailable witness, deliberately NOT the golden BUS_ERROR (5).
    if(word(p,12)&1u){r->status=6;return;}
    if(op<3) {
        for(unsigned row=0;row<rows;++row) {
            unsigned visible=word(p,11)?n-rows+row+1:n;
            unsigned ids[8];int32_t scores[8];
            for(unsigned i=0;i<visible;++i){ids[i]=i;scores[i]=dot(iq+row*8,ik+i*8,8);}
            unsigned count=visible;
            if(op==1) {
                for(unsigned i=0;i<visible;++i)for(unsigned j=i+1;j<visible;++j)
                    if(scores[ids[j]]>scores[ids[i]] || (scores[ids[j]]==scores[ids[i]] && ids[j]<ids[i])) {
                        unsigned t=ids[i];ids[i]=ids[j];ids[j]=t;
                    }
                if(count>k)count=k;
                for(unsigned i=0;i<count;++i)r->selected[r->selected_count++]=(uint8_t)ids[i];
            }
            state total={0};
            unsigned chunk=op==1?count:(count+splits-1)/splits;
            for(unsigned start=0;start<count;start+=chunk) {
                state partial={0};
                for(unsigned i=start;i<start+chunk && i<count;++i) {
                    unsigned token=ids[i];int16_t score;
                    course_int32_scale_to_q5_11(dot(x+row*12,keys+token*12,12),real(p,21),&score);
                    update(&partial,score,v+token*8);
                }
                merge(&total,&partial);
            }
            for(unsigned j=0;j<8;++j) {
                int64_t q=rne(total.value[j]*65536,total.sum);
                // Weighted average of INT8 values is in [-128,127]; its Q16
                // quotient fits INT32. Avoid an unavailable RV32 int64->float
                // helper without changing either rounding boundary.
                float scaled=((float)(int32_t)q/65536.0f)*real(p,22);
                r->output[r->count++]=course_bf16_rne_bits(scaled);
            }
        }
    } else {
        float gs=real(p,16)*real(p,17),us=real(p,16)*real(p,18);
        float is=real(p,19),ds=is*real(p,20);
        for(unsigned row=0;row<rows;++row) {
            unsigned offset=word(p,14+row)*256;int8_t intermediate[16];
            for(unsigned j=0;j<16;j+=4) {
                int32_t ga[4]={0},ua[4]={0};
                for(unsigned k=0;k<16;++k) {
                    int32_t a=x[row*16+k];
                    for(unsigned lane=0;lane<4;++lane) {
                        ga[lane]+=a*gate[offset+(j+lane)*16+k];
                        ua[lane]+=a*up[offset+(j+lane)*16+k];
                    }
                }
                for(unsigned lane=0;lane<4;++lane) {
                    int16_t g,u;
                    course_int32_scale_to_q5_11(ga[lane],gs,&g);
                    course_int32_scale_to_q5_11(ua[lane],us,&u);
                    course_q22_requantize_int8((int64_t)course_silu_q11(g)*u,is,&intermediate[j+lane]);
                }
            }
            float route=real(p,23+row),scale=ds*route;
            for(unsigned j=0;j<16;j+=4) {
                int32_t acc[4]={0};
                for(unsigned k=0;k<16;++k)
                    for(unsigned lane=0;lane<4;++lane)
                        acc[lane]+=(int32_t)intermediate[k]*down[offset+(j+lane)*16+k];
                for(unsigned lane=0;lane<4;++lane)
                    r->output[r->count++]=route==0.0f?0:course_bf16_rne_bits((float)acc[lane]*scale);
            }
        }
    }
    if(word(p,25)==1)r->primitive=(int32_t)rne((int32_t)word(p,26),word(p,27));
    if(word(p,25)==2){int32_t z=(int32_t)word(p,28);r->primitive=z<-128?-128:z>127?127:z;}
}

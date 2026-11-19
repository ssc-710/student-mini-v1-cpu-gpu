#ifndef P3_GPU_GENERIC_4THREAD_CUH
#define P3_GPU_GENERIC_4THREAD_CUH

#include <stdint.h>
#if defined(__CUDACC__)
#define P3G_HD __host__ __device__
#else
#define P3G_HD
#endif

P3G_HD static uint32_t p3g_word(const uint8_t *p, unsigned i) {
    p += 4u*i;
    return (uint32_t)p[0] | ((uint32_t)p[1]<<8) |
           ((uint32_t)p[2]<<16) | ((uint32_t)p[3]<<24);
}
P3G_HD static float p3g_real(const uint8_t *p, unsigned i) {
    union { uint32_t u; float f; } v = {p3g_word(p,i)};
    return v.f;
}
P3G_HD static unsigned p3g_validate(const uint8_t *p) {
    unsigned rows=p3g_word(p,4);
    if(p3g_word(p,0)!=0x31494e4du || p3g_word(p,1)!=3u ||
       !rows || rows>2u || p3g_word(p,8)!=16u || p3g_word(p,9)!=16u)
        return 1u;
    for(unsigned row=0;row<rows;++row) if(p3g_word(p,14+row)>=2u) return 1u;
    for(unsigned i=16;i<=20;++i) {
        float scale=p3g_real(p,i);
        if(!(scale>=0x1p-16f && scale<=0x1p16f)) return 4u;
    }
    // A device bus response is required before this can become BUS_ERROR.
    if(p3g_word(p,12)&1u) return 6u;
    return 0u;
}
P3G_HD static int32_t p3g_primitive(const uint8_t *p) {
    if(p3g_word(p,25)==1u) {
        int64_t n=(int32_t)p3g_word(p,26);
        uint64_t magnitude=n<0?(uint64_t)(-n):(uint64_t)n;
        uint64_t d=p3g_word(p,27),q=magnitude/d,r=magnitude%d;
        q += r*2u>d || (r*2u==d && (q&1u));
        return n<0?-(int32_t)q:(int32_t)q;
    }
    if(p3g_word(p,25)==2u) {
        int32_t v=(int32_t)p3g_word(p,28);
        return v<-128?-128:v>127?127:v;
    }
    return 0;
}

P3G_HD static int16_t p3g_silu(int16_t g,const int16_t *lut) {
    int32_t v=g;unsigned magnitude=v<0?(unsigned)-v:(unsigned)v;
    unsigned q=magnitude>>5,r=magnitude&31u;
    q += r>16u || (r==16u && (q&1u));
    int32_t index=v<0?-(int32_t)q:(int32_t)q;
    return lut[index+1024];
}

template<bool Candidate>
P3G_HD static unsigned p3g_columns(const uint8_t *p,unsigned row,unsigned tid,
                                  int8_t values[4],const int16_t *silu) {
    const int8_t *x=(const int8_t *)(p+128)+row*16u;
    const int8_t *gate=(const int8_t *)(p+400)+p3g_word(p,14+row)*256u;
    const int8_t *up=gate+512;
    int32_t ga[4]={0},ua[4]={0};
    unsigned first=tid*4u;
    if(Candidate) {
        for(unsigned k=0;k<16u;++k) {
            int32_t a=x[k];
            for(unsigned lane=0;lane<4u;++lane) {
                ga[lane]+=a*gate[(first+lane)*16u+k];
                ua[lane]+=a*up[(first+lane)*16u+k];
            }
        }
    } else {
        for(unsigned lane=0;lane<4u;++lane)
            for(unsigned k=0;k<16u;++k) {
                ga[lane]+=(int32_t)x[k]*gate[(first+lane)*16u+k];
                ua[lane]+=(int32_t)x[k]*up[(first+lane)*16u+k];
            }
    }
    unsigned error=0;
    float gs=p3g_real(p,16)*p3g_real(p,17),us=p3g_real(p,16)*p3g_real(p,18);
    for(unsigned lane=0;lane<4u;++lane) {
        int16_t g=0,u=0; values[lane]=0;
        if(course_int32_scale_to_q5_11(ga[lane],gs,&g) ||
           course_int32_scale_to_q5_11(ua[lane],us,&u) ||
           course_q22_requantize_int8((int64_t)p3g_silu(g,silu)*u,
                                      p3g_real(p,19),&values[lane])) error=4u;
    }
    return error;
}
P3G_HD static void p3g_down(const uint8_t *p,unsigned row,unsigned tid,
                           const int8_t intermediate[16],uint16_t *output) {
    const int8_t *down=(const int8_t *)(p+1424)+p3g_word(p,14+row)*256u;
    float route=p3g_real(p,23+row),scale=(p3g_real(p,19)*p3g_real(p,20))*route;
    int32_t acc[4]={0};
    for(unsigned k=0;k<16u;++k)
        for(unsigned lane=0;lane<4u;++lane)
            acc[lane]+=(int32_t)intermediate[k]*down[(tid*4u+lane)*16u+k];
    for(unsigned lane=0;lane<4u;++lane)
        output[row*16u+tid*4u+lane]=route==0.0f?0u:
            course_bf16_rne_bits((float)acc[lane]*scale);
}

#if !defined(__CUDACC__)
template<bool Candidate>
P3G_HD static void p3g_host_reference(const uint8_t *p,student_mini_result *r) {
    for(unsigned i=0;i<sizeof(*r);++i)((uint8_t *)r)[i]=0;
    r->status=p3g_validate(p);
    if(r->status)return;
    for(unsigned row=0;row<p3g_word(p,4);++row) {
        int8_t intermediate[16];
        for(unsigned tid=0;tid<4;++tid)
            r->status|=p3g_columns<Candidate>(p,row,tid,intermediate+tid*4u,
                                            course_silu_q11_q6_lut);
        if(r->status){r->count=0;return;}
        for(unsigned tid=0;tid<4;++tid)p3g_down(p,row,tid,intermediate,r->output);
    }
    r->count=p3g_word(p,4)*16u;r->primitive=p3g_primitive(p);
}
#endif

#if defined(__CUDACC__)
extern "C++" __device__ void barrier(unsigned);
template<bool Candidate>
__global__ void p3_gpu_generic_4thread_kernel(const int16_t *silu,
    const uint8_t *records,student_mini_result *results) {
    const unsigned tid=threadIdx.x;
    const uint8_t *p=records+blockIdx.x*STUDENT_MINI_RECORD_BYTES;
    student_mini_result *r=results+blockIdx.x;
    __shared__ unsigned status;
    __shared__ volatile unsigned error0,error1,error2,error3;
    __shared__ volatile int8_t i0,i1,i2,i3,i4,i5,i6,i7;
    __shared__ volatile int8_t i8,i9,i10,i11,i12,i13,i14,i15;
    if(tid==0u) {
        for(unsigned i=0;i<sizeof(*r);++i)((uint8_t *)r)[i]=0;
        status=blockDim.x==4u && blockDim.y==1u && blockDim.z==1u &&
               gridDim.y==1u && gridDim.z==1u?p3g_validate(p):1u;
        error0=error1=error2=error3=0u;
    }
    barrier(3u);
    // All lanes follow both row phases, including invalid descriptors.
    for(unsigned row=0;row<2u;++row) {
        if(!status && row<p3g_word(p,4) && tid<4u) {
            int8_t v[4];unsigned error=p3g_columns<Candidate>(p,row,tid,v,silu);
            if(tid==0u){error0=error;i0=v[0];i1=v[1];i2=v[2];i3=v[3];}
            else if(tid==1u){error1=error;i4=v[0];i5=v[1];i6=v[2];i7=v[3];}
            else if(tid==2u){error2=error;i8=v[0];i9=v[1];i10=v[2];i11=v[3];}
            else {error3=error;i12=v[0];i13=v[1];i14=v[2];i15=v[3];}
        }
        barrier(3u);
        if(tid==0u)status|=error0|error1|error2|error3;
        barrier(3u);
        if(!status && row<p3g_word(p,4) && tid<4u) {
            int8_t v[16]={i0,i1,i2,i3,i4,i5,i6,i7,i8,i9,i10,i11,i12,i13,i14,i15};
            p3g_down(p,row,tid,v,r->output);
        }
        barrier(3u);
    }
    if(tid==0u) {
        r->status=status;
        if(!status){r->count=p3g_word(p,4)*16u;r->primitive=p3g_primitive(p);}
    }
}
#endif
#undef P3G_HD
#endif

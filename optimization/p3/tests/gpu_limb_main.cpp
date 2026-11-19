#include "Vgpu_limb_tb.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <random>

static unsigned __int128 bits(const VlWide<3>& v) {
    return ((unsigned __int128)v[2]<<64)|((uint64_t)v[1]<<32)|v[0];
}
int main() {
    Vgpu_limb_tb t;
    const uint64_t mask=(UINT64_C(1)<<33)-1;
    const unsigned __int128 mask66=(((unsigned __int128)1)<<66)-1;
    const std::array<uint64_t,11> boundary={0,1,65535,65536,65537,
        (UINT64_C(1)<<31)-1,UINT64_C(1)<<31,(UINT64_C(1)<<32)-1,
        UINT64_C(1)<<32,mask-1,mask};
    unsigned checks=0,stalls=0;
    for(unsigned seed=1;seed<=10;++seed) {
        std::mt19937_64 rng(seed);
        std::array<unsigned __int128,3> q={};unsigned valid=0;
        unsigned __int128 held=0;
        for(unsigned n=0;n<20121;++n) {
            uint64_t a=n<121?boundary[n/11]:rng()&mask;
            uint64_t b=n<121?boundary[n%11]:rng()&mask;
            bool enable=n<3 || n<121 || (rng()%4)!=0;
            t.clk=0;t.enable=enable;t.dataa=a;t.datab=b;t.eval();
            t.clk=1;t.eval();
            if(enable) {
                int64_t sa=(a&(UINT64_C(1)<<32))?int64_t(a)-int64_t(UINT64_C(1)<<33):a;
                int64_t sb=(b&(UINT64_C(1)<<32))?int64_t(b)-int64_t(UINT64_C(1)<<33):b;
                q[2]=q[1];q[1]=q[0];q[0]=((__int128)sa*sb)&mask66;
                if(valid<3)++valid;
                if(valid==3 && (bits(t.candidate)!=q[2] || bits(t.baseline)!=q[2])) {
                    std::printf("FAIL seed=%u n=%u a=%llu b=%llu\n",seed,n,(unsigned long long)a,(unsigned long long)b);return 1;
                }
            } else if(valid==3) {
                if(bits(t.candidate)!=held || bits(t.baseline)!=held)return 2;
                ++stalls;
            }
            if(valid==3)++checks;
            held=bits(t.candidate);
        }
    }
    std::printf("GPU_LIMB_PASS checks=%u stall_checks=%u seeds=10\n",checks,stalls);
}

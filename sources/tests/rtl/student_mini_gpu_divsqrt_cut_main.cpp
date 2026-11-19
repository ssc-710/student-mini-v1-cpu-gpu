#include "Vstudent_mini_gpu_divsqrt_cut.h"
#include "verilated.h"
#include <cstdint>
#include <iostream>

static uint32_t next(uint32_t &state) {
  state ^= state << 13; state ^= state >> 17; state ^= state << 5; return state;
}
int main(int argc,char **argv) {
  Verilated::commandArgs(argc,argv);
  Vstudent_mini_gpu_divsqrt_cut top;
  const uint32_t special[]={0,0x80000000u,0x3f800000u,0xbf800000u,0x40000000u,
    1,0x007fffffu,0x00800000u,0x7f7fffffu,0xff7fffffu,0x7f800000u,0xff800000u,
    0x7fc00000u,0x7f800001u,0x3f800001u,0x3f7fffffu};
  uint64_t total=0,stalls=0,bubbles=0,resets=0;
  for(unsigned seed=1;seed<=10;++seed) {
    uint32_t rng=seed;
    auto tick=[&](){top.clk=0;top.eval();top.clk=1;top.eval();};
    top.reset=1;top.enable=1;top.mask=0;tick();++resets;top.reset=0;
    unsigned ordinal=0;
    for(unsigned cycle=0;cycle<6400;++cycle) {
      // Mid-flight reset must discard stale results; tail drains completely.
      top.reset=cycle==3017;
      if(top.reset)++resets;
      top.enable=cycle>=6300 || (next(rng)%4)!=0;
      top.mask=cycle<6300 && (next(rng)%4)!=0;
      if(!top.enable)++stalls;
      if(top.enable&&!top.mask)++bubbles;
      top.is_sqrt=cycle&1;top.frm=(cycle/2)%5;
      top.dataa=cycle<256?special[cycle/16]:next(rng);
      top.datab=cycle<256?special[cycle%16]:next(rng);
      tick();
      if(top.enable&&!top.reset&&top.valid) {
        bool match=top.expected==top.actual&&top.expected_flags==top.actual_flags;
        std::cout<<"{\"seed\":"<<seed<<",\"ordinal\":"<<ordinal++
          <<",\"a_bits\":"<<top.checked_a<<",\"b_bits\":"<<top.checked_b
          <<",\"sqrt\":"<<unsigned(top.checked_sqrt)<<",\"frm\":"<<unsigned(top.checked_frm)
          <<",\"expected_bits\":"<<top.expected<<",\"actual_bits\":"<<top.actual
          <<",\"expected_flags\":"<<unsigned(top.expected_flags)
          <<",\"actual_flags\":"<<unsigned(top.actual_flags)
          <<",\"xor_delta\":"<<(top.expected^top.actual)<<",\"match\":"<<(match?"true":"false")<<"}\n";
        ++total;
        if(!match)return 1;
      }
    }
  }
  std::cout<<"DIVSQRT_STEP_CUT_COMPLETE records="<<total<<" stalls="<<stalls
    <<" bubbles="<<bubbles<<" resets="<<resets<<"\n";
  top.final();return total>30000&&stalls>10000&&bubbles>10000&&resets==20?0:2;
}

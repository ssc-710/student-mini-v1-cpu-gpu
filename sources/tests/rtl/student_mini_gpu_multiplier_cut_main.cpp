#include "Vstudent_mini_gpu_multiplier_cut.h"
#include "verilated.h"
#include <cstdint>
#include <deque>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <vector>

using U128 = unsigned __int128;
static constexpr uint64_t MASK33 = (uint64_t(1) << 33)-1;
static constexpr U128 MASK66 = (U128(1) << 66)-1;
struct Transaction { uint64_t a, b; unsigned seed, id; U128 expected; };
static uint64_t next(uint64_t &state) { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int64_t signed33(uint64_t x) { return x & (uint64_t(1)<<32) ? int64_t(x)-int64_t(uint64_t(1)<<33) : int64_t(x); }
static U128 bits(const VlWide<3>& value) { return (U128(value[2]&3)<<64) | (U128(value[1])<<32) | value[0]; }
static std::string hex66(U128 value) { std::ostringstream s; s << std::hex << uint64_t(value>>64) << std::setw(16) << std::setfill('0') << uint64_t(value); return s.str(); }

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    Vstudent_mini_gpu_multiplier_cut dut;
    std::deque<Transaction> queue;
    Transaction visible{}; bool valid=false;
    unsigned cycles=0, records=0, stalls=0;
    auto tick = [&](bool enable, uint64_t a, uint64_t b, unsigned seed, unsigned id) {
        dut.clk=0; dut.enable=enable; dut.dataa=a; dut.datab=b; dut.eval();
        if (enable) {
            const __int128 product=__int128(signed33(a))*__int128(signed33(b));
            queue.push_back({a,b,seed,id,U128(product)&MASK66});
            if (queue.size()==3) { visible=queue.front(); queue.pop_front(); valid=true; }
        }
        dut.clk=1; dut.eval(); ++cycles;
        if (!valid) return true;
        const U128 actual=bits(dut.actual_result), original=bits(dut.original_result);
        const bool match=actual==visible.expected && original==visible.expected;
        if (!enable) ++stalls;
        if (enable || !match) {
            ++records;
            std::cout << "{\"seed\":" << visible.seed << ",\"id\":" << visible.id
                << ",\"cycle\":" << cycles << ",\"enabled\":" << (enable?"true":"false")
                << ",\"input_a_bits\":" << visible.a << ",\"input_b_bits\":" << visible.b
                << ",\"golden_bits\":\"" << hex66(visible.expected) << "\",\"original_bits\":\"" << hex66(original)
                << "\",\"actual_bits\":\"" << hex66(actual) << "\",\"xor_delta\":\"" << hex66(actual^visible.expected)
                << "\",\"match\":" << (match?"true":"false") << "}\n";
        }
        if (!match) { std::cerr << "MULTIPLIER_MISMATCH cycle=" << cycles << "\n"; return false; }
        return true;
    };
    const std::vector<uint64_t> values={0,1,2,0x7fff,0x8000,0xffff,0x10000,0x7fffffff,
        0x80000000,0xffffffff,0x100000000,0x100000001,0x1ffff0000,0x1fffffffe,0x1ffffffff};
    for (unsigned seed=1; seed<=10; ++seed) {
        uint64_t rng=seed; unsigned id=0;
        auto transaction = [&](uint64_t a, uint64_t b) {
            if ((next(rng)&3)==0) {
                for (unsigned k=0; k<3; ++k) {
                    const uint64_t sa=next(rng)&MASK33, sb=next(rng)&MASK33;
                    if (!tick(false,sa,sb,seed,id)) return false;
                }
            }
            return tick(true,a,b,seed,id++);
        };
        for (auto a: values) for (auto b: values) if (!transaction(a,b)) return 2;
        for (unsigned i=0; i<4096; ++i) {
            const uint64_t a=next(rng)&MASK33, b=next(rng)&MASK33;
            if (!transaction(a,b)) return 2;
        }
    }
    for (unsigned i=0;i<3;++i) if (!tick(true,0,0,10,4321+i)) return 2;
    if (records<43210 || stalls<10000) return 3;
    std::cout << "MULTIPLIER_CUT_COMPLETE records=" << records << " stall_checks=" << stalls << " cycles=" << cycles << "\n";
    dut.final(); return 0;
}

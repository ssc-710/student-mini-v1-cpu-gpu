// CPU protocol qualification driver (student-mini MINI-31/32/33).
//
// Same clocking and UART capture as student_mini_cpu_failfast_main.cpp; the
// testbench additionally drives the CPU's UART result-stream ready
// (uart_ready) and an extra reset (tb_reset, OR-ed into asic_reset_i).
//   STUDENT_MINI_CPU_PROTOCOL = "target,prob256,seed,hold,reset_after"
//   prob256/seed : seeded backpressure on the result stream (ready low with
//                  probability prob256/256 each cycle)
//   hold         : every result byte is held (ready low) for `hold` cycles
//   reset_after  : reset the CPU `reset_after` cycles after the target record
//                  started (the STUDENT_CPU_BEGIN line for slot 0, otherwise the
//                  preceding record's line), i.e. while the target executes;
//                  after reboot the CPU re-executes and the target must complete once.
// The target record's UART line must equal the reference payload.  Every byte
// presented while not ready must stay stable until accepted.
// argv[1]: file holding the reference STUDENT_CPU line of the target record.
#include "Vcpu_boundary_replay.h"
#include "verilated.h"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <memory>
#include <regex>
#include <string>

static std::string payload(const std::string &line) {
  static const std::regex counters(" (cycles|instructions|ibus_bytes|dbus_bytes|dma_bytes)=[0-9]+:[0-9]+");
  return std::regex_replace(line, counters, "");
}

int main(int argc, char **argv) {
  if (argc != 2) return 5;
  std::ifstream reference(argv[1]);
  std::string expected;
  if (!reference || !std::getline(reference, expected)) return 5;
  if (!expected.empty() && expected.back() == '\r') expected.pop_back();
  const char *text = std::getenv("STUDENT_MINI_CPU_PROTOCOL");
  long target = -1, prob = 0, seed = 0, hold = 0, reset_after = 0;
  if (!text || std::sscanf(text, "%ld,%ld,%ld,%ld,%ld", &target, &prob, &seed, &hold, &reset_after) != 5 || target < 0) return 5;
  auto context = std::make_unique<VerilatedContext>();
  context->commandArgs(argc, argv);
  auto device = std::make_unique<Vcpu_boundary_replay>(context.get());
  device->sys_clk = 0;
  device->uart_ready = 1;
  device->tb_reset = 0;
  device->eval();
  auto advance = [&](uint64_t when) {
    while (device->eventsPending() && device->nextTimeSlot() < when) {
      context->time(device->nextTimeSlot());
      device->eval();
    }
    context->time(when);
    device->eval();
  };
  const std::regex identity("^STUDENT_CPU ordinal=([0-9]+) ");
  std::smatch match;
  std::string line, target_line;
  uint32_t state = seed ? uint32_t(seed) ^ 0x9e3779b9u : 1u;
  long held = 0, completions = 0, completions_before_reset = 0, reset_cycle = -1, reset_left = 0, armed_at = -1;
  long stalled = 0, violations = 0, accepted = 0, lines_after_reset = 0;
  bool reset_done = false, prev_wait = false, matched = false;
  char prev_data = 0;
  for (uint64_t cycle = 0; cycle < 400000000ULL; ++cycle) {
    advance(cycle * 10000 + 5000);
    // Reset pulse: 16 cycles, `reset_after` cycles after the preceding record completed.
    if (reset_after && !reset_done && armed_at >= 0 && long(cycle) - armed_at == reset_after) {
      reset_cycle = long(cycle); reset_left = 16; reset_done = true;
    }
    device->tb_reset = reset_left > 0;
    if (reset_left > 0) --reset_left;
    bool ready = true;
    if (prob) {
      state ^= state << 13; state ^= state >> 17; state ^= state << 5;
      ready = long(state & 0xffu) >= prob;
    }
    device->uart_ready = ready;   // decided before looking at this cycle's byte
    device->eval();
    bool valid = device->uart_valid;
    char value = static_cast<char>(device->uart_data);
    if (hold && valid) {
      if (held < hold) { device->uart_ready = 0; ready = false; ++held; device->eval(); }
    }
    if (prev_wait && (!valid || value != prev_data)) ++violations;
    bool take = valid && ready;
    if (valid && !ready) ++stalled;
    prev_wait = valid && !ready && !device->tb_reset;   // a reset legitimately drops a pending byte
    prev_data = value;
    device->sys_clk = 1;
    device->eval();
    if (take) {
      ++accepted;
      held = 0;
      if (value == '\n') {
        std::cout << line << '\n' << std::flush;
        if (reset_done) ++lines_after_reset;
        if (target == 0 && armed_at < 0 && !reset_done && line.rfind("STUDENT_CPU_BEGIN ", 0) == 0) armed_at = long(cycle);
        if (std::regex_search(line, match, identity)) {
          long ordinal = std::stol(match[1]);
          if (ordinal == target - 1 && armed_at < 0 && !reset_done) armed_at = long(cycle);
          if (ordinal == target) {
            ++completions;
            if (reset_after && !reset_done) ++completions_before_reset;
            if (!reset_after || reset_done) {
              matched = payload(line) == payload(expected);
              target_line = line;
              std::printf("STUDENT_CPU_PROTOCOL target=%ld prob256=%ld seed=%ld hold=%ld reset_after=%ld completions=%ld "
                          "completions_before_reset=%ld reset_cycle=%ld armed_cycle=%ld lines_after_reset=%ld payload_match=%d "
                          "stalled_cycles=%ld stability_violations=%ld accepted_bytes=%ld cycles=%llu\n",
                          target, prob, seed, hold, reset_after, completions, completions_before_reset, reset_cycle, armed_at,
                          lines_after_reset, int(matched), stalled, violations, accepted, (unsigned long long)(cycle + 1));
              std::fflush(stdout);
              device->final();
              return matched && violations == 0 && completions_before_reset == 0 ? 0 : 4;
            }
          }
        }
        line.clear();
      } else if (value != '\r') line += value;
    }
    advance(cycle * 10000 + 10000);
    device->sys_clk = 0;
    device->eval();
    if (context->gotFinish()) return 2;
  }
  std::cerr << "CPU_PROTOCOL_TIMEOUT\n";
  return 3;
}

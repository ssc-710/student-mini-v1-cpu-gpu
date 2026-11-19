#include "Vcpu_boundary_replay.h"
#include "verilated.h"
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <regex>
#include <string>

// The reference is used only by the checker, never as a DUT input or memory
// return. Keep every actual UART record; ignore only measured counter fields.
static std::string payload(const std::string &line) {
  static const std::regex counters(" (cycles|instructions|ibus_bytes|dbus_bytes|dma_bytes)=[0-9]+:[0-9]+");
  return std::regex_replace(line, counters, "");
}

int main(int argc, char **argv) {
  if (argc != 2) return 5;
  std::ifstream reference(argv[1]);
  if (!reference) return 5;
  std::map<unsigned, std::string> expected;
  std::string line;
  const std::regex identity("^STUDENT_CPU ordinal=([0-9]+) ");
  std::smatch match;
  while (std::getline(reference, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (std::regex_search(line, match, identity)) {
      unsigned ordinal = std::stoul(match[1]);
      if (!expected.emplace(ordinal, payload(line)).second) return 5;
    }
  }
  if (expected.size() != 1000 || expected.begin()->first != 0 || expected.rbegin()->first != 999) return 5;
  auto context = std::make_unique<VerilatedContext>();
  context->commandArgs(argc, argv);
  auto device = std::make_unique<Vcpu_boundary_replay>(context.get());
  device->sys_clk = 0;
  device->eval();
  bool baseline = false, native = false;
  unsigned next_ordinal = 0;
  line.clear();
  auto advance = [&](uint64_t when) {
    while (device->eventsPending() && device->nextTimeSlot() < when) {
      context->time(device->nextTimeSlot());
      device->eval();
    }
    context->time(when);
    device->eval();
  };
  for (uint64_t cycle = 0; cycle < 1000000000ULL; ++cycle) {
    advance(cycle * 10000 + 5000);
    bool valid = device->uart_valid;
    char value = static_cast<char>(device->uart_data);
    device->sys_clk = 1;
    device->eval();
    if (valid) {
      if (value == '\n') {
        std::cout << line << '\n' << std::flush;
        if (std::regex_search(line, match, identity)) {
          unsigned ordinal = std::stoul(match[1]);
          if (ordinal != next_ordinal || !expected.count(ordinal) || payload(line) != expected.at(ordinal)) {
            std::cerr << "CPU_REPLAY_VALUE_MISMATCH ordinal=" << ordinal << " cycle=" << cycle << '\n';
            device->final();
            return 4;
          }
          ++next_ordinal;
        }
        if (line.rfind("STUDENT_NATIVE_CPU status=", 0) == 0 && line.rfind("STUDENT_NATIVE_CPU status=0 ", 0) != 0) {
          std::cerr << "CPU_REPLAY_NATIVE_FAILURE cycle=" << cycle << '\n';
          device->final();
          return 4;
        }
        if (line == "STUDENT_CPU_COMPLETE count=1000") baseline = next_ordinal == 1000;
        if (line.rfind("STUDENT_NATIVE_CPU_COMPLETE ", 0) == 0) native = true;
        line.clear();
      } else if (value != '\r') line += value;
    }
    advance(cycle * 10000 + 10000);
    device->sys_clk = 0;
    device->eval();
    if (context->gotFinish()) return 2;
    if (baseline && native) {
      std::cout << "CPU_BOUNDARY_REPLAY_COMPLETE cycles=" << cycle + 1 << '\n';
      device->final();
      return 0;
    }
  }
  std::cerr << "CPU_BOUNDARY_REPLAY_TIMEOUT\n";
  return 3;
}

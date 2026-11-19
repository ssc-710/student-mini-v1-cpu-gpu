#include "Vcpu_boundary_replay.h"
#include "verilated.h"
#include <cstdint>
#include <iostream>
#include <memory>
#include <string>

int main(int argc, char **argv) {
  auto context = std::make_unique<VerilatedContext>();
  context->commandArgs(argc, argv);
  auto device = std::make_unique<Vcpu_boundary_replay>(context.get());
  device->sys_clk = 0;
  device->eval();
  bool baseline = false, native = false;
  std::string line;
  auto advance = [&](uint64_t when) {
    while (device->eventsPending() && device->nextTimeSlot() < when) {
      context->time(device->nextTimeSlot());
      device->eval();
    }
    context->time(when);
    device->eval();
  };
  // Context precision is explicitly 1 ps; retain every actual SRAM delay.
  for (uint64_t cycle = 0; cycle < 1000000000ULL; ++cycle) {
    advance(cycle * 10000 + 5000);
    // Read the UART transfer that will be accepted at the next rising edge.
    bool valid = device->uart_valid;
    char value = static_cast<char>(device->uart_data);
    device->sys_clk = 1;
    device->eval();
    if (valid) {
      if (value == '\n') {
        // Verilog macro diagnostics share stdout. Emit complete UART lines
        // between eval calls so a warning cannot split a raw result record.
        std::cout << line << '\n' << std::flush;
        if (line == "STUDENT_CPU_COMPLETE count=1000") baseline = true;
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

; SPIR-V imports C++ abs(long) as _Z3absl with a 64-bit OpenCL long ABI.
; Define the IR type explicitly because the RV32 C++ host ABI makes long 32-bit.
target triple = "riscv32-unknown-unknown"

define i64 @_Z3absl(i64 %value) {
entry:
  %negative = icmp slt i64 %value, 0
  %negated = sub i64 0, %value
  %absolute = select i1 %negative, i64 %negated, i64 %value
  ret i64 %absolute
}

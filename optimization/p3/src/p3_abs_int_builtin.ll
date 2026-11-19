target triple = "riscv32-unknown-unknown"

define i32 @_Z3absi(i32 %value) {
entry:
  %negative = icmp slt i32 %value, 0
  %negated = sub i32 0, %value
  %absolute = select i1 %negative, i32 %negated, i32 %value
  ret i32 %absolute
}

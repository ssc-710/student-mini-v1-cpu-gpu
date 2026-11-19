target triple = "riscv32-unknown-unknown"

define i16 @_Z3abss(i16 %value) {
entry:
  %negative = icmp slt i16 %value, 0
  %negated = sub i16 0, %value
  %absolute = select i1 %negative, i16 %negated, i16 %value
  ret i16 %absolute
}

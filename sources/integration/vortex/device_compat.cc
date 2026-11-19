// SPDX-License-Identifier: Apache-2.0
// Freestanding helpers that LLVM may emit while lowering SPIR-V to RV32.
// Keep this deliberately tiny; Vortex's kernel archive does not provide the
// C++ overloads and the Nano scalar path must not depend on host libstdc++.

short abs(short value) { return value < 0 ? (short)-value : value; }
int abs(int value) { return value < 0 ? -value : value; }
long abs(long value) { return value < 0 ? -value : value; }
float fabs(float value) { return value < 0.0f ? -value : value; }
long popcount(long value) {
    unsigned long bits = (unsigned long)value;
    bits = bits - ((bits >> 1) & 0x55555555ul);
    bits = (bits & 0x33333333ul) + ((bits >> 2) & 0x33333333ul);
    bits = (bits + (bits >> 4)) & 0x0f0f0f0ful;
    bits += bits >> 8;
    bits += bits >> 16;
    return (long)(bits & 0x3ful);
}

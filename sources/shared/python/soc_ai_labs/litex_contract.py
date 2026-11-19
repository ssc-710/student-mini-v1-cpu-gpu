"""Stable software-visible contract for the LiteX accelerator integration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable

from .deepseek_v32 import Status


@dataclass(frozen=True)
class LiteXSoCProfile:
    release: str
    cpu: str
    dram_bytes: int
    dma_width_bits: int
    simulator: str
    target_hz: int


@dataclass(frozen=True)
class TinyModelProfile:
    name: str
    layers: int
    hidden: int
    heads: int
    kv_latent: int
    experts: int
    active_experts: int
    intermediate: int
    vocab: int
    context: int
    max_generated_tokens: int
    d_nope: int = 8
    d_rope: int = 4
    indexer_dim: int = 8
    value_dim: int = 8

    def estimated_parameter_count(self) -> int:
        embedding = self.vocab * self.hidden
        dense_per_layer = 4 * self.hidden * self.hidden
        # ``experts`` counts routed experts; nano also has one always-on shared expert.
        experts_per_layer = (self.experts + 1) * 3 * self.hidden * self.intermediate
        router_per_layer = self.hidden * self.experts
        return embedding + self.layers * (dense_per_layer + experts_per_layer + router_per_layer)

    def estimated_bytes(self) -> int:
        """Conservative INT8 weights + BF16 cache + fixed 8 MiB runtime arena."""
        weights = self.estimated_parameter_count()
        scale_and_tables = max(64 * 1024, weights // 16)
        kv_cache = self.layers * self.context * self.kv_latent * 2 * 2
        return weights + scale_and_tables + kv_cache + 8 * 1024 * 1024


LITEX_SOC = LiteXSoCProfile(
    release="2026.04",
    cpu="vexriscv-rv32im",
    dram_bytes=256 * 1024 * 1024,
    dma_width_bits=128,
    simulator="verilator",
    target_hz=100_000_000,
)

NANO_RTL_E2E = TinyModelProfile(
    "nano-rtl-e2e", 2, 64, 4, 16, 8, 2, 128, 256, 32, 8
)
MICRO_FAST_E2E = TinyModelProfile(
    "micro-fast-e2e", 4, 128, 8, 32, 8, 2, 256, 2048, 128, 32
)
NANO_CHAT_E2E = TinyModelProfile(
    name="nano-chat-e2e",
    layers=4,
    hidden=128,
    heads=8,
    kv_latent=12,
    experts=8,
    active_experts=2,
    intermediate=256,
    vocab=2048,
    context=128,
    max_generated_tokens=32,
    d_nope=8,
    d_rope=4,
    indexer_dim=8,
    value_dim=8,
)


def descriptor_beats(payload: bytes) -> tuple[int, int, int, int]:
    """Split the descriptor into four little-endian 128-bit DMA beats."""
    if len(payload) != 64:
        raise ValueError("descriptor must be exactly 64 bytes")
    beats = tuple(int.from_bytes(payload[offset : offset + 16], "little") for offset in range(0, 64, 16))
    return beats  # type: ignore[return-value]


class CSRName(IntEnum):
    CONTROL = 0
    OPCODE = 1
    DESCRIPTOR_ADDR = 2
    IRQ_CLEAR = 3
    RESULT_STATUS = 4
    RESULT_CYCLES_LOW = 5
    RESULT_CYCLES_HIGH = 6


class AcceleratorCSRModel:
    """Executable model for the generated LiteX CSR names and sticky IRQ rules."""

    def __init__(self) -> None:
        self.busy = False
        self.done = False
        self.irq = False
        self.opcode = 0
        self.descriptor_addr = 0
        self.status = Status.OK
        self.cycles = 0
        self._cycle_snapshot = 0

    def start(self, *, opcode: int, descriptor_addr: int) -> bool:
        if self.busy:
            return False
        if opcode not in (1, 2, 3, 4):
            raise ValueError("opcode must identify P1, P2, P3, or P4")
        if descriptor_addr < 0 or descriptor_addr > 0xFFFFFFFF or descriptor_addr & 0x3F:
            raise ValueError("descriptor address must be an aligned unsigned 32-bit address")
        self.opcode = opcode
        self.descriptor_addr = descriptor_addr
        self.busy = True
        self.done = False
        self.irq = False
        self.status = Status.OK
        self.cycles = 0
        return True

    def clock(
        self,
        *,
        irq_clear: bool = False,
        completion: tuple[Status | int, int] | None = None,
    ) -> None:
        if irq_clear:
            self.irq = False
            self.done = False
        if completion is not None:
            status, cycles = completion
            if cycles < 0 or cycles > 0xFFFFFFFFFFFFFFFF:
                raise ValueError("cycles must fit unsigned 64-bit")
            self.status = Status(int(status))
            self.cycles = int(cycles)
            self.busy = False
            self.done = True
            self.irq = True

    def read_cycles_low(self) -> int:
        self._cycle_snapshot = self.cycles
        return self._cycle_snapshot & 0xFFFFFFFF

    def read_cycles_high(self) -> int:
        return (self._cycle_snapshot >> 32) & 0xFFFFFFFF


def total_model_bytes(models: Iterable[TinyModelProfile]) -> int:
    return sum(model.estimated_bytes() for model in models)

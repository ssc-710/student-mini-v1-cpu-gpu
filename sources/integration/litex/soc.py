#!/usr/bin/env python3
"""LiteX/VexRiscv simulation target for the course accelerator.

Imports are intentionally lazy: ``--check`` validates the frozen contract on a
host without LiteX, while ``--build`` requires the pinned open-source stack.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time


ROOT = Path(__file__).resolve().parents[2]
LOCK = Path(__file__).with_name("toolchain.lock.json")


def check_contract() -> None:
    sys.path.insert(0, str(ROOT / "shared" / "python"))
    from soc_ai_labs.litex_contract import LITEX_SOC, MICRO_FAST_E2E, NANO_RTL_E2E

    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    if lock["litex_release"] != LITEX_SOC.release:
        raise RuntimeError("LiteX release differs between contract and toolchain lock")
    if NANO_RTL_E2E.estimated_bytes() >= 32 * 1024 * 1024:
        raise RuntimeError("nano-rtl-e2e exceeds its 32 MiB budget")
    if MICRO_FAST_E2E.estimated_bytes() >= 192 * 1024 * 1024:
        raise RuntimeError("micro-fast-e2e exceeds its 192 MiB budget")
    for dependency in lock["dependencies"]:
        if len(dependency["commit"]) != 40:
            raise RuntimeError(f"unresolved dependency commit: {dependency['name']}")
    print(
        f"contract OK: LiteX {LITEX_SOC.release}, {LITEX_SOC.cpu}, "
        f"DRAM={LITEX_SOC.dram_bytes // (1024 * 1024)} MiB, DMA={LITEX_SOC.dma_width_bits}-bit"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_files(paths: list[Path]) -> str:
    """Hash an ordered artifact set, binding both names and contents."""
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _normalize_nano_image_contract(report: dict[str, object]) -> dict[str, object]:
    """Normalize legacy eight-token and nano-chat manifests for firmware."""
    segments = report.get("segments")
    if not isinstance(segments, dict):
        raise ValueError("nano image manifest has no segment table")
    if report.get("profile") == "nano-chat-e2e":
        required = (
            "prompt.tokens.u32", "expected.tokens.u32",
            "generated.tokens.u32", "descriptors", "user.utf8",
            "tokenizer.offsets.u32", "tokenizer.bytes",
            "tokenizer.merges.u16", "kv_cache.bf16",
            "operator_scratch", "scales.fp32",
        )
        missing = [name for name in required if name not in segments]
        if missing:
            raise ValueError(f"nano-chat image is missing segments: {missing}")
        model_config = report.get("model_config")
        if not isinstance(model_config, dict):
            raise ValueError("nano-chat image is missing generated model dimensions")
        expected = report.get("expected_tokens")
        prompt = report.get("prompt_tokens")
        if not isinstance(expected, list) or not isinstance(prompt, list):
            raise ValueError("nano-chat image has no prompt/expected token arrays")
        if report.get("runtime_semantics") != "p1-p2-p3-native-nano-chat-hierarchical-position-decoder-v5":
            raise ValueError("nano-chat image uses an obsolete or unknown runtime contract")
        if report.get("question") != "今天天气怎么样？":
            raise ValueError("nano-chat image does not contain the frozen weather question")
        return {
            "is_chat": True,
            "prompt_segment": "prompt.tokens.u32",
            "expected_segment": "expected.tokens.u32",
            "generated_segment": "generated.tokens.u32",
            "descriptor_segment": "descriptors",
            "prompt_tokens": prompt,
            "expected_tokens": expected,
            "token_sha256": report["chat_token_sha256"],
            "model_config": model_config,
            "tokenizer_special_tokens": report.get("tokenizer_special_tokens", {}),
            "question": report.get("question"),
            "runtime_semantics": report.get("runtime_semantics"),
        }
    required = (
        "token_io", "prompt_tokens", "expected_tokens",
        "generated_tokens", "descriptors",
    )
    missing = [name for name in required if name not in segments]
    if missing:
        raise ValueError(f"legacy nano image is missing segments: {missing}")
    return {
        "is_chat": False,
        "prompt_segment": "prompt_tokens",
        "expected_segment": "expected_tokens",
        "generated_segment": "generated_tokens",
        "descriptor_segment": "descriptors",
        "prompt_tokens": report["golden_prompt"],
        "expected_tokens": report["golden_tokens"],
        "token_sha256": report["golden_tokens_sha256"],
        "model_config": {},
        "tokenizer_special_tokens": {},
    }


def _run_bios_smoke(
    simulator: Path,
    *,
    timeout_seconds: int = 30,
    evidence_path: Path | None = None,
    require_control_smoke: bool = False,
    require_numeric_smoke: bool = False,
    require_nano_session: bool = False,
    require_cpu_b0: bool = False,
    nano_image_sha256: str | None = None,
    nano_report: dict[str, object] | None = None,
    candidate: str = "b0",
    cpu_variant: str = "standard",
    execution: str = "accelerator",
) -> None:
    """Run the interactive simulator only until the BIOS SDRAM test passes."""
    simulator = simulator.resolve()
    wall_start = time.monotonic()
    chat_session = bool(
        require_nano_session
        and nano_report is not None
        and nano_report.get("profile") == "nano-chat-e2e"
    )
    success_marker = (
        "NANO_CHAT_SESSION PASS" if chat_session else
        "NANO_SESSION PASS" if require_nano_session else
        "NUMERIC_SMOKE PASS" if require_numeric_smoke else
        "CONTROL_SMOKE PASS" if require_control_smoke else
        "CPU_OPERATOR_B0 PASS" if require_cpu_b0 else "Memtest OK"
    )
    process = subprocess.Popen(
        [str(simulator)],
        cwd=simulator.parent.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    line_queue: queue.Queue[str | None] = queue.Queue()

    def drain_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            line_queue.put(line)
        line_queue.put(None)

    reader = threading.Thread(target=drain_stdout, daemon=True)
    reader.start()
    lines: list[str] = []
    live_log = None
    if evidence_path is not None:
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        live_log = evidence_path.with_suffix(".console.live.log").open(
            "w", encoding="utf-8", buffering=1,
        )
    deadline = time.monotonic() + timeout_seconds
    terminal_marker = False
    try:
        while time.monotonic() < deadline:
            try:
                line = line_queue.get(timeout=0.25)
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            if line is None:
                break
            lines.append(line)
            if live_log is not None:
                live_log.write(line)
            sys.stdout.write(line)
            sys.stdout.flush()
            if success_marker in line or any(
                marker in line
                for marker in (
                    "NANO_ERROR", "NUMERIC_ERROR", "CONTROL_ERROR", "CONTROL_SMOKE FAIL",
                    "CPU_B0 P1 FAIL", "CPU_B0 P2 FAIL", "CPU_B0 P3 FAIL",
                )
            ):
                terminal_marker = True
                break
    finally:
        if terminal_marker or process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        reader.join(timeout=1)
        while True:
            try:
                line = line_queue.get_nowait()
            except queue.Empty:
                break
            if line is not None:
                lines.append(line)
                if live_log is not None:
                    live_log.write(line)
                sys.stdout.write(line)
        if live_log is not None:
            live_log.close()
    output = "".join(lines)
    wall_seconds = time.monotonic() - wall_start
    if evidence_path is not None:
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.with_suffix(".console.log").write_text(output, encoding="utf-8")
    if success_marker not in output:
        raise RuntimeError(
            f"LiteX BIOS smoke did not reach {success_marker!r} within {timeout_seconds}s"
        )
    control_matches = re.findall(r"CONTROL_OP P([123]) status=(\d+) cycles=(\d+):(\d+)", output)
    numeric_matches = re.findall(r"NUMERIC_OP P([123]) status=(\d+) cycles=(\d+):(\d+)", output)
    nano_matches = re.findall(r"NANO_OP P([123]) status=(\d+) cycles=(\d+):(\d+)", output)
    cpu_b0_metric: dict[str, object] = {}
    if require_cpu_b0:
        if not all(f"CPU_B0 P{operator} PASS" in output for operator in (1, 2, 3)):
            raise RuntimeError("LiteX CPU directed B0 did not complete P1, P2, and P3")
        metric_match = re.search(
            r"CPU_B0_METRIC instructions=(\d+|unavailable) cycles=(\d+):(\d+)"
            r"(?: architectural_cycles=(\d+):(\d+))?",
            output,
        )
        if metric_match is None:
            raise RuntimeError("LiteX CPU directed B0 did not report a cycle measurement")
        cpu_b0_metric = {
            "instructions": (
                int(metric_match.group(1))
                if metric_match.group(1) != "unavailable" else None
            ),
            "cycles": (int(metric_match.group(2)) << 32) | int(metric_match.group(3)),
            "architectural_cycles": (
                (int(metric_match.group(4)) << 32) | int(metric_match.group(5))
                if metric_match.group(4) is not None else None
            ),
            "counter_source": (
                "VexRiscv mcycle/minstret CSRs"
                if metric_match.group(4) is not None else "LiteX 64-bit uptime CSR"
            ),
        }
        if not cpu_b0_metric["cycles"]:
            raise RuntimeError("LiteX CPU directed B0 cycle counter must be positive")
    if require_control_smoke:
        if "CONTROL_SMOKE PASS" not in output or [item[0] for item in control_matches] != ["1", "2", "3"]:
            raise RuntimeError("LiteX control smoke did not complete P1, P2, and P3 exactly once")
        if any(status != "0" for _, status, _, _ in control_matches):
            raise RuntimeError("LiteX control smoke returned a non-zero operator status")
    if require_numeric_smoke:
        if "NUMERIC_SMOKE PASS" not in output or [item[0] for item in numeric_matches] != ["1", "2", "3"]:
            raise RuntimeError("LiteX numeric smoke did not complete P1, P2, and P3 exactly once")
        if any(status != "0" for _, status, _, _ in numeric_matches):
            raise RuntimeError("LiteX numeric smoke returned a non-zero operator status")
        if "IMAGE_PROMPT first=68 last=107 count=8" not in output:
            raise RuntimeError("LiteX numeric smoke did not observe the frozen prompt in SDRAM")
    token_matches: list[tuple[str, str]] = []
    nano_metrics: dict[str, int] = {}
    if require_nano_session:
        if nano_report is None:
            raise RuntimeError("nano session validation requires the image manifest")
        nano_contract = _normalize_nano_image_contract(nano_report)
        token_matches = re.findall(r"^TOKEN (\d+) (\d+)$", output, re.MULTILINE)
        actual_tokens = [int(token) for _, token in token_matches]
        expected_tokens = [int(token) for token in nano_contract["expected_tokens"]]
        expected_indices = list(range(len(expected_tokens)))
        if [int(index) for index, _ in token_matches] != expected_indices:
            raise RuntimeError(
                "LiteX nano session did not emit every expected TOKEN index exactly once"
            )
        if actual_tokens != expected_tokens:
            raise RuntimeError(
                f"LiteX nano tokens differ: actual={actual_tokens}, expected={expected_tokens}"
            )
        actual_token_sha = hashlib.sha256(
            b"".join(token.to_bytes(4, "little") for token in actual_tokens)
        ).hexdigest()
        if actual_token_sha != nano_contract["token_sha256"]:
            raise RuntimeError("LiteX nano token SHA differs from the image manifest")
        print(f"NANO_TOKEN_SHA {actual_token_sha}")
        if {item[0] for item in nano_matches} != {"1", "2", "3"}:
            raise RuntimeError("LiteX nano session did not execute P1, P2, and P3")
        if any(status != "0" for _, status, _, _ in nano_matches):
            raise RuntimeError("LiteX nano session returned a non-zero operator status")
        irq_marker = (
            "NANO_IRQ NOT_APPLICABLE cpu-scalar-no-accelerator-command"
            if execution == "scalar" else "NANO_IRQ PASS"
        )
        if irq_marker not in output:
            raise RuntimeError(
                "LiteX nano session did not report the expected IRQ applicability/status"
            )
        if chat_session:
            if f"USER {nano_contract['question']}" not in output:
                raise RuntimeError("LiteX nano-chat session did not emit the frozen user text")
            if f"ASSISTANT {nano_report['expected_text']}" not in output:
                raise RuntimeError("LiteX nano-chat session did not decode the generated answer")
        metric_match = re.search(
            r"NANO_METRIC ttft=(\d+) decode_total=(\d+) total=(\d+)", output
        )
        if metric_match is None:
            raise RuntimeError("LiteX nano session did not emit cycle metrics")
        nano_metrics = {
            "ttft_cycles": int(metric_match.group(1)),
            "decode_total_cycles": int(metric_match.group(2)),
            "total_cycles": int(metric_match.group(3)),
        }
        if not all(nano_metrics.values()):
            raise RuntimeError("LiteX nano cycle metrics must be positive")
        decode_matches = re.findall(
            r"^DECODE_CYCLES (\d+) (\d+):(\d+)$", output, re.MULTILINE
        )
        if [int(index) for index, _, _ in decode_matches] != expected_indices:
            raise RuntimeError(
                "LiteX nano session did not emit every per-token cycle record"
            )
        nano_metrics["per_token_cycles"] = [
            (int(high) << 32) | int(low) for _, high, low in decode_matches
        ]
    if evidence_path is not None:
        output_root = simulator.parents[2]
        bios = output_root / "software" / "bios" / "bios.bin"
        csr = output_root / "csr.csv"
        verilator = shutil.which("verilator")
        if verilator is None:
            raise RuntimeError("Verilator executable disappeared before evidence capture")
        verilator_path = Path(verilator).resolve()
        verilator_version = subprocess.run(
            [str(verilator_path), "--version"], check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        evidence = {
            "schema_version": 1,
            "status": "PASS",
            "candidate": candidate,
            "promotion_candidate": (
                os.environ.get("COURSE_EVIDENCE_PROMOTION_CANDIDATE")
                or os.environ.get("COURSE_PROMOTION_CANDIDATE")
            ),
            "success_marker": success_marker,
            "simulator_sha256": _sha256(simulator),
            "verilator_version": verilator_version,
            "verilator_launcher_sha256": _sha256(verilator_path),
            "bios_sha256": _sha256(bios),
            "firmware_sha256": _sha256(bios),
            "csr_csv_sha256": _sha256(csr),
            "rtl_sha256": _sha256_files(
                sorted((ROOT / "shared" / "rtl").glob("*.sv"))
            ),
            "target_hz": 100_000_000,
            "simulation_hz": 1_000_000,
            "simulation_wall_seconds": wall_seconds,
            "simulation_host_optimization": "O3",
            "dram_bytes": 256 * 1024 * 1024,
            "control_smoke": require_control_smoke,
            "numeric_smoke": require_numeric_smoke,
            "nano_session": require_nano_session,
            "cpu_b0_directed": require_cpu_b0,
            "cpu_variant": cpu_variant if require_cpu_b0 else None,
            "execution": execution if require_nano_session else None,
            "nano_image_sha256": nano_image_sha256,
            "token_generation_exercised": require_nano_session,
            "control_operators": [
                {
                    "operator": f"P{operator}",
                    "status": int(status),
                    "cycles": (int(high) << 32) | int(low),
                }
                for operator, status, high, low in control_matches
            ],
            "numeric_operators": [
                {
                    "operator": f"P{operator}",
                    "status": int(status),
                    "cycles": (int(high) << 32) | int(low),
                }
                for operator, status, high, low in numeric_matches
            ],
            "nano_operators": [
                {
                    "operator": f"P{operator}",
                    "status": int(status),
                    "cycles": (int(high) << 32) | int(low),
                }
                for operator, status, high, low in nano_matches
            ],
            "generated_tokens": [int(token) for _, token in token_matches],
            "generated_tokens_sha256": (
                hashlib.sha256(
                    b"".join(
                        int(token).to_bytes(4, "little")
                        for _, token in token_matches
                    )
                ).hexdigest()
                if token_matches else None
            ),
            "golden_tokens_sha256": (
                _normalize_nano_image_contract(nano_report)["token_sha256"]
                if nano_report else None
            ),
            "nano_chat_session": chat_session,
            "question": nano_report.get("question") if chat_session else None,
            "assistant_text": nano_report.get("expected_text") if chat_session else None,
            "runtime_semantics": (
                nano_report.get("runtime_semantics") if nano_report else None
            ),
            **nano_metrics,
            "cpu_b0_metric": cpu_b0_metric or None,
            "promotion_eligible": False,
            "baseline_status": "PARTIAL" if require_cpu_b0 else None,
            "boundary": (
                "Complete P1/P2/P3-native firmware generation session with exact "
                "variable-length token comparison and hardware-cycle evidence"
                if require_nano_session else
                "CPU/CSR/descriptor-DMA/response/sticky-done control path only; "
                "numeric P1/P2/P3 and nano token inference are not exercised"
                if require_control_smoke else
                "CPU prepared valid minimal numerical P1/P2/P3 descriptors in the "
                "preloaded nano image workspace and exercised the unified dispatcher; "
                "this is not a model-layer or generated-token nano session"
                if require_numeric_smoke else
                "VexRiscv scalar C executed directed P1/P2/P3 numeric seams; the full "
                "RV32IM variant reported architectural mcycle/minstret counters. The "
                "100 manifest cases and physical evidence are absent"
                if require_cpu_b0 and cpu_variant == "full" else
                "VexRiscv scalar C executed directed P1/P2/P3 numeric seams; the "
                "LiteX 64-bit uptime counter measured cycles because the standard "
                "simulation CPU does not expose progressing mcycle/minstret. The 100 "
                "manifest cases and physical evidence are absent"
                if require_cpu_b0 else
                "BIOS and SDRAM initialization only"
            ),
        }
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_soc(
    *, output_dir: Path, run: bool, control_smoke: bool = False,
    numeric_smoke: bool = False, nano_session: bool = False,
    cpu_b0: bool = False,
    numeric_accelerators: bool = False,
    nano_image: Path | None = None,
    candidate: str = "b0",
    cpu_variant: str = "standard",
    execution: str = "accelerator",
    student_mini_image: Path | None = None,
    student_mini_count: int = 0,
) -> None:
    runtime_foundation_candidates = {
        "accelerator-p1-r1-timing-foundation",
        "accelerator-p2-r1-online-arithmetic-cuts",
        "accelerator-p3-r1-down-requant-cuts",
        "accelerator-p1-a1-stream-topk-mla",
        "accelerator-p2-a1-radix16-canonical-merge",
        "accelerator-p3-a1-expert-group-empty-skip",
        "accelerator-p1-m1-shared-vector-softmax",
        "accelerator-p2-m1-dma-compute-overlap",
        "accelerator-p3-m1-weight-stationary",
        "accelerator-p1-p1-low-power-route",
        "accelerator-p2-p1-low-power-physical",
        "accelerator-p3-p1-low-power-physical",
    }
    microarchitecture_candidates = {
        "accelerator-p1-m1-shared-vector-softmax",
        "accelerator-p2-m1-dma-compute-overlap",
        "accelerator-p3-m1-weight-stationary",
        "accelerator-p1-p1-low-power-route",
        "accelerator-p2-p1-low-power-physical",
        "accelerator-p3-p1-low-power-physical",
    }
    p1_grouped_candidates = {
        "accelerator-p1-a1-stream-topk-mla",
        "accelerator-p1-m1-shared-vector-softmax",
        "accelerator-p1-p1-low-power-route",
    }
    p2_radix16_candidates = {
        "accelerator-p2-a1-radix16-canonical-merge",
        "accelerator-p2-m1-dma-compute-overlap",
        "accelerator-p2-p1-low-power-physical",
    }
    p3_grouped_candidates = {
        "accelerator-p3-a1-expert-group-empty-skip",
        "accelerator-p3-m1-weight-stationary",
        "accelerator-p3-p1-low-power-physical",
    }
    if cpu_variant not in {"standard", "full"}:
        raise ValueError("cpu_variant must be standard or full")
    if execution not in {"accelerator", "scalar"}:
        raise ValueError("execution must be accelerator or scalar")
    if execution == "scalar" and not nano_session:
        raise ValueError("scalar execution is currently defined only for nano sessions")
    frozen_verilator = os.environ.get("COURSE_VERILATOR_BIN")
    if frozen_verilator:
        launcher = Path(frozen_verilator).resolve()
        if not launcher.is_file():
            raise RuntimeError(f"COURSE_VERILATOR_BIN does not exist: {launcher}")
        os.environ["PATH"] = str(launcher.parent) + os.pathsep + os.environ.get("PATH", "")
    if nano_session:
        verilator = shutil.which("verilator")
        if verilator is None:
            raise RuntimeError("Verilator is required for the nano session")
        version = subprocess.run(
            [verilator, "--version"], check=True, capture_output=True, text=True,
        ).stdout.strip()
        if not version.startswith("Verilator 5.040"):
            raise RuntimeError(
                "promotion nano sessions require locked Verilator 5.040; "
                f"resolved {verilator}: {version}"
            )
    allowed_candidates = {
        "b0", "p1-b1-softmax-lut-pipeline",
        "p2-b1-merge-lut-pipeline", "p3-b1-synchronous-silu-pipeline",
        "p3-b1b-radix16-requant-pipeline", "p3-b1c-scale-quantize-pipeline",
        "p2-b1b-output-validation-cut", "p1-b1b-product-pipeline",
        "p2-b1c-serial-bf16-output", "p1-b1c-score-pipeline",
        "p2-b2-radix16-merge-rescale",
        "p1-b2-bf16-format-pipeline", "p2-b3-online-product-pipeline",
        "p3-b2-bf16-format-pipeline", "p2-b4-divider-finalize-cut",
        "p3-b3-requant-finalize-cut", "p2-b5-exp-input-pipeline",
        "p2-b8-online-accumulate-cut", "p1-b7-page-validate-cut",
        "p1-b8-radix8-online-product", "p1-b15-radix4-online-product",
        "p1-b16-weighted-half-cut",
        "p1-b17-divider-step-cut", "p1-b21-vector-half-product",
        "p1-b23-grouped-topk", "p1-b24-grouped-topk-antenna10",
        "p1-b25-grouped-softmax16",
        "p3-b12-output-row-base",
        "p3-b13-weight-cache", "p3-b16-down-product-cut",
        *runtime_foundation_candidates,
    }
    if candidate not in allowed_candidates:
        raise ValueError(f"unsupported nano candidate: {candidate}")
    try:
        from migen import If, Instance, Signal
        from litex.build.sim.config import SimConfig
        from litex.soc.integration.builder import Builder
        from litex.soc.integration.common import get_mem_data
        from litex.soc.integration.soc import SoCRegion
        from litex.soc.interconnect import wishbone
        from litex.soc.interconnect.csr import AutoCSR, CSRStatus, CSRStorage
        from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourceLevel
        from litedram.frontend.wishbone import LiteDRAMWishbone2Native
        from litex.gen import LiteXModule
        from litex.tools.litex_sim import SimSoC
    except ImportError as error:
        raise SystemExit(
            "LiteX build dependencies are unavailable. Install the exact commits in "
            "integration/litex/toolchain.lock.json inside Linux/WSL; no fake build was run."
        ) from error

    nano_report = None
    nano_contract = None
    nano_init: list[int] = []
    if student_mini_image is not None:
        if nano_image is not None or not cpu_b0 or cpu_variant != "full":
            raise ValueError("mini inputs require standalone full-cache CPU mode")
        if student_mini_count <= 0 or student_mini_image.stat().st_size != student_mini_count * 1936:
            raise ValueError("mini input image size/count mismatch")
        nano_init = get_mem_data(str(student_mini_image),data_width=32,endianness="little",mem_size=256*1024*1024)
    if nano_image is not None:
        nano_image = nano_image.resolve()
        report_path = nano_image.with_suffix(nano_image.suffix + ".json")
        if not nano_image.is_file() or not report_path.is_file():
            raise SystemExit(
                "--nano-image requires both the binary and its .bin.json manifest"
            )
        nano_report = json.loads(report_path.read_text(encoding="utf-8"))
        if nano_report["size_bytes"] >= 32 * 1024 * 1024:
            raise SystemExit("nano image exceeds the frozen 32 MiB budget")
        if _sha256(nano_image) != nano_report["sha256"]:
            raise SystemExit("nano image hash does not match its manifest")
        if (
            nano_session
            and nano_report.get("profile") == "nano-chat-e2e"
            and nano_report.get("quality_qualified") is not True
        ):
            raise SystemExit(
                "formal nano-chat sessions require a quality-qualified image; "
                "development images may only be inspected by the Python oracle"
            )
        nano_contract = _normalize_nano_image_contract(nano_report)
        nano_init = get_mem_data(
            # SDRAMPHYModel's bank initializer consumes a list of 32-bit
            # words and performs its own conversion to the 128-bit DFI width.
            # Supplying 128-bit values here silently truncated/interleaved the
            # preloaded image, even though the accelerator DMA itself is 128-bit.
            str(nano_image), data_width=32, endianness="little",
            mem_size=256 * 1024 * 1024,
        )

    class AcceleratorIRQ(LiteXModule):
        def __init__(self, level):
            self.ev = EventManager()
            self.ev.done = EventSourceLevel(description="Sticky P1-P4 completion interrupt.")
            self.ev.finalize()
            self.comb += self.ev.done.trigger.eq(level)

    class CourseCpuTrafficCounters(LiteXModule, AutoCSR):
        """Count accepted VexRiscv I/D Wishbone bytes in hardware.

        The status CSRs expose an atomic snapshot so the reads used to collect
        evidence cannot feed back into the measured interval.  ``reset`` and
        ``capture`` are deliberately level CSRs with an internal edge detector;
        generated firmware accessors therefore remain portable across the
        locked LiteX CSR data width.
        """

        def __init__(self, ibus, dbus, dma_signals=None):
            self.reset = CSRStorage(1, description="Hold CPU traffic counters at zero.")
            self.capture = CSRStorage(1, description="Snapshot CPU traffic counters.")
            self.ibus_bytes = CSRStatus(64, description="Accepted instruction-bus bytes.")
            self.dbus_bytes = CSRStatus(64, description="Accepted data-bus bytes.")

            ibus_count = Signal(64)
            dbus_count = Signal(64)
            ibus_snapshot = Signal(64)
            dbus_snapshot = Signal(64)
            capture_q = Signal()
            dbus_increment = Signal(3)
            self.comb += [
                dbus_increment.eq(
                    dbus.sel[0] + dbus.sel[1] + dbus.sel[2] + dbus.sel[3]
                ),
                self.ibus_bytes.status.eq(ibus_snapshot),
                self.dbus_bytes.status.eq(dbus_snapshot),
            ]
            self.sync += [
                capture_q.eq(self.capture.storage),
                If(
                    self.reset.storage,
                    ibus_count.eq(0),
                    dbus_count.eq(0),
                ).Else(
                    If(
                        ibus.cyc & ibus.stb & ibus.ack,
                        ibus_count.eq(ibus_count + 4),
                    ),
                    If(
                        dbus.cyc & dbus.stb & dbus.ack,
                        dbus_count.eq(dbus_count + dbus_increment),
                    ),
                ),
                If(
                    self.capture.storage & ~capture_q,
                    ibus_snapshot.eq(ibus_count),
                    dbus_snapshot.eq(dbus_count),
                ),
            ]
            if dma_signals is not None:
                valid, ready, write, strobes = dma_signals
                self.dma_bytes = CSRStatus(64, description="Accepted 128-bit accelerator DMA payload bytes; zero is measured, not inferred.")
                dma_count = Signal(64)
                dma_snapshot = Signal(64)
                dma_increment = Signal(5)
                self.comb += [dma_increment.eq(16), self.dma_bytes.status.eq(dma_snapshot),
                              If(write, dma_increment.eq(sum(strobes[index] for index in range(16))))]
                self.sync += [If(self.reset.storage, dma_count.eq(0)).Elif(valid & ready, dma_count.eq(dma_count + dma_increment)),
                              If(self.capture.storage & ~capture_q, dma_snapshot.eq(dma_count))]

    class CourseSimSoC(SimSoC):
        def __init__(self):
            super().__init__(
                with_sdram=True,
                sdram_init=nano_init,
                sdram_data_width=128,
                cpu_type="vexriscv",
                cpu_variant=cpu_variant,
                integrated_rom_size=0x20000,
                integrated_main_ram_size=0,
                uart_name="sim",
            )
            # VexRiscv's ``standard`` variant used by the simulator does not
            # expose a progressing ``mcycle`` CSR.  LiteX's timer uptime block
            # is a real 64-bit sys_clk counter with an atomic latch, so use it
            # as the firmware/service-cycle clock instead of silently
            # accepting a constant-zero architectural counter.
            self.timer0.add_uptime(width=64)
            if student_mini_image is not None:
                self.cpu.use_external_variant(str(ROOT / "build/vexriscv-profiles/VexRiscv_Full_4k.v"))
                self.add_constant("COURSE_STUDENT_MINI_COUNT",student_mini_count)
            self.add_constant("COURSE_TARGET_CLOCK_HZ", 100_000_000)
            self.add_constant("COURSE_DRAM_BYTES", 256 * 1024 * 1024)
            self.add_constant("COURSE_DESCRIPTOR_BYTES", 64)
            # CPU-visible uncached alias for DMA destinations.  VexRiscv's
            # generic LiteX cache API has no invalidate-without-writeback
            # primitive; consuming DMA results through the cached main_ram
            # aperture can therefore write a stale line over fresh data.
            uncached_dram_base = 0xE200_0000
            uncached_dram_size = 32 * 1024 * 1024
            self.add_constant("COURSE_UNCACHED_DRAM_BASE", uncached_dram_base)
            uncached_wb = wishbone.Interface(
                data_width=32, address_width=30, addressing="word"
            )
            self.bus.add_slave(
                name="uncached_dram",
                slave=uncached_wb,
                region=SoCRegion(
                    origin=uncached_dram_base,
                    size=uncached_dram_size,
                    cached=False,
                ),
            )
            # Request a native 32-bit CPU port.  Keeping Wishbone and native
            # widths equal avoids the narrow-Wishbone burst upconverter's
            # lane/ack path; the LiteDRAM crossbar performs the width
            # conversion against the 128-bit DRAM fabric instead.  The
            # accelerator DMA remains independently frozen at 128 bits.
            uncached_port = self.sdram.crossbar.get_port(
                mode="both", data_width=32
            )
            self.submodules.uncached_dram_bridge = LiteDRAMWishbone2Native(
                wishbone=uncached_wb,
                port=uncached_port,
                base_address=uncached_dram_base,
            )
            if cpu_variant == "full":
                self.add_constant("COURSE_CPU_PERF_COUNTERS", 1)
            if cpu_b0:
                if student_mini_image is None:
                    self.submodules.cpu_traffic = CourseCpuTrafficCounters(
                        self.cpu.ibus, self.cpu.dbus
                    )
                self.add_constant("COURSE_CPU_TRAFFIC_COUNTERS", 1)
            if nano_report is not None:
                assert nano_contract is not None
                contract_segments = nano_report["segments"]
                self.add_constant("COURSE_NANO_IMAGE_PRESENT", 1)
                self.add_constant("COURSE_NANO_IMAGE_BYTES", nano_report["size_bytes"])
                self.add_constant(
                    "COURSE_NANO_TOKEN_IO_OFFSET",
                    contract_segments[nano_contract["prompt_segment"]]["offset"],
                )
                self.add_constant(
                    "COURSE_NANO_PROMPT_OFFSET",
                    contract_segments[nano_contract["prompt_segment"]]["offset"],
                )
                self.add_constant(
                    "COURSE_NANO_EXPECTED_OFFSET",
                    contract_segments[nano_contract["expected_segment"]]["offset"],
                )
                self.add_constant(
                    "COURSE_NANO_GENERATED_OFFSET",
                    contract_segments[nano_contract["generated_segment"]]["offset"],
                )
                self.add_constant(
                    "COURSE_NANO_DESCRIPTOR_OFFSET",
                    contract_segments[nano_contract["descriptor_segment"]]["offset"],
                )
                self.add_constant("COURSE_NANO_PROMPT_TOKENS", len(nano_contract["prompt_tokens"]))
                self.add_constant("COURSE_NANO_GENERATED_TOKENS", len(nano_contract["expected_tokens"]))
                if nano_contract["is_chat"]:
                    self.add_constant("COURSE_NANO_CHAT_IMAGE", 1)
                    for config_name, config_value in sorted(
                        nano_contract["model_config"].items()
                    ):
                        if isinstance(config_value, int):
                            constant_name = re.sub(
                                r"[^A-Za-z0-9]", "_", config_name
                            ).upper()
                            self.add_constant(
                                f"COURSE_NANO_MODEL_{constant_name}", config_value
                            )
                    for token_name, token_value in sorted(
                        nano_contract["tokenizer_special_tokens"].items()
                    ):
                        constant_name = re.sub(
                            r"[^A-Za-z0-9]", "_", token_name.strip("<>")
                        ).upper()
                        self.add_constant(
                            f"COURSE_NANO_TOKEN_{constant_name}", token_value
                        )
                if nano_session:
                    self.add_constant("COURSE_RUN_NANO_SESSION", 1)
                    if execution == "scalar":
                        self.add_constant("COURSE_NANO_CPU_SCALAR", 1)
                for segment_name, segment in sorted(nano_report["segments"].items()):
                    constant_name = re.sub(r"[^A-Za-z0-9]", "_", segment_name).upper()
                    self.add_constant(
                        f"COURSE_NANO_SEGMENT_{constant_name}_OFFSET", segment["offset"]
                    )
                    self.add_constant(
                        f"COURSE_NANO_SEGMENT_{constant_name}_SIZE", segment["size"]
                    )
                for scale_name, scale_index in sorted(
                    nano_report["scale_index"].items()
                ):
                    constant_name = re.sub(r"[^A-Za-z0-9]", "_", scale_name).upper()
                    self.add_constant(
                        f"COURSE_NANO_SCALE_{constant_name}_INDEX", scale_index
                    )
            if cpu_b0 and student_mini_image is None:
                self.add_constant("COURSE_RUN_CPU_B0", 1)

            wb = wishbone.Interface(data_width=32, address_width=30, addressing="word")
            self.bus.add_slave(
                name="accelerator",
                slave=wb,
                # VexRiscv marks 0x8000_0000.. as uncached I/O.  Keep this
                # aperture away from LiteX's CSR window at 0xf000_0000.
                region=SoCRegion(origin=0xE000_0000, size=0x1000, cached=False),
            )

            csr_req_valid = Signal()
            csr_req_ready = Signal()
            csr_write = Signal()
            csr_addr = Signal(8)
            csr_wdata = Signal(32)
            csr_rsp_valid = Signal()
            csr_rsp_ready = Signal()
            csr_rdata = Signal(32)
            accel_cmd_valid = Signal()
            accel_cmd_ready = Signal()
            accel_cmd_opcode = Signal(3)
            accel_cmd_desc_addr = Signal(32)
            accel_rsp_valid = Signal()
            accel_rsp_ready = Signal()
            accel_rsp_status = Signal(8)
            accel_rsp_cycles = Signal(64)
            irq = Signal()

            mem_req_valid = Signal()
            mem_req_ready = Signal()
            mem_req_write = Signal()
            mem_req_addr = Signal(32)
            mem_req_wdata = Signal(128)
            mem_req_wstrb = Signal(16)
            mem_rsp_valid = Signal()
            mem_rsp_ready = Signal()
            mem_rsp_data = Signal(128)
            mem_rsp_error = Signal()
            if cpu_b0 and student_mini_image is not None:
                self.submodules.cpu_traffic = CourseCpuTrafficCounters(
                    self.cpu.ibus, self.cpu.dbus,
                    (mem_req_valid, mem_req_ready, mem_req_write, mem_req_wstrb),
                )

            # LiteDRAM native writes use independent command and payload
            # channels and have no explicit completion response.  The RTL
            # bridge turns that protocol into the same one-outstanding
            # request/response seam used by cocotb and the operator shells.
            dma = self.sdram.crossbar.get_port(mode="both", data_width=128)
            native_cmd_valid = Signal()
            native_cmd_ready = Signal()
            native_cmd_we = Signal()
            native_cmd_addr = Signal(len(dma.cmd.addr))
            native_wdata_valid = Signal()
            native_wdata_ready = Signal()
            native_wdata = Signal(128)
            native_wstrb = Signal(16)
            native_rdata_valid = Signal()
            native_rdata_ready = Signal()
            native_rdata = Signal(128)

            self.specials += Instance(
                "litex_wishbone_csr_bridge",
                i_clk_i=self.crg.cd_sys.clk,
                i_rst_ni=~self.crg.cd_sys.rst,
                i_wb_cyc_i=wb.cyc,
                i_wb_stb_i=wb.stb,
                i_wb_we_i=wb.we,
                i_wb_adr_i=wb.adr,
                i_wb_dat_w_i=wb.dat_w,
                i_wb_sel_i=wb.sel,
                o_wb_dat_r_o=wb.dat_r,
                o_wb_ack_o=wb.ack,
                o_wb_err_o=wb.err,
                o_csr_req_valid_o=csr_req_valid,
                i_csr_req_ready_i=csr_req_ready,
                o_csr_write_o=csr_write,
                o_csr_addr_o=csr_addr,
                o_csr_wdata_o=csr_wdata,
                i_csr_rsp_valid_i=csr_rsp_valid,
                o_csr_rsp_ready_o=csr_rsp_ready,
                i_csr_rdata_i=csr_rdata,
            )
            self.specials += Instance(
                "accelerator_shell",
                i_clk_i=self.crg.cd_sys.clk,
                i_rst_ni=~self.crg.cd_sys.rst,
                i_csr_req_valid_i=csr_req_valid,
                o_csr_req_ready_o=csr_req_ready,
                i_csr_write_i=csr_write,
                i_csr_addr_i=csr_addr,
                i_csr_wdata_i=csr_wdata,
                o_csr_rsp_valid_o=csr_rsp_valid,
                i_csr_rsp_ready_i=csr_rsp_ready,
                o_csr_rdata_o=csr_rdata,
                o_accel_cmd_valid_o=accel_cmd_valid,
                i_accel_cmd_ready_i=accel_cmd_ready,
                o_accel_cmd_opcode_o=accel_cmd_opcode,
                o_accel_cmd_desc_addr_o=accel_cmd_desc_addr,
                i_accel_rsp_valid_i=accel_rsp_valid,
                o_accel_rsp_ready_o=accel_rsp_ready,
                i_accel_rsp_status_i=accel_rsp_status,
                i_accel_rsp_cycles_i=accel_rsp_cycles,
                o_irq_o=irq,
            )
            if numeric_accelerators:
                candidate_parameters = {
                    "p1-b1-softmax-lut-pipeline": (1, 0, 0, 0, 0, 0),
                    "p2-b1-merge-lut-pipeline": (0, 1, 0, 0, 0, 0),
                    "p3-b1-synchronous-silu-pipeline": (0, 0, 1, 0, 0, 0),
                    "p3-b1b-radix16-requant-pipeline": (0, 0, 1, 0, 0, 0),
                    "p3-b1c-scale-quantize-pipeline": (0, 0, 1, 0, 1, 0),
                    "p2-b1b-output-validation-cut": (0, 1, 0, 0, 0, 0),
                    "p2-b1c-serial-bf16-output": (0, 1, 0, 0, 0, 0),
                    "p2-b2-radix16-merge-rescale": (0, 1, 0, 0, 0, 1),
                    "p1-b1b-product-pipeline": (1, 0, 0, 0, 0, 0),
                    "p1-b1c-score-pipeline": (1, 0, 0, 1, 0, 0),
                    "p1-b2-bf16-format-pipeline": (1, 0, 0, 1, 0, 0),
                    "p2-b3-online-product-pipeline": (0, 1, 0, 0, 0, 1),
                    "p2-b4-divider-finalize-cut": (0, 1, 0, 0, 0, 1),
                    "p2-b5-exp-input-pipeline": (0, 1, 0, 0, 0, 1),
                    "p2-b8-online-accumulate-cut": (0, 1, 0, 0, 0, 1),
                    "p1-b7-page-validate-cut": (1, 0, 0, 1, 0, 0),
                    "p1-b8-radix8-online-product": (1, 0, 0, 1, 0, 0),
                    "p1-b15-radix4-online-product": (1, 0, 0, 1, 0, 0),
                    "p1-b16-weighted-half-cut": (1, 0, 0, 1, 0, 0),
                    "p1-b17-divider-step-cut": (1, 0, 0, 1, 0, 0),
                    "p1-b21-vector-half-product": (1, 0, 0, 1, 0, 0),
                    "p1-b23-grouped-topk": (1, 0, 0, 1, 0, 0),
                    "p1-b24-grouped-topk-antenna10": (1, 0, 0, 1, 0, 0),
                    "p1-b25-grouped-softmax16": (1, 0, 0, 1, 0, 0),
                    "p3-b12-output-row-base": (0, 0, 1, 0, 1, 0),
                    "p3-b13-weight-cache": (0, 0, 1, 0, 1, 0),
                    "p3-b16-down-product-cut": (0, 0, 1, 0, 1, 0),
                    "p3-b2-bf16-format-pipeline": (0, 0, 1, 0, 1, 0),
                    "p3-b3-requant-finalize-cut": (0, 0, 1, 0, 1, 0),
                    "accelerator-p1-a1-stream-topk-mla": (1, 0, 0, 1, 0, 0),
                    "accelerator-p2-a1-radix16-canonical-merge": (0, 1, 0, 0, 0, 1),
                    "accelerator-p3-a1-expert-group-empty-skip": (0, 0, 1, 0, 1, 0),
                    "accelerator-p1-m1-shared-vector-softmax": (1, 0, 0, 1, 0, 0),
                    "accelerator-p2-m1-dma-compute-overlap": (0, 1, 0, 0, 0, 1),
                    "accelerator-p3-m1-weight-stationary": (0, 0, 1, 0, 1, 0),
                    "accelerator-p1-p1-low-power-route": (1, 0, 0, 1, 0, 0),
                    "accelerator-p2-p1-low-power-physical": (0, 1, 0, 0, 0, 1),
                    "accelerator-p3-p1-low-power-physical": (0, 0, 1, 0, 1, 0),
                }.get(candidate, (0, 0, 0, 0, 0, 0))
                dispatcher_top = (
                    "litex_p123_microarchitecture_top"
                    if candidate in microarchitecture_candidates
                    else
                    "litex_p123_runtime_foundation_top"
                    if candidate in runtime_foundation_candidates
                    else
                    "litex_p123_b25_p1_grouped_softmax16_top"
                    if candidate == "p1-b25-grouped-softmax16"
                    else
                    "litex_p123_b24_p1_grouped_topk_antenna_top"
                    if candidate == "p1-b24-grouped-topk-antenna10"
                    else
                    "litex_p123_b23_p1_grouped_topk_top"
                    if candidate == "p1-b23-grouped-topk"
                    else
                    "litex_p123_b21_p1_vector_half_product_top"
                    if candidate == "p1-b21-vector-half-product"
                    else
                    "litex_p123_b17_p1_divider_step_cut_top"
                    if candidate == "p1-b17-divider-step-cut"
                    else
                    "litex_p123_b16_p1_weighted_half_cut_top"
                    if candidate == "p1-b16-weighted-half-cut"
                    else
                    "litex_p123_b15_p1_radix4_online_product_top"
                    if candidate == "p1-b15-radix4-online-product"
                    else
                    "litex_p123_b8_p1_radix8_top"
                    if candidate == "p1-b8-radix8-online-product"
                    else
                    "litex_p123_b7_p1_page_validate_top"
                    if candidate == "p1-b7-page-validate-cut"
                    else
                    "litex_p123_b16_p3_down_product_cut_top"
                    if candidate == "p3-b16-down-product-cut"
                    else
                    "litex_p123_b13_p3_weight_cache_top"
                    if candidate == "p3-b13-weight-cache"
                    else
                    "litex_p123_b12_p3_output_row_base_top"
                    if candidate == "p3-b12-output-row-base"
                    else
                    "litex_p123_b8_p2_online_accumulate_cut_top"
                    if candidate == "p2-b8-online-accumulate-cut"
                    else
                    "litex_p123_b5_p2_exp_input_pipeline_top"
                    if candidate == "p2-b5-exp-input-pipeline"
                    else
                    "litex_p123_b3_p3_requant_finalize_top"
                    if candidate == "p3-b3-requant-finalize-cut"
                    else
                    "litex_p123_b4_p2_divider_finalize_top"
                    if candidate == "p2-b4-divider-finalize-cut"
                    else
                    "litex_p123_b2_p3_bf16_pipeline_top"
                    if candidate == "p3-b2-bf16-format-pipeline"
                    else "litex_p123_b3_p2_product_pipeline_top"
                    if candidate == "p2-b3-online-product-pipeline"
                    else "litex_p123_b2_p1_bf16_pipeline_top"
                    if candidate == "p1-b2-bf16-format-pipeline"
                    else "litex_p123_b1_requant_top"
                    if candidate in {"p3-b1b-radix16-requant-pipeline", "p3-b1c-scale-quantize-pipeline"}
                    else "litex_p123_b1_p2_serial_output_top"
                    if candidate in {"p2-b1c-serial-bf16-output", "p2-b2-radix16-merge-rescale"}
                    else "litex_p123_b1_p2_output_cut_top"
                    if candidate == "p2-b1b-output-validation-cut"
                    else "litex_p123_b1_p1_product_pipeline_top"
                    if candidate in {"p1-b1b-product-pipeline", "p1-b1c-score-pipeline"}
                    else "litex_p123_b0_top"
                )
                self.specials += Instance(
                    dispatcher_top,
                    # The Nano image is the source of truth for the compiled
                    # P1 vector shape.  The old default (4 heads) is valid for
                    # nano-rtl-e2e but silently wrote only half of the
                    # nano-chat-e2e 8-head output tensor.
                    p_P1_HEADS=int(
                        (nano_contract or {}).get("model_config", {}).get("heads", 4)
                    ),
                    p_P1_NOPE_DIM=int(
                        (nano_contract or {}).get("model_config", {}).get("d_nope", 8)
                    ),
                    p_P1_ROPE_DIM=int(
                        (nano_contract or {}).get("model_config", {}).get("d_rope", 4)
                    ),
                    p_P1_INDEX_DIM=int(
                        (nano_contract or {}).get("model_config", {}).get("indexer_dim", 8)
                    ),
                    p_P1_VALUE_DIM=int(
                        (nano_contract or {}).get("model_config", {}).get("value_dim", 8)
                    ),
                    # The dispatcher must cover both nano-rtl-e2e (128) and
                    # nano-chat-e2e (256) with the same parameterized source.
                    p_P3_MAX_HIDDEN=256,
                    p_P3_MAX_INTERMEDIATE=256,
                    p_P1_PIPELINED_SOFTMAX=candidate_parameters[0],
                    p_P2_PIPELINED_SOFTMAX=candidate_parameters[1],
                    p_P3_PIPELINED_SILU=candidate_parameters[2],
                    p_P1_PIPELINED_SCORE_SCALE=candidate_parameters[3],
                    p_P3_PIPELINED_SCALE_QUANTIZE=candidate_parameters[4],
                    p_P2_RADIX16_MERGE=candidate_parameters[5],
                    i_clk_i=self.crg.cd_sys.clk,
                    i_rst_ni=~self.crg.cd_sys.rst,
                    i_cmd_valid_i=accel_cmd_valid,
                    o_cmd_ready_o=accel_cmd_ready,
                    i_cmd_opcode_i=accel_cmd_opcode,
                    i_cmd_desc_addr_i=accel_cmd_desc_addr,
                    o_mem_req_valid_o=mem_req_valid,
                    i_mem_req_ready_i=mem_req_ready,
                    o_mem_req_write_o=mem_req_write,
                    o_mem_req_addr_o=mem_req_addr,
                    o_mem_req_wdata_o=mem_req_wdata,
                    o_mem_req_wstrb_o=mem_req_wstrb,
                    i_mem_rsp_valid_i=mem_rsp_valid,
                    o_mem_rsp_ready_o=mem_rsp_ready,
                    i_mem_rsp_rdata_i=mem_rsp_data,
                    i_mem_rsp_error_i=mem_rsp_error,
                    o_rsp_valid_o=accel_rsp_valid,
                    i_rsp_ready_i=accel_rsp_ready,
                    o_rsp_status_o=accel_rsp_status,
                    o_rsp_cycles_o=accel_rsp_cycles,
                )
            else:
                self.specials += Instance(
                    "litex_descriptor_engine",
                    i_clk_i=self.crg.cd_sys.clk,
                    i_rst_ni=~self.crg.cd_sys.rst,
                    i_cmd_valid_i=accel_cmd_valid,
                    o_cmd_ready_o=accel_cmd_ready,
                    i_cmd_opcode_i=accel_cmd_opcode,
                    i_cmd_desc_addr_i=accel_cmd_desc_addr,
                    o_mem_req_valid_o=mem_req_valid,
                    i_mem_req_ready_i=mem_req_ready,
                    o_mem_req_addr_o=mem_req_addr,
                    i_mem_rsp_valid_i=mem_rsp_valid,
                    o_mem_rsp_ready_o=mem_rsp_ready,
                    i_mem_rsp_data_i=mem_rsp_data,
                    i_mem_rsp_error_i=mem_rsp_error,
                    o_rsp_valid_o=accel_rsp_valid,
                    i_rsp_ready_i=accel_rsp_ready,
                    o_rsp_status_o=accel_rsp_status,
                    o_rsp_cycles_o=accel_rsp_cycles,
                )
                self.comb += [
                    mem_req_write.eq(0),
                    mem_req_wdata.eq(0),
                    mem_req_wstrb.eq(0),
                ]
            self.specials += Instance(
                "student_mini_native_dma_bridge" if student_mini_image is not None else "litex_native_dma_bridge",
                p_NATIVE_ADDR_WIDTH=len(dma.cmd.addr),
                p_DEBUG=0,
                i_clk_i=self.crg.cd_sys.clk,
                i_rst_ni=~self.crg.cd_sys.rst,
                i_req_valid_i=mem_req_valid,
                o_req_ready_o=mem_req_ready,
                i_req_write_i=mem_req_write,
                i_req_addr_i=mem_req_addr,
                i_req_wdata_i=mem_req_wdata,
                i_req_wstrb_i=mem_req_wstrb,
                o_rsp_valid_o=mem_rsp_valid,
                i_rsp_ready_i=mem_rsp_ready,
                o_rsp_rdata_o=mem_rsp_data,
                o_rsp_error_o=mem_rsp_error,
                o_native_cmd_valid_o=native_cmd_valid,
                i_native_cmd_ready_i=native_cmd_ready,
                o_native_cmd_we_o=native_cmd_we,
                o_native_cmd_addr_o=native_cmd_addr,
                o_native_wdata_valid_o=native_wdata_valid,
                i_native_wdata_ready_i=native_wdata_ready,
                o_native_wdata_o=native_wdata,
                o_native_wstrb_o=native_wstrb,
                i_native_rdata_valid_i=native_rdata_valid,
                o_native_rdata_ready_o=native_rdata_ready,
                i_native_rdata_i=native_rdata,
            )
            self.comb += [
                dma.cmd.valid.eq(native_cmd_valid),
                native_cmd_ready.eq(dma.cmd.ready),
                dma.cmd.we.eq(native_cmd_we),
                dma.cmd.addr.eq(native_cmd_addr),
                # B0 deliberately permits only one outstanding native
                # transaction.  Mark every command as the end of its burst
                # so LiteDRAM commits writes before another crossbar port
                # (notably the CPU uncached alias) observes the location.
                # Leaving ``last`` at its reset value lets the issuing port
                # read its write buffer while another port still sees the
                # pre-write DRAM contents.
                dma.cmd.last.eq(1),
                dma.wdata.valid.eq(native_wdata_valid),
                native_wdata_ready.eq(dma.wdata.ready),
                dma.wdata.data.eq(native_wdata),
                dma.wdata.we.eq(native_wstrb),
                dma.rdata.ready.eq(native_rdata_ready),
                native_rdata_valid.eq(dma.rdata.valid),
                native_rdata.eq(dma.rdata.data),
            ]

            self.accelerator_irq = AcceleratorIRQ(irq)
            if self.irq.enabled:
                self.irq.add("accelerator_irq", use_loc_if_exists=True)

            sources = [
                ROOT / "shared" / "rtl" / "course_csr.sv",
                ROOT / "shared" / "rtl" / "litex_wishbone_csr_bridge.sv",
                ROOT / "shared" / "rtl" / "litex_descriptor_engine.sv",
                ROOT / "shared" / "rtl" / "litex_native_dma_bridge.sv",
                ROOT / "exercises" / "05-integration" / "05.01-ibex-accelerator" / "solution" / "rtl" / "accelerator_shell.sv",
            ]
            if numeric_accelerators:
                sources.extend(ROOT / "shared" / "rtl" / name for name in (
                    "exp_neg_q15.sv", "stable_topk.sv",
                    "online_softmax_step.sv", "online_softmax_step_sync.sv",
                    "softmax_merge_q.sv", "softmax_merge_q_sync.sv",
                    "fp32_scale_check.sv",
                    "fp32_positive_mul_rne.sv", "int32_times_fp32_to_bf16.sv",
                    "int8_dot_serial.sv", "int32_scale_to_q5_11.sv",
                    "q22_requantize_int8.sv", "silu_q11.sv", "silu_q11_sync.sv",
                    "p1_dsa_mla_b0.sv",
                    "p2_split_kv_b0.sv", "p3_expert_row_b0.sv", "dma_128_adapter.sv",
                    "litex_accelerator_dispatcher.sv", "p1_dma_operator_b0.sv",
                    "p1_trace_operator_b0.sv", "p2_dma_operator_b0.sv",
                    "p3_dma_operator_b0.sv", "litex_p123_b0_top.sv",
                ))
                if candidate in {"p1-b15-radix4-online-product", "p1-b16-weighted-half-cut", "p1-b17-divider-step-cut", "p1-b21-vector-half-product", "p1-b23-grouped-topk", "p1-b24-grouped-topk-antenna10", "p1-b25-grouped-softmax16"}:
                    sources = [source for source in sources if source.name != "int8_dot_serial.sv"]
                if candidate in {"p1-b23-grouped-topk", "p1-b24-grouped-topk-antenna10", "p1-b25-grouped-softmax16"}:
                    sources = [source for source in sources if source.name != "stable_topk.sv"]
                if candidate not in {"p1-b7-page-validate-cut", "p1-b8-radix8-online-product", "p1-b15-radix4-online-product", "p1-b16-weighted-half-cut", "p1-b17-divider-step-cut", "p1-b21-vector-half-product", "p1-b23-grouped-topk", "p1-b24-grouped-topk-antenna10", "p1-b25-grouped-softmax16"}:
                    sources.append(ROOT / "shared" / "rtl" / "fixed_divider_rne.sv")
                if candidate not in {"p2-b5-exp-input-pipeline", "p2-b8-online-accumulate-cut", "p1-b7-page-validate-cut", "p1-b8-radix8-online-product", "p1-b15-radix4-online-product", "p1-b16-weighted-half-cut", "p1-b17-divider-step-cut", "p1-b21-vector-half-product", "p1-b23-grouped-topk", "p1-b24-grouped-topk-antenna10", "p1-b25-grouped-softmax16"}:
                    sources.append(ROOT / "shared" / "rtl" / "exp_neg_q15_sync.sv")
                if candidate == "p1-b7-page-validate-cut":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "exp_neg_q15_sync_banked.sv",
                        "exp_neg_q15_sync_input_pipeline.sv",
                        "exp_neg_q15_sync_input_compat.sv",
                        "online_softmax_step_sync_exp_output_pipeline.sv",
                        "online_softmax_step_sync_accumulate_cut_compat.sv",
                        "fixed_divider_rne_finalize_pipeline.sv",
                        "fixed_divider_rne_finalize_compat.sv",
                        "int32_scale_to_q5_11_finalize_pipeline.sv",
                        "int32_scale_to_q5_11_finalize_compat.sv",
                        "int32_times_fp32_to_bf16_pipeline.sv",
                        "p1_dsa_mla_b1_product_pipeline.sv",
                        "p1_dsa_mla_b2_bf16_pipeline.sv",
                        "p1_dma_operator_b2_bf16_pipeline.sv",
                        "litex_p123_b2_p1_bf16_pipeline_top.sv",
                        "litex_p123_b7_p1_page_validate_top.sv",
                    ))
                if candidate == "p1-b8-radix8-online-product":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "exp_neg_q15_sync_banked.sv",
                        "exp_neg_q15_sync_input_pipeline.sv",
                        "exp_neg_q15_sync_input_compat.sv",
                        "online_softmax_step_sync_radix8_pipeline.sv",
                        "online_softmax_step_sync_radix8_compat.sv",
                        "fixed_divider_rne_finalize_pipeline.sv",
                        "fixed_divider_rne_finalize_compat.sv",
                        "int32_scale_to_q5_11_finalize_pipeline.sv",
                        "int32_scale_to_q5_11_finalize_compat.sv",
                        "int32_times_fp32_to_bf16_pipeline.sv",
                        "p1_dsa_mla_b1_product_pipeline.sv",
                        "p1_dsa_mla_b2_bf16_pipeline.sv",
                        "p1_dma_operator_b2_bf16_pipeline.sv",
                        "litex_p123_b2_p1_bf16_pipeline_top.sv",
                        "litex_p123_b8_p1_radix8_top.sv",
                    ))
                if candidate == "p1-b15-radix4-online-product":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "exp_neg_q15_sync_banked.sv",
                        "exp_neg_q15_sync_input_pipeline.sv",
                        "exp_neg_q15_sync_input_compat.sv",
                        "online_softmax_step_sync_radix4_pipeline.sv",
                        "online_softmax_step_sync_radix4_compat.sv",
                        "fixed_divider_rne_round_pipeline.sv",
                        "fixed_divider_rne_round_compat.sv",
                        "int32_scale_to_q5_11_finalize_pipeline.sv",
                        "int32_scale_to_q5_11_finalize_compat.sv",
                        "int32_times_fp32_to_bf16_pipeline.sv",
                        "int8_dot_serial_pipelined.sv",
                        "int8_dot_serial_pipelined_compat.sv",
                        "p1_dsa_mla_b1_product_pipeline.sv",
                        "p1_dsa_mla_b2_bf16_pipeline.sv",
                        "p1_dma_operator_b14_page_token_base_cut.sv",
                        "litex_p123_b15_p1_radix4_online_product_top.sv",
                    ))
                if candidate == "p1-b16-weighted-half-cut":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "exp_neg_q15_sync_banked.sv",
                        "exp_neg_q15_sync_input_pipeline.sv",
                        "exp_neg_q15_sync_input_compat.sv",
                        "online_softmax_step_sync_radix4_half_pipeline.sv",
                        "online_softmax_step_sync_radix4_half_compat.sv",
                        "fixed_divider_rne_round_pipeline.sv",
                        "fixed_divider_rne_round_compat.sv",
                        "int32_scale_to_q5_11_finalize_pipeline.sv",
                        "int32_scale_to_q5_11_finalize_compat.sv",
                        "int32_times_fp32_to_bf16_pipeline.sv",
                        "int8_dot_serial_pipelined.sv",
                        "int8_dot_serial_pipelined_compat.sv",
                        "p1_dsa_mla_b1_product_pipeline.sv",
                        "p1_dsa_mla_b2_bf16_pipeline.sv",
                        "p1_dma_operator_b14_page_token_base_cut.sv",
                        "litex_p123_b15_p1_radix4_online_product_top.sv",
                        "litex_p123_b16_p1_weighted_half_cut_top.sv",
                    ))
                if candidate == "p1-b17-divider-step-cut":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "exp_neg_q15_sync_banked.sv",
                        "exp_neg_q15_sync_input_pipeline.sv",
                        "exp_neg_q15_sync_input_compat.sv",
                        "online_softmax_step_sync_radix4_pipeline.sv",
                        "online_softmax_step_sync_radix4_compat.sv",
                        "fixed_divider_rne_step_cut_pipeline.sv",
                        "fixed_divider_rne_step_cut_compat.sv",
                        "int32_scale_to_q5_11_finalize_pipeline.sv",
                        "int32_scale_to_q5_11_finalize_compat.sv",
                        "int32_times_fp32_to_bf16_pipeline.sv",
                        "int8_dot_serial_pipelined.sv",
                        "int8_dot_serial_pipelined_compat.sv",
                        "p1_dsa_mla_b1_product_pipeline.sv",
                        "p1_dsa_mla_b2_bf16_pipeline.sv",
                        "p1_dma_operator_b14_page_token_base_cut.sv",
                        "litex_p123_b15_p1_radix4_online_product_top.sv",
                        "litex_p123_b17_p1_divider_step_cut_top.sv",
                    ))
                if candidate == "p1-b21-vector-half-product":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "exp_neg_q15_sync_banked.sv",
                        "exp_neg_q15_sync_input_pipeline.sv",
                        "exp_neg_q15_sync_input_compat.sv",
                        "online_softmax_step_sync_vector_half_serial_accum_pipeline.sv",
                        "fixed_divider_rne_step_cut_pipeline.sv",
                        "fixed_divider_rne_step_cut_compat.sv",
                        "int32_scale_to_q5_11_finalize_pipeline.sv",
                        "int32_scale_to_q5_11_finalize_compat.sv",
                        "int32_times_fp32_to_bf16_pipeline.sv",
                        "int8_dot_serial_pipelined.sv",
                        "int8_dot_serial_pipelined_compat.sv",
                        "p1_dsa_mla_b1_product_pipeline.sv",
                        "p1_dsa_mla_b2_bf16_pipeline.sv",
                        "p1_dma_operator_b14_page_token_base_cut.sv",
                        "litex_p123_b15_p1_radix4_online_product_top.sv",
                        "litex_p123_b21_p1_vector_half_product_top.sv",
                    ))
                if candidate in {"p1-b23-grouped-topk", "p1-b24-grouped-topk-antenna10", "p1-b25-grouped-softmax16"}:
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "exp_neg_q15_sync_banked.sv",
                        "exp_neg_q15_sync_input_pipeline.sv",
                        "exp_neg_q15_sync_input_compat.sv",
                        "stable_topk_grouped_pipeline.sv",
                        (
                            "online_softmax_step_sync_vector_grouped_pipeline.sv"
                            if candidate == "p1-b25-grouped-softmax16"
                            else "online_softmax_step_sync_vector_round_cut_pipeline.sv"
                        ),
                        "fixed_divider_rne_step_cut_pipeline.sv",
                        "fixed_divider_rne_step_cut_compat.sv",
                        "int32_scale_to_q5_11_finalize_pipeline.sv",
                        "int32_scale_to_q5_11_finalize_compat.sv",
                        "int32_times_fp32_to_bf16_pipeline.sv",
                        "int8_dot_serial_pipelined.sv",
                        "int8_dot_serial_pipelined_compat.sv",
                        "p1_dsa_mla_b1_product_pipeline.sv",
                        "p1_dsa_mla_b2_bf16_pipeline.sv",
                        "p1_dma_operator_b14_page_token_base_cut.sv",
                        "litex_p123_b15_p1_radix4_online_product_top.sv",
                        "litex_p123_b21_p1_vector_half_product_top.sv",
                        "litex_p123_b23_p1_grouped_topk_top.sv",
                    ))
                    if candidate == "p1-b24-grouped-topk-antenna10":
                        sources.append(
                            ROOT / "shared" / "rtl" /
                            "litex_p123_b24_p1_grouped_topk_antenna_top.sv"
                        )
                    if candidate == "p1-b25-grouped-softmax16":
                        sources.append(
                            ROOT / "shared" / "rtl" /
                            "litex_p123_b25_p1_grouped_softmax16_top.sv"
                        )
                if candidate == "p3-b12-output-row-base":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "fp32_positive_mul_rne_pipeline.sv",
                        "int32_scale_to_q5_11_pipeline.sv",
                        "q22_requantize_int8_finalize_pipeline.sv",
                        "q22_requantize_int8_low_digit_compat.sv",
                        "int32_times_fp32_to_bf16_pipeline.sv",
                        "p3_expert_row_b2_bf16_pipeline.sv",
                        "litex_accelerator_dispatcher_counter8.sv",
                        "p3_dma_operator_b2_bf16_pipeline.sv",
                        "litex_p123_b2_p3_bf16_pipeline_top.sv",
                        "litex_p123_b12_p3_output_row_base_top.sv",
                    ))
                if candidate == "p3-b13-weight-cache":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "fp32_positive_mul_rne_pipeline.sv",
                        "int32_scale_to_q5_11_pipeline.sv",
                        "q22_requantize_int8_finalize_pipeline.sv",
                        "q22_requantize_int8_low_digit_compat.sv",
                        "int32_times_fp32_to_bf16_pipeline.sv",
                        "p3_expert_row_b2_bf16_pipeline.sv",
                        "litex_accelerator_dispatcher_counter8.sv",
                        "p3_dma_operator_b13_weight_cache.sv",
                        "litex_p123_b13_p3_weight_cache_top.sv",
                    ))
                if candidate == "p3-b16-down-product-cut":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "fp32_positive_mul_rne_pipeline.sv",
                        "int32_scale_to_q5_11_pipeline.sv",
                        "q22_requantize_int8_product_pipeline.sv",
                        "q22_requantize_int8_product_compat.sv",
                        "int32_times_fp32_to_bf16_pipeline.sv",
                        "p3_expert_row_b16_down_product_cut.sv",
                        "litex_accelerator_dispatcher_counter8.sv",
                        "p3_dma_operator_b16_down_product_cut.sv",
                        "litex_p123_b16_p3_down_product_cut_top.sv",
                    ))
                if candidate in {"p3-b1b-radix16-requant-pipeline", "p3-b1c-scale-quantize-pipeline"}:
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "q22_requantize_int8_radix16.sv",
                        "int32_scale_to_q5_11_pipeline.sv",
                        "p3_expert_row_b1_requant.sv",
                        "p3_dma_operator_b1_requant.sv",
                        "litex_p123_b1_requant_top.sv",
                    ))
                if candidate == "p2-b1b-output-validation-cut":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "p2_split_kv_b1_output_cut.sv",
                        "p2_dma_operator_b1_output_cut.sv",
                        "litex_p123_b1_p2_output_cut_top.sv",
                    ))
                if candidate in {"p2-b1c-serial-bf16-output", "p2-b2-radix16-merge-rescale"}:
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "int32_times_fp32_to_bf16_serial.sv",
                        "softmax_merge_q_radix16.sv",
                        "p2_split_kv_b1_output_cut.sv",
                        "p2_split_kv_b1c_serial_output.sv",
                        "p2_dma_operator_b1c_serial_output.sv",
                        "litex_p123_b1_p2_serial_output_top.sv",
                    ))
                if candidate in {"p1-b1b-product-pipeline", "p1-b1c-score-pipeline"}:
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "online_softmax_step_sync_product_pipeline.sv",
                        "int32_scale_to_q5_11_pipeline.sv",
                        "p1_dsa_mla_b1_product_pipeline.sv",
                        "p1_dma_operator_b1_product_pipeline.sv",
                        "litex_p123_b1_p1_product_pipeline_top.sv",
                    ))
                if candidate == "p1-b2-bf16-format-pipeline":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "online_softmax_step_sync_product_pipeline.sv",
                        "int32_scale_to_q5_11_pipeline.sv",
                        "int32_times_fp32_to_bf16_pipeline.sv",
                        "p1_dsa_mla_b1_product_pipeline.sv",
                        "p1_dsa_mla_b2_bf16_pipeline.sv",
                        "p1_dma_operator_b2_bf16_pipeline.sv",
                        "litex_p123_b2_p1_bf16_pipeline_top.sv",
                    ))
                if candidate == "p2-b3-online-product-pipeline":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "online_softmax_step_sync_product_pipeline.sv",
                        "int32_times_fp32_to_bf16_serial.sv",
                        "softmax_merge_q_radix16.sv",
                        "p2_split_kv_b3_product_pipeline.sv",
                        "p2_split_kv_b3_serial_output.sv",
                        "p2_dma_operator_b3_product_pipeline.sv",
                        "litex_p123_b3_p2_product_pipeline_top.sv",
                    ))
                if candidate == "p2-b4-divider-finalize-cut":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "online_softmax_step_sync_product_pipeline.sv",
                        "fixed_divider_rne_finalize_pipeline.sv",
                        "int32_times_fp32_to_bf16_serial.sv",
                        "softmax_merge_q_radix16.sv",
                        "p2_split_kv_b3_product_pipeline.sv",
                        "p2_split_kv_b3_serial_output.sv",
                        "p2_dma_operator_b3_product_pipeline.sv",
                        "p2_split_kv_b4_divider_finalize.sv",
                        "p2_split_kv_b4_serial_output.sv",
                        "p2_dma_operator_b4_divider_finalize.sv",
                        "p2_dma_operator_b4_divider_finalize_compat.sv",
                        "litex_p123_b3_p2_product_pipeline_top.sv",
                        "litex_p123_b4_p2_divider_finalize_top.sv",
                    ))
                if candidate == "p2-b5-exp-input-pipeline":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "exp_neg_q15_sync_banked.sv",
                        "exp_neg_q15_sync_input_pipeline.sv",
                        "exp_neg_q15_sync_input_compat.sv",
                        "online_softmax_step_sync_product_pipeline.sv",
                        "fixed_divider_rne_finalize_pipeline.sv",
                        "int32_times_fp32_to_bf16_serial.sv",
                        "softmax_merge_q_radix16.sv",
                        "p2_split_kv_b4_divider_finalize.sv",
                        "p2_split_kv_b4_serial_output.sv",
                        "p2_dma_operator_b4_divider_finalize.sv",
                        "p2_dma_operator_b4_divider_finalize_compat.sv",
                        "litex_p123_b3_p2_product_pipeline_top.sv",
                        "litex_p123_b4_p2_divider_finalize_top.sv",
                        "litex_p123_b5_p2_exp_input_pipeline_top.sv",
                    ))
                if candidate == "p2-b8-online-accumulate-cut":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "exp_neg_q15_sync_banked.sv",
                        "exp_neg_q15_sync_input_pipeline.sv",
                        "exp_neg_q15_sync_input_compat.sv",
                        "online_softmax_step_sync_exp_output_pipeline.sv",
                        "online_softmax_step_sync_accumulate_cut_compat.sv",
                        "fixed_divider_rne_finalize_pipeline.sv",
                        "int32_times_fp32_to_bf16_serial.sv",
                        "softmax_merge_q_radix16.sv",
                        "p2_split_kv_b3_product_pipeline.sv",
                        "p2_split_kv_b3_serial_output.sv",
                        "p2_dma_operator_b3_product_pipeline.sv",
                        "p2_split_kv_b4_divider_finalize.sv",
                        "p2_split_kv_b4_serial_output.sv",
                        "p2_dma_operator_b4_divider_finalize.sv",
                        "litex_p123_b3_p2_product_pipeline_top.sv",
                        "litex_p123_b4_p2_divider_finalize_top.sv",
                        "litex_p123_b8_p2_online_accumulate_cut_top.sv",
                    ))
                if candidate == "p3-b2-bf16-format-pipeline":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "q22_requantize_int8_radix16.sv",
                        "int32_scale_to_q5_11_pipeline.sv",
                        "int32_times_fp32_to_bf16_pipeline.sv",
                        "p3_expert_row_b2_bf16_pipeline.sv",
                        "p3_dma_operator_b2_bf16_pipeline.sv",
                        "litex_p123_b2_p3_bf16_pipeline_top.sv",
                    ))
                if candidate == "p3-b3-requant-finalize-cut":
                    sources.extend(ROOT / "shared" / "rtl" / name for name in (
                        "q22_requantize_int8_finalize_pipeline.sv",
                        "q22_requantize_int8_finalize_pipeline_compat.sv",
                        "int32_scale_to_q5_11_pipeline.sv",
                        "int32_times_fp32_to_bf16_pipeline.sv",
                        "p3_expert_row_b2_bf16_pipeline.sv",
                        "p3_dma_operator_b2_bf16_pipeline.sv",
                        "litex_p123_b2_p3_bf16_pipeline_top.sv",
                        "litex_p123_b3_p3_requant_finalize_top.sv",
                    ))
                if candidate in runtime_foundation_candidates:
                    # Assemble the exact timing-safe B0 implementations in one
                    # Nano router.  The selected R1 substitutes only its own
                    # module or grouping define; the other two operators stay
                    # at B0 and no legacy B8/B16 promotion stack is pulled in.
                    names = [
                        "exp_neg_q15.sv", "exp_neg_q15_sync_banked.sv",
                        "exp_neg_q15_sync_input_pipeline.sv",
                        "exp_neg_q15_sync_input_compat.sv",
                        (
                            "stable_topk_grouped_pipeline.sv"
                            if candidate in p1_grouped_candidates
                            else "stable_topk_serial_baseline.sv"
                        ),
                        "online_softmax_step.sv",
                        "online_softmax_step_sync_product_pipeline.sv",
                        "online_softmax_step_sync_vector_grouped_pipeline.sv",
                        "fixed_divider_rne_step_cut_pipeline.sv",
                        "fixed_divider_rne_step_cut_compat.sv", "fp32_scale_check.sv",
                        "fp32_positive_mul_rne.sv", "fp32_positive_mul_rne_pipeline.sv",
                        "int32_times_fp32_to_bf16.sv",
                        "int32_times_fp32_to_bf16_pipeline.sv",
                        "int8_dot_serial_pipelined.sv", "int8_dot_serial_pipelined_compat.sv",
                        "int32_scale_to_q5_11.sv",
                        "int32_scale_to_q5_11_finalize_pipeline.sv",
                        "int32_scale_to_q5_11_finalize_compat.sv",
                        "int32_scale_to_q5_11_pipeline.sv",
                        "p1_dsa_mla_b1_product_pipeline.sv", "p1_dsa_mla_b2_bf16_pipeline.sv",
                        "dma_128_adapter.sv", "litex_descriptor_engine.sv",
                        "litex_accelerator_dispatcher.sv",
                        "litex_accelerator_dispatcher_counter8.sv",
                        "p1_dma_operator_b13_meta_validate_cut.sv",
                        "p1_dma_operator_b13_meta_length_compat.sv",
                        "p1_trace_operator_b0.sv", "p1_b2_bf16_pipeline_litex_top.sv",
                        "online_softmax_step_sync_exp_output_pipeline.sv",
                        "online_softmax_step_sync_accumulate_cut_compat.sv",
                        "softmax_merge_q.sv", "softmax_merge_q_sync.sv",
                        (
                            "softmax_merge_q_radix16_canonical.sv"
                            if candidate in p2_radix16_candidates
                            else "softmax_merge_q_radix16.sv"
                        ),
                        "fixed_divider_rne_finalize_pipeline.sv",
                        "p2_split_kv_b4_divider_finalize.sv",
                        "p2_split_kv_b4_serial_output.sv",
                        "p2_dma_operator_b4_divider_finalize.sv",
                        "p2_b4_divider_finalize_litex_top.sv",
                        "p2_b5_exp_input_pipeline_litex_top.sv",
                        "p2_b6_merge_product_pipeline_litex_top.sv",
                        "p2_b8_online_accumulate_cut_litex_top.sv",
                        "silu_q11.sv", "silu_q11_sync.sv",
                        "q22_requantize_int8_finalize_pipeline.sv",
                        "q22_requantize_int8_low_digit_compat.sv",
                        "p3_dma_operator_b2_bf16_pipeline.sv",
                        "p3_b2_bf16_pipeline_litex_top.sv",
                        "p3_b3_requant_finalize_litex_top.sv",
                        "p3_b11_dispatcher_counter8_litex_top.sv",
                        "p3_b12_output_row_base_litex_top.sv",
                        (
                            "litex_p123_microarchitecture_top.sv"
                            if candidate in microarchitecture_candidates
                            else "litex_p123_runtime_foundation_top.sv"
                        ),
                    ]
                    if candidate in p3_grouped_candidates:
                        names.extend((
                            "p3_dma_operator_b13_weight_cache.sv",
                            "p3_b13_weight_cache_litex_top.sv",
                        ))
                    if candidate in microarchitecture_candidates:
                        names.extend((
                            "dma_128_read_reuse_buffer.sv",
                            "p2_m1_dma_compute_overlap_litex_top.sv",
                            "p3_m1_weight_stationary_litex_top.sv",
                        ))
                    if candidate in {
                        "accelerator-p2-r1-online-arithmetic-cuts",
                        "accelerator-p2-a1-radix16-canonical-merge",
                        "accelerator-p2-m1-dma-compute-overlap",
                        "accelerator-p2-p1-low-power-physical",
                    }:
                        names.append("int32_times_fp32_to_bf16_pipeline_as_serial_compat.sv")
                    else:
                        names.append("int32_times_fp32_to_bf16_serial.sv")
                    if candidate in {
                        "accelerator-p3-r1-down-requant-cuts",
                        "accelerator-p3-a1-expert-group-empty-skip",
                        "accelerator-p3-m1-weight-stationary",
                        "accelerator-p3-p1-low-power-physical",
                    }:
                        names.extend((
                            "p3_expert_row_b16_down_product_cut.sv",
                            "p3_expert_row_down_requant_cuts_compat.sv",
                        ))
                    else:
                        names.append("p3_expert_row_b2_bf16_pipeline.sv")
                    control_sources = sources[:5]
                    sources = control_sources + [
                        ROOT / "shared" / "rtl" / name for name in dict.fromkeys(names)
                    ]
            if student_mini_image is not None:
                sources.append(ROOT / "shared/rtl/student_mini_native_dma_bridge.sv")
            for source in sources:
                self.platform.add_source(str(source))

    soc = CourseSimSoC()
    sim_config = SimConfig()
    sim_config.add_clocker("sys_clk", freq_hz=1_000_000)
    sim_config.add_module("serial2console", "serial")
    builder = Builder(
        soc,
        output_dir=str(output_dir),
        csr_csv=str(output_dir / "csr.csv"),
        compile_software=True,
        compile_gateware=True,
    )
    if control_smoke or numeric_smoke or nano_session or cpu_b0:
        # Replace only the BIOS package.  The custom Makefile reuses upstream
        # BIOS sources and adds one init hook after SDRAM initialization.
        builder.add_software_package("bios", str(Path(__file__).with_name("bios")))
    # The LiteX simulator is an interactive BIOS and does not exit after its
    # memory test.  Always compile first; smoke mode then uses a bounded,
    # marker-based success condition.
    builder.build(sim_config=sim_config, interactive=False, run=False)
    build_script = output_dir / "gateware" / "build_sim.sh"
    build_command = build_script.read_text(encoding="utf-8")
    if "OPT_LEVEL=O0" not in build_command:
        raise RuntimeError("LiteX simulation build no longer exposes the frozen OPT_LEVEL seam")
    # The numerical nano session executes tens of millions of simulated
    # cycles.  O3 changes only host wall-clock CI cost, never hardware cycles.
    build_script.write_text(
        build_command.replace(
            'CC_SRCS="',
            'CC_SRCS="-DP1_SHARED_SOFTMAX_VECTOR -DP1_SOFTMAX_GROUP8 '
            '-DP1_SERIAL_OUTPUT -DP1_EXTERNAL_BF16_PIPELINE '
            '-DP2_MERGE_PRODUCT_PIPELINE '
            if candidate in {
                "accelerator-p1-m1-shared-vector-softmax",
                "accelerator-p1-p1-low-power-route",
            }
            else 'CC_SRCS="-DP1_SHARED_SOFTMAX_VECTOR -DP1_SOFTMAX_GROUP4 '
            '-DP1_SERIAL_OUTPUT -DP1_EXTERNAL_BF16_PIPELINE '
            '-DP2_MERGE_PRODUCT_PIPELINE '
            if candidate in {
                "accelerator-p1-r1-timing-foundation",
                "accelerator-p1-a1-stream-topk-mla",
            }
            else 'CC_SRCS="-DP1_SHARED_SOFTMAX_VECTOR -DP1_SOFTMAX_GROUP1 '
            '-DP1_SERIAL_OUTPUT -DP1_EXTERNAL_BF16_PIPELINE '
            '-DP2_MERGE_PRODUCT_PIPELINE '
            if candidate in runtime_foundation_candidates
            else 'CC_SRCS="-DP2_MERGE_PRODUCT_PIPELINE '
            if candidate == "p2-b8-online-accumulate-cut"
            else 'CC_SRCS="-DP1_PIPELINE_READY_INVARIANT -DP1_SHARED_SOFTMAX_VECTOR '
            if candidate in {"p1-b21-vector-half-product", "p1-b23-grouped-topk", "p1-b24-grouped-topk-antenna10", "p1-b25-grouped-softmax16"}
            else 'CC_SRCS="',
        ).replace(
            'CC_SRCS="',
            'CC_SRCS="-DP2_MERGE_PRODUCT_STEP_CUT -DP2_MERGE_RESCALE_PIPELINE '
            if candidate in runtime_foundation_candidates else 'CC_SRCS="',
        ).replace(
            'CC_SRCS="', 'CC_SRCS="-DP3_EXPERT_GROUP_LINE_BUFFER '
            '-DP3_M1_WEIGHT_STATIONARY '
            if candidate in {
                "accelerator-p3-m1-weight-stationary",
                "accelerator-p3-p1-low-power-physical",
            }
            else 'CC_SRCS="-DP3_EXPERT_GROUP_LINE_BUFFER '
            if candidate in p3_grouped_candidates
            else 'CC_SRCS="',
            1,
        ).replace(
            'CC_SRCS="', 'CC_SRCS="-DP2_M1_DMA_REUSE '
            if candidate in {
                "accelerator-p2-m1-dma-compute-overlap",
                "accelerator-p2-p1-low-power-physical",
            }
            else 'CC_SRCS="',
            1,
        ).replace("OPT_LEVEL=O0", "OPT_LEVEL=O3"), encoding="utf-8"
    )
    subprocess.run(
        ["bash", "build_sim.sh"],
        cwd=output_dir / "gateware",
        check=True,
    )
    # The standalone simulator runs from gateware/.  Keep the generated ROM
    # files at the exact fallback paths compiled into the offline RTL so a run
    # never silently substitutes an all-zero exp/SiLU table.
    rtl_data = output_dir / "gateware" / "shared" / "rtl"
    rtl_data.mkdir(parents=True, exist_ok=True)
    for name in ("exp_q15_q6.mem", "silu_q11_q6.mem"):
        shutil.copy2(ROOT / "shared" / "rtl" / name, rtl_data / name)
    if numeric_accelerators:
        simulator = output_dir / "gateware" / "obj_dir" / "Vsim"
        bios = output_dir / "software" / "bios" / "bios.bin"
        csr = output_dir / "csr.csv"
        dram_init_files = list((output_dir / "gateware").glob("sim_mem*.init"))
        build_evidence = {
            "schema_version": 1,
            "status": "PASS",
            "kind": "litex-p123-compile-integration",
            "simulator_sha256": _sha256(simulator),
            "bios_sha256": _sha256(bios),
            "csr_csv_sha256": _sha256(csr),
            "dispatcher_source_sha256": _sha256(
                ROOT / "shared" / "rtl" / (
                    "litex_p123_runtime_foundation_top.sv"
                    if candidate in runtime_foundation_candidates
                    else "litex_p123_b25_p1_grouped_softmax16_top.sv"
                    if candidate == "p1-b25-grouped-softmax16"
                    else
                    "litex_p123_b24_p1_grouped_topk_antenna_top.sv"
                    if candidate == "p1-b24-grouped-topk-antenna10"
                    else
                    "litex_p123_b23_p1_grouped_topk_top.sv"
                    if candidate == "p1-b23-grouped-topk"
                    else
                    "litex_p123_b21_p1_vector_half_product_top.sv"
                    if candidate == "p1-b21-vector-half-product"
                    else
                    "litex_p123_b17_p1_divider_step_cut_top.sv"
                    if candidate == "p1-b17-divider-step-cut"
                    else
                    "litex_p123_b16_p1_weighted_half_cut_top.sv"
                    if candidate == "p1-b16-weighted-half-cut"
                    else
                    "litex_p123_b15_p1_radix4_online_product_top.sv"
                    if candidate == "p1-b15-radix4-online-product"
                    else
                    "litex_p123_b8_p1_radix8_top.sv"
                    if candidate == "p1-b8-radix8-online-product"
                    else
                    "litex_p123_b7_p1_page_validate_top.sv"
                    if candidate == "p1-b7-page-validate-cut"
                    else
                    "litex_p123_b16_p3_down_product_cut_top.sv"
                    if candidate == "p3-b16-down-product-cut"
                    else
                    "litex_p123_b13_p3_weight_cache_top.sv"
                    if candidate == "p3-b13-weight-cache"
                    else
                    "litex_p123_b12_p3_output_row_base_top.sv"
                    if candidate == "p3-b12-output-row-base"
                    else
                    "litex_p123_b8_p2_online_accumulate_cut_top.sv"
                    if candidate == "p2-b8-online-accumulate-cut"
                    else
                    "litex_p123_b5_p2_exp_input_pipeline_top.sv"
                    if candidate == "p2-b5-exp-input-pipeline"
                    else
                    "litex_p123_b3_p3_requant_finalize_top.sv"
                    if candidate == "p3-b3-requant-finalize-cut"
                    else
                    "litex_p123_b4_p2_divider_finalize_top.sv"
                    if candidate == "p2-b4-divider-finalize-cut"
                    else
                    "litex_p123_b2_p3_bf16_pipeline_top.sv"
                    if candidate == "p3-b2-bf16-format-pipeline"
                    else "litex_p123_b3_p2_product_pipeline_top.sv"
                    if candidate == "p2-b3-online-product-pipeline"
                    else "litex_p123_b2_p1_bf16_pipeline_top.sv"
                    if candidate == "p1-b2-bf16-format-pipeline"
                    else "litex_p123_b1_requant_top.sv"
                    if candidate in {"p3-b1b-radix16-requant-pipeline", "p3-b1c-scale-quantize-pipeline"}
                    else "litex_p123_b1_p2_serial_output_top.sv"
                    if candidate in {"p2-b1c-serial-bf16-output", "p2-b2-radix16-merge-rescale"}
                    else "litex_p123_b1_p2_output_cut_top.sv"
                    if candidate == "p2-b1b-output-validation-cut"
                    else "litex_p123_b1_p1_product_pipeline_top.sv"
                    if candidate in {"p1-b1b-product-pipeline", "p1-b1c-score-pipeline"}
                    else "litex_p123_b0_top.sv"
                )
            ),
            "p3_max_hidden": 256,
            "p3_max_intermediate": 256,
            "candidate": candidate,
            "cpu_variant": cpu_variant,
            "execution": execution,
            "nano_image_sha256": (
                nano_report["sha256"] if nano_report is not None else None
            ),
            "nano_init_word_bits": 32 if nano_report is not None else None,
            "sdram_init_sha256": (
                _sha256_files(dram_init_files) if nano_report is not None else None
            ),
            "promotion_eligible": False,
            "boundary": (
                "VexRiscv/LiteDRAM/P1-P3 numerical dispatcher compiled into one "
                "Verilator SoC; no firmware command or nano token session was run"
            ),
        }
        (output_dir / "p123-build.evidence.json").write_text(
            json.dumps(build_evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if run:
        _run_bios_smoke(
            output_dir / "gateware" / "obj_dir" / "Vsim",
            evidence_path=output_dir / (
                "nano-chat-session.evidence.json"
                if nano_session and nano_report is not None
                and nano_report.get("profile") == "nano-chat-e2e" else
                "nano-session.evidence.json" if nano_session else
                "numeric-smoke.evidence.json" if numeric_smoke else
                "control-smoke.evidence.json" if control_smoke else
                "cpu-b0-directed.evidence.json" if cpu_b0 else "bios-smoke.evidence.json"
            ),
            require_control_smoke=control_smoke,
            require_numeric_smoke=numeric_smoke,
            require_nano_session=nano_session,
            require_cpu_b0=cpu_b0,
            nano_image_sha256=(nano_report["sha256"] if nano_report is not None else None),
            nano_report=nano_report,
            candidate=candidate,
            cpu_variant=cpu_variant,
            execution=execution,
            timeout_seconds=(21600 if nano_session and nano_report is not None
                             and nano_report.get("profile") == "nano-chat-e2e"
                             else 7200 if nano_session else 30),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate pins and memory budgets without LiteX")
    parser.add_argument("--build", action="store_true", help="generate BIOS/gateware and compile the Verilator SoC")
    parser.add_argument(
        "--build-p123", action="store_true",
        help="compile the LiteX SoC with the real P1/P2/P3 B0 numerical dispatcher",
    )
    parser.add_argument("--run-smoke", action="store_true", help="build and run the LiteX BIOS/SDRAM smoke simulation")
    parser.add_argument(
        "--run-control-smoke",
        action="store_true",
        help="run CPU/CSR/descriptor-DMA/response smoke for P1, P2, and P3",
    )
    parser.add_argument(
        "--run-numeric-smoke", action="store_true",
        help="run valid minimal P1/P2/P3 numerical descriptors on the unified LiteX dispatcher",
    )
    parser.add_argument(
        "--run-nano", action="store_true",
        help="run the complete P1/P2/P3-native eight-token LiteX firmware session",
    )
    parser.add_argument(
        "--run-chat", action="store_true",
        help="run the qualified variable-length P1/P2/P3 Nano-chat session",
    )
    parser.add_argument(
        "--run-cpu-b0-directed", action="store_true",
        help="run directed scalar P1/P2/P3 seams on LiteX/VexRiscv (not full B0)",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build" / "litex")
    parser.add_argument(
        "--cpu-variant", choices=("standard", "full"), default="standard",
        help="VexRiscv RV32IM variant; full enables architectural performance counters",
    )
    parser.add_argument(
        "--execution", choices=("accelerator", "scalar"), default="accelerator",
        help="run Nano P1/P2/P3 on the RTL accelerator or VexRiscv scalar C",
    )
    parser.add_argument(
        "--nano-image", type=Path,
        help="preload a deterministic nano-sdram.bin during --build-p123 or --run-numeric-smoke",
    )
    parser.add_argument(
        "--chat-image", type=Path,
        help="qualified nano-chat SDRAM image used with --run-chat",
    )
    parser.add_argument(
        "--candidate",
        choices=(
            "b0", "p1-b1-softmax-lut-pipeline",
            "p2-b1-merge-lut-pipeline", "p3-b1-synchronous-silu-pipeline",
            "p3-b1b-radix16-requant-pipeline", "p3-b1c-scale-quantize-pipeline",
            "p2-b1b-output-validation-cut", "p1-b1b-product-pipeline",
            "p2-b1c-serial-bf16-output", "p1-b1c-score-pipeline",
            "p2-b2-radix16-merge-rescale",
            "p1-b2-bf16-format-pipeline", "p2-b3-online-product-pipeline",
            "p3-b2-bf16-format-pipeline", "p2-b4-divider-finalize-cut",
            "p3-b3-requant-finalize-cut", "p2-b5-exp-input-pipeline",
            "p2-b8-online-accumulate-cut", "p1-b7-page-validate-cut",
            "p1-b8-radix8-online-product", "p1-b15-radix4-online-product",
            "p1-b16-weighted-half-cut",
            "p1-b17-divider-step-cut", "p1-b21-vector-half-product",
            "p1-b23-grouped-topk", "p1-b24-grouped-topk-antenna10",
            "p1-b25-grouped-softmax16",
            "p3-b12-output-row-base",
            "p3-b13-weight-cache", "p3-b16-down-product-cut",
            "accelerator-p1-r1-timing-foundation",
            "accelerator-p2-r1-online-arithmetic-cuts",
            "accelerator-p3-r1-down-requant-cuts",
            "accelerator-p1-a1-stream-topk-mla",
            "accelerator-p2-a1-radix16-canonical-merge",
            "accelerator-p3-a1-expert-group-empty-skip",
            "accelerator-p1-m1-shared-vector-softmax",
            "accelerator-p2-m1-dma-compute-overlap",
            "accelerator-p3-m1-weight-stationary",
            "accelerator-p1-p1-low-power-route",
            "accelerator-p2-p1-low-power-physical",
            "accelerator-p3-p1-low-power-physical",
        ),
        default="b0",
        help="select exactly one frozen B1 mechanism for a comparable nano run",
    )
    args = parser.parse_args()
    check_contract()
    if args.nano_image is not None and args.chat_image is not None:
        parser.error("--nano-image and --chat-image are mutually exclusive")
    selected_image = args.chat_image if args.chat_image is not None else args.nano_image
    if args.run_chat and args.chat_image is None:
        parser.error("--run-chat requires --chat-image")
    if args.run_nano and args.run_chat:
        parser.error("choose only one of --run-nano and --run-chat")
    if args.build or args.build_p123 or args.run_smoke or args.run_control_smoke or args.run_numeric_smoke or args.run_nano or args.run_chat or args.run_cpu_b0_directed:
        if selected_image is not None and not (args.build_p123 or args.run_numeric_smoke or args.run_nano or args.run_chat):
            parser.error("--nano-image is only valid with --build-p123, --run-numeric-smoke, or --run-nano")
        if (args.run_numeric_smoke or args.run_nano or args.run_chat) and selected_image is None:
            parser.error("--run-numeric-smoke and --run-nano require --nano-image")
        build_soc(
            output_dir=args.output_dir,
            run=args.run_smoke or args.run_control_smoke or args.run_numeric_smoke or args.run_nano or args.run_chat or args.run_cpu_b0_directed,
            control_smoke=args.run_control_smoke,
            numeric_smoke=args.run_numeric_smoke,
            nano_session=args.run_nano or args.run_chat,
            cpu_b0=args.run_cpu_b0_directed,
            numeric_accelerators=args.build_p123 or args.run_numeric_smoke or args.run_nano or args.run_chat,
            nano_image=selected_image,
            candidate=args.candidate,
            cpu_variant=args.cpu_variant,
            execution=args.execution,
        )
    elif not args.check:
        parser.error("choose --check, --build, --build-p123, --run-smoke, --run-control-smoke, --run-numeric-smoke, --run-nano, --run-chat, or --run-cpu-b0-directed")


if __name__ == "__main__":
    main()

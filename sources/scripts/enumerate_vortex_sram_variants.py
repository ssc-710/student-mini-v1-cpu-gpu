#!/usr/bin/env python3
"""Enumerate reachable parameterized Vortex ASIC SRAM instances from Yosys JSON."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess


RAM_TYPES = {"VX_dp_ram_asic", "VX_sp_ram_asic"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def integer(value: str) -> int:
    if not value or any(bit not in "01" for bit in value):
        raise ValueError(f"non-constant Yosys parameter: {value!r}")
    return int(value, 2)


def enumerate_rams(payload: dict, top: str = "Vortex") -> Counter[tuple[str, int, int, int]]:
    modules = payload.get("modules")
    if not isinstance(modules, dict) or top not in modules:
        raise ValueError(f"Yosys JSON has no top module {top!r}")
    active: set[str] = set()
    cache: dict[str, Counter[tuple[str, int, int, int]]] = {}

    def visit(module_name: str) -> Counter[tuple[str, int, int, int]]:
        if module_name in cache:
            return cache[module_name].copy()
        if module_name in active:
            raise ValueError(f"recursive module hierarchy at {module_name}")
        active.add(module_name)
        result: Counter[tuple[str, int, int, int]] = Counter()
        for cell in modules[module_name].get("cells", {}).values():
            cell_type = cell.get("type")
            if cell_type in RAM_TYPES:
                parameters = cell.get("parameters", {})
                result[(
                    cell_type,
                    integer(parameters["DATAW"]),
                    integer(parameters["SIZE"]),
                    integer(parameters["WRENW"]),
                )] += 1
            elif cell_type in modules:
                result.update(visit(cell_type))
        active.remove(module_name)
        cache[module_name] = result.copy()
        return result

    return visit(top)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--yosys-json", type=Path, required=True)
    parser.add_argument("--source-verilog", type=Path, required=True)
    parser.add_argument("--vortex-root", type=Path, required=True)
    parser.add_argument("--config", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.yosys_json.read_text(encoding="utf-8"))
    rams = enumerate_rams(payload)
    variants = []
    for (ram_type, data_width, depth, write_enable_width), count in sorted(rams.items()):
        port_kind = "dp" if ram_type == "VX_dp_ram_asic" else "sp"
        variants.append({
            "module": ram_type,
            "macro_name": f"vortex_{port_kind}_{data_width}x{depth}_w{write_enable_width}",
            "data_width": data_width,
            "depth": depth,
            "write_enable_width": write_enable_width,
            "instance_count": count,
            "bits_per_instance": data_width * depth,
            "total_bits": count * data_width * depth,
        })
    if not variants:
        raise SystemExit("no reachable Vortex ASIC SRAM instances found")
    result = {
        "schema_version": 1,
        "profile": args.profile,
        "vortex_commit": subprocess.check_output(
            ["git", "-C", str(args.vortex_root), "rev-parse", "HEAD"], text=True,
        ).strip(),
        "configs": args.config,
        "source_verilog": str(args.source_verilog.resolve()),
        "source_verilog_sha256": sha256(args.source_verilog),
        "yosys_json_sha256": sha256(args.yosys_json),
        "variant_count": len(variants),
        "instance_count": sum(item["instance_count"] for item in variants),
        "total_memory_bits": sum(item["total_bits"] for item in variants),
        "variants": variants,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

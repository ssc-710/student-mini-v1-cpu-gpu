#!/usr/bin/env python3
"""Generate deterministic, routing-grid-phase-compatible Vortex macro placement."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

try:
    from scripts.add_openram_via3_dogbones import parse_lef
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from add_openram_via3_dogbones import parse_lef  # type: ignore[no-redef]


GRID_PHASE_QUANTUM_UM = 15.64  # lcm(0.68 um M3 pitch, 0.92 um M4 pitch)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reachable_instances(payload: dict, targets: set[str], *, top: str = "Vortex",
                        prefix: str = "core") -> list[tuple[str, str]]:
    modules = payload.get("modules", {})
    if top not in modules:
        raise ValueError(f"Yosys JSON has no top module {top!r}")
    result: list[tuple[str, str]] = []
    active: set[str] = set()

    def visit(module: str, hierarchy: str) -> None:
        if module in active:
            raise ValueError(f"recursive module hierarchy at {module}")
        active.add(module)
        for name, cell in sorted(modules[module].get("cells", {}).items()):
            cell_type = cell.get("type")
            path = f"{hierarchy}.{name}" if hierarchy else name
            if cell_type in targets:
                result.append((path, cell_type))
            elif cell_type in modules:
                visit(cell_type, path)
        active.remove(module)

    visit(top, prefix)
    return result


def _ceil_grid(distance: float, quantum: float = GRID_PHASE_QUANTUM_UM) -> float:
    return math.ceil((distance - 1e-9) / quantum) * quantum


def pack(instances: list[tuple[str, str]], sizes: dict[str, tuple[float, float]], *,
         origin: tuple[float, float], limit: tuple[float, float],
         clearance_um: float = 31.28) -> list[dict]:
    """Shelf-pack R0 macros while preserving one M3/M4 origin phase."""
    x0, y0 = origin
    max_x, max_y = limit
    x, y = x0, y0
    row_height = 0.0
    placements: list[dict] = []
    for instance, macro in sorted(instances):
        if macro not in sizes:
            raise ValueError(f"missing LEF size for {macro}")
        width, height = sizes[macro]
        if x + width > max_x and x != x0:
            x = x0
            y += _ceil_grid(row_height + clearance_um)
            row_height = 0.0
        if x + width > max_x or y + height > max_y:
            raise ValueError(
                f"macro placement does not fit fixed die: {instance} at {x},{y} "
                f"size {width}x{height}, limit {max_x}x{max_y}"
            )
        placements.append({
            "instance": instance, "macro": macro,
            "x_um": round(x, 3), "y_um": round(y, 3),
            "width_um": width, "height_um": height, "orientation": "R0",
        })
        x += _ceil_grid(width + clearance_um)
        row_height = max(row_height, height)
    return placements


def render_tcl(placements: list[dict]) -> str:
    lines = [
        "# Generated hash-bound Vortex macro placement.  Do not hand-edit.",
        "# Every R0 origin shares one M3/M4 routing-grid phase for via3 dogbones.",
    ]
    for item in placements:
        lines.extend([
            "place_macro \\",
            f"  -macro_name {{{item['instance']}}} \\",
            f"  -location {{{item['x_um']:.3f} {item['y_um']:.3f}}} \\",
            "  -orientation R0 -exact",
        ])
    return "\n".join(lines) + "\n"


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elaborated-json", type=Path, required=True)
    parser.add_argument("--staged-manifest", type=Path, required=True)
    parser.add_argument("--output-tcl", type=Path, required=True)
    parser.add_argument("--output-evidence", type=Path, required=True)
    parser.add_argument("--die-width", type=float, required=True)
    parser.add_argument("--die-height", type=float, required=True)
    parser.add_argument("--margin", type=float, default=60.25)
    parser.add_argument("--origin-x", type=float, default=60.25)
    parser.add_argument("--origin-y", type=float, default=78.76)
    args = parser.parse_args()

    elaborated = json.loads(args.elaborated_json.read_text(encoding="utf-8"))
    staged = json.loads(args.staged_manifest.read_text(encoding="utf-8"))
    if staged.get("status") != "PASS":
        raise SystemExit("staged Vortex macro manifest is not PASS")
    by_name = {item["macro_name"]: item for item in staged["macros"]}
    targets = set(by_name)
    instances = reachable_instances(elaborated, targets)
    sizes = {}
    for name, record in by_name.items():
        lef_record = record["artifacts"][f"{name}.lef"]
        lef = Path(lef_record["path"])
        if not lef.is_file() or lef_record["sha256"] != sha256(lef):
            raise SystemExit(f"staged LEF binding failed: {lef}")
        sizes[name] = parse_lef(lef)[0]
    placements = pack(
        instances, sizes, origin=(args.origin_x, args.origin_y),
        limit=(args.die_width - args.margin, args.die_height - args.margin),
    )
    tcl = render_tcl(placements)
    write_atomic(args.output_tcl, tcl)
    evidence = {
        "schema_version": 1, "status": "PASS",
        "elaborated_json": str(args.elaborated_json.resolve()),
        "elaborated_json_sha256": sha256(args.elaborated_json),
        "staged_manifest": str(args.staged_manifest.resolve()),
        "staged_manifest_sha256": sha256(args.staged_manifest),
        "output_tcl": str(args.output_tcl.resolve()),
        "output_tcl_sha256": sha256(args.output_tcl),
        "macro_count": len(placements),
        "macro_origin_phase_um": [args.origin_x, args.origin_y],
        "routing_grid_phase_quantum_um": GRID_PHASE_QUANTUM_UM,
        "die_um": [args.die_width, args.die_height],
        "placements": placements,
    }
    write_atomic(args.output_evidence, json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "PASS", "macro_count": len(placements)}, indent=2))


if __name__ == "__main__":
    main()

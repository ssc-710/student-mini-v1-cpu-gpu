#!/usr/bin/env python3
"""Add collision-free, grid-aligned M3/M4 via3 dogbones to OpenRAM pins.

The native 40x16 macro exposes dense 0.38 um perimeter pins.  Enlarging them
in the tangential direction makes adjacent pins overlap, while merely growing
them inward does not create a legal via access point.  This post-process keeps
the native pin metal, adds a narrow same-layer stem to a routing-grid landing,
and mirrors the landing on the adjacent layer with a real via3 cut in GDS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


PIN_RE = re.compile(r"^(\s*)PIN\s+(\S+)\s*$")
END_PIN_RE = re.compile(r"^\s*END\s+(\S+)\s*$")
LAYER_RE = re.compile(r"^\s*LAYER\s+(\S+)\s*;\s*$")
RECT_RE = re.compile(
    r"^\s*RECT\s+(-?[0-9.]+)\s+(-?[0-9.]+)\s+"
    r"(-?[0-9.]+)\s+(-?[0-9.]+)\s*;\s*$"
)
SIZE_RE = re.compile(r"^\s*SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;\s*$")

GDS_LAYERS = {"met3": (70, 20), "met4": (71, 20), "via3": (70, 44)}
POWER_PINS = {"vccd1", "vssd1", "vdd", "gnd"}


@dataclass(frozen=True)
class Rect:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grid_points(offset: float, pitch: float, origin: float, limit: float) -> list[float]:
    """Return global routing tracks translated into macro-local coordinates."""
    first = int((origin - offset) // pitch) - 2
    last = int((origin + limit - offset) // pitch) + 2
    return [offset + index * pitch - origin for index in range(first, last + 1)
            if 0.0 < offset + index * pitch - origin < limit]


def overlaps(left: Rect, right: Rect) -> bool:
    return min(left.x2, right.x2) > max(left.x1, right.x1) and min(
        left.y2, right.y2
    ) > max(left.y1, right.y1)


def parse_lef(lef: Path) -> tuple[tuple[float, float], dict[str, list[tuple[str, Rect]]]]:
    lines = lef.read_text(encoding="utf-8").splitlines()
    size_match = next((SIZE_RE.match(line) for line in lines if SIZE_RE.match(line)), None)
    if size_match is None:
        raise ValueError("LEF is missing macro SIZE")
    pins: dict[str, list[tuple[str, Rect]]] = {}
    pin: str | None = None
    layer: str | None = None
    for line in lines:
        if match := PIN_RE.match(line):
            pin = match.group(2)
            pins.setdefault(pin, [])
        elif pin and (match := LAYER_RE.match(line)):
            layer = match.group(1)
        elif pin and layer and (match := RECT_RE.match(line)):
            pins[pin].append((layer, Rect(*(float(value) for value in match.groups()))))
        elif pin and (match := END_PIN_RE.match(line)) and match.group(1) == pin:
            pin = None
            layer = None
    return (float(size_match.group(1)), float(size_match.group(2))), pins


def _nearest_unique(value: float, points: list[float], used: set[float]) -> float:
    candidates = sorted((abs(point - value), point) for point in points if point not in used)
    if not candidates:
        raise ValueError("no unused routing track remains")
    chosen = candidates[0][1]
    used.add(chosen)
    return chosen


def _rect(cx: float, cy: float, width: float, height: float) -> Rect:
    return Rect(cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)


def build_dogbones(
    bounds: tuple[float, float],
    pins: dict[str, list[tuple[str, Rect]]],
    *,
    origin: tuple[float, float],
    met3_offset: float = 0.34,
    met3_pitch: float = 0.68,
    met4_offset: float = 0.46,
    met4_pitch: float = 0.92,
    stem_width: float = 0.14,
    clock_track_shift: int = 0,
    exclude_pin_prefixes: tuple[str, ...] = (),
) -> dict[str, dict[str, list[Rect]]]:
    """Construct one via3 dogbone for every non-power perimeter pin."""
    width, height = bounds
    x_tracks = grid_points(met4_offset, met4_pitch, origin[0], width)
    y_tracks = grid_points(met3_offset, met3_pitch, origin[1], height)
    used_x: dict[str, set[float]] = {"top": set(), "bottom": set()}
    used_y: dict[str, set[float]] = {"left": set(), "right": set()}

    # Power rings leave two narrow routing channels just inside each boundary.
    x_channels = [point for point in x_tracks if 1.95 <= point <= 3.25 or width - 3.25 <= point <= width - 1.95]
    y_channels = [point for point in y_tracks if 1.95 <= point <= 3.25 or height - 3.25 <= point <= height - 1.95]
    if not x_channels or not y_channels:
        raise ValueError("macro placement leaves no legal M3/M4 dogbone channel")

    result: dict[str, dict[str, list[Rect]]] = {}
    for pin_name, shapes in pins.items():
        if pin_name.lower() in POWER_PINS:
            continue
        if any(pin_name.startswith(prefix) for prefix in exclude_pin_prefixes):
            continue
        perimeter = next(
            (
                (layer, rect)
                for layer, rect in shapes
                if rect.x1 <= 0 or rect.x2 >= width or rect.y1 <= 0 or rect.y2 >= height
            ),
            None,
        )
        if perimeter is None:
            continue
        layer, native = perimeter
        if native.y1 <= 0 or native.y2 >= height:
            side = "bottom" if native.y1 <= 0 else "top"
            if layer != "met4":
                raise ValueError(f"{pin_name}: {side} pin must be on met4")
            preferred_x = native.cx
            if pin_name == "clk0" and clock_track_shift:
                preferred_x += clock_track_shift * met4_pitch
            landing_x = _nearest_unique(preferred_x, x_tracks, used_x[side])
            side_y = [point for point in y_channels if (point < height / 2) == (side == "bottom")]
            if pin_name == "clk0" and clock_track_shift:
                # Give the long clock escape its own horizontal lane so it
                # cannot cross the short vertical stems of adjacent data pins.
                landing_y = max(side_y) if side == "bottom" else min(side_y)
            else:
                landing_y = min(side_y, key=lambda point: abs(point - native.cy))
            vertical = Rect(
                native.cx - stem_width / 2,
                min(native.cy, landing_y),
                native.cx + stem_width / 2,
                max(native.cy, landing_y),
            )
            horizontal = Rect(
                min(native.cx, landing_x),
                landing_y - stem_width / 2,
                max(native.cx, landing_x),
                landing_y + stem_width / 2,
            )
        elif native.x1 <= 0 or native.x2 >= width:
            side = "left" if native.x1 <= 0 else "right"
            if layer != "met3":
                raise ValueError(f"{pin_name}: {side} pin must be on met3")
            side_x = [point for point in x_channels if (point < width / 2) == (side == "left")]
            landing_x = min(side_x, key=lambda point: abs(point - native.cx))
            landing_y = _nearest_unique(native.cy, y_tracks, used_y[side])
            horizontal = Rect(
                min(native.cx, landing_x),
                native.cy - stem_width / 2,
                max(native.cx, landing_x),
                native.cy + stem_width / 2,
            )
            vertical = Rect(
                landing_x - stem_width / 2,
                min(native.cy, landing_y),
                landing_x + stem_width / 2,
                max(native.cy, landing_y),
            )
        else:
            continue

        met4_landing = _rect(landing_x, landing_y, 0.33, 0.33)
        met3_landing = _rect(landing_x, landing_y, 0.38, 0.32)
        via3 = _rect(landing_x, landing_y, 0.20, 0.20)
        same_layer = (
            [vertical, horizontal, met4_landing]
            if layer == "met4"
            else [horizontal, vertical, met3_landing]
        )
        # A native pin center can already be on the selected routing track.
        # Omit that zero-length connector: the antenna polygon builder cannot
        # represent a degenerate LEF/GDS rectangle.
        same_layer = [
            rect
            for rect in same_layer
            if rect.x2 - rect.x1 >= 0.001 and rect.y2 - rect.y1 >= 0.001
        ]
        result[pin_name] = {
            layer: same_layer,
            "met3" if layer == "met4" else "met4": [met3_landing if layer == "met4" else met4_landing],
            "via3": [via3],
        }
    if not result:
        raise ValueError("no perimeter signal pins found")
    return result


def rewrite_lef(lef: Path, dogbones: dict[str, dict[str, list[Rect]]]) -> None:
    lines = lef.read_text(encoding="utf-8").splitlines()
    rendered: list[str] = []
    pin: str | None = None
    in_port = False
    for line in lines:
        if match := PIN_RE.match(line):
            pin = match.group(2)
        if pin and line.strip() == "PORT":
            in_port = True
        if pin in dogbones and in_port and line.strip() == "END":
            indent = line[: len(line) - len(line.lstrip())] + "   "
            for layer in ("met3", "met4"):
                rectangles = dogbones[pin].get(layer, [])
                if not rectangles:
                    continue
                rendered.append(f"{indent}LAYER {layer} ;")
                for rect in rectangles:
                    rendered.append(
                        f"{indent}RECT  {rect.x1:.3f} {rect.y1:.3f} {rect.x2:.3f} {rect.y2:.3f} ;"
                    )
            in_port = False
        rendered.append(line)
        if pin and (match := END_PIN_RE.match(line)) and match.group(1) == pin:
            pin = None
            in_port = False
    temporary = lef.with_suffix(lef.suffix + ".tmp")
    temporary.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    temporary.replace(lef)


def rewrite_gds(gds: Path, dogbones: dict[str, dict[str, list[Rect]]], compiler: Path) -> None:
    sys.path.insert(0, str(compiler.parent))
    sys.path.insert(0, str(compiler))
    os.environ.setdefault("OPENRAM_HOME", str(compiler))
    from common import make_openram_package  # type: ignore[import-not-found]

    make_openram_package()
    from openram.gdsMill import gdsMill  # type: ignore[import-not-found]

    layout = gdsMill.VlsiLayout()
    gdsMill.Gds2reader(layout).loadFromFile(str(gds))
    for shapes in dogbones.values():
        for layer_name, rectangles in shapes.items():
            layer, purpose = GDS_LAYERS[layer_name]
            for rect in rectangles:
                layout.addBox(
                    layerNumber=layer,
                    purposeNumber=purpose,
                    offsetInMicrons=(rect.x1, rect.y1),
                    width=rect.x2 - rect.x1,
                    height=rect.y2 - rect.y1,
                )
    temporary = gds.with_suffix(gds.suffix + ".tmp")
    gdsMill.Gds2writer(layout).writeToFile(str(temporary))
    temporary.replace(gds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lef", type=Path, required=True)
    parser.add_argument("--gds", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--macro-origin-x", type=float, required=True)
    parser.add_argument("--macro-origin-y", type=float, required=True)
    parser.add_argument("--clock-track-shift", type=int, default=0)
    args = parser.parse_args()

    before = {"lef": sha256(args.lef), "gds": sha256(args.gds)}
    bounds, pins = parse_lef(args.lef)
    dogbones = build_dogbones(
        bounds,
        pins,
        origin=(args.macro_origin_x, args.macro_origin_y),
        clock_track_shift=args.clock_track_shift,
    )
    rewrite_lef(args.lef, dogbones)
    rewrite_gds(args.gds, dogbones, args.compiler)
    packet = {
        "schema_version": 1,
        "rule": "collision-free-track-aligned-via3-dogbone",
        "macro_origin_um": [args.macro_origin_x, args.macro_origin_y],
        "clock_track_shift": args.clock_track_shift,
        "modified_pins": len(dogbones),
        "via3_count": sum(len(shapes["via3"]) for shapes in dogbones.values()),
        "via3_geometry_um": {
            "cut": [0.20, 0.20],
            "met3_landing": [0.38, 0.32],
            "met4_landing": [0.33, 0.33],
        },
        "before_sha256": before,
        "after_sha256": {"lef": sha256(args.lef), "gds": sha256(args.gds)},
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n")
    print(json.dumps(packet, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

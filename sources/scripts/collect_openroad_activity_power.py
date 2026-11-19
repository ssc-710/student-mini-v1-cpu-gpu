#!/usr/bin/env python3
"""Build a hash-bound 100 MHz power report from raw OpenROAD output.

This collector deliberately does not estimate missing activity.  Coverage is
derived from OpenROAD's ``report_activity_annotation`` counters and power is
derived from the ``Total`` row emitted by ``report_power -format json``.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re


_ACTIVITY_LINE = re.compile(r"^\s*(vcd|saif|input|unannotated)\s+(\d+)\s*$", re.I)
_VCD_TIMESTAMP = re.compile(r"^#(\d+)\s*$", re.M)
_VCD_TIMESCALE = re.compile(
    r"\$timescale\s+(\d+)\s*(s|ms|us|ns|ps|fs)\s+\$end", re.I | re.S
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_vcd_text(path: Path) -> str:
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="strict") as stream:
            return stream.read()
    return path.read_text(encoding="utf-8")


def validate_vcd_window(path: Path, begin_ns: int, end_ns: int) -> None:
    if begin_ns < 0 or end_ns <= begin_ns:
        raise ValueError("VCD activity window must be positive")
    text = read_vcd_text(path)
    match = _VCD_TIMESCALE.search(text)
    if match is None or (int(match.group(1)), match.group(2).lower()) != (1, "ns"):
        raise ValueError("VCD must use an exact 1 ns timescale")
    timestamps = [int(value) for value in _VCD_TIMESTAMP.findall(text)]
    if not timestamps:
        raise ValueError("VCD contains no timestamps")
    if end_ns > max(timestamps):
        raise ValueError("VCD activity window exceeds the recorded trace")


def parse_activity_annotation(text: str, activity_format: str) -> tuple[int, int, float]:
    counts: dict[str, int] = {}
    for line in text.splitlines():
        match = _ACTIVITY_LINE.match(line)
        if match:
            key = match.group(1).lower()
            if key in counts:
                raise ValueError(f"duplicate OpenROAD activity counter: {key}")
            counts[key] = int(match.group(2))
    if "unannotated" not in counts:
        raise ValueError("OpenROAD activity report lacks unannotated count")
    expected = activity_format.lower()
    annotated = counts.get(expected, 0)
    unexpected = sum(
        value for key, value in counts.items()
        if key not in {expected, "unannotated"}
    )
    if unexpected:
        raise ValueError("activity report mixes VCD/SAIF/manual activity origins")
    total = annotated + counts["unannotated"]
    if annotated <= 0 or total <= 0:
        raise ValueError("OpenROAD annotated no activity pins")
    return annotated, total, 100.0 * annotated / total


def parse_power_json(path: Path) -> tuple[float, float, float]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("Total"), dict):
        raise ValueError("OpenROAD power JSON lacks Total row")
    total_row = raw["Total"]
    try:
        internal_w = float(total_row["internal"])
        switching_w = float(total_row["switching"])
        leakage_w = float(total_row["leakage"])
        reported_w = float(total_row["total"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("OpenROAD Total power row is incomplete") from exc
    values = (internal_w, switching_w, leakage_w, reported_w)
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("OpenROAD power values must be finite and non-negative")
    calculated_w = internal_w + switching_w + leakage_w
    if calculated_w <= 0 or internal_w + switching_w <= 0:
        raise ValueError("OpenROAD power report lacks positive dynamic power")
    # OpenROAD aggregates the category rows and the Total row through
    # different floating-point reduction paths.  Even with 15 printed digits
    # a real report can differ by a few parts in 1e8.  Keep a bounded numeric
    # tolerance while still rejecting any materially inconsistent report.
    if not math.isclose(reported_w, calculated_w, rel_tol=1e-6, abs_tol=1e-12):
        raise ValueError("OpenROAD Total power is inconsistent with its components")
    dynamic_mw = (internal_w + switching_w) * 1000.0
    leakage_mw = leakage_w * 1000.0
    return dynamic_mw, leakage_mw, dynamic_mw + leakage_mw


def validate_activity_manifest_inputs(manifest: dict, netlist: Path) -> None:
    records = manifest.get("inputs")
    if not isinstance(records, list) or not records:
        raise ValueError("gate activity manifest lacks simulator inputs")
    netlist_resolved = netlist.resolve()
    netlist_bound = False
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ValueError("gate activity manifest has an invalid input record")
        path = Path(record["path"]).resolve()
        if not path.is_file():
            raise ValueError(f"gate activity input is missing: {path}")
        if record.get("sha256") != sha256(path) or record.get("bytes") != path.stat().st_size:
            raise ValueError(f"gate activity input binding changed: {path}")
        netlist_bound |= path == netlist_resolved
    if not netlist_bound:
        raise ValueError("gate activity manifest does not bind the routed netlist")
    for tool in ("iverilog", "vvp"):
        raw_path = manifest.get(tool)
        expected = manifest.get(f"{tool}_sha256")
        if not isinstance(raw_path, str) or not isinstance(expected, str):
            raise ValueError(f"gate activity manifest lacks {tool} binding")
        path = Path(raw_path).resolve()
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"gate activity {tool} binding changed")


def collect(
    *, activity: Path, activity_format: str, activity_scope: str,
    activity_start_ns: int, activity_end_ns: int,
    annotation_report: Path, raw_power_json: Path, netlist: Path,
    toolchain: Path, route_evidence: Path, activity_manifest: Path, output: Path,
) -> dict[str, object]:
    activity_format = activity_format.upper()
    if activity_format != "VCD":
        raise ValueError("collector currently requires windowed VCD activity")
    for path in (
        activity, annotation_report, raw_power_json, netlist,
        toolchain, route_evidence, activity_manifest,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not activity_scope:
        raise ValueError("activity scope must not be empty")
    manifest = json.loads(activity_manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("gate activity manifest is not an object")
    for field, expected in (
        ("schema_version", 1), ("kind", "gate-activity"),
        ("status", "PASS"), ("clock_hz", 100_000_000),
        ("activity_sha256", sha256(activity)),
    ):
        if manifest.get(field) != expected:
            raise ValueError(f"gate activity manifest {field} does not match")
    normalization = manifest.get("timescale_normalization")
    if (not isinstance(normalization, dict) or
            normalization.get("output_timescale") != "1ns"):
        raise ValueError("gate activity manifest lacks lossless 1 ns normalization")
    validate_activity_manifest_inputs(manifest, netlist)
    validate_vcd_window(activity, activity_start_ns, activity_end_ns)
    annotated, total_pins, coverage = parse_activity_annotation(
        annotation_report.read_text(encoding="utf-8"), activity_format
    )
    if coverage < 95.0:
        raise ValueError(f"OpenROAD activity coverage is below 95 percent: {coverage:.6f}")
    dynamic_mw, leakage_mw, total_mw = parse_power_json(raw_power_json)
    result: dict[str, object] = {
        "clock_period_ns": 10.0,
        "clock_hz": 100_000_000,
        "activity_format": activity_format,
        "activity_scope": activity_scope,
        "activity_start_ns": activity_start_ns,
        "activity_end_ns": activity_end_ns,
        "activity_annotated_pins": annotated,
        "activity_total_pins": total_pins,
        "activity_coverage_percent": coverage,
        "activity_sha256": sha256(activity),
        "activity_manifest_sha256": sha256(activity_manifest),
        "netlist_sha256": sha256(netlist),
        "toolchain_sha256": sha256(toolchain),
        "route_evidence_sha256": sha256(route_evidence),
        "annotation_report_sha256": sha256(annotation_report),
        "raw_power_json_sha256": sha256(raw_power_json),
        "dynamic_mw": dynamic_mw,
        "leakage_mw": leakage_mw,
        "total_mw": total_mw,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activity", type=Path, required=True)
    parser.add_argument("--activity-format", choices=("VCD",), default="VCD")
    parser.add_argument("--activity-scope", required=True)
    parser.add_argument("--activity-start-ns", type=int, required=True)
    parser.add_argument("--activity-end-ns", type=int, required=True)
    parser.add_argument("--annotation-report", type=Path, required=True)
    parser.add_argument("--raw-power-json", type=Path, required=True)
    parser.add_argument("--netlist", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--route-evidence", type=Path, required=True)
    parser.add_argument("--activity-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    result = collect(**vars(parser.parse_args()))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

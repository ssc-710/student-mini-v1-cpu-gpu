#!/usr/bin/env python3
"""Replace Vortex ASIC RAM blackboxes with exact frozen OpenRAM bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


RAM_MODULES = ("VX_sp_ram_asic", "VX_dp_ram_asic")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_module(source: str, name: str, replacement: str) -> str:
    match = re.search(
        rf"(?m)^(?:\(\*[^\n]*\*\)\s*)?module\s+{re.escape(name)}\b",
        source,
    )
    if match is None:
        raise ValueError(f"source does not define {name}")
    end = re.search(r"(?m)^endmodule\s*$", source[match.start():])
    if end is None:
        raise ValueError(f"unterminated module {name}")
    stop = match.start() + end.end()
    if re.search(
        rf"(?m)^(?:\(\*[^\n]*\*\)\s*)?module\s+{re.escape(name)}\b",
        source[stop:],
    ):
        raise ValueError(f"source defines {name} more than once")
    return source[:match.start()] + replacement.rstrip() + "\n" + source[stop:]


def render_instance(item: dict, *, dual_address: bool) -> str:
    name = item["macro_name"]
    condition = (
        f"DATAW == {item['data_width']} && SIZE == {item['depth']} && "
        f"WRENW == {item['write_enable_width']}"
    )
    write_address = "waddr" if dual_address else "addr"
    read_address = "raddr" if dual_address else "addr"
    mask = "\n        .wmask0(wren)," if item["write_enable_width"] != 1 else ""
    return f"""    if ({condition}) begin : g_{name}
      {name} u_macro (
        .clk0(clk), .csb0(~(write && |wren)),{mask}
        .addr0({write_address}), .din0(wdata),
        .clk1(clk), .csb1(~read), .addr1({read_address}), .dout1(macro_rdata)
      );
    end else"""


def render_binding(module: str, variants: list[dict]) -> str:
    dual_address = module == "VX_dp_ram_asic"
    addresses = (
        "    input wire [ADDRW-1:0]   waddr,\n"
        "    input wire [DATAW-1:0]   wdata,\n"
        "    input wire [ADDRW-1:0]   raddr,"
        if dual_address else
        "    input wire [ADDRW-1:0]   addr,\n"
        "    input wire [DATAW-1:0]   wdata,"
    )
    branches = "\n".join(render_instance(item, dual_address=dual_address) for item in variants)
    return f"""// Generated from a hash-bound Vortex SRAM plan.  Do not hand-edit.
module {module} #(
    parameter DATAW = 1,
    parameter SIZE  = 1,
    parameter WRENW = 1,
    parameter ADDRW = $clog2(SIZE)
) (
    input wire               clk,
    input wire               reset,
    input wire               read,
    input wire               write,
    input wire [WRENW-1:0]   wren,
{addresses}
    output wire [DATAW-1:0]  rdata
);
  wire [DATAW-1:0] macro_rdata;
  reg read_seen_q;

  always @(posedge clk) begin
    if (reset) read_seen_q <= 1'b0;
    else if (read) read_seen_q <= 1'b1;
  end
  assign rdata = (reset || !read_seen_q) ? {{DATAW{{1'b0}}}} : macro_rdata;

  generate
{branches} begin : g_unsupported_shape
      // The hierarchy enumerator rejects this branch before physical build.
      assign macro_rdata = {{DATAW{{1'bx}}}};
    end
  endgenerate
endmodule
"""


def render_blackbox(item: dict) -> str:
    width, depth, wren = item["data_width"], item["depth"], item["write_enable_width"]
    addrw = (depth - 1).bit_length()
    mask_decl = f"  input wire [{wren - 1}:0] wmask0,\n" if wren != 1 else ""
    return f"""(* blackbox *)
module {item['macro_name']} (
  input wire clk0,
  input wire csb0,
{mask_decl}  input wire [{addrw - 1}:0] addr0,
  input wire [{width - 1}:0] din0,
  input wire clk1,
  input wire csb1,
  input wire [{addrw - 1}:0] addr1,
  output wire [{width - 1}:0] dout1
);
endmodule
"""


def generate(plan: dict, source: str) -> tuple[str, str, str]:
    variants = plan.get("variants", [])
    by_module = {module: [] for module in RAM_MODULES}
    for item in variants:
        if item.get("module") not in by_module:
            raise ValueError(f"unsupported RAM module {item.get('module')!r}")
        if item.get("port_topology") != "1r1w":
            raise ValueError(f"macro {item['macro_name']} is not 1r1w")
        by_module[item["module"]].append(item)
    bindings = "\n".join(render_binding(module, by_module[module]) for module in RAM_MODULES)
    transformed = source
    for module in RAM_MODULES:
        if not by_module[module]:
            raise ValueError(f"plan has no variants for {module}")
        transformed = replace_module(transformed, module, render_binding(module, by_module[module]))
    # Logical wide shapes may be implemented by synthesizable bank wrappers.
    # They must participate in the VX_* shape dispatch, but declaring them as
    # physical blackboxes would hide the constituent audited OpenRAM macros.
    physical_variants = [item for item in variants if item.get("physical_macro", True)]
    blackboxes = "\n".join(render_blackbox(item) for item in physical_variants)
    return transformed, blackboxes, bindings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-source", type=Path, required=True)
    parser.add_argument("--output-blackboxes", type=Path, required=True)
    parser.add_argument("--output-bindings", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    transformed, blackboxes, bindings = generate(plan, args.source.read_text(encoding="utf-8"))
    args.output_source.parent.mkdir(parents=True, exist_ok=True)
    args.output_blackboxes.parent.mkdir(parents=True, exist_ok=True)
    args.output_bindings.parent.mkdir(parents=True, exist_ok=True)
    args.output_source.write_text(transformed, encoding="utf-8")
    args.output_blackboxes.write_text(blackboxes, encoding="utf-8")
    args.output_bindings.write_text(bindings, encoding="utf-8")
    result = {
        "schema_version": 1,
        "plan_sha256": sha256(args.plan),
        "source_sha256": sha256(args.source),
        "output_source": str(args.output_source.resolve()),
        "output_source_sha256": sha256(args.output_source),
        "output_blackboxes": str(args.output_blackboxes.resolve()),
        "output_blackboxes_sha256": sha256(args.output_blackboxes),
        "output_bindings": str(args.output_bindings.resolve()),
        "output_bindings_sha256": sha256(args.output_bindings),
        "logical_shape_count": len(plan["variants"]),
        "macro_count": sum(
            item.get("physical_macro", True) for item in plan["variants"]
        ),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

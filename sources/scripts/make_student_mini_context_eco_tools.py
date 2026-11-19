"""Derive the context post-route ECO tools from the unchanged platform runner and its ECO scripts.

The GPU's first full-chip sign-off (2026-10-14) showed that the quadrant blocks' post-route ECO had aimed at the
partition budgets, not at the chip: rst_ni reaches block UL ~0.85 ns later than its budget assumed.  The fix is a
post-route ECO of the block against its real chip surroundings (integration/student-mini/gpu_block_context.tcl).
The runner and the ECO scripts are bound by passing guarded runs (CPU top, GPU blocks), so they stay byte-identical;
this script writes the context variants next to them by mechanical, asserted substitutions:

  scripts/run_student_mini_platform_physical_ctx.py  = run_student_mini_platform_physical.py + --eco-context SDC
      (bound as an ECO input, passed as STUDENT_MINI_ECO_CONTEXT, recorded as eco_context; ECO scripts = *_ctx.tcl)
  integration/student-mini/post_route_eco_ctx.tcl     = post_route_eco.tcl    + the context overlay after eco_chip_io
  integration/student-mini/post_route_timing_ctx.tcl  = post_route_timing.tcl + the context overlay after eco_chip_io

usage: python3 scripts/make_student_mini_context_eco_tools.py   (re-running it reproduces the same bytes)
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISM = ROOT / 'integration/student-mini'


def derive(src, dst, edits):
    text = src.read_bytes().decode()
    for old, new in edits:
        if text.count(old) != 1:
            raise SystemExit(f'{src.name}: expected exactly one {old[:60]!r}, found {text.count(old)}')
        text = text.replace(old, new)
    dst.write_bytes(text.encode())
    print(f'{dst.relative_to(ROOT)} <- {src.relative_to(ROOT)} ({len(edits)} edits)')


OVERLAY = ('# chip timing context of the block (gpu_block_context.tcl): replaces the budgets of its ports by the chip\n'
           '# arrival / required times and models the chip clock edge at clk_i (run_student_mini_platform_physical_ctx.py)\n'
           'if {[info exists env(STUDENT_MINI_ECO_CONTEXT)] && $env(STUDENT_MINI_ECO_CONTEXT) ne ""} {\n'
           '  read_sdc $env(STUDENT_MINI_ECO_CONTEXT)\n'
           '  puts "STUDENT_MINI_ECO_CONTEXT $env(STUDENT_MINI_ECO_CONTEXT)"\n'
           '}\n')
CHIP_IO = 'if {[info exists env(STUDENT_MINI_ECO_CHIP_IO)] && $env(STUDENT_MINI_ECO_CHIP_IO)} {\n' \
          '  source [file join [file dirname [info script]] eco_chip_io.tcl]\n}\n'

derive(ISM / 'post_route_eco.tcl', ISM / 'post_route_eco_ctx.tcl', [
    ('# Post-route setup ECO of a routed', '# Context variant of post_route_eco.tcl (scripts/make_student_mini_context_eco_tools.py): '
                                         'the chip timing context\n# (STUDENT_MINI_ECO_CONTEXT) is read after the chip-I/O overlay.\n'
                                         '# Post-route setup ECO of a routed'),
    (CHIP_IO, CHIP_IO + OVERLAY)])
derive(ISM / 'post_route_timing.tcl', ISM / 'post_route_timing_ctx.tcl', [
    (CHIP_IO, CHIP_IO + OVERLAY)])
derive(ROOT / 'scripts/run_student_mini_platform_physical.py', ROOT / 'scripts/run_student_mini_platform_physical_ctx.py', [
    ('"""Complete ORFS implementation', '"""Context variant (scripts/make_student_mini_context_eco_tools.py): --eco-context SDC runs the post-route ECO\n'
            'and its pass timing against the block\'s chip timing context (gpu_block_context.tcl) with post_route_eco_ctx.tcl /\n'
            'post_route_timing_ctx.tcl; otherwise identical to run_student_mini_platform_physical.py.\n\n'
            'Complete ORFS implementation'),
    ("    result = dict(status='HOLD', platform=args.platform, bindings=bindings,",
     "    result = dict(status='HOLD', platform=args.platform, eco_context=str(args.eco_context.resolve()) if args.eco_context else None,\n"
     "                  bindings=bindings,"),
    ("               STUDENT_MINI_ECO_CHIP_IO='1' if args.platform == 'gpu-block' else '0')",
     "               STUDENT_MINI_ECO_CHIP_IO='1' if args.platform == 'gpu-block' else '0',\n"
     "               STUDENT_MINI_ECO_CONTEXT=str(args.eco_context.resolve()) if args.eco_context else '')"),
    # the context runner is derived from the base runner by this script: both are bound as its own sources (an ECO may
    # continue a run made by an earlier, freeze-amended base runner)
    ("    audit_scripts = [Path(__file__), ROOT / 'scripts/audit_student_mini_route.py',",
     "    audit_scripts = [Path(__file__), ROOT / 'scripts/run_student_mini_platform_physical.py',\n"
     "                     ROOT / 'scripts/make_student_mini_context_eco_tools.py', ROOT / 'scripts/audit_student_mini_route.py',"),
    ("tool('post_route_timing.tcl',", "tool('post_route_timing_ctx.tcl',"),
    ("tool('post_route_eco.tcl',", "tool('post_route_eco_ctx.tcl',"),
    ("    parser.add_argument('--eco-passes', type=int, default=3)\n",
     "    parser.add_argument('--eco-passes', type=int, default=3)\n"
     "    parser.add_argument('--eco-context', type=Path,\n"
     "                        help='chip timing context SDC of a GPU quadrant block (gpu_block_context.tcl) for the post-route ECO')\n"),
    ("        'post_route_eco.tcl', 'post_route_timing.tcl', 'rc_calibrated.tcl', 'useful_skew_eco.tcl', 'eco_chip_io.tcl')] \\\n"
     "        if args.eco_from or args.post_route_eco else []\n",
     "        'post_route_eco_ctx.tcl', 'post_route_timing_ctx.tcl', 'rc_calibrated.tcl', 'useful_skew_eco.tcl', 'eco_chip_io.tcl')] \\\n"
     "        if args.eco_from or args.post_route_eco else []\n"
     "    if args.eco_context:\n"
     "        if not eco_scripts:\n"
     "            raise ValueError('--eco-context needs --eco-from or --post-route-eco')\n"
     "        eco_scripts.append(args.eco_context.resolve())\n"),
])

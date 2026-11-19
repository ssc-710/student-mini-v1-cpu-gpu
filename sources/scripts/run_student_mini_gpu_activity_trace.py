"""GPU port-activity traces for gate-level power (same mapped RTL, same kernel, same inputs).

The whole-platform GPU RTL producer (run_student_mini_gpu_platform_rtl.py) is
reused verbatim except for three derivation seams:
  * the simulation bridge is tests/rtl/student_mini_gpu_fault_bridge_trace.sv,
    which must equal the bound bridge plus an observation-only recorder of the
    DUT ports (checked here, line endings normalised);
  * the rtlsim model calls final() before teardown so the recorder closes its
    trace with the last simulated cycle, and initialises every register and
    memory to zero (VERILATOR_RESET_VALUE 0, as the gate-level replay does)
    instead of seeded random values, so both can be compared bit for bit;
  * one counter class (0) per case and a separate work root.
Each executed case leaves runs/<ordinal>-c0/port-trace.txt next to its
transcript; the gate-level replay compares every recorded output cycle.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha

ORIGINAL = ROOT / 'scripts/run_student_mini_gpu_platform_rtl.py'
BRIDGE = ROOT / 'tests/rtl/student_mini_gpu_fault_bridge.sv'
TRACED = ROOT / 'tests/rtl/student_mini_gpu_fault_bridge_trace.sv'
RECORDER_MARK = '  // ---- Port-activity recorder (gate-level power stimulus; observation only) ----\n'


def checked_bridge():
    original = BRIDGE.read_text().replace('\r\n', '\n').rstrip()
    traced = TRACED.read_text().replace('\r\n', '\n')
    if not original.endswith('endmodule'):
        raise ValueError('bridge layout changed')
    prefix = original[:-len('endmodule')]
    if not traced.startswith(prefix + RECORDER_MARK) or not traced.rstrip().endswith('endmodule'):
        raise ValueError('traced bridge is not the bound bridge plus the recorder')
    recorder = traced[len(prefix):]
    if 'dut' in recorder.replace('(gate-level', '') or 'assign ' in recorder:
        raise ValueError('recorder must not drive or reach into the design')
    return recorder


def derive(source):
    changes = {
        "'tests/rtl/student_mini_gpu_fault_bridge.sv'": "'tests/rtl/student_mini_gpu_fault_bridge_trace.sv'",
        "CLASSES = (0, 4, 7)": "CLASSES = (0,)",
        "ROOT / 'build/student-mini/gpu-platform-rtl' / key": "ROOT / 'build/student-mini/gpu-activity-rtl' / key",
        "    (private / 'processor.cpp').write_text(processor)\n":
            "    if processor.count('    delete device_;\\n') != 1:\n        raise ValueError('rtlsim teardown seam changed')\n"
            "    if processor.count('#define VERILATOR_RESET_VALUE 2') != 1:\n        raise ValueError('rtlsim reset-value seam changed')\n"
            "    processor = processor.replace('#define VERILATOR_RESET_VALUE 2', '#define VERILATOR_RESET_VALUE 0')\n"
            "    (private / 'processor.cpp').write_text(processor.replace('    delete device_;\\n', '    device_->final();\\n    delete device_;\\n'))\n",
        "    paths = [Path(__file__), ": "    paths = [Path(__file__), ROOT / 'scripts/run_student_mini_gpu_activity_trace.py', ROOT / 'tests/rtl/student_mini_gpu_fault_bridge.sv', ",
        'ROOT = Path(__file__).resolve().parents[1]': 'ROOT = Path(' + repr(str(ROOT)) + ')',
    }
    for old, new in changes.items():
        if source.count(old) != 1:
            raise ValueError('GPU platform producer seam changed: ' + old.strip()[:60])
        source = source.replace(old, new)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('build', 'run'))
    parser.add_argument('rest', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    checked_bridge()
    producer = ROOT / 'build/student-mini/gpu-activity-rtl/producers' / (sha(ORIGINAL)[:16] + '-' + sha(Path(__file__))[:16] + '.py')
    producer.parent.mkdir(parents=True, exist_ok=True)
    text = derive(ORIGINAL.read_text())
    if producer.exists() and producer.read_text() != text:
        raise ValueError('existing derived producer differs')
    producer.write_text(text)
    return subprocess.call([sys.executable, str(producer), args.phase, *args.rest], cwd=ROOT)


if __name__ == '__main__':
    raise SystemExit(main())

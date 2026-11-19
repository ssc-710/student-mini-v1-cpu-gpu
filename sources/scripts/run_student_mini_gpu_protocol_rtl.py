"""GPU protocol qualification (MINI-31 backpressure, MINI-32 response hold, MINI-33 reset recovery).

The whole-platform GPU RTL producer (run_student_mini_gpu_platform_rtl.py) is
reused with these derivation seams only:
  * bridge tests/rtl/student_mini_gpu_protocol_bridge.sv (same DUT, packing and
    fault decode; seeded memory-handshake stalls, host-response hold, command
    FIFO, stability checks, protocol counters);
  * host model patches of scripts/student_mini_gpu_protocol_sources.py
    (protocol parameters, DCR log, reset during the first launch + reissue,
    counters reported through DPI) and OpenRAM models without the simultaneous
    access $display (it corrupts the heap during process teardown);
  * every executed case receives its own frozen protocol parameters
    (STUDENT_MINI_PROTOCOL) and its record keeps the parsed protocol events;
  * a separate work root.  build / run subcommands as in the producer.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_gpu_protocol_sources import protocol_env

ORIGINAL = ROOT / 'scripts/run_student_mini_gpu_platform_rtl.py'
PROTOCOL_CASES = ('MINI-31', 'MINI-32', 'MINI-33')


def derive(source, protocol):
    changes = {
        "'tests/rtl/student_mini_gpu_fault_bridge.sv'": "'tests/rtl/student_mini_gpu_protocol_bridge.sv'",
        "    processor = status_processor(": "    processor = __import__('scripts.student_mini_gpu_protocol_sources', fromlist=['x']).protocol_processor(status_processor(",
        "(SOURCE / 'sim/rtlsim/processor.cpp').read_text())))\n": "(SOURCE / 'sim/rtlsim/processor.cpp').read_text()))))\n",
        "ROOT / 'build/student-mini/gpu-platform-rtl' / key": "ROOT / 'build/student-mini/gpu-protocol-rtl' / key",
        "        output.write_text(quiet_macro(model.read_text()))\n":
            "        output.write_text(__import__('scripts.student_mini_gpu_protocol_sources', fromlist=['x']).silent_macro(quiet_macro(model.read_text())))\n",
        "    paths = [Path(__file__), ": "    paths = [Path(__file__), ROOT / 'scripts/run_student_mini_gpu_protocol_rtl.py', "
                                     "ROOT / 'scripts/student_mini_gpu_protocol_sources.py', ",
        "dict(env, VORTEX_PROFILING=str(cls)))": "dict(env, VORTEX_PROFILING=str(cls), STUDENT_MINI_PROTOCOL=PROTOCOL.get(str(ordinal), '0,0,0,0')))",
        "    record.write_text(json.dumps(value) + '\\n')\n":
            "    value['protocol_parameters'] = PROTOCOL.get(str(ordinal), '0,0,0,0')\n"
            "    value['protocol'] = __import__('scripts.student_mini_gpu_protocol_sources', fromlist=['x']).protocol_events(text)\n"
            "    record.write_text(json.dumps(value) + '\\n')\n",
        'ROOT = Path(__file__).resolve().parents[1]': 'ROOT = Path(' + repr(str(ROOT)) + ')\nPROTOCOL = json.loads(' + repr(json.dumps(protocol, sort_keys=True)) + ')',
    }
    for old, new in changes.items():
        if source.count(old) != 1:
            raise ValueError('GPU platform producer seam changed: ' + old.strip()[:60])
        source = source.replace(old, new)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vectors', type=Path, required=True)
    parser.add_argument('phase', choices=('build', 'run', 'ordinals'))
    parser.add_argument('rest', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    vectors = [json.loads(line) for line in args.vectors.read_text().splitlines()]
    protocol = {str(i): protocol_env(v) for i, v in enumerate(vectors) if v['case']['id'].split('-', 1)[1] in PROTOCOL_CASES}
    if args.phase == 'ordinals':
        print(' '.join(sorted(protocol, key=int)))
        return 0
    text = derive(ORIGINAL.read_text(), protocol)
    producer = ROOT / 'build/student-mini/gpu-protocol-rtl/producers' / (hashlib_hex(text)[:32] + '.py')
    producer.parent.mkdir(parents=True, exist_ok=True)
    if not producer.exists():
        producer.write_text(text)
    elif producer.read_text() != text:
        raise ValueError('derived producer differs')
    return subprocess.call([sys.executable, str(producer), args.phase, *args.rest], cwd=ROOT)


def hashlib_hex(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


if __name__ == '__main__':
    raise SystemExit(main())

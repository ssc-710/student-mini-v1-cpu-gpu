"""Observe actual role-specific tools; preserve conflicting historical locks."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha


def command(args):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=30)
    if result.returncode: raise ValueError('version/source probe failed: '+str(args[0]))
    return result.stdout.strip()


def collect():
    cad = Path('/home/soclab/tools/oss-cad-suite/bin')
    entries = [
        ('CPU / accelerator RTL', Path('/home/soclab/tools/verilator-5.040/bin/verilator'), ['--version'], 'https://github.com/verilator/verilator', 'LGPL-3.0-only OR Artistic-2.0'),
        ('GPU RTLSIM / source export', Path('/mnt/d/open-soc-ai-labs-vortex-tools/verilator/bin/verilator'), ['--version'], 'https://github.com/verilator/verilator', 'LGPL-3.0-only OR Artistic-2.0'),
        ('Synthesis / formal', cad/'yosys', ['-V'], 'https://github.com/YosysHQ/yosys', 'ISC'),
        ('Post-route gate simulation', cad/'iverilog', ['-V'], 'https://github.com/steveicarus/iverilog', 'GPL-2.0-or-later'),
        ('Gate simulation runtime', cad/'vvp', ['-V'], 'https://github.com/steveicarus/iverilog', 'GPL-2.0-or-later'),
        ('Bounded formal orchestration', cad/'sby', ['--version'], 'https://github.com/YosysHQ/sby', 'ISC'),
        ('Bounded formal solver', cad/'boolector', ['--version'], 'https://github.com/Boolector/boolector', 'MIT'),
        ('Placement / route / STA / power', Path('/home/soclab/.local/bin/openroad'), ['-version'], 'https://github.com/The-OpenROAD-Project/OpenROAD', 'BSD-3-Clause'),
    ]
    rows, bindings = [], {}
    for role, executable, args, homepage, license_id in entries:
        result = subprocess.run([str(executable), *args], capture_output=True, text=True, timeout=30)
        if result.returncode: raise ValueError('tool version probe failed: '+str(executable))
        version = (result.stdout.strip() or result.stderr.strip()).splitlines()[0]
        files = [executable.resolve()]
        if executable.name == 'verilator': files.append(executable.parent/'verilator_bin')
        records = []
        for path in files:
            digest = sha(path)
            bindings[str(path)] = digest
            records.append(dict(name=path.name, sha256=digest, installed_bytes=path.stat().st_size))
        rows.append(dict(role=role, name=executable.name, version=version, homepage=homepage,
            upstream_license=license_id, binaries=records, source_commit_verified=False,
            download_archive_verified=False, runtime_qualification='See workload-specific evidence; inventory alone is not PASS'))
    source = Path('/home/soclab/src/verilator-v5.040')
    revision = command(['git', '-C', source, 'rev-parse', 'HEAD'])
    if command(['git', '-C', source, 'status', '--porcelain', '--untracked-files=no']):
        raise ValueError('CPU/accelerator Verilator source tree is dirty')
    built, installed = source/'bin/verilator_bin', Path('/home/soclab/tools/verilator-5.040/bin/verilator_bin')
    if sha(built) != sha(installed): raise ValueError('installed Verilator differs from source build')
    bindings[str(built)] = sha(built)
    rows[0].update(source_commit=revision, source_commit_verified=True,
        source_url='https://github.com/verilator/verilator/tree/'+revision,
        resolution='Actual clean checkout and identical built/installed executable select this commit; conflicting legacy lock is historical only')
    for path in (ROOT/'integration/litex/toolchain.lock.json', ROOT/'third_party/sources.lock.json', Path(__file__)):
        bindings[str(path)] = sha(path)
    return dict(schema='student-mini-tool-roles-v1', status='OBSERVED_NOT_RELEASE_QUALIFIED',
        captured_at=datetime.now(timezone.utc).isoformat(), bindings=bindings, tools=rows,
        limitations=['This captures current files, not retroactive toolchain proof for older runs.',
            'Installed binary bytes are not total installation space; transitive libraries and source archives remain separately required.',
            'GPU RTLSIM uses a different Verilator version; never replace it with the CPU tool merely to reconcile a global lock.',
            'License labels describe upstream projects; bundled/transitive license notices require separate review.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle: json.dump(result, handle, indent=2)
    print(json.dumps(dict(path=str(args.output), sha256=sha(args.output), status=result['status'])))


if __name__ == '__main__': main()

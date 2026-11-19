"""Read-only installed dependency inventory. Does not certify mini workloads."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1048576),b''):h.update(block)
    return h.hexdigest()


def command(args):
    try:
        run=subprocess.run(args,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=15)
        return dict(exit_code=run.returncode,output=run.stdout.strip())
    except (OSError,subprocess.TimeoutExpired) as exc:return dict(exit_code=None,error=str(exc))


def collect():
    packages=[]
    for distribution in sorted(metadata.distributions(),key=lambda d:d.metadata.get('Name','').lower()):
        record=next((f for f in distribution.files or [] if str(f).endswith('.dist-info/RECORD')),None)
        packages.append(dict(name=distribution.metadata.get('Name'),version=distribution.version,
                             dependencies=distribution.requires or [],license=distribution.metadata.get('License-Expression') or distribution.metadata.get('License'),
                             official_urls=distribution.metadata.get_all('Project-URL') or [],
                             installed_record_sha256=digest(Path(distribution.locate_file(record))) if record else None))
    tools=[]
    commands=[('python3',['--version']),('git',['--version']),('gcc',['--version']),('g++',['--version']),('make',['--version']),('cmake',['--version']),('ninja',['--version']),('meson',['--version']),('verilator',['--version']),('yosys',['-V']),('openroad',['-version']),('sby',['--version']),('boolector',['--version']),('riscv64-unknown-elf-gcc',['--version'])]
    for name,args in commands:
        binary=shutil.which(name)
        tools.append(dict(name=name,available=bool(binary),sha256=digest(Path(binary).resolve()) if binary else None,
                          version=command([binary,*args]) if binary else None))
    payload=dict(schema_version=1,status='INVENTORY_ONLY',mini_qualified=False,created_at=datetime.now(timezone.utc).isoformat(),
                 system=platform.system(),machine=platform.machine(),python_version=platform.python_version(),
                 available_cpus=len(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else os.cpu_count(),
                 python_dependencies=packages,tools=tools,
                 system_dependencies=command(['dpkg-query','-W','-f=${Package}\t${Version}\t${Installed-Size}\n']) if platform.system()=='Linux' else None,
                 notes=['Installed RECORD hash is not a wheel/archive SHA.','Host inventory is not a 2-vCPU/8-GiB workload qualification.','Dependencies not present in this interpreter may exist in isolated tool prefixes; no automatic PASS.'])
    return payload


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    data=collect();args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as handle:json.dump(data,handle,ensure_ascii=False,indent=2)
    print(json.dumps(dict(path=str(args.output),status=data['status'],python_packages=len(data['python_dependencies']),tools=len(data['tools']))))

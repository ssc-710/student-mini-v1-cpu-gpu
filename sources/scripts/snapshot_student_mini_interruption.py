"""Inventory only known incomplete task directories before recoverable moves."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import os

ROOT=Path(__file__).resolve().parents[1]
TARGETS=[
 'cpu-macro-mapping/cdba074583e9a1f93910b00ed72a1a1d30f34a6634b7e7baf98a2229ee7dccee',
 'cpu-boundary-replay/cbf0834b5e3b275c7a23d3ac21241297e6022d33f1dfc2ec6788ad6c122e0c26',
 'cpu-synthesis/e19f8b53ae16766239e37ceb5dc5314b156b56ac584c18efcc9c41d99dab59b8',
 'gpu-cut-boundary/6fd4beb872550610a7193e28b1e1e254c8f3f3591167d0fd4e3d51972da0a718',
 'gpu-cut-mapping-continuation/08535765b00c3050644bf75090aeaf7f4a38ba6f807b5b3044d44ef82a09910c',
 'gpu-cut-synthesis/358a950c18ca35d6b050c8c003230162bfe174b8a1912126649b3c3fd1813263',
 'native-nano/876398eac822028468e275044f350988a847429d5c3a2f3aed2be1e74ca47572',
 'pdk-audit/ff6b1918a5a78cd7a044899ec5f3c471440e3da71ffb550eaf38b4eb3bb47fb4',
 'gpu-counters/6c93c0aa4d6ea2ebbfcb505793deb581ec67bc25de83d937f969a72b80b584d3/cases-500-100',
]


def main():
    output=ROOT/'grading/evidence/student-mini-v1/interventions/host-reboot-20261008T011814-wsl-inventory'
    rows=[]
    for name in TARGETS:
        path=ROOT/'build/student-mini'/name
        if path.is_symlink() or not path.is_dir() or any((path/file).exists() for file in ('completion.json','audit.json','candidate.json')):
            raise ValueError('not a known incomplete task: '+name)
        destination=path.with_name(path.name+'.interrupted-20261008T011814')
        if destination.exists():raise FileExistsError(destination)
        files={}
        for item in path.rglob('*'):
            if item.is_symlink():continue
            if item.is_file():
                raw=item.read_bytes();files[item.relative_to(path).as_posix()]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        rows.append(dict(source=path.relative_to(ROOT).as_posix(),destination=destination.relative_to(ROOT).as_posix(),files=files))
    result=dict(status='INCOMPLETE_TASKS_INTERRUPTED_NOT_PASS',observed_windows_last_boot='2026-10-08T09:18:14+08:00',
        created_at=datetime.now(timezone.utc).isoformat(),reason='Host reboot; prior Linux processes and cgroups are gone',
        lost_resource_peaks_reconstructed=False,completed_evidence_modified=False,planned_recoverable_moves=rows)
    output.mkdir(parents=True,exist_ok=False)
    (output/'snapshot.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(path=str(output/'snapshot.json'),directories=len(rows))))


if __name__=='__main__':main()

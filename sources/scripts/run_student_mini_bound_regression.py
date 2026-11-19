"""Record a full Linux regression and verify that its source snapshot stayed fixed."""
from datetime import datetime,timezone
import importlib.metadata
import json
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_checkpoint_sources import snapshot,changes
from scripts.retry_student_mini_route import execute_locked_route


def junit_counts(path):
    root=ET.parse(path).getroot()
    cases=list(root.iter('testcase'))
    if not cases:raise ValueError('empty regression cannot pass')
    result={key:0 for key in ('passed','failed','errors','skipped')}
    for case in cases:
        key='failed' if case.find('failure') is not None else 'errors' if case.find('error') is not None else 'skipped' if case.find('skipped') is not None else 'passed'
        result[key]+=1
    return result


def sources():
    result=snapshot(ROOT)
    for name in ('docs/first-class/p1_p4_progress_server.py','docs/first-class/teacher/deepseek-v32-inference-map.html','docs/first-class/deepseek-v32-inference-map.html'):
        result[name]=sha(ROOT/name)
    return result


def main():
    import fcntl
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    work=ROOT/'grading/evidence/student-mini-v1/full-regressions'/stamp;work.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    heartbeat('WAITING_FOR_SERIAL_QUEUE');print(json.dumps(dict(work=str(work))),flush=True)
    with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        before=sources();(work/'sources-before.json').write_text(json.dumps(before,sort_keys=True,indent=2)+'\n')
        execution_started=time.monotonic()
        command=[sys.executable,'-m','pytest','-q','--junitxml='+str(work/'junit.xml')]
        code=execute_locked_route(command,work/'pytest.log',1800,lambda _:heartbeat('FULL_PYTEST_RUNNING'))
        after=sources();(work/'sources-after.json').write_text(json.dumps(after,sort_keys=True,indent=2)+'\n')
        changed=changes(before,after)
        counts=junit_counts(work/'junit.xml') if (work/'junit.xml').is_file() else None
        passed=code==0 and counts is not None and not counts['failed'] and not counts['errors'] and not changed
        versions={}
        for name in ('pytest','numpy','ml-dtypes','torch','cocotb','cocotb-test','jsonschema'):
            try:versions[name]=importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:versions[name]=None
        report=dict(status='SOURCE_BOUND_REGRESSION_PASS' if passed else 'HOLD',formal_baseline=False,release_complete=False,
            command=command,exit_code=code,counts=counts,changed_sources=changed,python_version=sys.version,
            dependency_versions=versions,python_sha256=sha(Path(sys.executable).resolve()),
            elapsed_seconds=time.monotonic()-started,execution_seconds=time.monotonic()-execution_started,
            artifacts={p.name:sha(p) for p in work.iterdir() if p.is_file() and p.name!='heartbeat.json'})
        heartbeat(report['status']);(work/'completion.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=report['status'],counts=counts,changed_source_count=len(changed))),flush=True)
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())

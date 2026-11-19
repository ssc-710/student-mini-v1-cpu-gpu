"""Qualify the isolated CPU-only teacher environment, then train its candidate."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha

def teacher_environment():
    return dict(os.environ, PYTHONPATH=os.pathsep.join((str(ROOT), str(ROOT/'shared/python'))),
                CUDA_VISIBLE_DEVICES='', HIP_VISIBLE_DEVICES='', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2')


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment', type=Path, required=True)
    parser.add_argument('--pip-pid', type=int, required=True)
    parser.add_argument('--attempt-dir', type=Path)
    args = parser.parse_args()
    environment = args.environment.resolve()
    if not environment.is_relative_to((ROOT/'build/student-mini').resolve()):
        raise ValueError('teacher environment must stay inside task build area')
    attempt = args.attempt_dir.resolve() if args.attempt_dir else environment
    if not attempt.is_relative_to((ROOT/'build/student-mini').resolve()):
        raise ValueError('qualification attempt must stay inside task build area')
    if args.attempt_dir:
        attempt.mkdir(parents=True, exist_ok=False)
    output = attempt/'qualification.json'
    if output.exists():
        raise ValueError('never replace a qualification record')
    python = environment/'bin/python'
    started = time.monotonic()
    report = dict(status='HOLD', teacher_training_environment_only=True,
                  target_execution=False, software_in_student_package=False, checks=[])
    def heartbeat(stage):
        (attempt/'qualification-heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-started), indent=2)+'\n')
    def run(name, command, timeout=300):
        heartbeat(name)
        with (attempt/(name+'.log')).open('x') as log:
            child = subprocess.run(command, cwd=ROOT, env=teacher_environment(), stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        report['checks'].append(dict(name=name, exit_code=child.returncode,
            log=name+'.log', sha256=sha(attempt/(name+'.log'))))
        if child.returncode:
            raise RuntimeError(name+' failed')
    try:
        process = Path('/proc')/str(args.pip_pid)
        while process.exists():
            command = (process/'cmdline').read_bytes().replace(b'\0', b' ')
            if b'pip install torch==2.9.1+cpu' not in command:
                raise ValueError('waiting PID no longer identifies the requested teacher installation')
            if time.monotonic()-started > 5400:
                raise TimeoutError('teacher CPU wheel download exceeded bounded wait')
            heartbeat('WAITING_FOR_CPU_ONLY_TORCH_INSTALL')
            time.sleep(10)
        torch_report = environment/'torch-install-report.json'
        payload = json.loads(torch_report.read_text())
        locks = ROOT/'build/student-mini/python-lock-20261007'
        baseline = json.loads((locks/'python-lock.json').read_text())
        artifacts = {}
        for row in baseline['packages']:
            path = locks/'downloaded-artifacts'/row['filename']
            if sha(path) != row['sha256']:
                raise ValueError('Python dependency archive changed')
            artifacts[row['name']] = path
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE')
            fcntl.flock(lock, fcntl.LOCK_EX)
            run('bootstrap', [str(python), '-m', 'pip', 'install', '--no-index', '--no-deps',
                *[str(artifacts[name]) for name in ('pip', 'setuptools', 'wheel')]])
            run('numerical-stack', [str(python), '-m', 'pip', 'install', '--no-index', '--no-build-isolation',
                '--find-links', str(locks/'downloaded-artifacts'), '--require-hashes', '-r', str(locks/'requirements-hashed.txt')])
            run('pip-check', [str(python), '-m', 'pip', 'check'])
            run('cpu-only', [str(python), '-c', "import torch; assert torch.__version__=='2.9.1+cpu'; assert torch.version.cuda is None; assert not torch.cuda.is_available(); print(torch.__version__)"])
            run('native-regression', [str(python), '-m', 'pytest', 'tests/test_student_mini_nano_native.py', 'tests/test_nano_chat_runtime.py', '-q'])
            inventory = subprocess.check_output([str(python), '-m', 'pip', 'list', '--format=json'], text=True)
            installed = json.loads(inventory)
            normalize = lambda name: name.lower().replace('_', '-').replace('.', '-')
            available = {(normalize(row['name']), row['version']): row for row in baseline['packages']}
            for row in payload['install']:
                metadata, download = row['metadata'], row['download_info']
                digest = download['archive_info']['hashes']['sha256']
                available[(normalize(metadata['name']), metadata['version'])] = dict(name=metadata['name'],
                    version=metadata['version'], download_url=download['url'], sha256=digest,
                    license=metadata.get('license_expression') or metadata.get('license'),
                    requires_dist=metadata.get('requires_dist', []))
            selected = []
            for row in installed:
                key = (normalize(row['name']), row['version'])
                if key not in available:
                    raise ValueError('installed dependency has no verified archive source: '+str(key))
                selected.append(available[key])
            lock_data = dict(status='CPU_TEACHER_ENVIRONMENT_VERIFIED', packages=selected,
                python_executable_sha256=sha(python), pip_check_passed=True, entity_gpu_required=False,
                torch_install_report_sha256=sha(torch_report), numerical_lock_sha256=sha(locks/'python-lock.json'))
            (environment/'teacher-lock.json').write_text(json.dumps(lock_data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            report.update(environment_qualified=True, teacher_lock_sha256=sha(environment/'teacher-lock.json'))
            run('native-training', [str(python), str(ROOT/'scripts/train_student_mini_native_nano.py')], timeout=2700)
            candidate = json.loads((attempt/'native-training.log').read_text().splitlines()[-1])
            report.update(status='PASS', training_candidate=candidate,
                reason='CPU-only teacher environment and candidate generation verified, not platform Nano acceptance')
    except Exception as error:
        report['reason'] = f'{type(error).__name__}: {error}'
    report['elapsed_seconds'] = time.monotonic()-started
    report['installed_bytes'] = sum(p.stat().st_size for p in environment.rglob('*') if p.is_file())
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(path=str(output), status=report['status'], reason=report['reason'])), flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())

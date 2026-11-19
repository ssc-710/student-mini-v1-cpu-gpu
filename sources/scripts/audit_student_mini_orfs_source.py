"""Read-only provenance of the executed ORFS flow and SKY130HD source export.

Unused tool gitlinks are declared, not substituted for the explicitly selected
OpenROAD and OSS CAD binaries. No active flow script or PDK file is modified.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.audit_student_mini_openroad_source import parse_tree, blob_identity, symlink_content, export_classification

COMMIT = 'aabf2a397059704f68ddafe7e2c8bd1a0e7c65f5'


def relevant(name):
    return name in ('flow/Makefile', 'flow/variables.yaml') or name.startswith(
        ('flow/scripts/', 'flow/util/', 'flow/platforms/sky130hd/'))


def lfs_matches(pointer, payload):
    match = re.fullmatch(rb'version https://git-lfs.github.com/spec/v1\noid sha256:([0-9a-f]{64})\nsize ([0-9]+)\n', pointer)
    return bool(match and hashlib.sha256(payload).hexdigest() == match[1].decode() and len(payload) == int(match[2]))


def classify_export(original, actual):
    if b'\r\n' not in original and b'\n' in original and original.replace(b'\n', b'\r\n') == actual:
        return 'MATCH_DECLARED_LF_TO_CRLF_EXPORT'
    return export_classification(original, actual)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    work = args.output_dir.resolve(); work.mkdir(parents=True, exist_ok=False)
    repository = ROOT/'third_party/src/openroad-flow-scripts'
    source = Path('/home/soclab/src/orfs-clean-aabf2a')
    entries = parse_tree(subprocess.check_output(['git', '-C', str(repository), 'ls-tree', '-rz', '--full-tree', COMMIT], timeout=60))
    rows = []
    for entry in entries:
        if not relevant(entry['path']): continue
        if entry['kind'] != 'blob': raise ValueError('unexpected flow submodule')
        path = source/entry['path']; row = dict(entry)
        if entry['mode'] == '120000':
            if not path.is_symlink(): row['status']='MISSING_SYMLINK'; rows.append(row); continue
            content = symlink_content(path)
        elif path.is_file() and not path.is_symlink(): content = path.read_bytes()
        else: row['status']='MISSING_FILE'; rows.append(row); continue
        row.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest(), status='MATCH')
        if blob_identity(content) != entry['git_blob_or_commit']:
            original = subprocess.check_output(['git', '-C', str(repository), 'cat-file', 'blob', entry['git_blob_or_commit']], timeout=30)
            row['status'] = 'MATCH_PINNED_LFS_OBJECT' if lfs_matches(original, content) else classify_export(original, content)
        rows.append(row)
    if not rows or not any(row['path']=='flow/Makefile' for row in rows): raise ValueError('empty/incomplete flow inventory')
    differences = [row for row in rows if row['status'] not in ('MATCH', 'MATCH_PINNED_LFS_OBJECT', 'MATCH_DECLARED_CRLF_TO_LF_EXPORT', 'MATCH_DECLARED_LF_TO_CRLF_EXPORT')]
    # Check that every currently executed, previously bound flow file is covered.
    physical = ROOT/'build/student-mini/physical/67a898cb10bc0bb084b627a5e0fc3b923ab7296c4dcfd221c8f0db92193ac1bc/inputs.json'
    prior = json.loads(physical.read_text()); indexed={row['path']:row for row in rows}
    prior_rows=[]
    for name, value in prior['files'].items():
        path = Path(name)
        if not path.is_relative_to(source): continue
        relative=path.relative_to(source).as_posix()
        row=indexed.get(relative)
        if row is None or row.get('sha256') != value or sha(path) != value:
            raise ValueError('previously bound flow input not matched: '+relative)
        prior_rows.append(dict(path=relative, sha256=value))
    if not prior_rows: raise ValueError('no executed flow source bound')
    report = dict(schema='student-mini-orfs-source-v1',
        status='ORFS_EXECUTED_SOURCE_STAGE_PASS' if not differences else 'HOLD_ORFS_SOURCE_DIFFERS',
        created_at=datetime.now(timezone.utc).isoformat(), source_commit=COMMIT,
        source_url='https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/tree/'+COMMIT,
        files=rows, differences=differences, prior_bound_files=prior_rows,
        declared_export_transforms=[row for row in rows if row['status'].startswith('MATCH_DECLARED_')],
        declared_tool_gitlinks=[row for row in entries if row['kind']=='commit'],
        complete_student_environment=False, scope='Executed flow and SKY130HD source only; actual tool binary provenance is audited separately',
        bindings={str(path):sha(path) for path in (Path(__file__), physical, ROOT/'scripts/audit_student_mini_openroad_source.py')})
    output=work/'audit.json'; output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(path=str(output), sha256=sha(output), status=report['status'],
        files=len(rows), prior_bound_files=len(prior_rows), differences=len(differences))), flush=True)
    return 0 if not differences else 2


if __name__ == '__main__': raise SystemExit(main())

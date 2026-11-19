"""Detect source changes during a control-plane regression, including new tests."""
import hashlib
from pathlib import Path

FOLDERS = ('scripts', 'tests', 'shared', 'integration', 'software', 'rtl', 'ppa',
           'docs/first-class/src', 'grading/student-mini')
SUFFIXES = frozenset(('.py', '.js', '.mjs', '.c', '.cc', '.cpp', '.h', '.hpp', '.sv',
                      '.v', '.tcl', '.mk', '.toml', '.json', '.html', '.css', '.sdc',
                      '.yaml', '.yml', '.sh', '.ps1', '.svh', '.vh', '.mem', '.cu', '.sby'))


def snapshot(root):
    root=Path(root); paths=set()
    for folder in FOLDERS:
        directory=root/folder
        if not directory.is_dir():continue
        paths.update(p for p in directory.rglob('*') if p.is_file() and not p.is_symlink()
                     and (p.suffix in SUFFIXES or p.name=='Makefile')
                     and not any(part in ('.git','__pycache__','.pytest_cache','node_modules','.venv') for part in p.parts))
    paths.update(root/name for name in ('pyproject.toml','pytest.ini','setup.cfg','conftest.py') if (root/name).is_file())
    result={}
    for path in sorted(paths):
        with path.open('rb') as source:
            result[path.relative_to(root).as_posix()]=hashlib.file_digest(source,'sha256').hexdigest()
    return result


def changes(before,after):
    return sorted(name for name in before.keys()|after.keys() if before.get(name)!=after.get(name))

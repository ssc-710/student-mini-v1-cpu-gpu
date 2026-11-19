"""Deterministic whitelist ZIP transport, not a baseline/release verifier.

Callers must qualify every experiment separately. A transport PASS only proves
that these exact explicitly listed files survived packaging; it never supplies
missing physical, protocol, Nano, dependency or resource evidence.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

ROLES = frozenset(('source', 'spec', 'input', 'result', 'model', 'tool-lock',
                   'physical', 'html', 'asset', 'instructions', 'license'))
RESERVED = 'PACKAGE-MANIFEST.json'
FORBIDDEN_PARTS = frozenset(('.git', '.venv', 'venv', 'node_modules', '__pycache__',
                             '.pytest_cache', 'site-packages', 'optimizer-state'))


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024), b''):
            value.update(chunk)
    return value.hexdigest()


def relative_name(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('portable relative POSIX path required')
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or str(path) != value:
        raise ValueError('noncanonical package path')
    for part in path.parts:
        if (part in ('.', '..') or part.rstrip(' .') != part
            or any(ord(c) < 32 for c in part) or any(c in '<>"|?*' for c in part)
            or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?', part, re.I)):
            raise ValueError('unsafe package path component')
    return value


def allowed_content(name):
    parts = PurePosixPath(name).parts
    if any(part.casefold() in FORBIDDEN_PARTS for part in parts):
        raise ValueError('environment/cache/history directories are not deliverables')
    if name.lower().endswith(('.docx', '.whl', '.deb', '.rpm', '.msi', '.exe', '.iso',
                              '.zip', '.tar', '.tar.gz', '.tar.xz', '.tar.zst', '.pyc', '.o')):
        raise ValueError('installer, software archive, cache or DOCX excluded')


def inventory(root, rows):
    root = Path(root).resolve(strict=True)
    if not isinstance(rows, list) or not rows:
        raise ValueError('nonempty explicit whitelist required')
    names = {RESERVED.casefold()}
    output = []
    for row in rows:
        if set(row) != {'source', 'path', 'role', 'sha256'} or row['role'] not in ROLES:
            raise ValueError('exact whitelist fields and known role required')
        source = relative_name(row['source']); name = relative_name(row['path'])
        allowed_content(name); allowed_content(source)
        if name.casefold() in names:
            raise ValueError('duplicate, case-colliding or reserved ZIP member')
        names.add(name.casefold())
        path = root
        for part in PurePosixPath(source).parts:
            path = path/part
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                raise ValueError('source links are not portable package files')
        if not path.resolve(strict=True).is_relative_to(root) or not path.is_file():
            raise ValueError('source must be a regular file inside the declared root')
        if not re.fullmatch('[0-9a-f]{64}', row['sha256']) or digest(path) != row['sha256']:
            raise ValueError('whitelisted source hash differs')
        output.append(dict(row, bytes=path.stat().st_size))
    # On Windows a file cannot simultaneously be the parent directory of another.
    folded = {RESERVED.casefold(), *(row['path'].casefold() for row in output)}
    for row in output:
        if any(str(parent).casefold() in folded for parent in PurePosixPath(row['path']).parents):
            raise ValueError('file/directory path collision')
    return sorted(output, key=lambda row: row['path'])


def checked_limit(value):
    if type(value) is not int or value <= 0:
        raise ValueError('positive byte limit required')
    return value


def verify_archive(path, expected, manifest_bytes):
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if sorted(names) != sorted([RESERVED] + [r['path'] for r in expected]):
            raise ValueError('ZIP entries differ from the exact whitelist')
        if archive.read(RESERVED) != manifest_bytes:
            raise ValueError('archive manifest differs')
        for row in expected:
            info = archive.getinfo(row['path'])
            if info.file_size != row['bytes']:
                raise ValueError('ZIP expanded size differs')
            value = hashlib.sha256()
            with archive.open(info) as source:
                for chunk in iter(lambda: source.read(1024*1024), b''):
                    value.update(chunk)
            if value.hexdigest() != row['sha256']:
                raise ValueError('ZIP content hash differs')
    return sum(info.file_size for info in infos)


def create_archive(root, rows, output, *, route, compressed_limit=1024**3, expanded_limit=3*1024**3):
    """Transport only. Never call this to replace unmet whole-release gates."""
    if route not in ('A', 'B'):
        raise ValueError('explicit student route required')
    compressed_limit = checked_limit(compressed_limit); expanded_limit = checked_limit(expanded_limit)
    root = Path(root).resolve(strict=True); output = Path(output)
    pending = output.with_name(output.name + '.incomplete')
    if output.exists() or pending.exists():
        raise FileExistsError('preserve previous archive; use a new destination')
    checked = inventory(root, rows)
    manifest = dict(schema='student-mini-whitelist-transport-v1', route=route,
                    release_qualified=False, files=[{k: v for k, v in r.items() if k != 'source'} for r in checked])
    data = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode()
    if sum(row['bytes'] for row in checked)+len(data) > expanded_limit:
        raise ValueError('expanded package exceeds frozen limit')
    def info(name):
        item = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        item.compress_type = zipfile.ZIP_DEFLATED; item.create_system = 3
        item.external_attr = 0o100644 << 16
        return item
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(pending, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(info(RESERVED), data)
        for row in checked:
            with (root/row['source']).open('rb') as source, archive.open(info(row['path']), 'w', force_zip64=True) as destination:
                for chunk in iter(lambda: source.read(1024*1024), b''):
                    destination.write(chunk)
    expanded = verify_archive(pending, checked, data)
    inventory(root, rows)  # detect source changes during packaging
    if pending.stat().st_size > compressed_limit:
        raise ValueError('compressed package exceeds limit; incomplete artifact retained')
    # Hard-link creation is exclusive on both Windows and Linux; do not replace
    # a destination that another process created while compression was running.
    output.hardlink_to(pending)
    pending.unlink()  # only our completed transport's extra directory entry
    return dict(status='WHITELIST_TRANSPORT_PASS', release_qualified=False,
                route=route, sha256=digest(output), compressed_bytes=output.stat().st_size,
                expanded_bytes=expanded, file_count=len(checked), manifest=manifest)

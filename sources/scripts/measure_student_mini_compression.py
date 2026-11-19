"""Measure lossless file compression without publishing an incomplete ZIP."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import zlib


def measure_file(path):
    before = path.stat(); digest = hashlib.sha256(); compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
    expanded = compressed = 0
    with path.open('rb') as handle:
        while block := handle.read(1024*1024):
            expanded += len(block); digest.update(block); compressed += len(compressor.compress(block))
    compressed += len(compressor.flush())
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or expanded != before.st_size:
        raise ValueError('source changed during compression measurement')
    return dict(bytes=expanded, deflate_bytes=compressed, sha256=digest.hexdigest())


def measure_tree(root):
    root = root.resolve(); rows = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink(): raise ValueError('symlink not accepted in size probe')
        if path.is_file(): rows.append(dict(path=path.relative_to(root).as_posix(), **measure_file(path)))
    if not rows: raise ValueError('empty component')
    return dict(status='COMPONENT_COMPRESSION_MEASURED', release_complete=False, archives_created=0,
        scope='Exact DEFLATE payload size only; ZIP headers, other components, package manifest and final package verification excluded',
        files=rows, expanded_bytes=sum(r['bytes'] for r in rows), deflate_payload_bytes=sum(r['deflate_bytes'] for r in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.root.resolve()): raise ValueError('probe output must not enter measured tree')
    if args.output.exists(): raise FileExistsError('preserve earlier measurement')
    started = time.monotonic(); report = measure_tree(args.root)
    report.update(created_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-started,
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle: json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('status', 'release_complete', 'archives_created', 'expanded_bytes', 'deflate_payload_bytes', 'elapsed_seconds')}), flush=True)


if __name__ == '__main__': main()

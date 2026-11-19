"""List the repository source files the student-mini evidence chain is bound to (package whitelist).

Starting from the release plan, every JSON evidence file is read and every
string naming an existing file under the repository is collected; bound JSON
files under build/ or grading/ are followed transitively.  Output: repo-relative
source files outside build/ and grading/evidence/ (code, RTL, configs, firmware,
docs needed to rerun), plus the model/tokenizer files of the Nano candidate.
Third-party trees (Vortex/LiteX/OpenROAD installs) live outside the repository
and are covered by third_party/sources.lock.json instead.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIN = 'C:/Users/admin/Downloads/open-soc-ai-labs'


def repo_path(text):
    if not isinstance(text, str) or len(text) > 600 or '\n' in text:
        return None
    candidate = text.replace('\\', '/')
    for prefix in (str(ROOT) + '/', WIN + '/'):
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix):]
            break
    else:
        if candidate.startswith('/'):
            return None
    path = ROOT / candidate
    try:
        return path if path.is_file() else None
    except OSError:
        return None


def strings(value, top=True):
    """Declared inputs only: keys of every `bindings` mapping, plus top-level string values of the plan."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k == 'bindings' and isinstance(v, dict):
                yield from v.keys()
            elif top and isinstance(v, str):
                yield v
            else:
                yield from strings(v, top)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v, top)
    elif isinstance(value, str) and top:
        yield value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--max-json', type=int, default=4000)
    args = parser.parse_args()
    seen_json, files = set(), set()
    queue = [args.plan.resolve()]
    while queue and len(seen_json) < args.max_json:
        path = queue.pop()
        if path in seen_json:
            continue
        seen_json.add(path)
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        for text in strings(value, top=path == args.plan.resolve()):
            found = repo_path(text)
            if found is None:
                continue
            files.add(found)
            if found.suffix == '.json' and found.stat().st_size < 5_000_000:
                queue.append(found)
    rel = sorted(p.relative_to(ROOT).as_posix() for p in files)
    sources = [r for r in rel if not r.startswith(('build/', 'grading/evidence/', '.git/'))]
    extras = ['third_party/sources.lock.json', 'scripts/install_and_run_p1_p4.sh', 'scripts/student_mini_resource_guard.py',
              'tools/gatesim/gatesim.cpp', 'task.md']
    sources = sorted(set(sources) | {e for e in extras if (ROOT / e).is_file()})
    args.out.write_text('\n'.join(sources) + '\n')
    size = sum((ROOT / s).stat().st_size for s in sources)
    print(json.dumps(dict(json_followed=len(seen_json), files=len(rel), sources=len(sources), source_bytes=size)))


if __name__ == '__main__':
    main()

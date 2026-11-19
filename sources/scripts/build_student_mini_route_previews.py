"""Build route-scoped offline HTML previews, explicitly not released packages."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_inference_map_editions import assemble, INDEX
from scripts.student_mini import sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    index = json.loads(INDEX.read_text(encoding='utf-8'))
    records = []
    for route in ('A', 'B'):
        folder = output/route; folder.mkdir()
        page = folder/'deepseek-v32-inference-map.html'
        page.write_text(assemble(teacher=True, idx=index, package_route=route), encoding='utf-8')
        records.append(dict(route=route, path=page.relative_to(output).as_posix(),
                            bytes=page.stat().st_size, sha256=sha(page)))
    receipt = dict(status='OFFLINE_ROUTE_PREVIEWS_ONLY', release_qualified=False,
                   required_execution_and_physical_payload_included=False, pages=records,
                   page_evidence_sha256=sha(ROOT/'grading/student-mini/page-evidence.json'))
    (output/'preview-manifest.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(dict(output=str(output), **receipt)))


if __name__ == '__main__':
    main()

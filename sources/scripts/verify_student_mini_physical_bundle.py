"""Offline verification of an accelerator mini physical bundle.

The trusted profile SHA is supplied out of band (the teacher release manifest).
Passing this check is not a whole-platform baseline, Nano, or release PASS.
Historical absolute source paths are provenance only: none are opened here.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.validate_student_mini_physical import bound_file, sha
from scripts.audit_student_mini_route import check_metrics
from scripts.audit_student_mini_pdk import lef_blocks, compare_geometry, components
from scripts.assemble_student_mini_physical import validate_power_join
from scripts.run_student_mini_sourcebound_power import parse_worst_slack, validate_samples
from scripts.collect_openroad_activity_power import parse_power_json, parse_activity_annotation, validate_vcd_window
from scripts.run_student_mini_p3_activity import check_transcript
from scripts.run_student_mini_attention_activity import check_transcript as check_attention


def read(path):
    return path.read_text(encoding='utf-8')


def load(path):
    return json.loads(read(path))


def inventory(root, profile):
    """Check the full allowlist, not just a few selected artifacts."""
    records = profile.get('package_files')
    if not isinstance(records, dict) or not records:
        raise ValueError('missing package allowlist')
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('symlink in physical package')
        if path.is_file() and path != root/'profile.json':
            actual.add(path.relative_to(root).as_posix())
    if actual != set(records):
        raise ValueError('package file inventory differs')
    for name, record in records.items():
        path = bound_file(root, dict(record, path=name))
        if type(record.get('bytes')) is not int or path.stat().st_size != record['bytes']:
            raise ValueError('artifact byte count differs')


def verify(profile_path, expected_sha256):
    profile_path = Path(profile_path).resolve()
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256 or '') or sha(profile_path) != expected_sha256:
        raise ValueError('trusted profile SHA missing or mismatched')
    root = profile_path.parent
    if profile_path.name != 'profile.json':
        raise ValueError('canonical profile filename required')
    profile = load(profile_path)
    if (profile.get('schema'), profile.get('platform'), profile.get('profile'), profile.get('process')) != (
            'student-mini-physical-v2', 'accelerator', 'mini', 'sky130hd'):
        raise ValueError('wrong schema, platform, profile or process')
    if profile.get('physical_evidence_complete') is not True or profile.get('formal_baseline') is not False:
        raise ValueError('wrong physical/baseline semantics')
    if profile.get('clock_period_ns') != 10 or profile.get('frequency_hz') != 100000000:
        raise ValueError('100 MHz required')
    inventory(root, profile)
    artifacts = {key: bound_file(root, row) for key, row in profile['artifacts'].items()}
    required = {'def', 'netlist', 'sdc', 'spef', 'odb', 'detailed_metrics', 'finish_metrics', 'route_log'}
    if set(artifacts) != required:
        raise ValueError('physical artifact set incomplete')
    metrics = check_metrics(load(artifacts['detailed_metrics']), load(artifacts['finish_metrics']), read(artifacts['sdc']))
    if metrics != profile['route_metrics']:
        raise ValueError('route summary differs from raw reports')
    source = load(root/'lineage/0-inputs.json')
    route = load(root/'lineage/2-completion.json')
    activity = load(root/'lineage/3-completion.json')
    power = load(root/'lineage/4-completion.json')
    pdk = load(root/'lineage/5-audit.json')
    workload = load(root/'lineage/6-manifest.json')
    if route.get('exit_code') != 0 or route.get('source_freshness_verified') is not True:
        raise ValueError('route source qualification absent')
    if power.get('power_complete') is not True or pdk.get('status') != 'PDK_GEOMETRY_STAGE_PASS':
        raise ValueError('incomplete raw signoff')
    # Join historical identities using digests; never use a developer path as a
    # local file dependency in the student archive.
    for key in required:
        if sha(artifacts[key]) not in route['artifacts'].values():
            raise ValueError('artifact not bound to route')
    for key in ('def', 'odb'):
        if sha(artifacts[key]) not in pdk['bindings'].values():
            raise ValueError('PDK replay belongs to another route')
    if sha(artifacts['netlist']) not in activity['bindings'].values():
        raise ValueError('activity netlist not bound')
    if sha(root/'lineage/3-completion.json') not in power['bindings'].values():
        raise ValueError('power/activity provenance differs')
    operator = profile['operator']
    tops = {'p1': 'p1_b2_bf16_pipeline_litex_top', 'p2': 'p2_student_mini_top', 'p3': 'p3_b12_output_row_base_litex_top'}
    if operator not in tops or source['design']['top'] != tops[operator] or workload['operator'] != operator:
        raise ValueError('operator/hardware mismatch')
    boundary = {}
    for name, row in profile['rtl_sources'].items():
        path = bound_file(root, row)
        if sha(path) not in source['files'].values():
            raise ValueError('RTL not bound to physical inputs')
        boundary[name] = sha(path)
    if not set(source['design']['sources']).issubset(boundary):
        raise ValueError('RTL closure incomplete')
    hardware = hashlib.sha256(json.dumps(dict(design=source['design'], rtl=boundary), sort_keys=True).encode()).hexdigest()
    if hardware != profile['hardware_boundary_sha256']:
        raise ValueError('hardware boundary SHA differs')
    libraries = []
    for folder in ('fresh-pdk', 'routed-db'):
        blocks = {}
        for path in sorted((root/'pdk-replay'/folder).glob('library*.lef')):
            for key, value in lef_blocks(read(path)).items():
                if key in blocks and blocks[key] != value:
                    raise ValueError('conflicting LEF snapshots')
                blocks[key] = value
        libraries.append(blocks)
    masters, count = components(artifacts['def'])
    geometry = compare_geometry(*libraries, masters)
    if any(pdk.get(key) != value for key, value in geometry.items()) or pdk.get('component_count') != count:
        raise ValueError('raw geometry differs from audit')
    if profile.get('macro_count') != 0 or profile.get('macro_pin_access') != 'NOT_APPLICABLE_NO_MACROS':
        raise ValueError('macro pin access unqualified')
    samples = validate_samples(activity)
    expected = {row['seed']: row for row in workload['samples']}
    if len(workload['samples']) != 10 or sorted(expected) != list(range(1, 11)):
        raise ValueError('workload seed definition incomplete')
    validate_power_join(profile['loads'], samples, sha(artifacts['netlist']), sha(artifacts['spef']), operator)
    validate_power_join(power['records'], samples, sha(artifacts['netlist']), sha(artifacts['spef']), operator)
    checker = check_transcript if operator == 'p3' else check_attention
    for row in profile['loads']:
        seed = row['seed']
        sample = next(item for item in samples if item['seed'] == seed)
        original = next(item for item in power['records'] if item['seed'] == seed)
        if any(row.get(key) != value for key, value in original.items()):
            raise ValueError('load differs from original power record')
        if row.get('hardware_boundary_sha256') != hardware or row.get('backend') != 'rtl':
            raise ValueError('load hardware/backend differs')
        files = {key: bound_file(root, row[key]) for key in ('activity', 'power_json', 'annotation_rpt', 'openroad_log', 'gate_log', 'input_image')}
        if sha(files['input_image']) != expected[seed]['image_sha256'] or row['input_sha256'] != expected[seed]['input_sha256']:
            raise ValueError('wrong workload input')
        checked = checker(read(files['gate_log']), expected[seed])
        if any(sample[key] != value for key, value in checked.items()):
            raise ValueError('gate transcript differs')
        if sha(files['activity']) != row['activity_sha256']:
            raise ValueError('VCD identity differs')
        validate_vcd_window(files['activity'], row['begin_ns'], row['end_ns'])
        dynamic, leakage, total = parse_power_json(files['power_json'])
        _, _, coverage = parse_activity_annotation(read(files['annotation_rpt']), 'VCD')
        slack = parse_worst_slack(read(files['openroad_log']))
        if (row['dynamic_mw'], row['leakage_mw'], row['annotation_percent'], row['worst_setup_slack_ns']) != (dynamic, leakage, coverage, slack):
            raise ValueError('power components/annotation/timing differs')
        if not math.isclose(row['power_w'], total/1000, rel_tol=1e-12):
            raise ValueError('raw power differs')
    tools = profile.get('external_tool_binary_sha256', {})
    if {Path(name).name for name in tools} != {'openroad', 'yosys', 'iverilog', 'vvp'}:
        raise ValueError('incomplete external tool identity')
    historical = {**source['files'], **activity['bindings'], **power['bindings']}
    if any(not re.fullmatch('[0-9a-f]{64}', digest) or historical.get(name) != digest for name, digest in tools.items()):
        raise ValueError('unbound external tool SHA')
    return dict(status='PHYSICAL_BUNDLE_VERIFIED', physical_evidence_complete=True,
                formal_baseline=False, release_complete=False, operator=operator,
                load_count=10, profile_sha256=expected_sha256)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', type=Path)
    parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.profile, args.expected_sha256)))


if __name__ == '__main__':
    main()

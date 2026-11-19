"""Audit completed fresh CPU prompt pairs; never promote a partial run."""
import hashlib
import json
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    rows = []
    sources = {}
    for name in ['cpu-native-regression-smoke-envfixed', 'cpu-native-regression-remaining']:
        directory = BASE / 'runs' / name
        receipt = directory / 'receipt.json'
        source = receipt if receipt.exists() else directory / 'progress.json'
        if not source.exists():
            continue
        report = json.loads(source.read_text())
        if source == receipt:
            assert report['status'] == 'SELECTED_PROMPTS_CPU_RTL_EXACT_PASS'
            records = report['records']
        else:
            records = report
        sources[str(source)] = sha(source)
        for row in records:
            assert row['status'] == 'FRESH_CPU_RTL_EXACT_PASS'
            manifest_path = BASE / 'build/native-regression-inputs' / f"{row['index']:02d}" / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            assert manifest['question'] == row['question']
            assert row['baseline']['states'] == row['algorithm']['states']
            variants = {}
            for variant in ['baseline', 'algorithm']:
                value = row[variant]
                states = value['states']
                assert [int(s['step']) for s in states] == list(range(len(states)))
                assert 0 < len(states) <= 12
                assert len(states) == 12 or int(states[-1]['token']) == 4
                assert all(len(s['hidden'].split(',')) == 16 and len(s['logits'].split(',')) == 256 for s in states)
                for filename, digest in value['bindings'].items():
                    assert sha(Path(filename)) == digest, filename
                log = directory / f"{row['index']:02d}-{variant}" / 'execute.log'
                assert sha(log) == value['log_sha256'], str(log)
                text = log.read_text(errors='replace')
                assert len(re.findall(r'^STUDENT_NATIVE_CPU_BEGIN prompt_tokens=' + str(len(manifest['prompt_tokens'])) + r' max_tokens=12\b', text, re.M)) == 1
                observed = [dict(re.findall(r'(\w+)=([^ ]+)', line)) for line in text.splitlines()
                            if line.startswith('STUDENT_NATIVE_TOKEN ')]
                assert [{k: s[k] for k in ['step', 'token', 'hidden', 'logits']} for s in observed] == states
                assert len(re.findall(r'^STUDENT_NATIVE_CPU_COMPLETE count=' + str(len(states)) + r'\b', text, re.M)) == 1
                cycles = value['generation_cycles']
                assert cycles > 0
                timing = re.findall(r'^STUDENT_NATIVE_CPU status=0 count=' + str(len(states)) + r' cycles=(\d+):(\d+)', text, re.M)
                assert len(timing) == 1 and cycles == (int(timing[0][0]) << 32) + int(timing[0][1])
                assert value['simulation_seconds_at_1MHz'] == cycles / 1e6
                assert value['tokens_per_sim_second_including_eos'] == len(states) * 1e6 / cycles
                variants[variant] = {k: value[k] for k in ['generation_cycles', 'simulation_seconds_at_1MHz', 'tokens_per_sim_second_including_eos', 'process_wall_seconds']}
            rows.append(dict(index=row['index'], question=row['question'], token_ids=[int(s['token']) for s in row['algorithm']['states']], variants=variants))
    indices = [row['index'] for row in rows]
    assert len(indices) == len(set(indices)), 'Duplicate prompt evidence'
    assert all(0 <= i < 12 for i in indices)
    complete = sorted(indices) == list(range(12))
    result = dict(status='TWELVE_FRESH_PAIRED_CPU_RTL_EXACT_PASS' if complete else 'PARTIAL_CPU_RTL_AUDITED_HOLD',
                  completed=len(rows), missing_indices=sorted(set(range(12)) - set(indices)),
                  records=sorted(rows, key=lambda row: row['index']), bindings=sources,
                  limitation='Original CPU core, diagnostic UART timings and different ELF layouts; not CSA/physical qualification or pure P3 performance attribution. A partial audit is not a twelve-prompt PASS.')
    out = BASE / 'runs' / 'cpu-prompt-regression-audit.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(result['status'], 'completed', len(rows), 'missing', result['missing_indices'])


if __name__ == '__main__':
    main()

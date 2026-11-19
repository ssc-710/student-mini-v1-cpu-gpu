"""Model card of the accepted student-mini NanoChat candidate, computed from the delivered artifacts.

    python3 scripts/build_student_mini_nano_model_card.py --plan PLAN.json --out model-card.json

Everything is derived, nothing is typed in: the deployed checkpoint is the one named by the
'deployment' of every session in the plan (all must agree); tensor shapes, dtypes, sizes and the
parameter count come from loading that exported .npz; the model shape from its embedded metadata
(cross-checked against the tensor shapes and grading/student-mini/spec.json "nano"); the training
seed, the fixed train/validation/test sets and the tokenizer from the training run's inputs.json
(exact-question dedup and the weather hold-out check are recomputed here); SHA-256 values are
re-measured.  Mismatches are listed under "mismatches", items that cannot be derived under "holds";
the card status is PASS only if both are empty.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
WEATHER = '今天天气怎么样？'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def rel(path):
    path = Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def tensor_class(name):
    if name.startswith('shared_'):
        return 'shared-expert FFN'
    if name in ('gate', 'up', 'down'):
        return 'routed-expert FFN'
    if name == 'router':
        return 'router'
    if name.startswith('attention_') and not name.endswith('_norm'):
        return 'attention (MLA + indexer)'
    if name.endswith('norm'):
        return 'norm'
    return name  # embedding, lm_head


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    plan = load(args.plan)
    candidate_path = Path(plan['nano_candidate'])
    work = candidate_path.parent
    candidate = load(candidate_path)
    inputs = load(work / 'inputs.json')
    spec = load(plan['spec'])['nano']
    mismatches, holds = [], []

    # ---- which checkpoint the accepted sessions ran
    sessions = [(p, path) for p, paths in plan['nano'].items() for path in paths]
    deployments = {}
    backends, images = {}, {}
    for platform, path in sessions:
        value = load(path)
        deployments.setdefault(json.dumps(value.get('deployment'), sort_keys=True), []).append(f'{platform}:{value.get("question")}')
        backends.setdefault(platform, set()).add(json.dumps({k: value.get(k) for k in ('backend', 'operator_backend', 'residual_model_backend')
                                                              if value.get(k)}, sort_keys=True))
        for key, digest in (value.get('bindings') or {}).items():
            if re.search(r'/(selected-native-image|native-image)/[0-9a-f]{64}/image\.bin$', key):
                images.setdefault(key, dict(sha256=digest, sessions=[]))['sessions'].append(f'{platform}:{value.get("question")}')
    if len(deployments) != 1:
        mismatches.append(f'sessions name {len(deployments)} different deployments')
    deployment = json.loads(next(iter(deployments)))
    export = work / deployment['quantized']
    export_sha = sha(export)
    if export_sha != deployment['quantized_sha256']:
        mismatches.append(f"deployed export {export.name} SHA-256 {export_sha} != sessions' {deployment['quantized_sha256']}")
    lineage = next((l for l in candidate['lineage'].values() if l.get('quantized') == deployment['quantized']), None)
    fp32 = work / lineage['checkpoint'] if lineage else None
    fp32_sha = sha(fp32) if fp32 and fp32.is_file() else None
    if not lineage or fp32_sha != deployment.get('source_checkpoint_sha256'):
        mismatches.append(f'FP32 source checkpoint SHA-256 {fp32_sha} != deployment source {deployment.get("source_checkpoint_sha256")}')

    # ---- tensors and parameter count from the export
    z = np.load(export)
    metadata = json.loads(bytes(z['metadata_utf8']).decode('utf-8')) if 'metadata_utf8' in z.files else None
    tensors = [dict(name=k, shape=list(z[k].shape), dtype=str(z[k].dtype), elements=int(z[k].size), bytes=int(z[k].nbytes),
                    tensor_class=tensor_class(k), scale=(metadata or {}).get('scales', {}).get(k))
               for k in z.files if k != 'metadata_utf8']
    parameters = sum(t['elements'] for t in tensors)
    if parameters != candidate.get('parameters'):
        mismatches.append(f"export holds {parameters} weights, candidate.json records {candidate.get('parameters')} parameters")
    classes = {}
    for t in tensors:
        c = classes.setdefault(t['tensor_class'], dict(tensors=0, elements=0, bytes=0))
        c['tensors'] += 1
        c['elements'] += t['elements']
        c['bytes'] += t['bytes']
    if metadata is None:
        holds.append('export has no embedded metadata: model shape cannot be read from the export')
    profile = (metadata or {}).get('profile', {})
    shape_of = {t['name']: t['shape'] for t in tensors}
    derived = dict(layers=profile.get('layers'), hidden=profile.get('hidden'), heads=profile.get('heads'),
                   intermediate=profile.get('intermediate'), experts=profile.get('experts'), active_experts=profile.get('active_experts'),
                   shared_experts=(1 if shape_of.get('shared_gate') and len(shape_of['shared_gate']) == 3 else
                                   shape_of['shared_gate'][1] if shape_of.get('shared_gate') else 0),
                   vocab=profile.get('vocab'), context=profile.get('context'), max_generated_tokens=profile.get('max_generated_tokens'))
    # tensor-shape cross-checks of the metadata
    checks = dict(vocab=shape_of.get('embedding', [None])[0], hidden=shape_of.get('embedding', [None, None])[1],
                  layers=shape_of.get('router', [None])[0], experts=shape_of.get('router', [None, None, None])[2],
                  intermediate=shape_of.get('gate', [None] * 4)[3])
    for key, value in checks.items():
        if value != derived.get(key):
            mismatches.append(f'{key}: metadata {derived.get(key)} but tensor shapes give {value}')
    for key in ('layers', 'hidden', 'heads', 'intermediate', 'experts', 'active_experts', 'shared_experts', 'vocab', 'context',
                'max_generated_tokens'):
        frozen = spec.get(key)
        if frozen is not None and frozen != derived.get(key):
            mismatches.append(f'{key}: export {derived.get(key)} != frozen spec {frozen}')

    # ---- training data, seed, tokenizer
    dataset = inputs.get('dataset') or {}
    splits = {k: [r['question'] for r in dataset.get(k, [])] for k in ('train', 'validation', 'test')}
    within = {k: len(v) - len(set(v)) for k, v in splits.items()}
    across = {f'{a}&{b}': sorted(set(splits[a]) & set(splits[b])) for a, b in (('train', 'validation'), ('train', 'test'), ('validation', 'test'))}
    weather = {k: WEATHER in v for k, v in splits.items()}
    if any(within.values()) or any(across.values()):
        mismatches.append(f'question dedup failed: within {within}, across {across}')
    if weather != dict(train=False, validation=False, test=True):
        mismatches.append(f'{WEATHER} must be only in the test set: {weather}')
    if str(inputs.get('seed')) != str(spec.get('training_seed')):
        mismatches.append(f"training seed {inputs.get('seed')} != spec {spec.get('training_seed')}")
    if inputs.get('device') != spec.get('training_device'):
        mismatches.append(f"training device {inputs.get('device')} != spec {spec.get('training_device')}")
    tokenizer = inputs.get('tokenizer') or {}
    used = len(tokenizer.get('characters') or {}) + len(tokenizer.get('special') or {})
    if tokenizer.get('vocab_capacity') != spec.get('vocab') or used > (tokenizer.get('vocab_capacity') or 0):
        mismatches.append(f"tokenizer capacity {tokenizer.get('vocab_capacity')} (used {used}) vs spec vocab {spec.get('vocab')}")
    test_questions = [q['question'] for q in candidate['quality']['ptq_exact']]
    if test_questions != splits['test']:
        mismatches.append('candidate ptq_exact questions differ from the frozen test split')
    tokenizer_json = json.dumps(tokenizer, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    bindings = inputs.get('bindings') or {}
    trainer = next((k for k in bindings if k.endswith('scripts/train_student_mini_nano.py')), None)

    # ---- calibration samples and image/ROM
    quantization = (metadata or {}).get('quantization')
    calibration = dict(status='NOT_APPLICABLE' if quantization and 'no calibration' in quantization else 'HOLD', method=quantization,
                       samples=None)
    if calibration['status'] == 'HOLD':
        holds.append('calibration samples: export metadata does not state the quantization method')
    image_rows = []
    for key, entry in sorted(images.items()):
        path = ROOT / key.split('open-soc-ai-labs/', 1)[-1] if 'open-soc-ai-labs/' in key else Path(key)
        manifest = path.parent / 'manifest.json'
        current = sha(path) if path.is_file() else None
        image_rows.append(dict(path=rel(path) if path.is_file() else key, recorded_sha256=entry['sha256'], current_sha256=current,
                               bytes=path.stat().st_size if path.is_file() else None, sessions=entry['sessions'],
                               manifest=rel(manifest) if manifest.is_file() else None,
                               manifest_sha256=sha(manifest) if manifest.is_file() else None,
                               manifest_status=load(manifest).get('status') if manifest.is_file() else None,
                               deployment_matches=(load(manifest).get('deployment') == deployment) if manifest.is_file() else None))
        if current != entry['sha256']:
            mismatches.append(f'image {key}: current SHA-256 {current} != recorded {entry["sha256"]}')
    if not image_rows:
        holds.append('no CPU image bound by the sessions')
    export_scripts = sorted({k.split('open-soc-ai-labs/', 1)[-1] for p, path in sessions for k in (load(path).get('bindings') or {})
                             if re.search(r'scripts/export_student_mini_(selected|native)_image\.py$', k)})
    card = dict(
        status='PASS' if not mismatches and not holds else 'HOLD', mismatches=mismatches, holds=holds,
        candidate=dict(path=rel(candidate_path), sha256=sha(candidate_path), kind=candidate.get('kind'),
                       candidate_status_field=candidate.get('status'),
                       note='candidate.json status is the producer stage status; acceptance is the release Nano gate (12/12 token-exact per platform)'),
        deployment=dict(deployment, sessions=sum(len(v) for v in deployments.values()),
                        export=dict(path=rel(export), sha256=export_sha, bytes=export.stat().st_size),
                        fp32_checkpoint=dict(path=rel(fp32) if fp32 else None, sha256=fp32_sha,
                                             bytes=fp32.stat().st_size if fp32 and fp32.is_file() else None),
                        not_deployed={k: dict(checkpoint=v.get('checkpoint'), sha256=v.get('sha256'), quantized=v.get('quantized'),
                                              quantized_sha256=v.get('quantized_sha256'))
                                      for k, v in candidate['lineage'].items() if v.get('quantized') != deployment['quantized']}),
        backends={p: [json.loads(b) for b in sorted(v)] for p, v in backends.items()},
        model_shape=dict(derived, source='export metadata profile + tensor shapes (shared experts from shared_* tensors)',
                         frozen_spec={k: spec.get(k) for k in ('layers', 'hidden', 'heads', 'intermediate', 'experts', 'active_experts',
                                                               'shared_experts', 'vocab', 'context', 'max_generated_tokens')},
                         extra_profile={k: v for k, v in profile.items() if k not in derived}),
        parameters=dict(total=parameters, candidate_json=candidate.get('parameters'), classes=classes, tensors=tensors,
                        export_bytes_weights=sum(t['bytes'] for t in tensors)),
        quantization=dict(method=quantization, runtime_semantics=(metadata or {}).get('runtime_semantics'),
                          parent_checkpoint_sha256=(metadata or {}).get('parent_checkpoint_sha256')),
        calibration=calibration,
        tokenizer=dict(kind='character vocabulary + 6 special tokens', special=tokenizer.get('special'),
                       characters=len(tokenizer.get('characters') or {}), used_ids=used, capacity=tokenizer.get('vocab_capacity'),
                       sha256_canonical_json=hashlib.sha256(tokenizer_json).hexdigest(),
                       frozen_in=rel(work / 'inputs.json'), source_of_truth='scripts/train_student_mini_nano.py dataset()',
                       source_sha256_bound=bindings.get(trainer) if trainer else None,
                       source_sha256_current=sha(ROOT / 'scripts/train_student_mini_nano.py')),
        training=dict(seed=inputs.get('seed'), device=inputs.get('device'), torch_version=inputs.get('torch_version'),
                      steps=inputs.get('steps'), qat_steps=inputs.get('qat_steps'), checkpoint_selection=inputs.get('checkpoint_selection'),
                      inputs=dict(path=rel(work / 'inputs.json'), sha256=sha(work / 'inputs.json')),
                      split_sizes={k: len(v) for k, v in splits.items()},
                      duplicate_questions_within_split=within, overlapping_questions_across_splits=across,
                      weather_question=dict(question=WEATHER, present_in=weather, only_in_test=weather == dict(train=False, validation=False, test=True)),
                      test_questions=splits['test'], validation_questions=splits['validation']),
        image=dict(images=image_rows, export_scripts=[dict(path=s, sha256=sha(ROOT / s)) for s in export_scripts]),
        method=__doc__.strip().splitlines()[0])
    args.out.write_text(json.dumps(card, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=card['status'], mismatches=mismatches, holds=holds, parameters=parameters, images=len(image_rows)),
                     ensure_ascii=False))


if __name__ == '__main__':
    main()

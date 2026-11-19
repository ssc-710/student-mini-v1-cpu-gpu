"""Independently verify prepared prompt ABI and frozen payloads; no target PASS."""
import ast
import hashlib
import json
from pathlib import Path
import re
import struct
BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parents[1]
source=BASE/'tools/build_cpu.py'
tree=ast.parse(source.read_text())
# Execute exactly the input-validation branch used by the build entry point,
# without importing LiteX or starting any compiler.
branch=next(n for n in tree.body if isinstance(n,ast.If) and ast.unparse(n.test)=='a.image_dir')
code=compile(ast.Module(body=branch.body,type_ignores=[]),str(source),'exec')
prepared=BASE/'build/native-regression-inputs'
preparation=json.loads((prepared/'preparation.json').read_text())
records=[]
for session in preparation['sessions']:
    image_dir=Path(session['directory']);assert image_dir.resolve().is_relative_to(prepared.resolve())
    namespace=dict(image_dir=image_dir,alias=ROOT,json=json,hashlib=hashlib,re=re,struct=struct)
    exec(code,namespace)
    assert namespace['manifest']['question']==session['question']
    for name in ['manifest.json','image.bin','student_mini_native_image.h']:
        path=image_dir/name;key=str(path.relative_to(prepared))
        assert hashlib.sha256(path.read_bytes()).hexdigest()==preparation['artifacts'][key],key
    records.append(dict(index=session['index'],question=session['question'],status='INPUT_ABI_FROZEN_PAYLOAD_PASS'))
out=BASE/'runs/native-regression-input-audit';out.mkdir(exist_ok=False)
(out/'receipt.json').write_text(json.dumps(dict(status='TWELVE_INPUT_PACKAGES_VALID_NOT_TARGET_EXECUTION',records=records,
    validator_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    preparation_sha256=hashlib.sha256((prepared/'preparation.json').read_bytes()).hexdigest(),
    limitation='Post-preparation static input audit, not retroactive build/run instrumentation or twelve-question RTL/SimX regression.'),ensure_ascii=False,indent=2)+'\n')
print('TWELVE_INPUT_ABI_AUDIT_PASS_NOT_TARGET_EXECUTION')

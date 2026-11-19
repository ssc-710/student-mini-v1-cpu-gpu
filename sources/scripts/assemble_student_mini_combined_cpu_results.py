"""Join CPU baseline records from the exact ROM that also executed native Nano."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.assemble_student_mini_cpu_results import parse, join
from scripts.export_student_mini_input import encode
from scripts.export_student_mini_combined_cpu_boundary import checked_parent, check_rom


def check_container(blob,baseline,native,offset):
    if type(offset) is not int or offset!=len(baseline) or not baseline or not native:
        raise ValueError('wrong baseline/native image boundary')
    expected=baseline+native
    expected+=bytes((-len(expected))%1936)
    if blob!=expected:raise ValueError('loader input or transport padding differs')
    return dict(baseline_bytes=len(baseline),native_bytes=len(native),padding_bytes=len(expected)-len(baseline)-len(native),
        baseline_sha256=hashlib.sha256(baseline).hexdigest(),native_sha256=hashlib.sha256(native).hexdigest())


def assemble(vectors,work,image_dir,output_root):
    original,completed=checked_parent(work)
    for name,digest in completed['artifacts'].items():
        if sha(work/name)!=digest:raise ValueError('CPU artifact changed: '+name)
    manifest_path=image_dir/'manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if original['bindings'].get(str(manifest_path))!=sha(manifest_path):raise ValueError('wrong native image manifest')
    if manifest.get('contains_expected_tokens') is not False or sha(image_dir/'image.bin')!=manifest['image_sha256']:
        raise ValueError('native runtime input is not the verified input-only image')
    sources=original['input_manifest']['bindings']
    if sources.get(vectors.relative_to(ROOT).as_posix())!=sha(vectors):raise ValueError('mixed golden revision')
    for name,digest in sources.items():
        if sha(ROOT/name)!=digest:raise ValueError('baseline source changed')
    goldens=[json.loads(line) for line in vectors.read_text().splitlines()]
    if len(goldens)!=1000 or original.get('baseline_count')!=1000:raise ValueError('exact frozen case count required')
    container=check_container((work/'loader.bin').read_bytes(),b''.join(encode(row,i) for i,row in enumerate(goldens)),
        (image_dir/'image.bin').read_bytes(),original['native_image_offset'])
    rom=check_rom((work/'soc/gateware/sim_rom.init').read_text(),(work/'soc/software/bios/bios.bin').read_bytes())
    text=(work/'console.log').read_text()
    if text.splitlines().count('STUDENT_CPU_DMA_PROBE status=0 bytes=0:64')!=1:
        raise ValueError('DMA calibration missing/duplicate')
    report=join(goldens,parse(text,1000))
    paths=[vectors,work/'completion.json',work/'inputs.json',work/'console.log',work/'loader.bin',
        work/'soc/gateware/sim_rom.init',work/'soc/software/bios/bios.bin',manifest_path,image_dir/'image.bin',Path(__file__)]
    paths += [ROOT/'scripts'/name for name in ('student_mini.py','assemble_student_mini_cpu_results.py',
        'export_student_mini_input.py','export_student_mini_combined_cpu_boundary.py')]
    bindings={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    report.update(bindings=bindings,same_rom_baseline_and_nano=True,rom_check=rom,input_container=container,
        reason='All CPU baseline records from the single executed baseline/Nano ROM; DMA fault injection, full protocol/physical and Nano quality qualification remain separate')
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    output=output_root/identity;output.mkdir(parents=True,exist_ok=False)
    path=output/'results.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return dict(path=str(path),sha256=sha(path),numeric_matches=report['numeric_matches'],formal_baseline=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('vectors','work','image-dir'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(assemble(args.vectors.resolve(),args.work.resolve(),args.image_dir.resolve(),ROOT/'grading/evidence/student-mini-v1/results')))


if __name__=='__main__':main()

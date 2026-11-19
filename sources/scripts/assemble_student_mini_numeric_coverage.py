"""Join actual operator outputs and approved auxiliary paths without issuing B0."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_numeric_paths import digest
from scripts.student_mini_numeric_path_evidence import load_evidence
from scripts.assemble_student_mini_results import join_results


def join_coverage(goldens,primary,evidence):
    assigned={(r['case_id'],r['seed']):r for r in evidence['allocation']}
    if len(assigned)!=len(goldens):raise ValueError('complete unique numeric allocation required')
    components={}
    for row in evidence['component_records']:
        key=(row['case_id'],row['seed'])
        if key in components:raise ValueError('duplicate component seed')
        components[key]=row
    expected={(r['case']['id'],r['seed']):r for r in goldens}
    if len(expected)!=len(goldens) or expected.keys()!=assigned.keys():raise ValueError('case/seed allocation differs')
    actual={}
    for report in primary:
        if report.get('platform')!='accelerator' or report.get('formal_baseline') is not False:
            raise ValueError('scoped accelerator results required')
        op=report['operator']
        # Recompute bit comparisons, error statuses, Top-K and reset checks;
        # do not trust a saved PASS label or a mean that hides a failing seed.
        checked=join_results(goldens,[r['observation'] for r in report['records']],op)
        for row in report['records']:
            key=(row['case']['id'],row['seed'])
            if key in actual or key not in expected:raise ValueError('duplicate or extra primary record')
            original=expected[key]
            for field in ('case','seed','prng','inputs','golden'):
                if row[field]!=original[field]:raise ValueError('primary input/golden changed')
        for row in checked['records']:actual[(row['case']['id'],row['seed'])]=row
    if actual.keys()!=expected.keys():raise ValueError('missing primary case/seed')
    records=[]
    for key,golden in expected.items():
        assignment=assigned[key];row=actual[key]
        if assignment['original_record_sha256']!=digest(golden):raise ValueError('different numeric input lineage')
        required=assignment['auxiliary_owner'] is not None
        component=components.get(key) if required else None
        if required and (component is None or component.get('original_record_sha256')!=digest(golden)
            or component.get('auxiliary_owner')!=assignment['auxiliary_owner']
            or component.get('source')!='component-rtl' or component.get('whole_operator_pass') is not False):
            raise ValueError('assigned actual component missing or wrong owner')
        output_ok=row['comparison'] is not None and row['status']!='FAIL'
        auxiliary_ok=not required or (component['status']=='PASS' and component['actual']==assignment['expected_auxiliary']
            and component['actual_invalid']==0 and component['delta']==0 and component['bit_mismatch'] is False)
        records.append(dict(case_id=key[0],seed=key[1],operator=golden['case']['operator'],
            original_record_sha256=digest(golden),primary_report_status=row['status'],
            output_comparison=row['comparison'],auxiliary_owner=assignment['auxiliary_owner'],
            auxiliary_component=component,numerical_layer_status='PASS' if output_ok and auxiliary_ok else 'FAIL',
            primary_missing_witnesses=row['observation'].get('missing_witnesses',[]),
            whole_operator_pass=False,formal_baseline=False))
    return dict(status='NUMERIC_COVERAGE_JOIN_ONLY',records=records,
        numerical_layer_pass=sum(r['numerical_layer_status']=='PASS' for r in records),
        numerical_layer_fail=sum(r['numerical_layer_status']=='FAIL' for r in records),
        assigned_auxiliary_records=sum(r['auxiliary_component'] is not None for r in records),
        directed_bf16_component_records=sum(r.get('mode')==2 for r in components.values()),
        formal_baseline=False,whole_operator_pass=False,physical_evidence_complete=False,
        semantic_fp32_error_status='NOT_MEASURED',
        reason='Exact bit/status comparisons and allocated component execution only; original integration/protocol HOLDs, semantic FP32 error, physical, Nano and resource acceptance remain separate')


def main():
    pointer=json.loads((ROOT/'grading/student-mini/page-evidence.json').read_text())
    vectors=ROOT/pointer['golden'];goldens=[json.loads(x) for x in vectors.read_text().splitlines()]
    evidence=load_evidence(pointer,goldens);primary=[]
    files=[Path(__file__),vectors,ROOT/'grading/student-mini/numeric-paths-v1.json',
        ROOT/pointer['numeric_paths']['path'],ROOT/'scripts/student_mini_numeric_path_evidence.py',
        ROOT/'scripts/student_mini_numeric_paths.py',ROOT/'scripts/assemble_student_mini_results.py',
        ROOT/'scripts/student_mini.py',ROOT/'scripts/run_student_mini_numeric_paths.py']
    for reference in pointer['results']:
        path=ROOT/reference['path']
        if sha(path)!=reference['sha256']:raise ValueError('primary report SHA changed')
        report=json.loads(path.read_text())
        if report['platform']!='accelerator':continue
        for relative,digest_value in report['bindings'].items():
            if sha(ROOT/relative)!=digest_value:raise ValueError('primary source/artifact changed')
            files.append(ROOT/relative)
        files.append(path);primary.append(report)
    if sorted(r['operator'] for r in primary)!=['p1','p2','p3']:raise ValueError('exactly three primary operators required')
    result=join_coverage(goldens,primary,evidence)
    bindings={p.relative_to(ROOT).as_posix():sha(p) for p in files}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'grading/evidence/student-mini-v1/numeric-coverage'/key;work.mkdir(parents=True,exist_ok=False)
    result['bindings']=bindings
    path=work/'coverage.json';path.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(path=str(path),sha256=sha(path),counts={k:result[k] for k in ('numerical_layer_pass','numerical_layer_fail','assigned_auxiliary_records','directed_bf16_component_records')},formal_baseline=False)))


if __name__=='__main__':main()

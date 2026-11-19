"""Strict reader for supplemental numeric paths, never a B0 release verifier."""
import json
from pathlib import Path
from scripts.student_mini import ROOT,sha
from scripts.student_mini_numeric_paths import read_assignment,allocate,common_inputs,bf16_inputs
from scripts.run_student_mini_numeric_paths import check_transcript


def validate_records(report,rows,contract,transcript):
    if (report.get('status')!='NUMERIC_PATH_COMPONENT_STAGE_PASS'
        or report.get('formal_baseline') is not False or report.get('physical_evidence_complete') is not False
        or report.get('whole_operator_pass') is not False or report.get('contract_revision')!=contract['revision']):
        raise ValueError('numeric components must not claim operator or physical acceptance')
    assigned=allocate(rows,contract);expected=common_inputs(rows,contract)+bf16_inputs(len(rows))
    if report.get('allocation')!=assigned:raise ValueError('frozen case/input/seed allocation differs')
    actual=check_transcript(transcript,expected)
    if report.get('records')!=actual or any(r['status']!='PASS' for r in actual):raise ValueError('actual log/golden/component records differ')
    return assigned,actual


def load_evidence(pointer,rows,root=ROOT):
    root=Path(root);contract=read_assignment(root);source=pointer['numeric_paths'];path=root/source['path']
    if sha(path)!=source['sha256']:raise ValueError('numeric path receipt changed')
    report=json.loads(path.read_text(encoding='utf-8'))
    required=['grading/student-mini/spec.json','grading/student-mini/numeric-paths-v1.json',
        'scripts/student_mini_numeric_paths.py','scripts/run_student_mini_numeric_paths.py',
        'tests/rtl/student_mini_numeric_paths_tb.sv','shared/rtl/q22_requantize_int8_finalize_pipeline.sv',
        'shared/rtl/q22_requantize_int8_low_digit_compat.sv','shared/rtl/int32_times_fp32_to_bf16_pipeline.sv',pointer['golden']]
    for relative in required:
        matches=[value for name,value in report['bindings'].items() if name.replace('\\','/').endswith('/'+relative)]
        if matches!=[sha(root/relative)]:raise ValueError('numeric path source binding differs: '+relative)
    for name,digest in report['artifacts'].items():
        if Path(name).name!=name or name in ('.','..') or sha(path.parent/name)!=digest:raise ValueError('component artifact changed')
    if sha(root/pointer['golden'])!=contract['golden_sha256']:raise ValueError('different frozen corpus')
    assigned,actual=validate_records(report,rows,contract,(path.parent/'run.log').read_text())
    toolchain={Path(name).name:digest for name,digest in report['bindings'].items() if Path(name).name in ('iverilog','vvp')}
    if set(toolchain)!={'iverilog','vvp'} or any(len(digest)!=64 for digest in toolchain.values()):raise ValueError('component tool identities missing')
    return dict(contract=contract,contract_sha256=sha(root/'grading/student-mini/numeric-paths-v1.json'),toolchain_sha256=toolchain,
                workspace_source_sha256={relative:sha(root/relative) for relative in required},
                source=source,allocation=assigned,component_records=actual,component_count=len(actual),
                formal_baseline=False,whole_operator_pass=False,legacy_reports_unchanged=True)

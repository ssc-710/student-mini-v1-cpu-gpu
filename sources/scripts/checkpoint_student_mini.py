"""Record a truthful implementation checkpoint, including unmet release gates."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import readiness,read_contracts,sha
from scripts.student_mini_checkpoint_sources import snapshot as source_snapshot,changes as source_changes


def bound_progress(pointer, root=ROOT):
    """Keep raw stage progress distinct from release-qualified acceptance."""
    record=pointer['progress']
    path=root/record['path']
    if sha(path)!=record['sha256']:
        raise ValueError('progress report changed')
    report=json.loads(path.read_text(encoding='utf-8'))
    keys=('formal_baselines','physical_packages','raw_physical_bundles_verified',
          'nano_sessions','released_archives')
    if any(type(report.get(key)) is not int or report[key]<0 for key in keys):
        raise ValueError('invalid progress counts')
    return {key:report[key] for key in keys}


def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output=ROOT/'grading/evidence/student-mini-v1/checkpoints'/stamp
    output.mkdir(parents=True,exist_ok=False)
    source_before=source_snapshot(ROOT)
    (output/'control-sources-before.json').write_text(json.dumps(source_before,indent=2)+'\n',encoding='utf-8')
    commands={
        'python-regression':[sys.executable,'-m','pytest','-q'],
        'reproducible-page-build':[sys.executable,'scripts/build_inference_map_editions.py','--check'],
        'structure':[sys.executable,'scripts/lint_structure.py'],
        'edge-offline-three-widths':['node','scripts/check_student_package_page.mjs'],
    }
    if os.name=='nt':commands['wsl-eda-skipped-test-replay']=['wsl','-d','Ubuntu-24.04','--','bash','-lc','cd /mnt/c/Users/admin/Downloads/open-soc-ai-labs && PATH=/home/soclab/tools/verilator-5.040/bin:/home/soclab/.local/bin:/home/soclab/tools/oss-cad-suite/bin:/usr/local/bin:/usr/bin:/bin python3 -m pytest tests/test_openram_40x16_test_model.py tests/test_physical_wrapper_elaboration.py tests/test_platform_promotion_physical_wrappers.py tests/test_vortex_trace_physical_top.py tests/test_student_mini_p1_synthesis_contract.py tests/test_student_mini_p3_synthesis_contract.py tests/test_student_mini_p2_nano_capacity.py tests/test_student_mini_cpu_synthesis_contract.py tests/test_student_mini_cpu_dfi_results.py tests/test_student_mini_cpu_dfi_selected.py tests/test_student_mini_gpu_multiplier_physical.py tests/test_student_mini_cpu_multiplier_drive.py -q']
    if os.name=='nt':
        commands['wsl-eda-skipped-test-replay'][-1]=commands['wsl-eda-skipped-test-replay'][-1].removesuffix(' -q')+' tests/test_student_mini_native_bios.py tests/test_student_mini_native_rtl_inputs.py tests/test_student_mini_registered_route.py tests/test_student_mini_cpu_memory_enable.py tests/test_student_mini_cpu_sram_hold.py tests/test_student_mini_cpu_sram_mapping.py tests/test_student_mini_cpu_mapped_memory.py tests/test_student_mini_cpu_replay_sources.py tests/test_student_mini_cpu_uart_capture.py -q'
    if os.name=='nt':
        commands['wsl-eda-skipped-test-replay'][-1]=commands['wsl-eda-skipped-test-replay'][-1].removesuffix(' -q')+' tests/test_student_mini_gpu_overlay_configure.py tests/test_student_mini_native_dma_contract_elaboration.py tests/test_student_mini_gpu_divsqrt_elaboration.py tests/test_student_mini_gpu_cut_overlay.py tests/test_student_mini_gpu_constant_calls.py -q'
    if os.name=='nt':
        commands['wsl-eda-skipped-test-replay'][-1]=commands['wsl-eda-skipped-test-replay'][-1].removesuffix(' -q')+' tests/test_student_mini_gpu_idle_hold.py tests/test_student_mini_gpu_command_payload.py tests/test_student_mini_selected_cpu_replay.py tests/test_student_mini_cpu_loader_banks.py tests/test_student_mini_cpu_floorplan.py -q'
    if os.name=='nt':
        commands['wsl-eda-skipped-test-replay'][-1]=commands['wsl-eda-skipped-test-replay'][-1].removesuffix(' -q')+' tests/test_student_mini_gpu_repaired_boundary.py tests/test_student_mini_selected_accelerator_session.py tests/test_student_mini_cpu_pdn_placement.py tests/test_student_mini_gpu_port_packing.py tests/test_student_mini_gpu_port_boundary.py tests/test_student_mini_cpu_rom_cut.py tests/test_student_mini_cpu_timing.py tests/test_student_mini_gpu_host_handshake.py -q'
    checks=[]
    if os.name=='nt':
        commands['wsl-eda-skipped-test-replay'][-1]=commands['wsl-eda-skipped-test-replay'][-1].removesuffix(' -q')+' tests/test_student_mini_counter_process.py tests/test_student_mini_interleaved_gpu_counters.py tests/test_student_mini_repaired_gpu_counters.py tests/test_student_mini_repaired_gpu_placement.py tests/test_student_mini_gpu_repaired_replay.py tests/test_student_mini_cpu_tag_registers.py tests/test_student_mini_cpu_tag_physical.py -q'
    if os.name=='nt':
        commands['wsl-eda-skipped-test-replay'][-1]=commands['wsl-eda-skipped-test-replay'][-1].removesuffix(' -q')+' tests/test_student_mini_archive.py tests/test_student_mini_gpu_normalization_cut.py tests/test_student_mini_gpu_nrm_overlay.py tests/test_student_mini_gpu_nrm_replay.py -q'
    if os.name=='nt':
        commands['wsl-eda-skipped-test-replay'][-1]=commands['wsl-eda-skipped-test-replay'][-1].removesuffix(' -q')+' tests/test_student_mini_gpu_nrm_physical.py tests/test_student_mini_platform_route.py -q'
    if os.name=='nt':
        commands['wsl-eda-skipped-test-replay'][-1]=commands['wsl-eda-skipped-test-replay'][-1].removesuffix(' -q')+' tests/test_student_mini_gpu_multiclass.py tests/test_student_mini_gpu_counter_compile.py tests/test_student_mini_cpu_tag_banks.py tests/test_student_mini_cpu_tag_bank_replay.py -q'
    if os.name=='nt':
        commands['wsl-eda-skipped-test-replay'][-1]=commands['wsl-eda-skipped-test-replay'][-1].removesuffix(' -q')+' tests/test_student_mini_gpu_sign_cut.py tests/test_student_mini_gpu_sign_chain.py tests/test_student_mini_gpu_sign_measurements.py tests/test_student_mini_cpu_independent_memory.py tests/test_student_mini_cpu_rom_request_cut.py tests/test_student_mini_cpu_rom_request_proof.py tests/test_student_mini_cpu_rom_reset_probe.py tests/test_student_mini_cpu_latency_replay.py tests/test_student_mini_cpu_latency_runner.py tests/test_student_mini_cpu_request_physical.py -q'
    if os.name=='nt':
        commands['wsl-eda-skipped-test-replay'][-1]=commands['wsl-eda-skipped-test-replay'][-1].removesuffix(' -q')+' tests/test_student_mini_gpu_sign_full_counters.py tests/test_student_mini_cpu_request_route.py tests/test_student_mini_macro_access.py tests/test_student_mini_cpu_request_formal_lower.py -q'
    if os.name=='nt':
        commands['wsl-eda-skipped-test-replay'][-1]=commands['wsl-eda-skipped-test-replay'][-1].removesuffix(' -q')+' tests/test_student_mini_cpu_latency_counters.py tests/test_student_mini_cpu_counter_recheck.py tests/test_student_mini_cpu_request_selected.py tests/test_student_mini_gpu_cache_hold.py tests/test_student_mini_gpu_placement_report_retry.py -q'
    if os.name=='nt':
        commands['wsl-eda-skipped-test-replay'][-1]=commands['wsl-eda-skipped-test-replay'][-1].removesuffix(' -q')+' tests/test_student_mini_gpu_detail_placement_retry.py tests/test_student_mini_gpu_multiplier_cut.py tests/test_student_mini_gpu_multiplier_proof.py -q'
    if os.name=='nt':
        commands['wsl-eda-skipped-test-replay'][-1]=commands['wsl-eda-skipped-test-replay'][-1].removesuffix(' -q')+' tests/test_student_mini_gpu_legalization_hold.py tests/test_student_mini_gpu_diamond_placement.py tests/test_student_mini_cpu_read_buffer.py tests/test_student_mini_cpu_read_buffer_route.py tests/test_student_mini_cts_intervention.py tests/test_student_mini_cpu_dfi_cut.py tests/test_student_mini_cpu_dfi_replay.py tests/test_student_mini_cpu_dfi_physical.py tests/test_student_mini_route_cts_gate.py tests/test_student_mini_replay_intervention.py tests/test_student_mini_cpu_dfi_read_alignment.py tests/test_student_mini_cpu_failfast.py tests/test_student_mini_gpu_multiplier_overlay.py tests/test_student_mini_gpu_multiplier_replay.py -q'
    if os.name=='nt':
        # Queue the EDA tests behind actual hardware runs; do not run a second
        # heavy tool group alongside a 2-vCPU/8-GiB validation task.
        command=commands['wsl-eda-skipped-test-replay']
        command[-1]=command[-1].removesuffix(' -q')+' tests/test_student_mini_interruption_recovery.py tests/test_student_mini_congestion_geometry.py tests/test_student_mini_inspect.py tests/test_student_mini_cpu_drive_eco.py tests/test_student_mini_gpu_initial_difference.py tests/test_student_mini_congestion.py -q'
        command[-1]=command[-1].removesuffix(' -q')+' tests/test_student_mini_cpu_drive_api.py tests/test_student_mini_cpu_drive_audit.py tests/test_student_mini_cpu_two_gate_probe.py tests/test_student_mini_gpu_multiplier_full_counters.py tests/test_student_mini_numeric_paths.py tests/test_student_mini_numeric_path_execution.py tests/test_student_mini_numeric_path_evidence.py -q'
        shell=command[-1]
        prefix='cd /mnt/c/Users/admin/Downloads/open-soc-ai-labs && PATH='
        if not shell.startswith(prefix):raise ValueError('WSL regression command seam changed')
        bounded_output='/mnt/c/Users/admin/Downloads/open-soc-ai-labs/'+output.relative_to(ROOT).as_posix()+'/wsl-resource.json'
        command[command.index('--'):command.index('--')]=['-u','root']
        command[-1]=('cd /mnt/c/Users/admin/Downloads/open-soc-ai-labs && python3 scripts/student_mini_resource_guard.py '
            '--output '+bounded_output+' --timeout 7200 -- flock /mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock '
            'env PATH='+shell[len(prefix):])
    for name,command in commands.items():
        started=time.monotonic()
        result=subprocess.run(command,cwd=ROOT,env=dict(os.environ,PYTHONUTF8='1'),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            timeout=7350 if name=='wsl-eda-skipped-test-replay' else 300)
        path=output/(name+'.log');path.write_bytes(result.stdout)
        checks.append(dict(name=name,exit_code=result.returncode,elapsed_seconds=time.monotonic()-started,log=path.relative_to(ROOT).as_posix(),sha256=sha(path)))
        print(json.dumps(dict(name=name,exit_code=result.returncode)),flush=True)
    source_after=source_snapshot(ROOT);changed_sources=source_changes(source_before,source_after)
    (output/'control-sources-after.json').write_text(json.dumps(source_after,indent=2)+'\n',encoding='utf-8')
    spec,_=read_contracts()
    pointer=json.loads((ROOT/'grading/student-mini/page-evidence.json').read_text())
    progress=bound_progress(pointer)
    counts=dict(PASS=0,HOLD=0,FAIL=0)
    for source in pointer['results']:
        if sha(ROOT/source['path'])!=source['sha256']:raise ValueError('report changed')
        report=json.loads((ROOT/source['path']).read_text(encoding='utf-8'))
        for status in counts:counts[status]+=report['counts'][status]
    source_paths=list((ROOT/'scripts').glob('*student*'))+list((ROOT/'grading/student-mini').glob('*.json'))+list((ROOT/'docs/first-class/src/student-package').glob('*'))
    elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(spec['implementation_started_at'])).total_seconds()
    checkpoint=dict(schema_version=1,created_at=datetime.now(timezone.utc).isoformat(),status='HOLD',complete=False,
                    implementation_elapsed_seconds=elapsed,one_hour_full_delivery_achieved=False,
                    source_bindings={p.relative_to(ROOT).as_posix():sha(p) for p in source_paths if p.is_file()},checks=checks,
                    control_checks_passed=all(c['exit_code']==0 for c in checks) and not changed_sources,readiness=readiness(),
                    control_source_freshness=dict(unchanged=not changed_sources,changed=changed_sources,
                        before_sha256=sha(output/'control-sources-before.json'),after_sha256=sha(output/'control-sources-after.json')),
                    golden_records=sum(1 for line in (ROOT/pointer['golden']).read_text().splitlines() if line.strip()),partial_functional_records=counts,
                    progress_source=pointer['progress'],
                    formal_baselines=progress['formal_baselines'],unique_mini_physical_packages=progress['physical_packages'],
                    raw_physical_bundles_verified=progress['raw_physical_bundles_verified'],
                    accepted_mini_nano_sessions=progress['nano_sessions'],released_student_archives=progress['released_archives'],
                    remaining=[
                        'Mini GPU all-case RTL counters, real DMA fault injection and full CPU/GPU protocol qualification',
                        'P1/P2/P3 raw physical bundles independently verified; CPU/GPU physical implementation and all separate whole-release gates remain',
                        '510 approved numeric-path RTL component witnesses passed; platform integration and full protocol acceptance remain',
                        'Five unique 100 MHz routed physical packages and per-operator/seed activity power',
                        'Selected PTQ tokens/hidden/logits verified on mapped CPU RTL, GPU SimX and hybrid RTL-operator/host-C path. Complete platform acceptance, warm reset/full protocol and full accelerator execution remain',
                        '2-vCPU/8-GiB aggregate resource qualification and resolved dependency/archive locks',
                        'Qualified whole-release verifier, whitelist archives and clean-path package acceptance',
                    ])
    (output/'checkpoint.json').write_text(json.dumps(checkpoint,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(path=str(output/'checkpoint.json'),status='HOLD',control_checks_passed=checkpoint['control_checks_passed'],elapsed_seconds=elapsed)))
    return 0 if checkpoint['control_checks_passed'] else 1


if __name__=='__main__':raise SystemExit(main())

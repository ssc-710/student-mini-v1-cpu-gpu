"""Private sign-cut GPU overlay plus the locally proved 3-cycle multiplier."""
from pathlib import Path
from scripts.student_mini_gpu_physical_replay_sources import overlay_configure
from scripts.student_mini_gpu_cut_overlay import overlay_source_collector
from scripts.student_mini_gpu_multiplier_cut import project
from scripts.student_mini_gpu_sign_overlay import CONFIGS,checked_config

ROOT=Path(__file__).resolve().parents[1]


def create_overlay(source,destination,cut):
    source=Path(source).resolve();destination=Path(destination)
    if destination.exists():raise FileExistsError('preserve existing overlay')
    if cut.count('module VX_fdivsqrt_step_cut import')!=1 or 'localparam NR_STAGES = NR_BITS;' not in cut:
        raise ValueError('proved sign-cut source required')
    candidate=(ROOT/'integration/student-mini/gpu_signed33_mul3.sv').read_text()
    replacements={'configure':overlay_configure((source/'configure').read_text()),
        'hw/scripts/gen_sources.sh':overlay_source_collector((source/'hw/scripts/gen_sources.sh').read_text()),
        'hw/rtl/fpu/VX_fdivsqrt_unit.sv':cut.replace('module VX_fdivsqrt_step_cut import','module VX_fdivsqrt_unit import'),
        'hw/rtl/libs/VX_multiplier.sv':project((source/'hw/rtl/libs/VX_multiplier.sv').read_text(),candidate)}
    def fill(relative):
        (destination/relative).mkdir()
        for path in sorted((source/relative).iterdir()):
            if path.name=='.git':continue
            name=(Path(relative)/path.name).as_posix();output=destination/name
            if name in replacements:
                output.write_text(replacements[name])
                if name in ('configure','hw/scripts/gen_sources.sh'):output.chmod(0o755)
            elif any(key.startswith(name+'/') for key in replacements):fill(name)
            else:output.symlink_to(path,target_is_directory=path.is_dir())
    fill('')
    return list(replacements)


def validate_proof(proof,rtl_digest):
    if (proof.get('status')!='GPU_MULTIPLIER_LOCAL_DIFFERENTIAL_STAGE_PASS'
        or proof.get('records')!=43211 or proof.get('mutants_killed')!=4
        or proof.get('latency_before')!=3 or proof.get('latency_after')!=3
        or proof.get('stall_checks',0)<10000
        or set(proof.get('seeds',{}))!={str(i) for i in range(1,11)}
        or proof.get('bindings',{}).get(str(ROOT/'integration/student-mini/gpu_signed33_mul3.sv'))!=rtl_digest):
        raise ValueError('complete exact-source multiplier differential required')

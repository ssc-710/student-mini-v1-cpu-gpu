"""One checked change to the mapped GPU's existing cache pipeline parameter."""
import re


def pipeline_icache(source):
    # sv2v keeps cache-bank LATENCY as a parameter, including its data-deferral
    # register generate. Change the socket's ICACHE instance only, not defaults,
    # DCACHE, arithmetic latency, memory geometry or generated lookup logic.
    blocks = list(re.finditer(
        r'// expanded module instance: icache\s+(.*?)if \(1\) begin : icache\b',
        source, re.S))
    if len(blocks) != 1:
        raise ValueError('exactly one mapped icache instance required')
    block = blocks[0]
    prefixes = re.findall(r'localparam (_param_[A-F0-9]+)_CACHE_SIZE = 16384;', block[1])
    if len(prefixes) != 1:
        raise ValueError('frozen 16 KiB icache required')
    prefix = prefixes[0]
    for field, value in [('NUM_WAYS', '4'), ('NUM_BANKS', '1'), ('WRITE_ENABLE', '0')]:
        if block[1].count(f'localparam {prefix}_{field} = {value};') != 1:
            raise ValueError('frozen icache geometry changed')
    old = f'localparam {prefix}_LATENCY = 2;'
    new = f'localparam {prefix}_LATENCY = 3;'
    if block[1].count(old) != 1 or source.count(old) != 1:
        raise ValueError('original two-stage icache required')
    if 'localparam PIPE_EX = LATENCY - 2;' not in source:
        raise ValueError('existing data-deferral pipeline absent')
    return source.replace(old, new, 1)


def replay_producer(source, root):
    from scripts.run_student_mini_gpu_repaired_replay import derive
    value = derive(source, root)
    needle = 'paths=[Path(__file__),'
    if value.count(needle) != 1:
        raise ValueError('whole replay binding seam changed')
    return value.replace(needle, needle+"ROOT/'scripts/student_mini_gpu_icache_pipeline.py',")

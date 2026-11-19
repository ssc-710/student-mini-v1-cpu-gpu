"""Harness-only warm reset of the actual ASIC reset pin; preserve external RAM."""
import re
from scripts.resume_student_mini_interrupted import replace_once
from scripts.assemble_student_mini_cpu_results import parse


def bridge_source(source):
    source = replace_once(source, 'module cpu_boundary_replay(input wire sys_clk,',
                          'module cpu_boundary_replay(input wire sys_clk,input wire force_reset_i,')
    return replace_once(source, '.asic_reset_i(independent_memory.build_soc_coursesimsoc_int_rst)',
                        '.asic_reset_i(force_reset_i | independent_memory.build_soc_coursesimsoc_int_rst)')


def driver_source(source):
    changes = {
        '  device->sys_clk = 0;': '  device->force_reset_i = 0;\n  device->sys_clk = 0;',
        '  bool baseline = false, native = false;':
            '  bool baseline = false, native = false;\n  unsigned phase = 0;\n  uint64_t release_cycle = 0;\n  std::cout << "WARM_PHASE_BEGIN phase=0\\n" << std::flush;',
        '    advance(cycle * 10000 + 5000);':
            '    if (phase == 1 && device->force_reset_i && cycle == release_cycle) {\n'
            '      device->force_reset_i = 0;\n'
            '      std::cout << "WARM_RESET_RELEASE held_cycles=8\\nWARM_PHASE_BEGIN phase=1\\n" << std::flush;\n'
            '    }\n    advance(cycle * 10000 + 5000);',
        '    bool valid = device->uart_valid;': '    bool valid = device->uart_valid && !device->force_reset_i;',
        '      std::cout << "CPU_BOUNDARY_REPLAY_COMPLETE cycles=" << cycle + 1 << \'\\n\';\n      device->final();\n      return 0;':
            '      std::cout << "WARM_PHASE_COMPLETE phase=" << phase << " cycles=" << cycle + 1 << \'\\n\' << std::flush;\n'
            '      if (phase == 0) {\n'
            '        phase = 1; device->force_reset_i = 1; release_cycle = cycle + 9;\n'
            '        baseline = false; native = false; next_ordinal = 0; line.clear();\n'
            '        std::cout << "WARM_RESET_ASSERT\\n" << std::flush;\n'
            '      } else {\n'
            '        std::cout << "WARM_REPLAY_COMPLETE phases=2\\n" << std::flush;\n'
            '        device->final(); return 0;\n'
            '      }',
    }
    # The clock assignment also occurs inside the cycle loop; match indentation
    # plus newline so only the initialization is changed.
    first = '  device->sys_clk = 0;'
    source = replace_once(source, '\n'+first+'\n', '\n'+changes.pop(first)+'\n')
    for old, new in changes.items():
        source = replace_once(source, old, new)
    return source


def read_phases(path):
    phases = [[], []]; markers = []; current = None
    with path.open() as source:
        for line in source:
            line = line.rstrip('\r\n')
            if line.startswith('WARM_'):
                markers.append(line)
                if line.startswith('WARM_PHASE_BEGIN phase='):
                    if current is not None: raise ValueError('overlapping reset phases')
                    current = int(line.rsplit('=', 1)[1])
                    if current not in (0, 1): raise ValueError('invalid reset phase')
                elif line.startswith('WARM_PHASE_COMPLETE '):
                    current = None
            elif line.startswith(('STUDENT_CPU ', 'STUDENT_CPU_', 'STUDENT_NATIVE_')):
                if current is None: raise ValueError('UART record outside an execution phase')
                phases[current].append(line)
    patterns = [r'WARM_PHASE_BEGIN phase=0', r'WARM_PHASE_COMPLETE phase=0 cycles=\d+',
                r'WARM_RESET_ASSERT', r'WARM_RESET_RELEASE held_cycles=8',
                r'WARM_PHASE_BEGIN phase=1', r'WARM_PHASE_COMPLETE phase=1 cycles=\d+',
                r'WARM_REPLAY_COMPLETE phases=2']
    if len(markers) != len(patterns) or any(not re.fullmatch(p, m) for p, m in zip(patterns, markers)):
        raise ValueError('missing, reordered or repeated physical-reset execution markers')
    return ['\n'.join(lines)+'\n' for lines in phases]


def compare_baselines(reference, phases):
    expected = parse(reference, 1000)
    counters = ('cycles','instructions','ibus_bytes','dbus_bytes','dma_bytes')
    result = []
    for phase in phases:
        actual = parse(phase, 1000)
        for before, after in zip(expected, actual, strict=True):
            if {k:v for k,v in before.items() if k not in counters} != {k:v for k,v in after.items() if k not in counters}:
                raise ValueError('cold/warm baseline payload, primitive, status or selection differs')
        result.append(actual)
    return result

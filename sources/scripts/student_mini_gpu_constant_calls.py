"""Equivalent constant-call lowering for the frozen 1-core/2-warp export.

Only two scheduler localparams are lowered. Runtime calls and function bodies
stay untouched. Refuse a changed function signature/body instead of guessing.
"""
import re


def lower_scheduler_constants(source):
    changes = []
    for suffix, value, body in (
        ('isw', "1'b0", 'VX_gpu_pkg_wid_to_isw = 0;'),
        ('wis', 'i[0]', 'VX_gpu_pkg_wid_to_wis = wid >> VX_gpu_pkg_ISSUE_ISW_BITS;'),
    ):
        name = 'VX_gpu_pkg_wid_to_' + suffix
        pattern = rf'localparam\s+\[0:0\]\s+{suffix}\s*=\s*{name}\(i\);'
        matches = list(re.finditer(pattern, source))
        if len(matches) != 1:
            raise ValueError('ambiguous scheduler constant call: ' + suffix)
        call = matches[0]
        functions = list(re.finditer(rf'function\s+automatic\s+\[0:0\]\s+{name};[\s\S]*?endfunction', source[:call.start()]))
        if not functions:
            raise ValueError('missing function: ' + name)
        clean = re.sub(r'//[^\n]*|/\*[\s\S]*?\*/', '', functions[-1].group())
        expected = f'function automatic [0:0] {name}; input reg [0:0] wid; begin {body} end endfunction'
        if re.sub(r'\s+', '', clean) != re.sub(r'\s+', '', expected):
            raise ValueError('function semantics changed: ' + name)
        if suffix == 'wis':
            parameters = re.findall(r'localparam\s+VX_gpu_pkg_ISSUE_ISW_BITS\s*=\s*(\d+)\s*;', source[:call.start()])
            if not parameters or parameters[-1] != '0':
                raise ValueError('not the frozen single-issue profile')
        changes.append((call.start(), call.end(), f'localparam [0:0] {suffix} = {value};'))
    for start, end, replacement in sorted(changes, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source

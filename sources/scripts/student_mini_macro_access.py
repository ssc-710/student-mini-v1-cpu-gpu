"""Validate complete macro signal access observations, not physical acceptance."""
import re

MASTERS=frozenset(('vortex_dp_80x64_w4','vortex_sp_32x256_w1','vortex_sp_32x512_w4',
                  'vortex_sp_32x1024_w4','vortex_sp_64x128_w8','vortex_sp_128x128_w16'))


def decoded(value):
    if not re.fullmatch(r'(?:[0-9a-f]{2})+',value):raise ValueError('invalid pin/name encoding')
    text=bytes.fromhex(value).decode('utf-8')
    if not text or any(ord(c)<32 for c in text):raise ValueError('invalid decoded pin/name')
    return text


def parse(text,platform):
    expected={'cpu':29,'gpu':37}
    if platform not in expected:raise ValueError('CPU/GPU macro boundary required')
    macros={};pins=[];unused=[];seen=set();terminal=[]
    for line in text.splitlines():
        if not line.startswith('MINI_ACCESS_'):continue
        m=re.fullmatch(r'MINI_ACCESS_MACRO instance=([0-9a-f]+) master=([0-9a-f]+)',line)
        if m:
            name,master=map(decoded,m.groups())
            allowed={'vortex_sp_32x1024_w4'} if platform=='cpu' else MASTERS
            if name in macros or master not in allowed:raise ValueError('duplicate/unqualified macro')
            macros[name]=master;continue
        m=re.fullmatch(r'MINI_ACCESS_PIN instance=([0-9a-f]+) pin=([0-9a-f]+) net=([0-9a-f]+) access_points=(\d+) routed=([01])',line)
        if m:
            name,pin,net=map(decoded,m.groups()[:3]);key=(name,pin)
            if name not in macros or key in seen:raise ValueError('duplicate pin or missing macro')
            seen.add(key)
            pins.append(dict(instance=name,pin=pin,net=net,access_points=int(m[4]),routed=m[5]=='1'))
            continue
        m=re.fullmatch(r'MINI_ACCESS_UNUSED instance=([0-9a-f]+) pin=([0-9a-f]+)',line)
        if m:
            key=tuple(map(decoded,m.groups()))
            if key[0] not in macros or key in seen:raise ValueError('duplicate unused pin or missing macro')
            seen.add(key);unused.append(dict(instance=key[0],pin=key[1]));continue
        m=re.fullmatch(r'MINI_ACCESS_COMPLETE macros=(\d+) connected_signals=(\d+) unused_signals=(\d+)',line)
        if not m:raise ValueError('malformed access observation')
        terminal.append(tuple(map(int,m.groups())))
    if len(macros)!=expected[platform] or terminal!=[(len(macros),len(pins),len(unused))]:
        raise ValueError('incomplete/duplicate access inventory')
    if {p['instance'] for p in pins}!=set(macros):raise ValueError('macro has no observed connected signal pins')
    failed=[p for p in pins if p['access_points']==0 or not p['routed']]
    return dict(status='HOLD' if failed else 'MACRO_CONNECTED_SIGNAL_ACCESS_OBSERVED',
                platform=platform,macros=macros,pins=pins,unused_pins=unused,failed_pins=failed,
                physical_evidence_complete=False,
                reason='Database observations only; source/DEF/ODB SHA, complete route, supply, geometry and power qualification remain')

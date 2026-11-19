"""Checked core-side packing correction; external adapter ABI is unchanged."""
import re


def restore_core_port_order(source):
    for name in ('req_byteen','req_addr','req_data','req_tag','rsp_data','rsp_tag'):
        anchor='vx_'+name+'[port_index*'
        if source.count(anchor)!=1:
            raise ValueError('unknown core payload slice: '+name)
        source=source.replace(anchor,'vx_'+name+'[(MEM_PORTS-1-port_index)*')
    return source


def verify_export_order(source):
    """Require the actual two-port sv2v ABI, not an assumed Verilog endian."""
    for name,width in (('addr',26),('data',512),('tag',10),('byteen',64)):
        pattern=rf'mem_req_{name}\[\(1 - i\) \* {width}\+:{width}\]'
        if not re.search(pattern,source):
            raise ValueError('export request order differs: '+name)
    for name,width in (('data',512),('tag',10)):
        if not re.search(rf'mem_rsp_{name}\[\(1 - i\) \* {width}\+:{width}\]',source):
            raise ValueError('export response order differs: '+name)
    if not re.search(r'output wire \[0:1\] mem_req_valid;',source):
        raise ValueError('export flag order differs')

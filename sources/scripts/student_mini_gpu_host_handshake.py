"""Acknowledge a physical DCR response before issuing the next host command."""


def drain_read_response(source):
    anchor='''    *value = device_->dcr_rsp_data;
    return 0;
'''
    if source.count(anchor)!=1:raise ValueError('unknown pinned simulator DCR read seam')
    return source.replace(anchor,'''    *value = device_->dcr_rsp_data;
    // The physical command adapter is still in RESP. Complete its ready/valid
    // transfer before a subsequent API call can issue another command.
    this->tick();
    return 0;
''')

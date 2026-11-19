"""Private DCR read-payload preservation candidate for the frozen adapter.

Vortex read payload carries MPM class/index/core selection. Zeroing it is not a
valid read transformation. This helper alone does not fix whole-GPU liveness.
"""


def preserve_read_payload(source):
    old="""              CMD_DCR_READ: begin
                dcr_req_valid_o <= 1'b1;
                dcr_req_rw_o <= 1'b0;
                dcr_req_addr_o <= host_cmd_addr_i;
                dcr_req_data_o <= '0;
                state_q <= WAIT_DCR;
              end"""
    if source.count(old)!=1:raise ValueError('DCR read payload seam changed')
    return source.replace(old,old.replace("dcr_req_data_o <= '0;","dcr_req_data_o <= host_cmd_data_i;"))


def preserve_read_contract(harness):
    old="assert(dcr_data==($past(host_kind)==0?$past(host_data):32'b0));"
    if harness.count(old)!=1:raise ValueError('frozen adapter contract differs')
    return harness.replace(old,'assert(dcr_data==$past(host_data));')


def drop_read_payload(source):
    start=source.index('              CMD_DCR_READ: begin')
    stop=source.index('              end',start)
    part=source[start:stop]
    if part.count('dcr_req_data_o <= host_cmd_data_i;')!=1:raise ValueError('read payload mutation seam differs')
    return source[:start]+part.replace('dcr_req_data_o <= host_cmd_data_i;',"dcr_req_data_o <= '0;")+source[stop:]

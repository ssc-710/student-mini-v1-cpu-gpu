import os
from pathlib import Path
import subprocess
import pytest
from scripts.student_mini_gpu_host_handshake import drain_read_response

ROOT=Path(__file__).resolve().parents[1]

def test_only_one_acknowledgement_tick_is_added():
    source='    *value = device_->dcr_rsp_data;\n    return 0;\n'
    result=drain_read_response(source)
    assert result.count('this->tick();')==1
    with pytest.raises(ValueError):drain_read_response(result)

def test_full_replay_derivation_changes_host_only():
    from scripts.run_student_mini_gpu_host_replay import derive
    from scripts.run_student_mini_gpu_port_replay import derive as port_derive
    source=port_derive((ROOT/'scripts/run_student_mini_gpu_physical_replay.py').read_text(),ROOT,Path('/proof/completion.json'))
    result=derive(source)
    compile(result,'derived-host-replay','exec')
    assert 'drain_read_response(timing_processor(' in result
    assert 'preserve_read_payload' not in result
    with pytest.raises(ValueError):derive(result)

@pytest.mark.skipif(os.name=='nt',reason='pinned four-state simulator')
def test_exact_pinned_driver_schedule_reproduces_real_bridge_assertion(tmp_path):
    tool=Path('/home/soclab/tools/oss-cad-suite/bin/iverilog')
    if not tool.exists():pytest.skip('pinned simulator absent')
    stub=(ROOT/'tests/rtl/student_mini_gpu_port_packing.sv').read_text().split('module bench;')[0]
    original='assign dcr_rsp_valid=0;assign dcr_rsp_data=0;assign busy=0;'
    assert stub.count(original)==1
    stub=stub.replace(original,'''reg response_valid=0;reg [31:0] response_data=0;
    assign dcr_rsp_valid=response_valid;assign dcr_rsp_data=response_data;assign busy=0;
    always @(posedge clk) begin
      if(reset) begin response_valid<=0;response_data<=0;end
      else begin response_valid<=dcr_req_valid && !dcr_req_rw;response_data<={20'b0,dcr_req_addr};end
    end''')
    source=tmp_path/'core.sv';source.write_text(stub);binary=tmp_path/'bench.vvp'
    rtl=[ROOT/'tests/rtl'/name for name in ('student_mini_gpu_host_read.sv','student_mini_gpu_physical_bridge.sv')]
    rtl += [ROOT/'shared/rtl'/name for name in ('vortex_physical_top.sv','vortex_command_adapter.sv','vortex_memory_adapter.sv')]
    subprocess.run([str(tool),'-g2012','-s','bench','-o',str(binary),str(source),*map(str,rtl)],check=True,capture_output=True,timeout=30)
    for drain in (0,1):
        result=subprocess.run([str(tool.with_name('vvp')),str(binary),f'+drain={drain}'],capture_output=True,text=True,timeout=10)
        if not drain:assert result.returncode!=0 and 'host ignored physical command backpressure' in result.stdout
        else:assert result.returncode==0 and 'GPU_HOST_READ_HANDSHAKE_PASS reads=64' in result.stdout

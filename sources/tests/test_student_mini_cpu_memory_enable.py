"""Reproduce the CPU inventory's unabsorbed read-enable mux, using real Yosys."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'tests/rtl/student_mini_enabled_memory.sv'


@pytest.mark.parametrize('optimization,expected_clocked', [('', 0), ('opt_dff; opt_clean;', 1)])
def test_enable_mux_requires_dff_optimization(tmp_path, optimization, expected_clocked):
    yosys = shutil.which('yosys')
    if not yosys:
        pytest.skip('locked WSL Yosys required')
    output = tmp_path/'memory.json'
    command = (f'read_verilog -sv "{FIXTURE.as_posix()}"; hierarchy -top enabled_memory; '
               f'proc; {optimization} memory_dff; memory_collect; opt_clean; '
               f'check -assert; write_json "{output.as_posix()}"')
    run = subprocess.run([yosys, '-Q', '-T', '-p', command], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout+run.stderr
    design = json.loads(output.read_text())['modules']['enabled_memory']
    memories = [cell for cell in design['cells'].values() if cell['type'] == '$mem_v2']
    assert len(memories) == 1
    params = memories[0]['parameters']
    assert int(params['RD_CLK_ENABLE'], 2) == expected_clocked, run.stdout
    assert int(params['WR_CLK_ENABLE'], 2) == 1
    assert int(params['WIDTH'], 2) == 8
    assert int(params['SIZE'], 2) == 16
    if expected_clocked:
        assert int(params['RD_CLK_POLARITY'], 2) == 1
        assert memories[0]['connections']['RD_EN'] == design['ports']['read_enable']['bits']
    else:
        assert "mux select that doesn't seem to correspond to transparency logic" in run.stdout

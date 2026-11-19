import os
from pathlib import Path
import sys

root=Path(__file__).resolve().parent.parent/'sources'
work=Path('/mnt/d/sqrt3-rerun/baselines-cpu')
work.mkdir(exist_ok=True)
sys.path.insert(0,str(root))
os.cpu_count=lambda:2
os.environ.update(COURSE_ROOT=str(root),COURSE_STUDENT_MINI='1',COURSE_VERILATOR_BIN='/usr/bin/verilator',MAKEFLAGS='-j2')
os.environ['PATH']=str(Path(sys.executable).parent)+':'+os.environ['PATH']
os.environ['PYTHONPATH']=str(Path(sys.prefix)/'lib/python3.12/site-packages')
from integration.litex.soc import build_soc
from litex.soc.integration.builder import Builder
original=Builder.add_software_package
def package(self,name,*args,**kwargs):
    if name=='bios':
        return original(self,name,str(root.parent/'rerun_sqrt3/baseline_bios'))
    return original(self,name,*args,**kwargs)
Builder.add_software_package=package
build_soc(output_dir=work/'soc',run=False,cpu_b0=True,control_smoke=True,cpu_variant='full',
          student_mini_image=Path(sys.argv[1]),student_mini_count=1000)
print('BASELINE_CPU_BUILD_COMPLETE',flush=True)

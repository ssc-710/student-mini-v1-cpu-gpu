from pathlib import Path
import subprocess
import time

root = Path(__file__).resolve().parent.parent
library = root / 'rerun_sqrt3/vortex-source/third_party/ramulator/libramulator.so'
for _ in range(900):
    if library.is_file():
        break
    time.sleep(2)
else:
    raise TimeoutError('Ramulator build did not finish')
subprocess.run(['python3', str(root / 'sources/scripts/run_student_mini_native_gpu.py'),
                '--work', str(root / 'sources/build/student-mini/native-gpu/fc14e0f618eacaeb78fd0df4626bab2fd19315064842dab6b7c12084b13bb61c')], check=True)

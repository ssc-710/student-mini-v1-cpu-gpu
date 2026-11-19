import hashlib
from pathlib import Path
import urllib.request

here=Path(__file__).resolve().parent
url='https://codeload.github.com/vortexgpgpu/vortex/tar.gz/b8c5a24336026d9d029a67197160eee6b017f262'
path=here/'downloads/vortex-b8c5a243.tar.gz'
with urllib.request.urlopen(url, timeout=90) as r, path.open('wb') as f:
    for block in iter(lambda:r.read(1024*1024), b''):f.write(block)
print(path, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest(), flush=True)

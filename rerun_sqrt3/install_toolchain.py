"""Install only locked prebuilt components into this isolated rerun folder."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tarfile
import time
import urllib.request
import sys

HERE = Path(__file__).resolve().parent
REV = 'd0e3fed1dbc4bbc882ea7d453d339b8dde874c13'
BASE = 'https://raw.githubusercontent.com/vortexgpgpu/vortex-toolchain-prebuilt/'+REV+'/'
cache = HERE/'downloads'
cache.mkdir(exist_ok=True)
tools = HERE/'tools'
tools.mkdir(exist_ok=True)
with urllib.request.urlopen('https://api.github.com/repos/vortexgpgpu/vortex-toolchain-prebuilt/git/trees/'+REV+'?recursive=1', timeout=60) as r:
    tree = json.load(r)['tree']
components = ['llvm-vortex', 'riscv32-gnu-toolchain', 'pocl', 'chipstar', 'libcrt32', 'libc32', 'verilator']
entries = [x for x in tree if x['type']=='blob' and x['path'].split('/')[0] in components
           and ('/ubuntu/focal/' in x['path'] or x['path'].startswith(('libcrt32/', 'libc32/')))]

def fetch(entry):
    path = cache/(entry['path'].replace('/', '_'))
    if path.exists() and path.stat().st_size == entry['size']:
        return path
    for attempt in range(4):
        try:
            print('DOWNLOAD', entry['path'], flush=True)
            with urllib.request.urlopen(BASE+entry['path'], timeout=90) as r, path.open('wb') as out:
                while True:
                    chunk = r.read(1024*1024)
                    if not chunk: break
                    out.write(chunk)
            assert path.stat().st_size == entry['size']
            h = hashlib.sha1()
            h.update(('blob '+str(entry['size'])+'\0').encode())
            with path.open('rb') as f:
                for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
            assert h.hexdigest() == entry['sha'], 'upstream Git blob mismatch'
            print('VERIFIED', entry['path'], flush=True)
            return path
        except Exception as e:
            print('RETRY', attempt, repr(e), flush=True)
            if attempt == 3: raise
            time.sleep(2)

with ThreadPoolExecutor(max_workers=4) as pool:
    list(pool.map(fetch, entries))
for component in components:
    stamp = tools/(component+'.installed.json')
    if stamp.exists(): continue
    parts = sorted([x for x in entries if x['path'].startswith(component+'/')], key=lambda x:x['path'])
    archive = cache/(component+'.tar.bz2')
    with archive.open('wb') as out:
        for part in parts:
            with (cache/part['path'].replace('/', '_')).open('rb') as f:
                for chunk in iter(lambda:f.read(1024*1024),b''):out.write(chunk)
    print('EXTRACT', component, flush=True)
    with tarfile.open(archive) as tar:
        if sys.version_info >= (3, 12):
            tar.extractall(tools, filter='data')
        else:
            # Windows only downloads; extraction must preserve Linux symlinks.
            print('READY_FOR_WSL_EXTRACTION', archive, flush=True)
            continue
    stamp.write_text(json.dumps(dict(revision=REV, parts=parts),indent=2))
print('TOOLCHAIN_INSTALLED', flush=True)

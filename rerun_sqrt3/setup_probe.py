"""Read-only upstream/environment inventory for the sqrt(3) rerun."""
import json
import urllib.request

for repo, endpoint in [
    ('vortexgpgpu/vortex-toolchain-prebuilt', 'releases'),
    ('vortexgpgpu/vortex', 'git/trees/b8c5a24336026d9d029a67197160eee6b017f262?recursive=1'),
]:
    try:
        with urllib.request.urlopen('https://api.github.com/repos/'+repo+'/'+endpoint) as r:
            data = json.load(r)
        if endpoint == 'releases':
            for release in data:
                print('RELEASE', release['tag_name'])
                for a in release['assets']:
                    print(a['name'], a['size'], a['browser_download_url'])
        else:
            for entry in data.get('tree', []):
                if any(s in entry['path'] for s in ('toolchain', 'install', 'blackbox')):
                    print('SOURCE', entry['path'])
            print('TREE_STATUS', data.get('message', 'OK'))
    except Exception as e:
        print(repo, type(e).__name__, str(e))

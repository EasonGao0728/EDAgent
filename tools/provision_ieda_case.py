"""Fetch a small, pinned official iEDA/Sky130 fixture; verify Git blob hashes."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REVISION = '460c656e04826d96d883331c323a6cf960d6e82d'
DEST = ROOT / 'third_party/ieda-reference'
BASE = f'https://raw.githubusercontent.com/OSCC-Project/iEDA/{REVISION}/'

def git_hash(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

def main():
    tree = json.loads((ROOT/'.cache/ieda/release-era-tree.json').read_text(encoding='utf-8'))['tree']
    foundry = 'scripts/foundry/sky130/'
    required = {'LICENSE', 'scripts/hello.tcl', foundry+'lef/LICENSE', foundry+'lib/LICENSE',
        foundry+'sdc/LICENSE', foundry+'lef/sky130_fd_sc_hs.tlef',
        foundry+'lef/sky130_fd_sc_hs_merged.lef', foundry+'lib/sky130_fd_sc_hs__tt_025C_1v80.lib',
        foundry+'sdc/gcd.sdc'}
    files = [x for x in tree if x['type']=='blob' and (x['path'] in required or
        (x['path'].startswith('scripts/design/sky130_gcd/') and x.get('size',0)<100_000))]
    def fetch(item):
        path = DEST/item['path']; path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and git_hash(path.read_bytes()) == item['sha']: return item
        for attempt in range(3):
            try:
                with urlopen(BASE+item['path'],timeout=120) as response: data=response.read()
                if git_hash(data)!=item['sha']: raise ValueError('Git blob hash mismatch')
                path.write_bytes(data)
                print('verified',item['path'],len(data),flush=True)
                return item
            except Exception:
                if attempt==2: raise
                time.sleep(2)
    with ThreadPoolExecutor(max_workers=4) as pool: fetched=list(pool.map(fetch,files))
    manifest={'repository':'https://github.com/OSCC-Project/iEDA','revision':REVISION,
              'note':'Release-era fixture; image build commit is not published, compatibility verified by execution.',
              'files':[{k:x[k] for k in ['path','sha','size']} for x in fetched]}
    (DEST/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('COMPLETE',len(fetched),flush=True)

if __name__=='__main__': main()

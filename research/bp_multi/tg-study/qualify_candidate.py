"""Resume an explicitly selected frozen build through canaries and the PA handoff."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

here=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--build-dir',type=Path,required=True)
    parser.add_argument('--candidate-receipt',default='candidate.json')
    parser.add_argument('--fanout-first',action='store_true')
    opts=parser.parse_args()
    start=time.monotonic()
    while True:
        path=opts.build_dir/opts.candidate_receipt
        if path.is_file():
            meta=json.loads(path.read_bytes())
            if meta['status']=='failed':raise RuntimeError('Build failed; see '+str(path))
            sha=meta.get('binary_sha256','')
            binary=opts.build_dir/('frozen-'+sha[:16])/'iEDA'
            if len(sha)==64 and (binary.parent/'snapshot.json').is_file():break
        if time.monotonic()-start>3600:raise TimeoutError('No frozen build published')
        time.sleep(5)
    print('Validating frozen candidate',sha,flush=True)
    cases = [('fanout','lazy')] if opts.fanout_first else []
    for case,mode in cases+[('extreme','lazy'),('extreme','eager'),('macro-io','lazy'),('macro-io','eager'),('full','lazy')]:
        subprocess.run([sys.executable,str(here/'verify_pa.py'),'run','--case',case,'--mode',mode,
                        '--binary',str(binary),'--sha',sha],check=True)


if __name__=='__main__':main()

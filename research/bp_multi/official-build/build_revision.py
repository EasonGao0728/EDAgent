"""Apply a reviewed patch and compile the next frozen candidate in the personal tree."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('version', type=int)
    cli.add_argument('patch_name')
    args = cli.parse_args()
    if args.version < 2 or not re.fullmatch(r'router-[a-z0-9-]+', args.patch_name):
        cli.error('Use the next candidate version and a staged router-* patch')
    root = Path(__file__).resolve().parent
    parent = 'candidate' if args.version == 2 else 'candidate-v'+str(args.version-1)
    previous = json.loads((root/(parent+'.json')).read_bytes())
    assert previous['status'] == 'completed'
    previous_snapshot = root / ('frozen-' + previous['binary_sha256'][:16]) / 'snapshot.json'
    assert json.loads(previous_snapshot.read_bytes())['binary_sha256'] == previous['binary_sha256']
    revision = 'candidate-v'+str(args.version)
    for argv in (['apply_port.py', args.patch_name], ['build_candidate.py', revision], ['freeze_candidate.py', revision]):
        subprocess.run([sys.executable, *argv], cwd=root, check=True)


if __name__ == '__main__':
    main()

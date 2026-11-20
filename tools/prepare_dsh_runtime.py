"""Extract the installed DSH runtime, preserving original package/license files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct

ROOT=Path(__file__).resolve().parents[1]
default_archive=Path('D:/dsh/resources/app.asar')
output=ROOT/'.cache/dsh-runtime'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=default_archive)
    source=parser.parse_args().archive.resolve(strict=True)
    output.mkdir(parents=True,exist_ok=True)
    with source.open('rb') as stream:
        header=struct.unpack('<4I',stream.read(16))
        tree=json.loads(stream.read(header[3]));base=8+header[1]
        def extract(node,rel):
            target=(output/rel).resolve()
            if not target.is_relative_to(output.resolve()):raise ValueError('unsafe archive path')
            if 'files' in node:
                for key,value in node['files'].items():extract(value,rel/key)
            elif 'link' in node:raise ValueError('archive links require explicit handling')
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                if node.get('unpacked'):shutil.copyfile(Path(str(source)+'.unpacked')/rel,target)
                else:
                    stream.seek(base+int(node['offset']));data=stream.read(node['size'])
                    if len(data)!=node['size']:raise ValueError('truncated archive')
                    target.write_bytes(data)
        extract(tree['files']['dsh'],Path('dsh'))
    manifest={'source':str(source),'sha256':hashlib.file_digest(source.open('rb'),'sha256').hexdigest(),
              'version':json.loads((output/'dsh/package.json').read_text())['version']}
    (output/'extraction.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest))

if __name__=='__main__':main()

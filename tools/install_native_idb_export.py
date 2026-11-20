"""Freeze a successful native build; qualification is a separate real execution."""
import hashlib,json,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
binary=ROOT/'.cache/idb-export-build/build/ieda-idb-export'
dest=ROOT/'environments/ieda-export/bin';dest.mkdir(exist_ok=True)
shutil.copyfile(binary,dest/binary.name)
docker=['D:/Docker/resources/bin/docker.exe','--config',str(ROOT/'.cache/ieda/docker-public'),'--host','npipe:////./pipe/dockerDesktopLinuxEngine']
image=subprocess.check_output(docker+['image','inspect','aieda/idb-build:public-20261106','--format','{{.Id}}'],text=True).strip()
manifest={'source':'https://github.com/OSCC-Project/iEDA','source_commit':'65c39fd28aa0dc0cdd56325df07f6e440069061b',
 'image':image,'executable':str((dest/binary.name).relative_to(ROOT)),
 'executable_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
 'patch_manifest':json.loads((ROOT/'.cache/idb-export-build/patch-manifest.json').read_text()),'qualified':False}
(dest.parent/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2))
print('Frozen candidate '+manifest['executable_sha256'])

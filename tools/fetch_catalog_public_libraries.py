"""Fetch only missing declared LEF/Liberty files from pinned public ORFS trees."""
import argparse
import hashlib
import json
import re
import subprocess
import urllib.request
from pathlib import Path

REPO = "The-OpenROAD-Project/OpenROAD-flow-scripts"
REVISIONS = {"nangate45": "73c804d45dc4084b05e0536dab69053b3bf9e591",
             "asap7": "5c9af09cf9bd79aa9f2864f9b721b31b659465f5"}


def materialize(matrix, destination):
    receipts = []
    for pdk, rev in REVISIONS.items():
        missing = sorted({name[5:] for case in matrix if case.get("pdk")==pdk
                          for name in case.get("missing",[]) if name.startswith("$PDK/")})
        if not missing:
            continue
        raw = subprocess.check_output(["gh","api",f"repos/{REPO}/git/trees/{rev}?recursive=1"])
        blobs = {e["path"]:e for e in json.loads(raw)["tree"] if e["type"]=="blob"}
        for rel in missing:
            if not re.fullmatch(r"(?:lib|lef)/[\w.-]+\.(?:lef|lib)",rel):
                raise ValueError("unexpected library path")
            name = "flow/platforms/"+pdk+"/"+rel
            blob = blobs[name]
            url = f"https://raw.githubusercontent.com/{REPO}/{rev}/{name}"
            target = destination / pdk / rel
            target.parent.mkdir(parents=True,exist_ok=True)
            data = target.read_bytes() if target.is_file() else None
            if data is None:
                with urllib.request.urlopen(url,timeout=60) as response:
                    data=response.read()
            if hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()!=blob["sha"]:
                raise ValueError("public Git blob mismatch: "+name)
            if not target.is_file():
                target.write_bytes(data)
            receipts.append(dict(file=pdk+"/"+rel,revision=rev,url=url,sha256=hashlib.sha256(data).hexdigest()))
    return receipts


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix",type=Path)
    parser.add_argument("destination",type=Path)
    args=parser.parse_args()
    print(json.dumps(materialize(json.loads(args.matrix.read_bytes()),args.destination),indent=2))

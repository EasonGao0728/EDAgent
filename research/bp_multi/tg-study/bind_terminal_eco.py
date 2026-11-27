"""Materialize an append-only, input-bound DR repair and verify every terminal group."""
from collections import defaultdict,Counter
from hashlib import sha256
import json
from pathlib import Path
import shutil
import struct
import sys
from analyze_dr_components import analyze


PARENT='dea12176e6bb0a2563a91ce56782ef537cc401731fb6d5b372477fe53e5a2734'
BINDING='80da2933df61da48ff06a0ef21173ab3746d25353e4a13a20b1628171221be03'
def digest(path):
    h=sha256()
    with path.open('rb') as f:
        for buf in iter(lambda:f.read(1<<20),b''):h.update(buf)
    return h.hexdigest()


def derive(old,dest,bridges,drop,partial=False):
    segments=defaultdict(list)
    grades=Counter()
    for row in bridges.read_text().splitlines():
        net,*coords,grade=map(int,row.split())
        assert grade in (0,1) and len(coords)==6
        p=tuple(coords[:3]);q=tuple(coords[3:])
        assert sum(a!=b for a,b in zip(p,q))==1 and (p[2]==q[2] or abs(p[2]-q[2])==1)
        segments[net].append(struct.pack('<6i',*coords))
        grades[grade]+=1
    assert len(segments)>=423 or (partial and segments)
    with old.open('rb') as src,dest.open('xb') as out:
        def number():return struct.unpack('<i',src.read(4))[0]
        def string():return src.read(number()).decode()
        assert [string(),string(),string()]==['ieda-route-state-v1','D12_4761',BINDING]
        n=number();src.read(8)
        assert n==78493
        for i in range(n):
            assert number()==i
            string();src.read(32)
            for _ in range(number()):number();string();src.read(20)
        pos=src.tell();src.seek(0);out.write(src.read(pos))
        for i in range(n):
            size=number();old_wires=src.read(24*size);extra=segments.get(i,[])
            excluded=drop.get(i,set())
            assert all(0<=j<size for j in excluded)
            out.write(struct.pack('<i',size-len(excluded)+len(extra)))
            if excluded:
                out.write(b''.join(old_wires[j*24:j*24+24] for j in range(size) if j not in excluded))
            else:out.write(old_wires)
            for wire in extra:out.write(wire)
        shutil.copyfileobj(src,out,1<<20)
    return grades


def certify(parent,folder):
    old=parent/'DR-batch.bin'
    assert digest(old)==PARENT
    new=folder/'terminal-repaired.bin'
    bridges=folder/'accepted.tsv'
    temp=folder/'terminal-repaired.candidate'
    stubproof=json.loads((folder/'native-clean/stub-proof.json').read_bytes())
    base=folder/'native-clean/pruned.bin'
    assert stubproof['original']==PARENT and stubproof['derived']==digest(base)
    assert stubproof['indexed_deletions']==digest(folder/'native-clean/removed-stubs.json')
    delta=folder/'displaced.tsv'
    drop=defaultdict(set)
    for line in delta.read_text().splitlines():
        i,j=map(int,line.split());drop[i].add(j)
    grades=derive(base,temp,bridges,drop)
    audit=folder/'terminal-audit.json'
    analyze(temp,audit)
    report=json.loads(audit.read_bytes())
    assert report['nets']==78493 and report['stage']=='D12_4761' and report['disconnected']==0 and report['binding']==BINDING
    assert not new.exists()
    temp.rename(new)
    proof=dict(original=PARENT,derived=digest(new),bridges=digest(bridges),terminal_audit=digest(audit),
               parent_receipt=digest(parent/'receipt.json'),binding=BINDING,nets=78493,repaired_nets=423,
               stub_pruning=stubproof,displaced_sha256=digest(delta),displaced_segments=sum(map(len,drop.values())),
               segments=sum(grades.values()),nominal_spacing_segments=grades[1],contact_screened_segments=grades[0])
    (folder/'terminal-eco-proof.json').write_text(json.dumps(proof,indent=2))
    print(proof)


if __name__=='__main__':certify(*map(Path,sys.argv[1:]))

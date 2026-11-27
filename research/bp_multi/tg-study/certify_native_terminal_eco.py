"""Check the native ECO against the prior candidate at per-net wire and patch granularity."""
from collections import Counter
import json
import os
from pathlib import Path
import struct
import sys
from analyze_dr_components import analyze
from bind_terminal_eco import digest,BINDING,PARENT


def header(f):
    def n():return struct.unpack('<i',f.read(4))[0]
    def s():return f.read(n())
    assert [s().decode(),s().decode(),s().decode()]==['ieda-route-state-v1','D12_4761',BINDING]
    nets=n();f.read(8)
    assert nets==78493
    for i in range(nets):
        assert n()==i
        s();f.read(32)
        for j in range(n()):
            assert n()==j
            s();f.read(20)
    pos=f.tell();f.seek(0)
    import hashlib
    return hashlib.sha256(f.read(pos)).hexdigest()


def certify(family):
    parent=family/'recovery-v17-r1'
    eco=family/'terminal-eco'
    probe=eco/'native-probe';old=probe/'partial.bin';new=probe/'terminal-native.bin'
    receipt=json.loads((probe/'receipt.json').read_bytes())
    assert receipt['passed'] and receipt['original']==digest(parent/'DR-batch.bin')==PARENT
    assert receipt['partial']==digest(old) and receipt['produced']==digest(new)
    assert receipt['requests']==digest(probe/'requests.txt') and receipt['screened']==digest(probe/'screened.tsv')
    authorized={}
    for line in receipt['rows']:
        i,w,p,v=map(int,line.split())
        assert i not in authorized
        authorized[i]={'wire':w,'patch':p,'local_markers':v}
    assert len(authorized)==20
    with old.open('rb') as a,new.open('rb') as b:
        assert header(a)==header(b)
        for key,unit in [('wire',24),('global',24),('patch',36)]:
            for net in range(78493):
                ca=struct.unpack('<i',a.read(4))[0];cb=struct.unpack('<i',b.read(4))[0]
                va=a.read(ca*unit);vb=b.read(cb*unit)
                expected=authorized.get(net,{}).get(key,0)
                assert cb-ca==expected,(key,net,ca,cb,expected)
                if va!=vb:
                    sa=Counter(va[j:j+unit] for j in range(0,len(va),unit))
                    sb=Counter(vb[j:j+unit] for j in range(0,len(vb),unit))
                    assert not sa-sb and sum((sb-sa).values())==expected,(key,net)
    audit=eco/'terminal-audit.json'
    analyze(new,audit)
    result=json.loads(audit.read_bytes())
    assert (result['disconnected'],result['nets'],result['binding'])==(0,78493,BINDING)
    candidate=eco/'terminal-repaired.bin'
    if candidate.exists():assert os.path.samefile(candidate,new)
    else:os.link(new,candidate)
    primary=eco/'accepted.tsv'
    if primary.exists():assert digest(primary)==receipt['screened']
    else:os.link(probe/'screened.tsv',primary)
    stub=json.loads((eco/'native-clean/stub-proof.json').read_bytes())
    proof=dict(original=PARENT,derived=digest(candidate),bridges=digest(primary),terminal_audit=digest(audit),
               parent_receipt=digest(parent/'receipt.json'),binding=BINDING,nets=78493,repaired_nets=423,
               native_eco_receipt=digest(probe/'receipt.json'),native_binary=receipt['binary'],
               native_supplemented_nets=len(authorized),native_segments=sum(v['wire'] for v in authorized.values()),
               native_patches=sum(v['patch'] for v in authorized.values()),stub_pruning=stub,
               native_local_markers_sum=sum(v['local_markers'] for v in authorized.values()))
    (eco/'terminal-eco-proof.json').write_text(json.dumps(proof,indent=2))
    print(proof)


if __name__=='__main__':certify(Path(sys.argv[1]))

"""Check that the real SRAM escape conductors are present before detailed routing."""
import json
import struct
from pathlib import Path

from test_route_checkpoint import RUNS, sha, study, table


def check(path):
    rows=[line.split() for line in table.read_text().splitlines()]
    expected={}
    for net,pin,x,y,a,b in rows:
        x,y,a,b=map(int,(x,y,a,b))
        for p,q in [((x,y,2),(a,y,2)),((a,y,2),(a,b,2))]:
            expected.setdefault(net,set()).add(tuple(sorted((p,q))))
    with path.open('rb') as stream:
        def ints(count):
            return struct.unpack('<'+'i'*count,stream.read(4*count))
        def name():
            n,=ints(1)
            assert 0<n<1048576
            return stream.read(n).decode()
        assert name()=='ieda-route-state-v1' and name()==path.stem
        binding=name()
        assert binding==sha(RUNS/'abutment-126.def')
        count,gw,gh=ints(3)
        names=[]
        for i in range(count):
            assert ints(1)==(i,)
            names.append(name())
            ints(8)
            for j in range(ints(1)[0]):
                assert ints(1)==(j,)
                name()
                ints(5)
        found=0
        missing=[]
        for net in names:
            segments=set()
            for _ in range(ints(1)[0]):
                u=ints(3)
                v=ints(3)
                segments.add(tuple(sorted((u,v))))
            needed=expected.get(net,set())
            found+=len(needed&segments)
            for xy in sorted(needed-segments):
                missing.append((net,xy))
    return dict(stage=path.stem,sha256=sha(path),pins=len(rows),nets=len(expected),distinct_expected=sum(map(len,expected.values())),
                found=found,missing=len(missing),examples=missing[:3])


if __name__=='__main__':
    print(json.dumps([check(study/'direct'/(stage+'.bin')) for stage in ('TG','LA')],indent=2))

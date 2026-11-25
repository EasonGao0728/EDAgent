"""Export transformed M1 ports for alternate access on already diagnosed nets."""
from pathlib import Path
import json
import sys
from prepare_terminal_eco import SOURCE,setup,PhysicalLibrary,read_def


if __name__=='__main__':
    parent,out=map(Path,sys.argv[1:])
    db=read_def(SOURCE);ref=setup()/'data'
    lib=PhysicalLibrary(ref/'input2.lef',[ref/f'input{i}.lef' for i in range(3,10)],db['units'])
    rows=json.loads((parent/'terminal-components.json').read_bytes())['failures']
    with out.open('w') as f:
        for net in rows:
            for pin in db['nets'][net['name']]:
                for l,*rect in lib.pin(db,*pin):
                    if l=='metal1':
                        assert all(v%2==0 for v in rect)
                        print(net['index'],*(v//2 for v in rect),file=f)

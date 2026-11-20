"""Equivalent single-PORT IO syntax for iDB readers with stale IO averages.

Geometry, names, connectivity, placements and orientations must be unchanged.
Multi-port/unsupported IO declarations fail closed. This is an input adapter,
not an IO placer and not a change to the iEDA binary.
"""
from pathlib import Path
import hashlib,json,re
from .def_validation import read_def,section


def convert(text,explicit=False):
    changed=0
    rows=section(text,'PINS')
    for row in rows:
        ports=re.findall(r'\+\s+PORT\b',row)
        placements=re.findall(r'\+\s+(?:PLACED|FIXED|COVER)\s*\(',row)
        if len(ports)>1:raise ValueError('Unsupported multi-PORT IO: '+row.split()[0])
        if not ports and not explicit:continue
        if len(placements)!=1 or re.search(r'\b(?:POLYGON|VIA|MASK|SPACING|DESIGNRULEWIDTH)\b',row):
            raise ValueError('Unsupported IO geometry: '+row.split()[0])
        if not re.search(r'\+\s+LAYER\s+\S+\s*\(\s*-?\d+\s+-?\d+\s*\)\s*\(\s*-?\d+\s+-?\d+\s*\)',row):
            raise ValueError('Missing rectangular IO shape')
        if explicit and not ports:
            new=re.sub(r'\+\s+LAYER\b','+ PORT + LAYER',row,count=1)
        elif not explicit and ports:
            new=re.sub(r'\+\s+PORT\s*','',row,count=1)
        else:continue
        # Exact complete record replacement; never touch NETS or cell ports.
        pattern=r'(^\s*-\s*)'+re.escape(row)+r'(\s*;)'
        text,n=re.subn(pattern,lambda m:m[1]+new+m[2],text,count=1,flags=re.M)
        if n!=1:raise ValueError('IO record replacement was not unique')
        changed+=1
    return text,changed


def equivalent(a,b):
    aa=read_def(a);bb=read_def(b)
    def pin_values(d):
        return {k:' '.join(re.sub(r'\+\s+PORT\b','',v).split()) for k,v in d['pins'].items()}
    return all(aa[k]==bb[k] for k in aa if k!='pins') and pin_values(aa)==pin_values(bb)


def write_equivalent(src,dst,explicit=False):
    src,dst=Path(src),Path(dst)
    if src.resolve()==dst.resolve():raise ValueError('Original DEF must not be overwritten')
    raw=src.read_bytes();text,count=convert(raw.decode('utf-8'),explicit)
    dst.parent.mkdir(parents=True,exist_ok=True);dst.write_text(text,encoding='utf-8')
    if not equivalent(src,dst):raise ValueError('IO adaptation changed physical/logical meaning')
    return {'input_sha256':hashlib.sha256(raw).hexdigest(),'output_sha256':hashlib.sha256(dst.read_bytes()).hexdigest(),
            'changed_pins':count,'explicit_port_output':explicit,'physical_semantics_equal':True}


def execute(stage,work,reference):
    """Opt-in corrected SWERV adapter; original backend and parent stay frozen."""
    from . import swerv_backend as b
    if stage not in ('macro_placement','fanout','placement','export_def','cts','to_drv','to_hold','legalization','timing'):
        raise ValueError('Unreviewed compatibility-study stage')
    work=Path(work);original_script=b.script;original_normalize=b.normalize_unplaced;events=[]
    def script(action,m):
        text=original_script(action,m);prev=b.PREVIOUS[action]
        src=work/'result'/(prev+'.def');dst=work/'native-inputs'/(action+'.def')
        events.append({'direction':'load','stage':action,**write_equivalent(src,dst)})
        old='/work/result/'+prev+'.def';new='/work/native-inputs/'+action+'.def'
        config_name={'fanout':'no_default_config_fixfanout.json','to_drv':'to_default_config_drv.json','to_hold':'to_default_config_hold.json'}.get(action)
        if config_name:
            config_path=work/'config'/config_name;cfg=json.loads(config_path.read_text())
            if cfg['file_path']['def_file']!=old:raise ValueError('Unexpected native config input')
            cfg['file_path']['def_file']=new;b.write(config_path,cfg)
            events.append({'direction':'config_input','stage':action,'key':'file_path.def_file','before':old,'after':new})
        if text.count('def_init -path '+old+'\n')!=1:raise ValueError('Unexpected load command')
        return text.replace('def_init -path '+old+'\n','def_init -path '+new+'\n')
    def normalize(path):
        value=original_normalize(path)
        raw=Path(path).with_suffix('.before-io-canonical.def')
        if raw.exists():raise ValueError('Do not overwrite an existing candidate output')
        Path(path).rename(raw)
        events.append({'direction':'export','stage':stage,**write_equivalent(raw,path,explicit=True)})
        return value
    b.script=script;b.normalize_unplaced=normalize
    try:
        result=b.execute(stage,work,reference)
        result['io_coordinate_compatibility']={'enabled':True,'events':events,'binary_modified':False}
        b.write(work/(stage+'-evidence.json'),result)
        return result
    finally:
        b.script=original_script;b.normalize_unplaced=original_normalize
        b.write(work/(stage+'-io-compatibility.json'),{'events':events})

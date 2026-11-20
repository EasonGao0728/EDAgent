"""Read SDC constants without executing Tcl. Supplement the read-only inventory."""
from pathlib import Path
import re,json,hashlib,os
ROOTS=(Path('/srv/benchmarks/iBench/benchmarks'),Path('/srv/edagent/main-agent-remote-v1'))

def profile(text):
    variables={};clocks=[];sources=[];units=[]
    for line in text.replace('\\\n',' ').splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        # Only literal numeric assignments; never eval Tcl, expressions or sourced files.
        m=re.fullmatch(r'set\s+(\w+)\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*;?\s*(?:#.*)?',line)
        if m:variables[m[1]]=float(m[2]);continue
        if line.startswith('source '):sources.append(line)
        if line.startswith('set_units '):units.append(line)
        if not re.match(r'create_(?:generated_)?clock\b',line):continue
        m=re.search(r'-period\s+(\S+)',line);token=m[1] if m else None;value=None;method=None
        if token:
            try:value=float(token);method='literal'
            except ValueError:
                if re.fullmatch(r'\$\w+',token) and token[1:] in variables:value=variables[token[1:]];method='prior_numeric_set'
        clocks.append({'statement':line,'period_token':token,'period_sdc_units':value,'resolution':method or 'unresolved'})
    return {'clocks':clocks,'numeric_variables':variables,'source_statements':sources,'set_units_statements':units,
            'tcl_executed':False,'unit':'SDC/library time units; not assumed ns across technologies',
            'limitations':'Only simple sequential numeric set and literal period; Tcl control flow, sourced files, clock object coverage not evaluated.'}

def main():
    assert os.getuid()==1015
    out=[]
    files=list((ROOTS[0]/'designs').glob('*/design.json'))+list((ROOTS[1]/'cases').rglob('manifest.json'))
    for f in sorted(files):
        if '/pdk/' in str(f):continue
        d=json.loads(f.read_text());own=f.name=='manifest.json';case=d.get('case_id',f.parent.name)
        base=ROOTS[1]/'third_party/ieda-reference' if own and case=='sky130_gcd' else f.parent
        p=(base/(d if own else d['inputs'])['sdc']).resolve()
        r={'case_id':case,'origin':'registered' if own else 'shared'}
        try:
            if not any(p==q or q in p.parents for q in ROOTS):raise ValueError('outside_authorized_roots')
            data=p.read_bytes();r.update(profile(data.decode()),source={'path':str(p),'sha256':hashlib.sha256(data).hexdigest()})
        except Exception as e:r.update(error=str(e))
        out.append(r)
    print(json.dumps(out))

if __name__=='__main__':main()

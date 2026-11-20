"""Prepare three provenance-preserving Sky130 AES packages; no reference DEF."""
from pathlib import Path
import hashlib,json,shutil,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from macro_agent.aes_netlist import parse

def prepare(name):
    source=ROOT/'runs/aes-p1-20261108/server-inputs'/name
    dst=ROOT/'cases/ibench'/name
    if dst.exists():raise ValueError('Case already exists: '+str(dst))
    original=json.loads((source/'design.json').read_text(encoding='utf-8'))
    netlist=source/original['inputs']['netlist']
    if name=='aes_core_sky130_t':netlist=source/'native.v'
    parsed=parse(netlist)
    if len(parsed['components'])!=original['input_preparation']['statistics']['cell_count']:
        raise ValueError('Source cell count changed')
    dst.mkdir(parents=True)
    for directory in ('netlist','sdc','provenance'):(dst/directory).mkdir()
    shutil.copyfile(netlist,dst/'netlist/design.v')
    shutil.copyfile(source/original['inputs']['sdc'],dst/'sdc/design.sdc')
    shutil.copyfile(source/'design.json',dst/'design.json')
    base=ROOT/'cases/ibench/gcd_legacy'
    for directory in ('pdk','config','script'):shutil.copytree(base/directory,dst/directory)
    for f in source.glob('normalization.json'):shutil.copyfile(f,dst/'provenance'/f.name)
    origins=[]
    for f in source.rglob('*'):
        if f.is_file():origins.append({'path':f.relative_to(source).as_posix(),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
    (dst/'provenance/source.json').write_text(json.dumps({'server_root':'/srv/benchmarks/iBench/benchmarks/designs/'+name,
        'files':origins,'pdk':'Existing public Sky130 HD bundle; not the inaccessible server Foundary symlink',
        'reference_def_used':False,'source_instances':len(parsed['components']),'aliases_checked':parsed['aliases_checked']},indent=2),encoding='utf-8')
    m=json.loads((base/'manifest.json').read_text());m.update(case_id=name,format_id='ibench_aes_hd_v1',top=original['top'],netlist='netlist/design.v',sdc='sdc/design.sdc',
        die_area_microns=list(map(float,original['floorplan']['die_area'].split())),
        core_area_microns=list(map(float,original['floorplan']['core_area'].split())),
        planning_source='Original shared iBench design.json, 60% native floorplan',
        scope=f'{name}: {len(parsed["components"])} mapped standard cells; zero hard macros',
        provenance=['design.json','provenance/source.json'],
        budget={'executions':22,'model_calls':40,'wall_seconds':32400,'cpu_threads':4,'memory_gb':8,'container_seconds':21600,'host_seconds':21620,'routing_seconds':21600})
    m.update(reference_revision='iBench-design-sha256:'+hashlib.sha256((source/'design.json').read_bytes()).hexdigest(),
        io_rule={'method':'auto_place_pins','layer':'met3','width_dbu':800,'height_dbu':800},
        routing_graph='shared' if name=='aes_sky130_t' else 'layered',
        acceptance_mode='flow_reproduction_separate_from_physical_quality',
        pdk_reference_revision='460c656e04826d96d883331c323a6cf960d6e82d',
        resource_rationale='Historical native routing takes 6026/7097/20115 seconds; prospective six-hour routing cap, four threads, 8 GiB, serial execution. Other native stages retain 1800-second caps.')
    m['qualification_status']='candidate_not_accepted'
    (dst/'manifest.json').write_text(json.dumps(m,indent=2),encoding='utf-8')
    print(name,len(parsed['components']),flush=True)

if __name__=='__main__':
    for name in sys.argv[1:]:prepare(name)

"""Read-only verification of the finished workbench delivery; never runs EDA."""
from pathlib import Path
import hashlib,json,sys,re

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from macro_agent.def_validation import read_def,lef_cells
from macro_agent.backend_checks import route_records

folder=ROOT/'runs/dsh-desktop-496d07b4ac6da42c/main-task'
evidence=ROOT/'runs/medium-macro-fullflow-20261114'
delivery=json.loads((folder/'remote-delivery.json').read_text(encoding='utf-8'))
checks=[]
for item in delivery['files'].values():
    p=Path(item['path'])
    ok=p.parent.resolve()==folder.resolve() and p.is_file()
    ok=ok and p.stat().st_size==item['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
    checks.append({'name':p.name,'passed':ok,'sha256':item['sha256']})
case=ROOT/'cases/ibench/swerv_nangate45'
m=json.loads((case/'manifest.json').read_text(encoding='utf-8'))
d=read_def(folder/'final.def');cells={}
for f in m['cell_lefs']:cells.update(lef_cells(case/f,d['units']))
macros={n:v for n,v in d['components'].items() if cells[v['master']]['hard_macro']}
macro_ok={n:v['master'] for n,v in macros.items()}==m['expected_macro_masters'] and all(v['placement'] and v['placement'][0]=='FIXED' for v in macros.values())
routes=route_records(folder/'final.def')
multi={n for n,p in d['nets'].items() if len(p)>1}
routed={n for n,r in routes.items() if re.search(r'\b(?:ROUTED|FIXED|COVER)\b',r)}
missing=sorted(multi-routed)
a=json.loads((folder/'acceptance.json').read_text(encoding='utf-8'))
metrics=json.loads((folder/'metrics.json').read_text(encoding='utf-8'))
result={'case_id':m['case_id'],'delivery_hashes':checks,'all_download_hashes_passed':all(c['passed'] for c in checks),
    'final_instances':len(d['components']),'final_nonmacro_instances':len(d['components'])-len(macros),
    'final_nets':len(d['nets']),'multiterminal_nets':len(multi),'nets_with_route_records':len(routed),
    'multiterminal_nets_without_route_records':missing,'route_record_presence_passed':not missing,
    'route_record_check_scope':'Presence only, not geometric electrical connectivity or LVS',
    'hard_macros':macros,'macro_identity_and_fixed_status_passed':macro_ok,
    'workflow_completed':a.get('full_backend_workflow_completed'),'physical_quality_passed':a.get('physical_quality_passed'),
    'drc_violation_count':a.get('drc',{}).get('violation_count'),'elapsed_wall_seconds':metrics['elapsed_wall_seconds'],
    'stage_seconds':metrics['stage_seconds'],'scope':'Independent local delivery integrity and DEF macro identity check; native gates retained separately'}
result['passed']=result['all_download_hashes_passed'] and macro_ok and not missing and result['workflow_completed'] is True
(evidence/'delivery-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
if not result['passed']:raise SystemExit(1)

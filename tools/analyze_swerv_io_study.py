"""Reconcile native HPWL with exported DEF; no EDA execution."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.analyze_swerv_screening import library,pin_hpwl,sta
from macro_agent.def_validation import read_def
P=ROOT/'runs/swerv-no-hold-20261115';E=P/'evidence'
OLD=ROOT/'runs/swerv-screening-20261115-v2'
load=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def measure(path,cells,override=None):
    r=pin_hpwl(path,cells,override);u=read_def(path)['units']
    rows=r.pop('rows')
    r.update(total_dbu=round(r['all_um']*u),io_nets_dbu=round(sum(v['um'] for v in rows.values() if v['io'])*u),
             without_io_dbu=round(sum(v['um'] for v in rows.values() if not v['io'])*u),units=u,def_sha256=sha(path))
    return r

def physical_cost(path,cells):
    d=read_def(path);masters={}
    for c in d['components'].values():masters[c['master']]=masters.get(c['master'],0)+1
    return {'instances':len(d['components']),'nets':len(d['nets']),
        'standard_cell_area_um2':round(sum(cells[k]['size'][0]*cells[k]['size'][1]*n for k,n in masters.items() if not k.startswith('fakeram')),6),
        'macro_area_um2':round(sum(cells[k]['size'][0]*cells[k]['size'][1]*n for k,n in masters.items() if k.startswith('fakeram')),6),
        'masters':masters}

def main():
    r=load(E/'io-receipt.json');assert r['status']=='completed' and r['frozen_inputs_unchanged']
    cells=library('idb_rect_mean');old=load(OLD/'analysis.json')
    out={'job_id':r['job_id'],'seconds':r['finished_at']-r['started_at'],'status':r['status'],
         'definition':'All DEF NETS, integer iDB LEF rectangle-corner mean, orientation transformed, real centered IO anchors; DBU comparison',
         'original':{},'corrected':{},'hold':{},'routing_executed':False,'frozen_inputs_unchanged':True}
    for label in ('macro_imp','macro_shelf'):
        p=OLD/'evidence'/(label+'-result-placement.def');native=old['macro'][label]['native_hpwl_dbu']
        real=measure(p,cells);stale=measure(p,cells,(-1,-1))
        out['original'][label]={'native_dbu':native,'real_io':real,'counterfactual_io_minus_one':stale,
            'stale_io_matches_native_exactly':stale['total_dbu']==native}
    for label in ('imp_fixed','shelf_fixed'):
        v=r['results'][label];p=E/(label+'-result-placement.def');native=v['native_placement_summary']['detail_placement']['hpwl']
        independent=measure(p,cells);final=E/(label+'-result-legalization.def')
        out['corrected'][label]={'native_dbu':native,'independent':independent,
            'native_matches_independent_exactly':native==independent['total_dbu'],
            'cost':physical_cost(final,cells),'final_hpwl':measure(final,cells),
            'timing':sta(E/(label+'-result-timing-swerv_wrapper.rpt')),
            'hold_insertions':v['hold_insertions'],'geometry_passed':v['metrics']['geometry']['passed'],
            'macro_positions':v['metrics']['macro_positions']}
    da,db=[read_def(E/(x+'-result-fanout.def')) for x in ('imp_fixed','shelf_fixed')]
    macros=set(r['results']['imp_fixed']['metrics']['macro_positions'])
    out['controls']={'fanout_same_nets':da['nets']==db['nets'],
        'fanout_same_nonmacro_instances':{k:v for k,v in da['components'].items() if k not in macros}=={k:v for k,v in db['components'].items() if k not in macros},
        'fanout_same_io':da['pins']==db['pins'],
        'fanout_other_fields_same':all(da[k]==db[k] for k in da if k not in ('components','nets','pins')),
        'placement_config_same':sha(E/'imp_fixed-config-pl_default_config.json')==sha(E/'shelf_fixed-config-pl_default_config.json'),
        'effective_config_same':r['results']['imp_fixed']['native_placement_summary']['effective_config_hash']==r['results']['shelf_fixed']['native_placement_summary']['effective_config_hash'],
        'both_hold_skipped':not r['hold_executed'] and all(out['corrected'][k]['hold_insertions']==0 for k in out['corrected'])}
    zero=E/'original_nohold-candidate-result-legalization.def'
    out['hold']['hold_00']={'hold_buffers':0,'cost':physical_cost(zero,cells),'timing':sta(E/'original_nohold-candidate-result-timing-swerv_wrapper.rpt')}
    for key,label in [('hold_05','hold_05'),('hold_10','hold_10'),('hold_20','hold_20_reused')]:
        path=OLD/'evidence'/(key+'-result-legalization.def' if key!='hold_20' else 'hold_20-legalization.def')
        out['hold'][key]={'hold_buffers':old['hold'][key]['inserted_buffers'],'cost':physical_cost(path,cells),
            'timing':sta(OLD/'evidence'/(label+'-timing.rpt'))}
    out['metric_gate_passed']=all(x['stale_io_matches_native_exactly'] for x in out['original'].values()) and all(x['native_matches_independent_exactly'] for x in out['corrected'].values())
    a,b=[out['corrected'][k]['independent']['total_dbu'] for k in ('imp_fixed','shelf_fixed')]
    out['comparison']={'imp_hpwl_reduction_vs_shelf_percent':100*(b-a)/b,'single_trial':True,
        'scope':'Pre-route HPWL and diagnostic no-SPEF STA; no new routed DRC, congestion or runtime measurement; no production promotion'}
    out['library_sha256']={p.name:sha(p) for p in (ROOT/'cases/ibench/swerv_nangate45/pdk/lef').glob('*.lef')}
    (P/'analysis.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'metric_gate_passed':out['metric_gate_passed'],'controls':out['controls'],
        'corrected':{k:{'native_dbu':v['native_dbu'],'independent_dbu':v['independent']['total_dbu'],'timing':v['timing'],'instances':v['cost']['instances']} for k,v in out['corrected'].items()},
        'comparison':out['comparison']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()

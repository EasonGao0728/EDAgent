"""Deterministic capability admission. Research candidates are never executable by name alone."""
from pathlib import Path
import hashlib
import json
from .common import digest

ROOT=Path(__file__).resolve().parents[1]

def cards():
    from . import ieda_runtime as rt
    result=[{'tool_id':'ieda_ipl','version':rt.IMAGE,'source':'https://github.com/OSCC-Project/iEDA',
             'license':'Mulan PSL v2 (repository; image dependencies separate)',
             'stage':'standard_cell_placement','formats':['sky130_gcd_v1'],
             'constraints':['fixed_instances','die_bounds','nonoverlap','row_site_alignment'],
             'installed':False,'verified':False,'evidence':None,'cpu_threads':4,'memory_gb':8,'timeout_seconds':65},
            {'tool_id':'ieda_ipl_nangate','version':rt.IMAGE,'source':'https://github.com/OSCC-Project/iEDA',
             'license':'Mulan PSL v2 (repository; image dependencies separate)',
             'stage':'standard_cell_placement','formats':['nangate_macro_smoke_v1'],
             'constraints':['fixed_instances','die_bounds','nonoverlap','row_site_alignment'],
             'installed':False,'verified':False,'evidence':None,'cpu_threads':4,'memory_gb':8,'timeout_seconds':180},
            {'tool_id':'openroad_hier_rtlmp','version':None,'source':'https://github.com/The-OpenROAD-Project/OpenROAD',
             'license':'BSD-3-Clause','stage':'macro_placement','formats':['nangate_macro_smoke_v1'],
             'constraints':['fixed_instances','die_bounds','nonoverlap'],
             'installed':False,'verified':False,'evidence':None,'cpu_threads':4,'memory_gb':8,'timeout_seconds':180},
            {'tool_id':'dreamplace','version':None,'source':'https://github.com/limbo018/DREAMPlace',
             'license':'BSD-3-Clause','stage':'macro_placement','formats':[], 'constraints':[],
             'installed':False,'verified':False,'evidence':None,'reason':'Adapter and local case validation not implemented'},
            {'tool_id':'ieda_imp','version':None,'source':'https://github.com/OSCC-Project/iEDA',
             'license':'Mulan PSL v2','stage':'macro_placement','formats':[],'constraints':[],
             'installed':False,'verified':False,'evidence':None,'reason':'Current native placer_run_mp placed two real SRAMs in an operator probe; fixed-macro stdcell placement, independent checks and readback passed under the sparse profile. Production case adapter/registration and DSH acceptance are pending. Legacy hMetis/NaN failures refer to a different build.'}]
    hd_card = {**result[0], 'tool_id': 'ieda_ipl_ibench_gcd',
               'formats': ['ibench_gcd_legacy_v1']}
    result.insert(1, hd_card)
    from .aes_backend import CASES,require_qualification
    for case_id in CASES:
        card={**result[0],'tool_id':'ieda_ipl_'+case_id,'formats':['ibench_aes_hd_v1:'+case_id],
              'timeout_seconds':1800,'qualification_required':True}
        try:require_qualification(case_id)
        except (ValueError,OSError,KeyError):card['admission_blocked']=True
        result.insert(2,card)
    for tool_id,stage in [('ieda_imp_sram_pair','macro_placement'),('ieda_ipl_sram_pair','standard_cell_placement')]:
        result.insert(-1,{**result[0],'tool_id':tool_id,'stage':stage,'formats':['sky130_sram_pair_v1'],
            'cpu_threads':2,'memory_gb':4,'timeout_seconds':140,
            'reason':'Explicit two-SRAM adapter; admission requires complete native-stage validation receipt'})
    for card in result:
        card['backend']='iEDA' if card['tool_id'].startswith('ieda_') else ('OpenROAD' if card['tool_id'].startswith('openroad_') else 'DREAMPlace')
        card['phase1_allowed']=card['backend']=='iEDA'
        if card.get('admission_blocked'):continue
        receipt=ROOT/'.cache/tool-verification'/(card['tool_id']+'.json')
        if not receipt.is_file():continue
        value=json.loads(receipt.read_text(encoding='utf-8'))
        if card['backend']=='iEDA' and (value.get('image')!=rt.IMAGE or value.get('version')!=rt.IMAGE):
            card['reason']='Qualification belongs to a different iEDA build'
            continue
        artifact=Path(value['evidence']['path'])
        if not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest()!=value['evidence']['sha256']:continue
        # Receipt binds a reviewed version and case; runtime still checks image availability.
        card.update(version=value['version'],verified=True,evidence=value['evidence'])
        try:
            rt.invoke(['image','inspect',value['image'],'--format','{{.Id}}'],timeout=8)
            card['installed']=True
        except Exception:card['reason']='Verified image currently unavailable'
    result[-1].update(version=rt.IMAGE,installed=result[0]['installed'],
        capability_probe=str(ROOT/'runs/stage1-progress-20261106/capabilities.json'),
        native_macro_probe=str(ROOT/'runs/stage1-native-macro-20261106-01/probe.json'),
        native_macro_validation=str(ROOT/'runs/stage1-native-macro-verify-20261106-03/verification.json'),
        legacy_probe=str(ROOT/'runs/ieda-capability-audit-20261105'))
    # Explicit, case-bound first qualification. Static evidence is NOT a native pass.
    from .swerv_backend import preflight
    try:
        evidence=preflight(ROOT/'cases/ibench/swerv_nangate45')
        rt.invoke(['image','inspect',rt.IMAGE,'--format','{{.Id}}'],timeout=8)
        for tool_id,stage in [('ieda_imp_swerv','macro_placement'),('ieda_ipl_swerv','standard_cell_placement')]:
            result.append({**result[0],'tool_id':tool_id,'stage':stage,'formats':['swerv_nangate45_v1'],
                'backend':'iEDA','phase1_allowed':True,'installed':True,'verified':False,
                'evidence':evidence,'timeout_seconds':600,'qualification_status':'first_native_case_run_pending',
                'experimental_admission':'registered_swerv_first_run_v1',
                'reason':'User-requested bounded qualification run; every native stage still requires independent checks'})
    except (ValueError,OSError,RuntimeError,KeyError):pass
    return result


def first_run_admitted(card,format_id):
    return (format_id=='swerv_nangate45_v1' and card.get('tool_id') in ('ieda_imp_swerv','ieda_ipl_swerv')
        and card.get('experimental_admission')=='registered_swerv_first_run_v1'
        and card.get('evidence',{}).get('passed') is True
        and card.get('evidence',{}).get('native_fullflow_qualified') is False)

def select_tool(*,stage,format_id,required_constraints,movable_hard_macros,state_id,budget,tool_cards=None):
    candidates=cards() if tool_cards is None else tool_cards
    rejected=[];eligible=[]
    if stage=='macro_placement' and movable_hard_macros==0:
        status='skip';selected=None;reason='No movable hard macros; standard-cell flow is appropriate'
    else:
        for card in candidates:
            reasons=[]
            if card.get('backend')!='iEDA':reasons.append('phase1_backend_forbidden')
            if card['stage']!=stage:reasons.append('wrong_stage')
            if not card['installed']:reasons.append('not_installed')
            if not card['verified'] and not first_run_admitted(card,format_id):reasons.append('not_verified')
            if format_id not in card['formats']:reasons.append('unsupported_adapter')
            if set(required_constraints)-set(card['constraints']):reasons.append('unsupported_required_constraints')
            for field in ('cpu_threads','memory_gb','timeout_seconds'):
                if card.get(field,0)>budget.get(field,0):reasons.append('insufficient_'+field)
            if reasons:rejected.append({'tool_id':card['tool_id'],'reasons':reasons})
            else:eligible.append(card)
        rank={'ieda_ipl':0,'ieda_ipl_nangate':0}
        eligible.sort(key=lambda c:rank.get(c['tool_id'],99))
        selected=eligible[0] if eligible else None
        status='selected' if selected else 'capability_gap'
        reason=('Explicit registered first qualification; native performance and fullflow success not yet verified' if selected and first_run_admitted(selected,format_id) else 'Conservative reviewed priority; no performance ranking claimed') if selected else 'No verified tool covers all requirements; Maker disabled in phase one'
    result={'state_id':state_id,'stage':stage,'format_id':format_id,'status':status,'selected':selected,
            'eligible':[c['tool_id'] for c in eligible],'rejected':rejected,'reason':reason,'budget':budget,
            'required_constraints':required_constraints,'movable_hard_macros':movable_hard_macros}
    result['decision_id']=digest(result)
    return result

def record_verification(tool_id,version,image,evidence):
    evidence=Path(evidence).resolve()
    folder=ROOT/'.cache/tool-verification';folder.mkdir(parents=True,exist_ok=True)
    value={'version':version,'image':image,'evidence':{'path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}}
    (folder/(tool_id+'.json')).write_text(json.dumps(value,indent=2),encoding='utf-8')

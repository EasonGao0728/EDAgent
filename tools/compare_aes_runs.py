"""Read-only comparison of a downloaded server baseline and a real DSH task.

No reruns, geometry rewriting or arbitrary numerical tolerance. Record exact
differences; order-only DEF serialization is compared canonically.
"""
import argparse,hashlib,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from macro_agent.def_validation import read_def,section
from macro_agent.aes_flow import STAGES
from tools.audit_aes_drivers import run as driver_audit
from tools.revalidate_aes_baseline import verify as verify_implementation

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def routes(p):
    result={}
    for row in section(p.read_text(encoding='utf-8'),'NETS'):
        name=row.split()[0];head,sep,tail=row.partition('+ ROUTED')
        result[name]=sorted(' '.join(x.split()) for x in re.split(r'\bNEW\b',tail)) if sep else []
    return result

def normalized_script(p):
    # Universal newline decoding only. Do not discard commands or whitespace.
    return p.read_text(encoding='utf-8')

def violation_records(p):
    # Core detail files approach 900 MB. Parse one complete record at a time,
    # retaining a multiplicity-sensitive SHA256 multiset, never sampled rows.
    import ijson
    from ijson.common import ObjectBuilder
    from collections import Counter
    metadata={};records=Counter();count=0;arrays=0;builder=None;depth=0
    try:
        with p.open('rb') as stream:
            for prefix,event,value in ijson.parse(stream,use_float=True):
                if builder is not None:
                    builder.event(event,value)
                    if event in ('start_map','start_array'):depth+=1
                    elif event in ('end_map','end_array'):depth-=1
                    if depth==0:
                        records[hashlib.sha256(json.dumps(builder.value,sort_keys=True).encode()).digest()]+=1
                        count+=1;builder=None
                elif prefix=='violations.item':
                    if event!='start_map':raise ValueError('DRC violation must be a complete object')
                    builder=ObjectBuilder();builder.event(event,value);depth=1
                elif prefix=='violations' and event=='start_array':arrays+=1
                elif prefix in ('count','coordinate_units','dbu_per_micron'):
                    if prefix in metadata or event not in ('number','string'):raise ValueError('Invalid DRC metadata')
                    metadata[prefix]=value
    except ijson.JSONError as exc:raise ValueError('Invalid or truncated DRC JSON') from exc
    if arrays!=1 or builder is not None:raise ValueError('Invalid DRC violations array')
    if metadata.get('count')!=count:raise ValueError('DRC detail count mismatch')
    return {'count':count,'units':metadata['coordinate_units'],'dbu':metadata['dbu_per_micron'],'records':records}

def timing_text(p):
    return '\n'.join(line for line in p.read_text(encoding='utf-8').splitlines()
        if not line.startswith(('Generate the report at ','iSTA elapsed time: ')))

def gds_geometry_equal(left,right,top_name):
    import klayout.db as db
    def layers(layout):return {(layout.get_info(i).layer,layout.get_info(i).datatype):i for i in layout.layer_indices()}
    a,b=layers(left),layers(right)
    if left.dbu!=right.dbu or set(a)!=set(b):return False
    ta,tb=left.cell(top_name),right.cell(top_name)
    if ta is None or tb is None:return False
    # Bound peak memory to one layer pair; every layer still undergoes exact XOR.
    for key in a:
        ra=db.Region(ta.begin_shapes_rec(a[key])).merged()
        rb=db.Region(tb.begin_shapes_rec(b[key])).merged()
        if not (ra^rb).is_empty():return False
    return True

def compare(server,desktop):
    server=Path(server);desktop=Path(desktop)
    s=json.loads((server/'run.json').read_text(encoding='utf-8'));d=json.loads((desktop/'task.json').read_text(encoding='utf-8'))
    result={'case':s['case'],'server':str(server),'dsh':str(desktop),'status':'not_matched','stages':{},'errors':[],
        'acceptance_mode':'flow_reproduction_separate_from_physical_quality','numerical_tolerance':'none; discrepancies require investigation',
        'server_run_sha256':sha(server/'run.json'),'dsh_task_sha256':sha(desktop/'task.json')}
    result['comparison_implementation_sha256']={name:sha(ROOT/name) for name in ('tools/compare_aes_runs.py','tools/audit_aes_timing_ties.py')}
    if d.get('resource_continuation'):
        from tools.core_resource_extension import validate as validate_resource_extension
        result['authorized_resource_extension']=validate_resource_extension(d,desktop)
        result['original_routing_resource_budget_met']=False
        result['comparison_implementation_sha256']['tools/core_resource_extension.py']=sha(ROOT/'tools/core_resource_extension.py')
        extended=d.get('results',{}).get('routing',{})
        if extended.get('deadline_seconds')!=64800 or extended.get('authorized_runtime_extension')!=result['authorized_resource_extension']:
            result['errors'].append('extended_routing_execution_evidence_mismatch')
    amendment=d.get('quota_continuation')
    if amendment:
        parent=Path(amendment['parent']['path'])
        original=json.loads(parent.read_text(encoding='utf-8'))
        valid=(sha(parent)==amendment['parent']['sha256'] and original['created_at']==d['created_at']
            and original['input_refs']==d['input_refs']
            and all(original['results'][stage]==d['results'].get(stage) for stage in original['completed'])
            and all(d['counts'][k]>=original['counts'][k] for k in ('executions','model_calls'))
            and amendment['original_deadline']==original['created_at']+original['contract']['budget']['wall_seconds']
            and abs(amendment['remaining_seconds']-(amendment['original_deadline']-amendment['interrupted_at']))<0.001
            and abs(d['created_at']+d['contract']['budget']['wall_seconds']-amendment['new_deadline'])<0.001
            and all(v==d['contract']['budget'][k] for k,v in original['contract']['budget'].items() if k!='wall_seconds'))
        result['authorized_wall_time_amendment']={**amendment,'parent_and_preserved_prefix_valid':valid}
        if not valid:result['errors'].append('quota_continuation_invalid')
    if d['contract']['case_id']!=s['case']:result['errors'].append('case_mismatch')
    if d['status']!='target_met' or s['status']!='passed':result['errors'].append('unfinished_workflow')
    if d['contract']['backend_version']!=s['version']:result['errors'].append('backend_version_mismatch')
    if d['contract'].get('input_source')!='conversation_attachments':result['errors'].append('not_conversation_file_input')
    if d['completed']!=STAGES or [r['stage'] for r in s['stages']]!=STAGES:result['errors'].append('missing_or_changed_stage_plan')
    if set(d['results'])!=set(STAGES):result['errors'].append('missing_or_extra_stage_results')
    if not all(r.get('passed') is True for r in s['stages']):result['errors'].append('server_stage_not_passed')
    if not all(r.get('passed') is True for r in d['results'].values()):result['errors'].append('dsh_stage_not_passed')
    reference=Path(d['contract'].get('input_root') or ROOT/'cases/ibench'/s['case'])
    for rel,h in s['input_sha256'].items():
        if sha(reference/rel)!=h:result['errors'].append('input_mismatch:'+rel)
    result['server_validation_revision_audit']=verify_implementation(s,server)
    result['driver_direction_audit']={'server':driver_audit(server,reference),'dsh':driver_audit(Path(d['accepted_work']),reference)}
    if not all(v['passed'] for v in result['driver_direction_audit'].values()):result['errors'].append('driver_direction_audit_failed')
    server_stages={r['stage']:r for r in s['stages']}
    for stage in STAGES:
        if stage in ('validate','gds_export'):continue
        if stage not in d['results'] or stage not in server_stages:continue
        a=server/'result'/(stage+'.def');b=Path(d['results'][stage]['artifact'])
        script_a=server/(stage+'.tcl');script_b=Path(d['results'][stage]['log']).parent.parent/(stage+'.tcl')
        r={'byte_identical':sha(a)==sha(b),'server_sha256':sha(a),'dsh_sha256':sha(b),
            'parsed_semantics_identical':read_def(a)==read_def(b),'route_segments_identical':routes(a)==routes(b),
            'script_bytes_identical':sha(script_a)==sha(script_b),'script_text_identical':normalized_script(script_a)==normalized_script(script_b),
            'binary_identical':server_stages[stage].get('binary_sha256')==d['results'][stage].get('binary_sha256'),
            'recorded_output_hashes_valid':sha(a)==server_stages[stage].get('artifact_sha256') and sha(b)==d['results'][stage].get('artifact_sha256')}
        result['stages'][stage]=r
        if not all(r[k] for k in ('parsed_semantics_identical','route_segments_identical','script_text_identical','binary_identical','recorded_output_hashes_valid')):result['errors'].append('stage_difference:'+stage)
    if 'drc' in d['results'] and 'drc' in server_stages:
        a=server_stages['drc']['drc_gate'];b=d['results']['drc']['drc_gate']
        result['drc']={'server_violations':a['violation_count'],'dsh_violations':b['violation_count'],
            'counts_equal':a['violation_count']==b['violation_count'],'coverage_equal':a['checked']==b['checked'] and a['unsupported']==b['unsupported'],
            'physical_quality_passed':a.get('quality_clean',False) and b.get('quality_clean',False),'signoff_clean':False}
        details_a=violation_records(server/'result/report/violations.json')
        details_b=violation_records(Path(d['accepted_work'])/'result/report/violations.json')
        result['drc']['details_equal']=details_a==details_b
        result['drc']['details_comparison']='Complete canonical JSON records as SHA256 multiset; duplicate multiplicities retained, no sampling'
        result['drc']['per_rule_counts_equal']={k:v['violation_count'] for k,v in a['runtime']['per_rule'].items()}=={k:v['violation_count'] for k,v in b['runtime']['per_rule'].items()}
        if not result['drc']['details_equal'] or not result['drc']['per_rule_counts_equal']:result['errors'].append('drc_detail_difference')
        if not result['drc']['counts_equal'] or not result['drc']['coverage_equal']:result['errors'].append('drc_difference')
    result['routing_profile_equal']=server_stages['routing']['routing_profile']==d['results']['routing']['routing_profile']
    if not result['routing_profile_equal']:result['errors'].append('routing_profile_difference')
    result['timing_cell_delay_report_equal']=timing_text(server/'result/timing'/(d['contract']['top']+'.rpt'))==timing_text(Path(d['accepted_work'])/'result/timing'/(d['contract']['top']+'.rpt'))
    if not result['timing_cell_delay_report_equal']:
        from tools.audit_aes_timing_ties import audit as audit_timing_ties
        try:
            result['timing_report_difference_audit']=audit_timing_ties(server,Path(d['accepted_work']),d['contract']['top'])
        except (ValueError,OSError,KeyError) as exc:
            result['timing_report_difference_audit']={'passed':False,'reason':str(exc)}
            result['errors'].append('cell_delay_timing_difference')
    if 'gds_export' in d['results'] and 'gds_export' in server_stages:
        import klayout.db as db
        ga=server/'result/final.gds';gb=Path(d['results']['gds_export']['artifact'])
        ea=server_stages['gds_export'];eb=d['results']['gds_export']
        result['native_gds_evidence']={
            'binary_identical':ea.get('binary_sha256')==eb.get('binary_sha256'),
            'recorded_output_hashes_valid':sha(ga)==ea.get('artifact_sha256') and sha(gb)==eb.get('artifact_sha256'),
            'both_independent_validations_passed':ea.get('validation',{}).get('passed') is True and eb.get('validation',{}).get('passed') is True}
        if not all(result['native_gds_evidence'].values()):result['errors'].append('native_gds_evidence_invalid')
        layouts=[]
        for p in [ga,gb]:
            layout=db.Layout();layout.read(str(p));layouts.append(layout)
        equal=gds_geometry_equal(layouts[0],layouts[1],d['contract']['top'])
        result['native_gds_geometry_equal']=equal
        if not equal:result['errors'].append('native_gds_geometry_difference')
    result['status']='matched' if not result['errors'] else 'not_matched'
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--server',required=True);ap.add_argument('--dsh',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
    output=Path(a.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    r=compare(a.server,a.dsh);output.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'case':r['case'],'status':r['status'],'errors':r['errors']}))

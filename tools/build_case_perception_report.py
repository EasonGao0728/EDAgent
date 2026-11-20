"""Build an evidence-labelled local case catalogue and hold calibration protocol.

Does not run EDA, change production defaults, or deploy anything to the server.
"""
from pathlib import Path
from collections import Counter,defaultdict
import json,re,html,hashlib

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'runs/case-perception-20261115'
OUT=ROOT/'output/case-perception-20261115'
KINDS={'measured_structural_scan':'结构重统计','hash_bound_historical_statistics':'哈希绑定历史统计','unbound_historical_statistics':'未绑定历史统计','unknown':'未知'}

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def pdk_of(r):
    if r.get('pdk'):return r['pdk']
    return 'nangate45' if 'nangate' in r['case_id'] else 'sky130' if 'sky130' in r['case_id'] else 'unknown'

def family(r):
    s=(r.get('logical_design_declared') or r['case_id']).lower()
    # Conservative grouping prevents related netlists/technology variants leaking across folds.
    if s.startswith('aes'):return 'aes-family'
    if s.startswith('ariane'):return 'ariane-family'
    if s.startswith('bp'):return 'blackparrot-family'
    if s.startswith('swerv'):return 'swerv-family'
    if s.startswith(('apb4_','osip_')):return 'peripheral-'+s.split('_',1)[1]
    if 'gcd' in s:return 'gcd-family'
    if s.startswith('ysyx'):return 'ysyx-family'
    return s

def function(r):
    s=(' '.join(str(r.get(k) or '') for k in ('case_id','logical_design_declared','role_declared'))).lower()
    if any(x in s for x in ('aes','salsa')):return '密码运算'
    if any(x in s for x in ('jpeg','ppu','gpu','vortex')):return '图像或并行计算'
    if any(x in s for x in ('apb4','osip')):return '外设与控制'
    if 'gcd' in s:return '算术小核'
    if re.search(r'\bs\d{4,5}',s):return '时序逻辑基准'
    if any(x in s for x in ('swerv','ariane','bp','cpu','soc','riscv','picorv','nut','openc','nanhu','tinyram','wukong','wenquxing')):return '处理器或SoC'
    if 'sram' in s:return '宏接口测试'
    return '待核实功能类型'

def size(n):
    if n is None:return '未知'
    return '小型 <1k' if n<1000 else '中型 1k–100k' if n<100000 else '大型 100k–1M' if n<1000000 else '超大型 ≥1M'

def area_box(v):
    try:
        a=[float(x) for x in (v.split() if isinstance(v,str) else v)]
        return (a[2]-a[0])*(a[3]-a[1]) if len(a)==4 else None
    except (TypeError,ValueError):return None

def enrich(rows,libs,constraints):
    by_pdk=defaultdict(dict);by_case=defaultdict(dict);sources=defaultdict(list)
    for l in libs:
        if l['status']!='read':continue
        p=l.get('pdk') or ('nangate45' if 'Nangate' in l['path'] or 'fakeram45' in l['path'] else 'sky130' if 'sky130' in l['path'] else None)
        for target in [by_case[l.get('case_id')],by_pdk[p]]:
            for name,attrs in l['cells'].items():target.setdefault(name,{}).update(attrs)
        sources[p].append({k:l.get(k) for k in ('path','sha256','case_id','library_time_unit')})
    cm={(c['origin'],c['case_id']):c for c in constraints}
    for r in rows:
        r['catalog_id']=r['origin']+':'+r['case_id'];r['pdk']=pdk_of(r)
        masters=r.get('counts',{}).get('masters',{});n=r.get('counts',{}).get('cell_count')
        refs=by_case[r['case_id']] if r['origin']=='registered' else by_pdk[r['pdk']]
        macro_known=sum(v for k,v in masters.items() if 'macro' in refs.get(k,{}))
        macro=sum(v for k,v in masters.items() if refs.get(k,{}).get('macro'))
        if n is not None and macro_known==n:
            r['macro_instances']=macro;r['macro_classification_kind']='exact_registered_LEF' if r['origin']=='registered' else 'reference_LEF_master_matching'
        else:macro=r.get('macro_instances')
        r['standard_cell_instances']=n-macro if n is not None and macro is not None else None
        std=[(k,v) for k,v in masters.items() if not refs.get(k,{}).get('macro') and k not in r.get('macro_masters',{})]
        seq_known=sum(v for k,v in std if 'sequential' in refs.get(k,{}))
        stdn=r['standard_cell_instances'];seq=sum(v for k,v in std if refs.get(k,{}).get('sequential'))
        # Unknown masters cannot silently become combinational cells.
        r['sequential']={'count':seq if stdn is not None and seq_known==stdn else None,
                         'known_count_lower_bound':seq,'classified_instances':seq_known,
                         'fraction_of_std':seq/stdn if stdn and seq_known==stdn else None,
                         'coverage_fraction':seq_known/stdn if stdn else None,
                         'kind':'registered_Liberty_ff_latch' if r['origin']=='registered' else 'reference_Liberty_master_matching',
                         'includes':'flip-flops and latches; excludes SRAM internals and clock-gating latch internals classified as macros'}
        area_known=sum(v for k,v in masters.items() if refs.get(k,{}).get('area_um2') is not None)
        cell_area=sum(v*refs[k]['area_um2'] for k,v in masters.items() if refs.get(k,{}).get('area_um2') is not None)
        macro_area=sum(v*refs[k]['area_um2'] for k,v in masters.items() if refs.get(k,{}).get('macro') and refs.get(k,{}).get('area_um2') is not None)
        core=area_box(r.get('floorplan_declared',{}).get('core_area'))
        r['reference_geometry']={'all_cell_area_um2':cell_area if area_known==n else None,
                                 'macro_area_um2':macro_area if area_known==n else None,
                                 'macro_fraction_of_cell_area':macro_area/cell_area if area_known==n and cell_area else None,
                                 'core_area_um2_declared':core,
                                 'utilization_from_reference':cell_area/core if area_known==n and core else None,
                                 'macro_fraction_of_core':macro_area/core if area_known==n and core else None,
                                 'area_coverage_instances':area_known,
                                 'kind':'registered_LEF_and_declared_core' if r['origin']=='registered' else 'reference_LEF_and_declared_core_not_historical_PDK_equivalence',
                                 'scope':'input instances only; before CTS, DRV, hold, fillers and routing'}
        r['constraint_profile']=cm.get((r['origin'],r['case_id']),{})
        r['size_class']=size(n);r['functional_tag']=function(r);r['functional_tag_kind']='name_and_declared_role_inference_not_RTL_verification';r['split_family']=family(r)
        r['io_to_instance_ratio']=r.get('counts',{}).get('top_pin_bits',0)/n if n else None
        tags=[r['size_class'],r['functional_tag'],r['pdk'],'含宏' if macro else '无宏' if macro==0 else '宏未知']
        sf=r['sequential']['fraction_of_std'];mf=r['reference_geometry']['macro_fraction_of_cell_area']
        tags+=['时序单元占比未知' if sf is None else '高时序占比≥30%' if sf>=.3 else '中时序占比10–30%' if sf>=.1 else '低时序占比<10%']
        if mf is not None and mf>=.5:tags.append('宏面积主导≥50%')
        if r['io_to_instance_ratio'] is not None and r['io_to_instance_ratio']>=.15:tags.append('高IO比≥0.15')
        if (r.get('counts',{}).get('modules') or 0)>1:tags.append('层次网表')
        if any('fakeram' in k.lower() for k in masters):tags.append('抽象RAM模型')
        if r.get('counts_kind')=='hash_bound_historical_statistics':tags.append('大网表统计未独立重算')
        hist=r.get('historical_package',{}).get('result_status')
        if hist:tags.append('历史:'+hist)
        r['tags']=tags
        r['experiment_readiness']={'stage':'qualification_required','ready_for_hold_calibration':False,
            'known_integration':'SWERV限定预算审查已接入；精确源检查点须另行核对' if r['catalog_id']=='registered:swerv_nangate45' else '需验证案例适配与后CTS检查点',
            'requirements':['输入/工艺/库/角落/二进制/配置哈希冻结','有效时钟、IO约束和STA端点覆盖','CTS/DRV成功并冻结同一检查点','IO等价与HPWL一致性门禁','统一时序口径，查明iTO内部与重载诊断差异','资源试运行合格']}
        r['feature_library_sources']=sources[r['pdk']]
    groups=defaultdict(list)
    for r in rows:groups[r.get('netlist',{}).get('sha256',r['catalog_id'])].append(r['catalog_id'])
    for r in rows:r['exact_netlist_duplicates']=groups[r.get('netlist',{}).get('sha256',r['catalog_id'])]
    return rows

def selection(rows):
    # Families are deliberately segregated; close variants are diagnostic controls, not independent samples.
    spec=[
        ('shared:gcd','首批校准','算术小核，校验零需求/少需求是否能保持零新增'),
        ('shared:apb4_timer_nangate45_t','首批校准','外设控制，与GCD比较相近规模不同结构'),
        ('shared:s35932_nangate45_t','首批校准','中型高时序单元占比，与低时序占比案例区分'),
        ('shared:aes','首批校准','密码逻辑，无宏；AES其他实现只作同家族诊断'),
        ('shared:jpeg','首批校准','较大中型图像逻辑，无宏'),
        ('shared:tinyram','首批校准','两宏、低时序占比，与SWERV比较宏结构'),
        ('registered:swerv_nangate45','首批校准','3宏；可在精确哈希匹配时复用已完成候选'),
        ('shared:bp_fe','首批校准','11宏；部分宏库缺少授权副本，补齐库并确认CTS后才能入组'),
        ('shared:toygpu','扩展校准','大型无宏且含时序单元；历史仅PLACED，先完成CTS资格'),
        ('shared:ariane133','扩展校准','大型132宏；历史FAIL，资格不通过则保留失败，不强跑'),
        ('shared:osip_uart','锁定留出','未参加校准的UART功能家族'),
        ('shared:PPU_nangate45_t','锁定留出','未参加校准的图像处理家族'),
        ('shared:picorv32_nangate45_t','锁定留出','独立处理器家族，无宏'),
        ('shared:ysyx2022_openEDA_noPLL','锁定留出','大型SoC外推；资源和CTS资格先行'),
        ('shared:bp_multi','同家族泛化','26宏；不能当作未见过BlackParrot家族的留出'),
        ('shared:beihai','边界对照','参考Liberty分类未发现标准FF/latch，历史无CTS；不作为普通hold校准样本'),
        ('shared:bp_quad','暂缓压力测试','超大型220宏，先不启动，避免失控运行时间'),
    ]
    lookup={r['catalog_id']:r for r in rows};result=[]
    for key,role,why in spec:
        r=lookup[key];result.append({'catalog_id':key,'role':role,'reason':why,'instances':r['counts']['cell_count'],
            'macros':r.get('macro_instances'),'size':r['size_class'],'family':r['split_family'],
            'sequential_fraction':r['sequential']['fraction_of_std'],
            'macro_area_fraction_reference':r['reference_geometry']['macro_fraction_of_cell_area'],
            'historical_status':r.get('historical_package',{}).get('result_status'),'qualified_now':False})
    return result

def experiment(rows):
    return {'schema':'hold_calibration_protocol_v1','date':'2026-11-15','state':'DESIGNED_NOT_EXECUTED',
        'production_defaults_changed':False,'algorithm_agent_started':False,
        'target':'Learn a first search cap and bounded expansion policy, not a mandatory buffer count.',
        'arms':[{'hold_enabled':False,'max_insert_instance_percent':None,'label':'no-hold control'},
                *[{'hold_enabled':True,'max_insert_instance_percent':x} for x in [.01,.025,.05,.10,.20]]],
        'zero_is_skip_not_zero_cap':True,
        'hypotheses':['one common cap','size-class conditioned cap','feature-conditioned cap','input prior plus measured post-CTS/DRV adaptive expansion'],
        'primary_stratum':'nangate45 with matched actual LEF/Liberty corner; do not mix processes as independent samples',
        'shortlist':selection(rows),'initial_calibration_cases':8,'initial_new_arms_upper_bound':48,
        'expanded_calibration_cases':10,'held_out_families':4,'expanded_arm_upper_bound':84,
        'upper_bound_excludes_qualification_repeats_and_final_routing':True,
        'cross_process_followup':'Repeat the same logical families on Sky130 only after qualification; ASAP7/ICS55 await authorized full library closure.',
        'resource_policy':{'server_only':True,'concurrent_native_jobs':1,'cpu_threads':4,'memory_gib':8,
            'pilot_hold_arm_seconds':600,'pilot_whole_case_seconds':3600,'automatic_timeout_extension':False,
            'large_case_action':'read-only profiling now; no unapproved larger resource allocations'},
        'fixed_controls':['same checkpoint SHA','same tool/library/SDC/config hashes','same macro placement','same seed when supported','same timing and HPWL measurement scope'],
        'metrics':['hold worst slack/TNS/violating endpoints','setup slack/TNS/headroom','actual new buffers and types',
            'standard-cell area growth','pin HPWL growth','nets growth','runtime/RSS','legality/connectivity',
            'global-route congestion only when measured','routed DRC and extracted-RC timing only for final routed candidates'],
        'decision':'Feasibility first; Pareto filter and paired relative costs. Unresolved hold never becomes a pass by changing weights.',
        'validation':'Split by logical family, keep exact netlist duplicates together. Freeze thresholds before reading holdout outcomes.',
        'replication':'If seed control is supported, 3 paired upstream checkpoints on representative families. Otherwise label deterministic rerun as reproducibility, not independent samples.',
        'failure_policy':'Keep timeout/unsupported/no feasible arm as outcomes; no deletion, relaxed SDC or silent budget increase.',
        'routing_policy':'Do not route every arm. Qualify pre-route finalists first; only selected paired finals receive separately bounded full routing.',
        'current_default_conclusion':'UNDETERMINED: neither a universal nor a feature-specific balanced cap has been calibrated.'}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    raw=[json.loads(x) for x in (SRC/'case-features-raw.jsonl').read_text(encoding='utf-8').splitlines()]
    summary=next(x for x in raw if x.get('record_type')=='summary');rows=[x for x in raw if x.get('record_type')!='summary']
    correction=read(SRC/'registered-reference-correction.json')
    rows=[correction if x['origin']=='registered' and x['case_id']=='sky130_gcd' else x for x in rows]
    expected={x['name'] for x in read(SRC/'shared-inventory-raw.json')['manifest']['designs']}
    actual={x['case_id'] for x in rows if x['origin']=='shared'}
    assert expected==actual and len(actual)==278 and len(rows)==285
    assert not any(x.get('status')=='failed' for x in rows)
    rows=enrich(rows,read(SRC/'library-reference-catalog.json'),read(SRC/'constraint-profile.json'))
    shared=[r for r in rows if r['origin']=='shared']
    counts={'shared':278,'registered':7,'shared_with_macros':sum((r.get('macro_instances') or 0)>0 for r in shared),
            'pdk':dict(Counter(r['pdk'] for r in shared)), 'size':dict(Counter(r['size_class'] for r in shared)),
            'evidence':dict(Counter(r['counts_kind'] for r in shared)),
            'unique_netlist_sha_shared':len({r['netlist']['sha256'] for r in shared}),
            'declared_logical_designs':len({r['logical_design_declared'] for r in shared}),
            'conservative_split_families':len({r['split_family'] for r in shared}),
            'history':dict(Counter(r.get('historical_package',{}).get('result_status') for r in shared)),
            'reference_seq_full_coverage':sum(r['sequential']['fraction_of_std'] is not None for r in shared),
            'reference_geometry_full_coverage':sum(r['reference_geometry']['all_cell_area_um2'] is not None for r in shared)}
    catalogue={'schema':'server_case_perception_v1','date':'2026-11-15','scope':'authorized shared benchmark designs and registered personal project cases, not other users or entire server disks',
        'scan':summary,'summary':counts,'production_defaults_changed':False,
        'thresholds':{'size_instances':[1000,100000,1000000],'sequential_fraction':[.1,.3],'macro_area_fraction':.5,'io_per_instance':.15,'status':'descriptive engineering bins, not learned budget rules'},
        'evidence_notes':['Measured structural counts use a limited mapped-Verilog parser, not equivalence verification.',
            'Hash-bound history verifies which input statistics refer to; it does not independently verify large-netlist statistics.',
            'Shared case library matching uses authorized reference libraries; no claim of historical private-PDK equivalence.',
            'Missing sequential/area/STA/congestion/DRC is null or unknown, never zero.',
            'Clock values are static SDC-unit candidates; no cross-process ns assumption or Tcl execution.'],
        'cases':rows}
    plan=experiment(rows)
    dump(OUT/'case-catalog.json',catalogue);dump(OUT/'hold-experiment-plan.json',plan)
    render(catalogue,plan)
    dump(SRC/'report-generation-summary.json',counts)
    print(json.dumps(counts,ensure_ascii=False))

def render(catalogue,plan):
    """Implemented below: a self-contained searchable report; no network dependency."""
    from case_perception_html import render_report
    (OUT/'服务器案例特征感知与hold实验设计.html').write_text(render_report(catalogue,plan),encoding='utf-8')

if __name__=='__main__':main()

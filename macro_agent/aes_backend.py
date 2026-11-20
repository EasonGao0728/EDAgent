"""DSH adapter over the same per-stage native AES runner as the Linux baseline."""
import copy,json,shutil
from pathlib import Path
from types import SimpleNamespace
from . import aes_flow,ieda_runtime as rt

CASES=('aes_sky130_t','aes_legacy','aes_core_sky130_t')
ROOT=Path(__file__).resolve().parents[1]

def require_qualification(case_id):
    receipt=ROOT/'.cache/aes-qualification'/(case_id+'.json')
    if not receipt.is_file():raise ValueError('AES_NOT_QUALIFIED: server full-flow baseline is not yet accepted for '+case_id)
    r=json.loads(receipt.read_text(encoding='utf-8'))
    evidence=Path(r['evidence']['path'])
    if r.get('status')!='passed' or r.get('version')!=aes_flow.VERSION or r.get('image')!=rt.IMAGE or aes_flow.sha(evidence)!=r['evidence']['sha256']:
        raise ValueError('AES_QUALIFICATION_CHANGED')
    reference=ROOT/'cases/ibench'/case_id
    for rel,h in r['input_sha256'].items():
        if aes_flow.sha(reference/rel)!=h:raise ValueError('AES_QUALIFIED_INPUT_CHANGED: '+rel)
    for rel,h in r['implementation_sha256'].items():
        if aes_flow.sha(ROOT/rel)!=h:raise ValueError('AES_QUALIFIED_IMPLEMENTATION_CHANGED: '+rel)
    return r

def for_case(case_id,reference_root=None):
    if case_id not in CASES:raise ValueError('Unknown AES case')
    reference=Path(reference_root) if reference_root else ROOT/'cases/ibench'/case_id
    def manifest():
        m=json.loads((reference/'manifest.json').read_text(encoding='utf-8'))
        m['format_id']='ibench_aes_hd_v1:'+case_id
        m['full_backend_policy']={'logical_optimizations':'Approved non-inverting buffer insertion with independent electrical endpoint contraction; reject cell resizing or removal',
           'timing':'Cell-delay diagnostic without SPEF; no timing closure claim',
           'optional_unavailable':{'rcx':'No validated RC extraction model','power':'No qualified activity/parasitic scenario','ir':'No qualified PG current/electrical model'},
           'gds':'Native public-iDB LEF abstract GDS with recorded serialization patch; not manufacturing signoff'}
        return m
    def files():
        m=manifest()
        from .native_gds import input_files
        paths=[reference/m['netlist'],reference/m['tech_lef'],*[reference/p for p in m['cell_lefs']],*[reference/p for p in m['libs']],reference/m['sdc']]
        paths+=sorted(p for p in reference.rglob('*') if p.is_file() and p not in paths)
        return paths+[Path(__file__),Path(aes_flow.__file__),Path(__file__).with_name('aes_transforms.py'),Path(__file__).with_name('aes_netlist.py'),Path(__file__).with_name('aes_reproduction.py'),ROOT/'environments/ieda-aes-router/iEDA',ROOT/'environments/ieda-aes-router/manifest.json']+input_files()
    def execute(stage,work):
        value=aes_flow.execute(stage,work,reference)
        if value.get('passed') is not True:raise ValueError('AES_BACKEND_GATE_FAILED: '+str(Path(work)/(stage+'-evidence.json')))
        if stage in ('export_def','routed_readback'):
            value.update(readback_equal=value['roundtrip']['passed'],readback_coverage=['DEF parsed physical/logical semantics','complete per-net route tokens'])
        return value
    return SimpleNamespace(rt=rt,BACKEND_VERSION=aes_flow.VERSION,STAGES=aes_flow.STAGES,manifest=manifest,
        input_files=files,setup=lambda work:aes_flow.setup(work,reference),execute=execute,package=package)

def package(state,folder,backend):
    from .task_artifacts import package as basic,write,write_report,ref
    folder=Path(folder);work=Path(state['accepted_work']);shadow=copy.deepcopy(state)
    shadow['results']['export_def']=state['results']['routed_readback']
    shadow['results']['validate']['independent']=state['results']['routed_readback']['geometry']
    outputs=basic(shadow,folder,backend,final_source=work/'result/routed_readback.def')
    for name,source in [('final.gds','final.gds'),('final.v','routed_readback.v')]:shutil.copyfile(work/'result'/source,folder/name)
    outputs.update(final_gds=ref(folder/'final.gds'),final_netlist=ref(folder/'final.v'))
    a=json.loads((folder/'acceptance.json').read_text(encoding='utf-8'))
    a.update(scope='Registered medium AES native backend; zero hard macros; no signoff',full_backend_workflow_completed=True,
        signoff_clean=False,routing=state['results']['routing']['routing_gate'],drc=state['results']['drc']['drc_gate'],
        native_gds=state['results']['gds_export']['validation'],timing=state['results']['timing']['timing'],
        input_verification=state['results']['import_netlist']['import_check'],
        transformations={s:r['transformation'] for s,r in state['results'].items() if 'transformation' in r},
        optional_unavailable=backend.manifest()['full_backend_policy']['optional_unavailable'])
    a.update(acceptance_mode='flow_reproduction_separate_from_physical_quality',
        physical_quality_passed=state['results']['drc']['drc_gate']['quality_clean'],
        physical_quality_status='supported_drc_clean' if state['results']['drc']['drc_gate']['quality_clean'] else 'not_passed_residual_drc')
    a['checks'].update(A1='Independent flat structural endpoint partitions including bit aliases',
        A3='Original cells retained; only explicitly approved buffers contracted; reviewed physical insertions',
        A7='Not covered: no hard macros in this AES case',A14='Requires separate server/DSH comparison')
    write(folder/'acceptance.json',a);write_report(folder)
    p=folder/'report.html'
    text=p.read_text(encoding='utf-8').replace('iEDA netlist → placement DEF','iEDA AES netlist → routed DEF / abstract GDS')
    text=text.replace('当前案例输出完成；整体第一阶段验收仍为部分完成，尚不能证明自动宏布局。',
        '本次 AES 的16阶段编排已完成；服务器与DSH的一致性另行验收。此案例无硬宏，不能用于证明宏布局能力。')
    if not a['physical_quality_passed']:
        notice='<p style="padding:16px;background:#fff0d5;color:#8b3500;font-weight:bold">版图质量未通过：存在残余 DRC。此结果不代表时序闭合或制造签核。</p>'
        text=text.replace('</h1>','</h1>'+notice,1)
    p.write_text(text,encoding='utf-8')
    outputs['acceptance']=ref(folder/'acceptance.json');outputs['report']=ref(p);return outputs

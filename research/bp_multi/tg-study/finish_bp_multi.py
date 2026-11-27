"""Continue downstream iEDA stages from a verified V11 route in its own directory."""
import argparse
import json
import os
import html
import time
from pathlib import Path
import shutil

from verify_pa import BASE, DEF_HASH, RUNS, SOURCE, active_jobs, remote_service, save, setup, sha
from qualify_route_state import DR_SHA
from macro_agent import def_io_compat, swerv_backend
from macro_agent.task_artifacts import render

BRANCH = RUNS / ('full-lazy-' + DR_SHA[:12])
CASE_ROOT = RUNS.parent.parent
STAGES = ('filler','drc','timing','gds_export','routed_readback')


def read(path):
    return json.loads(path.read_bytes())


def amended_deadline(stage,work,now=None):
    """Apply the owner's case-specific allowance without resetting the original clock."""
    if Path(work).resolve()!=BRANCH/'backend' or stage not in STAGES:
        raise ValueError('Amendment scope mismatch')
    record=RUNS/'dispatch-v11/budget-amendment-3h.json'
    launch=RUNS/'dispatch-v11/launch.json'
    budget=read(record)
    if (sha(record)!='fd4c3af89ca15e5650732b12532d35d17d54a13269a9f2ddd61543a7ebbd4666' or
        sha(launch)!=budget['launch_sha256'] or budget['legalization_sha256']!=DEF_HASH or
        int(launch.stat().st_mtime)!=budget['start'] or budget['family']!=BRANCH.name or
        budget['expires_at']!=budget['start']+7200+10800):
        raise ValueError('Amendment does not match the frozen bp_multi run')
    now=time.time() if now is None else now
    seconds=min(600,int(budget['expires_at']-now)-10)
    if seconds<=0:raise ValueError('Approved bp_multi time budget exhausted')
    return seconds


def prefix():
    reference = setup()
    accepted = read(BASE/'progress.json')
    expected = [s for s in swerv_backend.STAGES if s != 'import_netlist']
    assert accepted['completed'] == expected[:expected.index('routing')]
    assert sha(Path(swerv_backend.__file__)) == accepted['binding']['stage_engine']
    assert sha(Path(def_io_compat.__file__)) == read(BASE/'io-adapter-amendment.json')['source_sha256']
    imported = RUNS.parent/'structural-bp_multi'
    first = read(imported/'import.json')
    assert first['normalized_import']['passed'] and first['def_hash'] == sha(imported/'import.def') == accepted['binding']['import.def']
    evidence = {'import_netlist':sha(imported/'import.json')}
    for name in accepted['completed']:
        proof = BASE/('validation.json' if name=='validate' else name+'-evidence.json')
        row = read(proof)
        assert row['passed'], name
        if 'artifact' in row:
            file=Path(row['artifact']).resolve(strict=True)
            assert file.is_relative_to(RUNS.parent) and sha(file)==row['artifact_sha256'], name
        evidence[name]=sha(proof)
    assert sha(SOURCE)==DEF_HASH
    return reference,evidence


def finish(reference, inherited, revision):
    from resume_space import V12, V13, V14, V16, V17, open_budget, attempt_name
    repaired=revision in (12,13,14,16,17)
    route=BRANCH/attempt_name(revision) if repaired else BRANCH
    router={11:DR_SHA,12:V12,13:V13,14:V14,16:V16,17:V17}[revision]
    validation = read(route/'route-validation.json')
    routed = route/'result/routing.def'
    assert validation['passed'] and validation['run']['passed'] and validation['native_readback_graph']['passed']
    assert validation['offline_graph']['passed'] and validation['binary_sha256']==router
    assert validation['input_sha256']==DEF_HASH and sha(routed)==validation['artifact_sha256']
    work=BRANCH/'backend'
    work.mkdir(exist_ok=True)
    for name in ('logs','handles','result/report','result/drc','result/timing','result/rt'):
        (work/name).mkdir(exist_ok=True,parents=True)
    if not (work/'config').exists():
        shutil.copytree(reference/'config',work/'config')
    launch=RUNS/'dispatch-v11/launch.json'
    binding={'case_id':'bp_multi','time':launch.stat().st_mtime,'inherited_evidence':inherited,
             'route_validation_sha256':sha(route/'route-validation.json'),'router':router}
    amendment=RUNS/'dispatch-v11/budget-amendment-3h.json'
    engine=swerv_backend
    if revision>=16:
        from macro_agent import bp_multi_stage_backend as engine
        binding['budget']=open_budget()
        binding['original_timeout_receipt']=sha(BRANCH/'recovery-v14/receipt.json')
    elif amendment.exists():
        amended_deadline(STAGES[0],work)
        binding['budget']=read(amendment)
    if repaired:
        binding['previous_attempt']={'receipt':sha(BRANCH/'receipt.json'),'elapsed_s':read(BRANCH/'receipt.json')['wall_s'],
                                     'exit_code':read(BRANCH/'receipt.json')['returncode']}
    if revision>=13:
        old=BRANCH/'recovery-v12/receipt.json'
        previous=read(old)
        binding['intermediate_attempt']={'receipt':sha(old),'elapsed_s':previous['wall_s'],'exit_code':previous['returncode']}
    if revision>=14:
        old=BRANCH/'recovery-v13/receipt.json'
        previous=read(old)
        binding['track_assignment_attempt']={'receipt':sha(old),'elapsed_s':previous['wall_s'],'exit_code':previous['returncode']}
    stamp=work/'run-start.json'
    if stamp.exists():
        assert read(stamp)==binding
    else:
        save(stamp,binding)
    target=work/'result/routing.def'
    if not target.exists():
        tmp=target.with_suffix('.copy')
        shutil.copyfile(routed,tmp);tmp.replace(target)
    assert sha(target)==validation['artifact_sha256']
    os.environ['AIEDA_NATIVE_HANDLES']=str(work/'handles')
    if revision>=16:
        # The supervisor and the stage process run in different working directories.
        package_root=str(Path(engine.__file__).resolve().parents[1])
        inherited_paths=os.environ.get('PYTHONPATH','').split(os.pathsep)
        os.environ['PYTHONPATH']=os.pathsep.join([package_root,*(p for p in inherited_paths if p and p!=package_root)])
    for stage in STAGES:
        proof=work/(stage+'-evidence.json')
        if proof.exists():
            row=read(proof)
            if not row.get('passed'):raise RuntimeError('Unresolved prior failure: '+stage)
            assert sha(Path(row['artifact']))==row['artifact_sha256']
            continue
        save(work/'current.json',{'stage':stage,'status':'running'})
        original_deadline=engine.native_deadline
        original_runner=engine.rt.docker
        try:
            if revision>=16:
                import sys
                engine.native_deadline=lambda stage,work: 0
                engine.rt.docker=lambda: [sys.executable,'-B','-m','macro_agent.bp_multi_native']
            elif amendment.exists():engine.native_deadline=amended_deadline
            if stage=='timing':
                row=def_io_compat.execute(stage,work,reference,backend=engine)
            else:
                row=engine.execute(stage,work,reference)
        finally:
            engine.native_deadline=original_deadline
            engine.rt.docker=original_runner
        assert row['passed'] and sha(Path(row['artifact']))==row['artifact_sha256']
        print(stage,'passed',flush=True)
    save(work/'current.json',{'stage':'routed_readback','status':'completed','inherited':list(inherited),
                              'newly_completed':['routing',*STAGES]})
    publish(reference,work,validation,inherited)


def publish(reference,work,validation,inherited):
    out=work/'delivery'
    out.mkdir(exist_ok=True)
    if (out/'manifest.json').exists():
        for name,record in read(out/'manifest.json')['files'].items():
            assert sha(out/name)==record['sha256']
        return
    stages={s:read(work/(s+'-evidence.json')) for s in STAGES}
    assert all(r['passed'] for r in stages.values()) and stages['routed_readback']['readback_equal']
    files={'final.def':'routed_readback.def','final.v':'routed_readback.v','final.gds':'final.gds'}
    for name,source in files.items():
        src=work/'result'/source
        assert src.stat().st_size
        if not (out/name).exists():
            os.link(src,out/name)
        assert sha(out/name)==sha(src)
    design=read(reference/'manifest.json')
    render(out/'final.def',[reference/p for p in design['cell_lefs']],out/'placement.svg')
    drc=stages['drc']['drc_gate']
    g=validation['offline_graph']
    eco=read(route_proof) if (route_proof:=BRANCH/'terminal-eco/terminal-eco-proof.json').is_file() else {}
    eco_paragraph=''
    if eco:
        eco_paragraph=f"<p>详细布线完成 4,761 个分区后，逐网检查发现 {eco['repaired_nets']} 条网有引脚断开。局部修复复用了这些分区；最后 {eco['native_supplemented_nets']} 条网由 iEDA 原生路由器补入 {eco['native_segments']} 段连线。回读结果见下。</p>"
    quality={'drc':drc,'timing':stages['timing']['timing'],'gds':stages['gds_export']['validation']}
    completed=[*inherited,'routing',*STAGES]
    assert completed==swerv_backend.STAGES
    evidence={'case':'bp_multi','input':DEF_HASH,'router':validation['binary_sha256'],'inherited':inherited,'completed':completed,
              'route_validation':validation,'stages':stages,'quality':quality,'published_at':time.time()}
    evidence['attempt']=read(work/'run-start.json')
    save(out/'acceptance.json',evidence)
    details=''.join('<tr><td>'+html.escape(name)+'</td><td>'+label+'</td></tr>'
                    for name,label in ((s,'复用并校验哈希' if s in inherited else '本次执行并核验') for s in completed))
    document=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>bp_multi 后端验收</title>
<style>body{{max-width:58em;margin:3em auto;padding:0 1em;font:16px/1.65 system-ui;color:#1d2935}}td,th{{text-align:left;padding:.3em 1em;border-bottom:1px solid #ddd}}code{{overflow-wrap:anywhere}}</style>
<h1>bp_multi 后端验收</h1><p>Nangate45 · {len(design['expected_macro_masters'])} 个固定硬宏 · 完成 {len(completed)} 个阶段。</p>
<p>{'原两小时总时限未通过。本次获准追加最多三小时。' if evidence['attempt'].get('budget',{}).get('expires_at') else '原两小时总时限未通过。后续续跑已获准取消耗时上限。' if evidence['attempt'].get('original_timeout_receipt') else ''}</p>
<h2>布线与物理质量</h2>{eco_paragraph}<p>独立回读核验 {g['net_count']:,} 条网、{g['pins']:,} 个端点。原生读取器核验 {validation['native_readback_graph']['audited_nets']:,} 条网。</p>
<p>独立 DRC 的最终违规计数为 <strong>{drc['violation_count']:,}</strong>。{'版图质量未通过零违规门槛。' if drc['violation_count'] else '已检查的规则均为零违规。'}未覆盖规则见验收凭据。
时序分析使用单元延迟，缺少提取 RC。GDS 为库抽象几何。</p><h2>阶段记录</h2><table>{details}</table>
<p>最终 DEF SHA-256 <code>{sha(out/'final.def')}</code></p><p>工作台的版图预览由该 DEF 生成，默认隐藏填充单元。</p></html>'''
    (out/'report.html').write_text(document,encoding='utf-8')
    names=[*files,'placement.svg','report.html','acceptance.json']
    save(out/'manifest.json',{'case':'bp_multi','run':BRANCH.name,'router':validation['binary_sha256'],'inherited':len(inherited),
         'completed':len(completed),'drc_count':drc['violation_count'],'files':{
             n:{'sha256':sha(out/n),'bytes':(out/n).stat().st_size} for n in names}})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('verify-prefix','continue'))
    parser.add_argument('--revision',type=int,choices=(11,12,13,14,16,17),default=11)
    opt=parser.parse_args()
    remote_service.init()
    reference,evidence=prefix()
    print('Verified frozen prefix:',','.join(evidence),flush=True)
    if opt.action=='continue':
        with remote_service.gate():
            if active_jobs():raise RuntimeError('Other native operation in progress')
            finish(reference,evidence,opt.revision)

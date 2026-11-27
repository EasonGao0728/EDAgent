"""Resume the qualified bp_multi stream after layer assignment. Never replay the prefix."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from verify_pa import BASE, DEF_HASH, RT, RUNS, SOURCE, active_jobs, limits, remote_service, save, setup, sha, usage
from qualify_route_state import DR_SHA

BUILD=Path('/srv/edagent/bp-multi-official-build-v1')
FAMILY=RUNS/('full-lazy-'+DR_SHA[:12])
SAMPLE=RUNS.parent/'bp-multi-compact-layer-test'
V12='6f66e655f6ca5d82fe99820dac17858b65428cba0cf0490a2fe21034cdca4b15'
V17='4bcf90e29e58c12d68c3312fc1aba7214b51fa08a3bcac3b0ee25994d8d06092'
V16='38e1d582f61d1d524f367ecffde779684fffda49820feb938eef97fd04707555'
V15='50181c0703a342f1479998d1c0008d9b5adbe3ff11655c3dbdf9ec3738e63201'
V14='6e2bb1c604846cbc4c793194463472412dbd82deaa7e3432e48e3dfb1371c243'
V13='e7e4a2a204f01c3a20214382db99843b448441da5d836c1e3b6abf0e5fb7e811'
EDGE_TABLE='41d5e5dd77e65a5e4ab303aa8a278c5dba5095bb4c8113e73380fc061383cf39'
BINDING='80da2933df61da48ff06a0ef21173ab3746d25353e4a13a20b1628171221be03'
TABLE=RUNS.parent/'bp-multi-sram-ce-escape-drc-v1/screened-escapes.tsv'


def read(path):
    return json.loads(path.read_bytes())


def attempt_name(revision,index=None):
    if index is None:index=int(os.environ.get('BP_MULTI_RETRY','0')) if revision==17 else 0
    if index<0 or (index and revision!=17):raise ValueError('Invalid branch attempt')
    return f'recovery-v{revision}'+(f'-r{index}' if index else '')


def publish_handle(work):
    """Update the workbench probe's live pointer only for this verified child."""
    from macro_agent.remote_native import identity
    h=read(work/'active.json')
    assert work in (FAMILY/'recovery-v12',FAMILY/'recovery-v13',FAMILY/'recovery-v14',FAMILY/'recovery-v15',FAMILY/'recovery-v16',FAMILY/attempt_name(17)) and h['start_ticks'] and identity(h['pid'])==h['start_ticks']
    path=RUNS/'qualification-live.json'
    if path.is_file():
        old=read(path)
        if old.get('start_ticks') and identity(old['pid'])==old['start_ticks']:
            if old['pid']==h['pid'] and old['start_ticks']==h['start_ticks']:return
            raise RuntimeError('Another live qualification is already registered')
        if old.get('run')==FAMILY.name and not (FAMILY/'original-handle.json').exists():
            save(FAMILY/'original-handle.json',old)
    save(path,dict(pid=h['pid'],start_ticks=h['start_ticks'],case_id='bp_multi',stage='routing / '+work.name,
                   run=str(work.relative_to(RUNS)),input_sha256=DEF_HASH))


def binary(revision=12):
    digest,ancestor={12:(V12,DR_SHA),13:(V13,V12),14:(V14,V13),15:(V15,V14),16:(V16,V15),17:(V17,V16)}[revision]
    directory=BUILD/('frozen-'+digest[:16])
    new=read(directory/'snapshot.json')
    old=read(BUILD/('frozen-'+ancestor[:16])/'snapshot.json')
    assert new['binary_sha256']==sha(directory/'iEDA')==digest and old['binary_sha256']==ancestor
    for key in ('upstream_commit','runtime_system_libs_sha256'):
        assert old[key]==new[key]
    a,b=old['irt_source_delta'],new['irt_source_delta']
    changes={k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}
    allowed=(
        'interface/RTInterface.cpp','source/module/space_router/SpaceRouter.cpp',
        'source/module/space_router/sr_data_manager/SRNode.hpp') if revision==12 else (
        'interface/RTInterface.cpp','source/module/detailed_router/DetailedRouter.cpp')
    if revision==14:
        allowed=('source/module/detailed_router/DetailedRouter.cpp',
                 'source/module/detailed_router/dr_data_manager/DRNode.hpp')
    if revision==17:allowed=('source/module/detailed_router/DetailedRouter.cpp',)
    assert changes=={'src/operation/iRT/'+s for s in allowed}
    return directory/'iEDA'


def open_budget():
    root=RUNS/'dispatch-v11'
    record=root/'budget-open.json'
    assert sha(record)=='80bd30605a1e08431f284ccad341dd8e0e2c9308ed1e9146b6744834e6d54371'
    grant=read(record)
    assert grant['family']==FAMILY.name and grant['legalization_sha256']==DEF_HASH
    assert sha(root/'budget-amendment-3h.json')==grant['previous_budget_sha256']
    assert sha(FAMILY/'recovery-v14/receipt.json')==grant['previous_receipt_sha256']
    return grant


def qualified_terminal_eco(origin):
    folder=origin.parent/'terminal-eco'
    proof=read(folder/'terminal-eco-proof.json')
    prior=read(origin/'receipt.json')
    assert origin.name=='recovery-v17-r1' and prior['returncode']!=0
    assert prior['binary_sha256']==V17 and prior['state_binding']==BINDING
    assert proof['original']==prior['states']['DR-batch']==sha(origin/'DR-batch.bin')
    assert proof['parent_receipt']==sha(origin/'receipt.json') and proof['binding']==BINDING
    audit=read(folder/'terminal-audit.json')
    assert audit['nets']==78493 and audit['disconnected']==0 and audit['stage']=='D12_4761'
    assert proof['terminal_audit']==sha(folder/'terminal-audit.json') and proof['bridges']==sha(folder/'accepted.tsv')
    probe=folder/'native-probe/receipt.json'
    assert sha(probe)==proof['native_eco_receipt'] and read(probe)['passed']
    assert proof['native_binary']==read(probe)['binary']==read(BUILD/'candidate-v18.json')['binary_sha256']
    candidate=folder/'terminal-repaired.bin'
    assert proof['derived']==sha(candidate) and proof['repaired_nets']==423
    return candidate,proof


def execute(sample,revision=12,replay=False,interrupt_test=False):
    ref=setup()
    executable=binary(revision)
    digest={12:V12,13:V13,14:V14,15:V15,16:V16,17:V17}[revision]
    level={12:'LA',13:'SR',14:'TA',15:'TA',16:'TA',17:'TA'}[revision]
    parent=read(FAMILY/'receipt.json')
    assert parent['returncode']==134 and parent['state_binding']==BINDING
    assert parent['input_sha256']==sha(SOURCE)==DEF_HASH and parent['binary_sha256']==DR_SHA
    assert parent['pa']['passed'] and sha(FAMILY/'pa.tsv')==parent['pa']['ap_witness_sha256']
    assert sha(TABLE)=='74b9910526e4d0bf6c83997b7d6485303b476b7b6323ecbcd8a9256778526779'
    if sample:
        source=RUNS/'abutment-126.def'
        origin=SAMPLE/'direct'
        saved=read(origin/'receipt.json')
        state_hash=saved['states']['LA']
        assert sha(source)==saved['input'] and saved['ended']
        work=SAMPLE/'downstream-v12'
        contract=sha(source)
        template=SAMPLE/'downstream-v11/check.tcl'
    else:
        sample_work=SAMPLE/'downstream-v12'
        passed=read(sample_work/'sample-acceptance.json')
        assert passed['passed'] and passed['binary']==V12 and sha(sample_work/'result/routing.def')==passed['artifact']
        source=SOURCE
        origin=FAMILY
        work=FAMILY/attempt_name(revision)
        state_hash=parent['checkpoints']['LA']['sha256']
        assert state_hash=='55353093103e409f7147515e4e80c8d7cad75d6d137b5d291afe12a0196f4c8a'
        assert read(FAMILY/'state-contract.json')['sha256']==BINDING
        contract=BINDING
        template=FAMILY/'route.tcl'
    if revision==13:
        assert not sample
        origin=FAMILY/'recovery-v12'
        previous=read(origin/'receipt.json')
        assert previous['returncode'] and previous['restored'] and not any(previous['prefix_counts'].values())
        assert previous['binary_sha256']==V12 and previous['input_sha256']==DEF_HASH
        assert previous['restored_sha256']==state_hash
        state_hash=previous['states']['SR']
        prep=read(origin/'boundary-leads.json')
        assert prep['sr']==state_hash and prep['source']==DEF_HASH and prep['ports']==1431
        assert prep['cross_net_lead_and_io_overlaps']==0 and prep['table']==sha(origin/'boundary-leads.tsv')==EDGE_TABLE
    if revision>=14:
        origin=SAMPLE/'downstream-v12' if sample else FAMILY/'recovery-v13'
        previous=read(origin/'receipt.json')
        state_hash=previous['states']['TA']
        assert previous['input_sha256']==sha(source) and previous['restored'] and not any(previous['prefix_counts'].values())
        if sample:
            assert previous['binary_sha256']==V12 and previous['returncode']==0
            work=SAMPLE/f'downstream-v{revision}'
        else:
            assert previous['returncode']==134 and previous['binary_sha256']==V13 and previous['accepted_boundary_leads']
            assert state_hash=='95442bf49b01ad4174a5a5035d6b9dfb058ec9d37cb0bccea58fe6f39259a2d5'
            assert previous['boundary_table']==sha(FAMILY/'recovery-v12/boundary-leads.tsv')==EDGE_TABLE
            sample_work=SAMPLE/f'downstream-v{revision}'
            canary=read(sample_work/'sample-acceptance.json')
            assert canary['passed'] and canary['binary']==digest and canary['artifact']==sha(sample_work/'result/routing.def')
    if revision==16 and not sample:
        replay_check=read(SAMPLE/'downstream-v16-replay/sample-acceptance.json')
        assert replay_check['passed'] and replay_check['binary']==V16 and replay_check['same_reference_per_net_paths']
    if revision>=15:
        open_budget()
    state=origin/(level+'.bin')
    if interrupt_test:
        assert sample and revision==16
        work=SAMPLE/'downstream-v16-interrupt'
    if replay or revision==17:
        assert revision==17 or (sample and revision>=15)
        origin=SAMPLE/'downstream-v16-interrupt' if revision==16 else work
        if revision==17:
            origin=SAMPLE/'downstream-v16-interrupt' if sample else FAMILY/'recovery-v16'
            index=int(os.environ.get('BP_MULTI_RETRY','0')) if not sample else 0
            if index:
                origin=FAMILY/attempt_name(17,index-1)
            if not sample:
                prior=read(origin/'receipt.json')
                assert prior['binary_sha256']==(V17 if index else V16) and prior['returncode']!=0
                assert prior['input_sha256']==DEF_HASH and prior['state_binding']==BINDING
                if index and index!=2:
                    assert 'std::bad_alloc' in (origin/'stdout.log').read_text(errors='replace')
        state=origin/'DR-batch.bin'
        state_hash=read(origin/'receipt.json')['states']['DR-batch']
        eco=None
        if revision==17 and not sample and index==2:
            state,eco=qualified_terminal_eco(origin)
            state_hash=eco['derived']
        with state.open('rb') as batch:
            def field():
                length=int.from_bytes(batch.read(4),'little')
                assert 0<length<100
                return batch.read(length).decode()
            assert field()=='ieda-route-state-v1'
            level=field()
            assert re.fullmatch((r'D12_' if revision>=16 else r'D4_')+r'[1-9][0-9]*',level) and field()==contract
            if revision>=16:
                if revision==17 and not sample and index:
                    assert int(level[4:])>int(prior.get('restored_level','D12_128')[4:])
                else:assert level=='D12_128'
        if replay:work=SAMPLE/f'downstream-v{revision}-replay'
    assert sha(state)==state_hash
    if (work/'receipt.json').exists():
        saved=read(work/'receipt.json')
        assert saved['binary_sha256']==digest and saved['restored_sha256']==state_hash
        return saved
    work.mkdir(exist_ok=False)
    shutil.copytree(FAMILY/'config',work/'config')
    for n in ('result/rt','result/report'):
        (work/n).mkdir(parents=True)
    shutil.copy2(template,work/'route.tcl')
    if not sample:os.link(FAMILY/'pa.tsv',work/'pa.tsv')
    args=['bwrap','--die-with-parent','--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts']
    for p in ('/usr','/bin','/lib','/lib64'):args+=['--ro-bind',p,p]
    for p,d in [(executable,'/official/iEDA'),(RT,'/runtime'),(ref,'/reference'),(source,'/input.def' if sample else '/frozen.def'),
                (state,'/restore.bin'),(TABLE,'/screened.tsv')]:
        args+=['--ro-bind',str(p),d]
    if revision>=13 and not sample:args+=['--ro-bind',str(FAMILY/'recovery-v12/boundary-leads.tsv'),'/boundary.tsv']
    args+=['--proc','/proc','--dev','/dev','--tmpfs','/tmp','--bind',str(work),'/work','--chdir','/work','--clearenv']
    env=dict(read(FAMILY/'state-contract.json')['contract']['route_environment'])
    for key in ('IEDA_RT_PA_GATE','IEDA_RT_PA_WITNESS'):env.pop(key)
    env.update(IEDA_RT_RESTORE_LEVEL=level,IEDA_RT_RESTORE_STATE='/restore.bin',IEDA_RT_STATE_BINDING=contract,
               IEDA_RT_SAVE_SR='/work/SR.bin',IEDA_RT_SAVE_TA='/work/TA.bin')
    if revision>=13 and not sample:env.update(IEDA_RT_BOUNDARY_LEADS='/boundary.tsv')
    if revision==15:
        env.update(IEDA_RT_DR_WINDOW='4',IEDA_RT_SAVE_DR_BATCH='/work/DR-batch.bin')
    if revision>=16:
        env.update(IEDA_RT_SAVE_DR_BATCH='/work/DR-batch.bin')
        if interrupt_test:env['IEDA_RT_TEST_FIRST_BATCH']='1'
    if revision==17 and not sample and index:
        env.update(MALLOC_ARENA_MAX='2', MALLOC_TRIM_THRESHOLD_='131072')
    for k,v in env.items():args+=['--setenv',k,v]
    seconds=360 if sample else parent['timeout_s']
    if revision>=15:seconds=None
    if seconds:args+=['/usr/bin/timeout','--foreground','--kill-after=5',str(seconds)]
    args+=['/official/iEDA','-script','/work/route.tcl']
    started=time.time()
    rss=vm=0
    with (work/'stdout.log').open('xb') as log:
        proc=subprocess.Popen(args,preexec_fn=limits,start_new_session=True,stdout=log,stderr=subprocess.STDOUT)
        from macro_agent.remote_native import identity
        save(work/'active.json',dict(pid=proc.pid,start_ticks=identity(proc.pid),started=started,timeout_s=seconds))
        if not sample:publish_handle(work)
        while proc.poll() is None:
            a,b=usage(proc.pid);rss=max(rss,a);vm=max(vm,b);time.sleep(.75)
    rt=(work/'result/rt/rt.log').read_text(errors='replace') if (work/'result/rt/rt.log').exists() else ''
    modules=dict(PA=('PinAccessor','access'),SA=('SupplyAnalyzer','analyze'),TG=('TopologyGenerator','generate'),LA=('LayerAssigner','assign'))
    if revision>=13:modules['SR']=('SpaceRouter','route')
    if revision>=14:modules['TA']=('TrackAssigner','assign')
    counts={name:len(re.findall(rf'{cls}\.cpp:\d+ Info {method}\] Starting',rt)) for name,(cls,method) in modules.items()}
    artifact=work/'result/routing.def'
    row=dict(input_sha256=sha(source),binary_sha256=digest,restored_sha256=state_hash,state_binding=contract,
             parent_receipt_sha256=sha(origin/'receipt.json'),prefix_counts=counts,returncode=proc.returncode,
             timeout_s=seconds,wall_s=time.time()-started,peak_rss_bytes=rss,peak_vm_bytes=vm,cpus=4,address_space_gib=8,
             restored_level=level,restored=('Restored route checkpoint '+level) in rt,stage_marker='SWERV_STAGE_OK routing' in (work/'stdout.log').read_text(errors='replace'),
             states={p.stem:sha(p) for p in work.glob('*.bin')},output_sha256=sha(artifact) if artifact.is_file() else None)
    if not sample:row['pa']=parent['pa']
    if revision==17 and not sample and index==2:
        row['terminal_eco']=eco
    if revision==13:
        row['boundary_table']=EDGE_TABLE
        row['accepted_boundary_leads']=bool(re.search(r'EDA_BOUNDARY_LEADS ports=1431 nets=1431\b',rt))
    if revision>=14 and not sample:row['boundary_table']=EDGE_TABLE
    save(work/'receipt.json',row)
    return row


def sample_check(row,revision=12,replay=False):
    from verify_route_v7 import PhysicalLibrary, check, independent_graph, read_def
    from collections import Counter
    from macro_agent.def_validation import section
    work=SAMPLE/(f'downstream-v{revision}'+('-replay' if replay else ''))
    source=RUNS/'abutment-126.def'
    artifact=work/'result/routing.def'
    before,after=read_def(source),read_def(artifact)
    ref=setup()/'data'
    lib=PhysicalLibrary(ref/'input2.lef',[ref/f'input{i}.lef' for i in range(3,10)],after['units'])
    expected={k:v for k,v in before['nets'].items() if len(v)>=2}
    graph=independent_graph(artifact.read_text(),after,expected,lib)
    design=check(before,after,'routing')
    def routed_paths(path):
        rows={}
        for record in section(path.read_text(),'NETS'):
            blocks=re.split(r'\+\s+(?:ROUTED|FIXED|COVER)\s+',record)
            rows[record.split()[0]]=Counter(' '.join(segment.split()) for block in blocks[1:]
                                             for segment in re.split(r'\s+NEW\s+',block))
        return rows
    baseline=SAMPLE/'downstream-v11/result/routing.def'
    if revision==17:baseline=SAMPLE/'downstream-v16/result/routing.def'
    if replay:baseline=SAMPLE/f'downstream-v{revision}/result/routing.def'
    same_paths=routed_paths(artifact)==routed_paths(baseline)
    ok=design['passed'] and before['physical']==after['physical'] and graph['passed'] and graph['pins']==494 and len(expected)==126 and (same_paths or (revision==15 and not replay))
    report=dict(passed=ok,binary=row['binary_sha256'],artifact=row['output_sha256'],graph=graph,transformation=design,
                reference_def_sha256=sha(baseline),same_reference_per_net_paths=same_paths,compared_with=str(baseline))
    save(work/'sample-acceptance.json',report)
    if not ok:raise RuntimeError(report)


if __name__=='__main__':
    assert sys.argv[1:] in (['sample'],['whole'],['boundary'],['dr-sample'],['dr'],['window-sample'],['window-replay'],['window'],['batch-sample'],['batch-interrupt'],['batch-replay'],['batch'],['stable-sample'],['stable'])
    sample=sys.argv[1] in ('sample','dr-sample','window-sample','window-replay','batch-sample','batch-interrupt','batch-replay','stable-sample')
    revision={'sample':12,'whole':12,'boundary':13,'dr':14,'dr-sample':14,'window':15,'window-sample':15,'window-replay':15,'batch':16,'batch-sample':16,'batch-interrupt':16,'batch-replay':16,'stable':17,'stable-sample':17}[sys.argv[1]]
    remote_service.init()
    with remote_service.gate():
        if active_jobs():raise RuntimeError('Concurrent native operation')
        replay=sys.argv[1] in ('window-replay','batch-replay')
        interrupt_test=sys.argv[1]=='batch-interrupt'
        row=execute(sample,revision,replay,interrupt_test)
        if interrupt_test:
            assert row['returncode'] and row['states']['DR-batch'] and row['restored']
            assert 'TEST_CHECKPOINT_READY' in (SAMPLE/'downstream-v16-interrupt/stdout.log').read_text(errors='replace')
            sys.exit(0)
        assert row['returncode']==0 and row['stage_marker'] and row['restored'] and not any(row['prefix_counts'].values()),row
        if sys.argv[1]=='boundary':assert row['accepted_boundary_leads']
        if sample:sample_check(row,revision,replay)

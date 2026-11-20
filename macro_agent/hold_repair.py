"""Pinned, server-only repair experiment. Historical campaign stays read-only."""
from pathlib import Path
import hashlib,json,os,struct,subprocess,sys,time,shutil
from . import hold_calibration as h

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/hold-repair-20261116-v1'
OLD=ROOT/'runs/hold-calibration-20261115-v1'
BASE_SHA='d9ae28962bf622f1139e2b438c6f69deb646d93a48ece783da80a082d607694a'
HOLD_SHA256='f881cd0b0118bbfdab115a1cd793f18a666a6148da0a755eb591851c88df6abd'
RC_REFERENCE_SHA256='6e50227803fcf3162d64f6bfa739cf63521c72c63aa44b07d16121fbc25f36ea'
TOOL=ROOT/'environments/ieda-hold-guard-v1'

def guarded_binary(data):
    """Clamp the progress divisor in an existing 10-byte alignment NOP.

    No relocation, algorithm, library, limits or estimator changes. This is an
    explicitly identified binary compatibility patch, NOT an upstream build.
    """
    if hashlib.sha256(data).hexdigest()!=BASE_SHA:raise ValueError('BASE_BINARY_IDENTITY_MISMATCH')
    if data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',data,18)[0]!=62:raise ValueError('EXPECTED_X86_64_ELF')
    phoff=struct.unpack_from('<Q',data,32)[0];size,count=struct.unpack_from('<HH',data,54)
    address=0xd2b7b6;offset=None
    for i in range(count):
        typ,flags,off,va,pa,filesz,memsz,align=struct.unpack_from('<IIQQQQQQ',data,phoff+i*size)
        if typ==1 and flags&1 and va<=address and address+10<=va+filesz:offset=off+address-va
    if offset is None:raise ValueError('PATCH_NOT_IN_EXECUTABLE_SEGMENT')
    before=bytes.fromhex('66 2e 0f 1f 84 00 00 00 00 00')
    after=bytes.fromhex('85 d2 75 04 ff 44 24 2c 66 90')
    if data[offset:offset+10]!=before:raise ValueError('INSTRUCTION_BYTES_MISMATCH')
    out=data[:offset]+after+data[offset+10:]
    assert len(data)==len(out) and out[:offset]==data[:offset] and out[offset+10:]==data[offset+10:]
    return out,{'virtual_address':hex(address),'file_offset':offset,'before':before.hex(),'after':after.hex(),
        'semantics':'test edx; if zero increment batch_size slot from 0 to 1; original division and optimizer preserved',
        'scope':'alignment NOP before loop; empty fanin vector already bypasses loop'}

def build(folder):
    raw=(ROOT.parent/'portable-runtime-v1/iEDA').read_bytes();data,patch=guarded_binary(raw)
    TOOL.mkdir(parents=True,exist_ok=True);dest=TOOL/'iEDA';digest=hashlib.sha256(data).hexdigest()
    if dest.exists() and h.sha(dest)!=digest:raise ValueError('DO_NOT_OVERWRITE_TOOL_VARIANT')
    if not dest.exists():dest.write_bytes(data);dest.chmod(0o755)
    dis=subprocess.run(['objdump','-d','-C','--start-address=0xd2b740','--stop-address=0xd2b7e6',str(dest)],capture_output=True,text=True,timeout=15,check=True).stdout
    (folder/'disassembly.txt').write_text(dis)
    # Execute the actual guard instruction bytes in a small x86-64 C harness,
    # never load or rerun a historical design for this boundary test.
    code=r'''#include <cstdio>
extern "C" int guard_batch(int);
int main(){for(int n=0;n<=10000;n++){int d=guard_batch(n/10);if(d!=(n<10?1:n/10))return 1;for(int i=0;i<n;i++)if((i+1)%d<0)return 2;}puts("GUARD_BOUNDARIES_OK");}
'''
    (folder/'guard_test.cpp').write_text(code)
    assembly='.text\n.global guard_batch\n.type guard_batch,@function\nguard_batch:\nsub $64,%rsp\nmov %edi,%edx\nmov %edx,44(%rsp)\n.byte '+','.join('0x'+patch['after'][i:i+2] for i in range(0,20,2))+'\nmov 44(%rsp),%eax\nadd $64,%rsp\nret\n.section .note.GNU-stack,"",@progbits\n'
    (folder/'guard_test.S').write_text(assembly)
    subprocess.run(['g++','-O2','-fsanitize=undefined',str(folder/'guard_test.cpp'),str(folder/'guard_test.S'),'-o',str(folder/'guard_test')],check=True,capture_output=True,timeout=30)
    p=subprocess.run([str(folder/'guard_test')],check=True,capture_output=True,text=True,timeout=30)
    source=ROOT.parent/'ieda-rootcause-20261112/source/src/operation/iTO/source/module/fix_hold/HoldOptimizer_process.cpp'
    text=source.read_text();old='int batch_size = fanins.size() / 10;';assert text.count(old)==1
    (folder/'HoldOptimizer_process.fixed.cpp').write_text(text.replace(old,'int batch_size = fanins.size() < 10 ? 1 : fanins.size() / 10;'))
    value={'base_sha256':BASE_SHA,'binary_sha256':digest,'binary_patch':patch,'binary_kind':'isolated compatibility guard, not upstream rebuild',
        'source_reference':str(source),'source_sha256':h.sha(source),'unit_test':p.stdout.strip(),'original_unchanged':h.sha(ROOT.parent/'portable-runtime-v1/iEDA')==BASE_SHA,
        'algorithm_or_timing_model_changed':False,'production_default_replaced':False}
    h.save(TOOL/'manifest.json',value);return value

def run_phase(phase,folder):
    if phase=='build':return build(folder)
    if phase=='smoke':return smoke(folder)
    if phase=='clock-api':return h.native(folder,h.SWERV,'puts "CLOCK_API [info commands *clock*]"\nputs "PIN_API [info commands *pin*]"\nputs "RC_API [info commands *spef*]"',seconds=60)
    if phase=='rc-direct':return rc_direct(folder)
    if phase=='rc-official':return rc_official(folder)
    if phase=='rc-qualification':
        rc_official(folder,[('jpeg','skip')]);return qualification(folder)
    if phase=='resume-budgets':return resume_budgets(folder)
    raise ValueError('Unimplemented fixed phase')

def smoke(folder):
    q=json.loads((OLD/'checkpoints/qualification.json').read_text());rows=[]
    original=h.native;h.OUT=OUT
    def patched(*a,**kw):
        # h.stage passes its action as the fourth positional argument.
        if (a[3] if len(a)>3 else kw.get('label'))=='hold':kw['holdfix']=True
        return original(*a,**kw)
    h.native=patched
    try:
        for name in ('aes','tinyram'):
            c=next(x for x in q if x['case']==name);src=Path(c['frozen_checkpoint']['path'])
            if h.sha(src)!=c['frozen_checkpoint']['sha256']:raise ValueError('CHECKPOINT_CHANGED')
            previous=OLD/'sweep'/name/'cap01/hold/native-receipt.json'
            if json.loads(previous.read_text())['returncode']!=136:raise ValueError('EXPECTED_PREVIOUS_DIVIDE_FAILURE')
            row={'case':name,'previous_failure':str(previous),'previous_failure_sha256':h.sha(previous),'source':c['frozen_checkpoint'],'stages':[]};rows.append(row)
            ref=OLD/'references'/name
            for action in ('hold','legal','measure'):
                e=h.stage(ref,src,folder/name/action,action,.01 if action=='hold' else None);row['stages'].append(e);src=Path(e['artifact']['path'])
            row['timing']=h.estimated(folder/name/'measure',json.loads((ref/'manifest.json').read_text())['clocks'])
            row['source_unchanged']=h.sha(c['frozen_checkpoint']['path'])==c['frozen_checkpoint']['sha256']
            h.save(folder/'results.json',rows)
    finally:h.native=original
    return rows

def rc_direct(folder):
    from .def_io_compat import write_equivalent,equivalent
    import re
    q=json.loads((OLD/'checkpoints/qualification.json').read_text());rows=[];h.OUT=OUT
    for name in ('gcd','aes'):
        c=next(x for x in q if x['case']==name);ref=OLD/'references'/name;w=folder/name;m=h.configure(w,ref)
        write_equivalent(c['baseline_legal'],w/'input.def')
        body=h.preamble(m)+'run_timing_eval -path /work/result/estimated -eval_output_path /work/result/estimated -routing_type FLUTE\ndef_save -path /work/result/readback.def\n'
        r=h.native(w,ref,body,'direct-flute');s=(w/'logs/native.log').read_text(errors='replace')
        rows.append({'case':name,'native':r,'timing':h.estimated(w,m['clocks'],'direct_flute'),
            'pruned_net_count':len(set(re.findall(r'pruned .*?from net (\S+)',s))),
            'unclocked_endpoints':sorted(set(re.findall(r'end vertex (\S+) has no clock data',s))),
            'readback_unchanged':equivalent(w/'input.def',w/'result/readback.def')})
        h.save(folder/'results.json',rows)
    return rows

def rc_official(folder,selected=None):
    from .def_io_compat import write_equivalent,equivalent
    import re
    source=ROOT.parent/'ieda-rootcause-20261112/bin/iEDA'
    dest=ROOT/'environments/ieda-rc-reference-v1/iEDA'
    if h.sha(source)!=RC_REFERENCE_SHA256:raise ValueError('REFERENCE_BINARY_CHANGED')
    dest.parent.mkdir(exist_ok=True)
    if not dest.exists():shutil.copyfile(source,dest);dest.chmod(0o755)
    if h.sha(dest)!=RC_REFERENCE_SHA256:raise ValueError('REFERENCE_COPY_CHANGED')
    q=json.loads((OLD/'checkpoints/qualification.json').read_text());rows=[];h.OUT=OUT
    for name,label in selected or [('gcd','skip'),('aes','skip'),('aes','cap01'),('tinyram','skip'),('tinyram','cap01')]:
        c=next(x for x in q if x['case']==name);ref=OLD/'references'/name;w=folder/name/label
        src=Path(c['baseline_legal']) if label=='skip' else Path(json.loads((OUT/'smoke/results.json').read_text())[0 if name=='aes' else 1]['stages'][1]['artifact']['path'])
        m=h.configure(w,ref);write_equivalent(src,w/'input.def')
        row={'case':name,'label':label,'source':str(src),'source_sha256':h.sha(src)};rows.append(row)
        body=h.preamble(m)+'run_sta -output /work/result/timing\nrun_timing_eval -path /work/result/estimated -eval_output_path /work/result/estimated -routing_type FLUTE\ndef_save -path /work/result/readback.def\n'
        try:
            row['native']=h.native(w,ref,body,'official-flute',rc_reference=True)
            row.update(timing=h.estimated(w,m['clocks']),readback_unchanged=equivalent(w/'input.def',w/'result/readback.def'),status='measured')
        except Exception as e:row.update(status='failed',error=repr(e))
        s=(w/'logs/native.log').read_text(errors='replace')
        row.update(pruned_net_count=len(set(re.findall(r'pruned .*?from net (\S+)',s))),unclocked_endpoints=sorted(set(re.findall(r'end vertex (\S+) has no clock data',s))),source_unchanged=h.sha(src)==row['source_sha256'])
        h.save(folder/'results.json',rows)
    return rows

TIMING_KEYS=('max_worst_slack_ns','max_tns_ns','min_worst_slack_ns','min_tns_ns')

def comparable(reference,candidate,tolerance=1e-9):
    import math
    return all(math.isfinite(reference[k]) and math.isfinite(candidate[k]) and abs(reference[k]-candidate[k])<=tolerance for k in TIMING_KEYS)

def qualification(folder):
    q=json.loads((OLD/'checkpoints/qualification.json').read_text())
    smoke_rows=json.loads((OUT/'smoke/results.json').read_text())
    rows=json.loads((OUT/'rc-official/results.json').read_text())+json.loads((folder/'results.json').read_text())
    comparisons=[]
    for r in rows:
        c=next(x for x in q if x['case']==r['case'])
        expected=c['baseline_timing'] if r['label']=='skip' else next(x for x in smoke_rows if x['case']==r['case'])['timing']
        passed=(r['status']=='measured' and r['readback_unchanged'] and r['source_unchanged'] and not r['unclocked_endpoints'] and comparable(expected,r['timing']))
        comparisons.append({'case':r['case'],'label':r['label'],'passed':passed,'reference_binary_sha256':RC_REFERENCE_SHA256,
            'maximum_abs_delta_ns':max(abs(expected[k]-r['timing'][k]) for k in TIMING_KEYS) if r.get('timing') else None})
    passed=len(comparisons)==6 and all(x['passed'] for x in comparisons)
    result={'comparative_estimated_screening_qualified':passed,'comparisons':comparisons,
        'blocked_cases':{'apb4_timer_nangate45_t':'missing derived-clock mode/constraints; user confirmed unavailable',
            'swerv_nangate45':'missing JTAG clock period/mode; user confirmed unavailable',
            's35932_nangate45_t':'missing IO timing constraints','bp_fe':'missing three macro LEF/Liberty model pairs'},
        'measurement_protocol':'fresh process, frozen libraries/SDC/DEF; run_sta then run_timing_eval FLUTE; aggregate every expected clock; inspect uncovered endpoints',
        'scope':'same-profile pre-route comparisons only; reference uses same iSTA family, not independent signoff',
        'production_default_calibration_qualified':False,'extracted_rc_validated':False}
    h.save(folder/'qualification.json',result)
    if not passed:raise ValueError('RC_COMPARISON_NOT_QUALIFIED')
    return result

def resume_budgets(folder):
    from . import pin_metrics,hold_policy
    gate=json.loads((OUT/'rc-qualification/qualification.json').read_text())
    if not gate['comparative_estimated_screening_qualified']:raise ValueError('MEASUREMENT_GATE_BLOCKED')
    q=json.loads((OLD/'checkpoints/qualification.json').read_text())
    previous=json.loads((OLD/'sweep/results.json').read_text());smoke_rows=json.loads((OUT/'smoke/results.json').read_text())
    result=[];original=h.native;h.OUT=OUT
    def patched(*a,**kw):
        if (a[3] if len(a)>3 else kw.get('label'))=='hold':kw['holdfix']=True
        return original(*a,**kw)
    h.native=patched
    try:
        for name in ('aes','tinyram'):
            case=next(x for x in q if x['case']==name);old=next(x for x in previous if x['case']==name)
            src=Path(case['frozen_checkpoint']['path']);ref=OLD/'references'/name;m=json.loads((ref/'manifest.json').read_text());lefs=[ref/p for p in m['cell_lefs']]
            if h.sha(src)!=case['frozen_checkpoint']['sha256']:raise ValueError('FROZEN_CHECKPOINT_CHANGED')
            base=old['candidates'][0];sm=next(x for x in smoke_rows if x['case']==name)
            one={'label':'cap01','cap':.01,'status':'measured','reused_completed_smoke':True,'artifact':sm['stages'][1]['artifact'],
                'measurement':pin_metrics.measure(sm['stages'][1]['artifact']['path'],lefs),'timing':sm['timing'],'geometry_passed':sm['stages'][1]['geometry']['passed'],'connectivity_passed':True}
            row={'case':name,'candidates':[base,one],'production_replaced':False};result.append(row);start=time.monotonic()
            cache={sm['stages'][0]['artifact']['sha256']:one}
            for label,cap in [('cap025',.025),('cap05',.05),('cap10',.1),('cap20',.2)]:
                old_failure=OLD/'sweep'/name/label/'hold/native-receipt.json'
                if json.loads(old_failure.read_text())['returncode']!=136:raise ValueError('ONLY_FAILED_ARMS_MAY_RESUME')
                arm_start=time.monotonic()
                def remaining():
                    seconds=int(min(600-(time.monotonic()-arm_start),3600-(time.monotonic()-start)))
                    if seconds<1:raise TimeoutError('FROZEN_BUDGET_EXHAUSTED')
                    return seconds
                c={'label':label,'cap':cap,'previous_failure':str(old_failure),'previous_failure_sha256':h.sha(old_failure)};row['candidates'].append(c)
                try:
                    r=h.stage(ref,src,folder/name/label/'hold','hold',cap,seconds=remaining());c['hold_evidence']=r
                    key=r['artifact']['sha256']
                    if key in cache:
                        matched=cache[key]
                        if h.sha(matched['artifact']['path'])!=matched['artifact']['sha256']:raise ValueError('REUSE_ARTIFACT_CHANGED')
                        for k in ('artifact','measurement','timing','geometry_passed','connectivity_passed'):c[k]=matched[k]
                        c['reused_identical_hold_output_from']=matched['label']
                    else:
                        legal=h.stage(ref,Path(r['artifact']['path']),folder/name/label/'legal','legal',seconds=remaining())
                        measured=h.stage(ref,Path(legal['artifact']['path']),folder/name/label/'measure','measure',seconds=remaining())
                        c.update(artifact=legal['artifact'],measurement=pin_metrics.measure(legal['artifact']['path'],lefs),timing=h.estimated(folder/name/label/'measure',m['clocks']),geometry_passed=legal['geometry']['passed'],connectivity_passed=measured['transformation']['passed'])
                        cache[key]=c
                    c['status']='measured'
                except Exception as e:c.update(status='failed',error=repr(e))
                c['seconds']=time.monotonic()-arm_start;h.save(folder/'results.json',result)
            row['review']=hold_policy.review([c for c in row['candidates'] if c['status']=='measured'],{**hold_policy.POLICY,'scope':gate['scope']})
            row['review']['routing_allowed']=False
            row['checkpoint_unchanged']=h.sha(src)==case['frozen_checkpoint']['sha256']
            h.save(folder/'results.json',result)
    finally:h.native=original
    return result

def worker(phase):
    from .remote_platform import install
    from .swerv_screening import active_jobs
    import resource
    os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:4]);resource.setrlimit(resource.RLIMIT_AS,(8*1024**3,8*1024**3));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    task=install();p=OUT/phase/'receipt.json'
    with task.locked(ROOT/'scheduler'):
        r=json.loads(p.read_text());r.update(status='running',started_at=time.time(),pid=os.getpid());h.save(p,r)
        try:
            if active_jobs():raise RuntimeError('SERVER_BUSY')
            r.update(result=run_phase(phase,p.parent),status='completed')
        except BaseException as e:r.update(status='failed',error=repr(e))
        r['finished_at']=time.time();h.save(p,r)

def dispatch(op,phase):
    from .remote_platform import install
    from .swerv_screening import active_jobs
    if phase not in {'build','smoke','clock-api','rc-direct','rc-official','rc-qualification','resume-budgets'}:raise ValueError('UNREVIEWED_PHASE')
    task=install();p=OUT/phase/'receipt.json'
    if op=='status':return json.loads(p.read_text()) if p.exists() else {'status':'not_started','job_id':OUT.name+'-'+phase}
    if op!='start':raise ValueError('FIXED_START_STATUS_ONLY')
    with task.locked(ROOT/'scheduler'):
        if p.exists():return dispatch('status',phase)
        if active_jobs():raise RuntimeError('SERVER_BUSY')
        p.parent.mkdir(parents=True,exist_ok=False);r={'status':'queued','job_id':OUT.name+'-'+phase,'source_sha256':h.sha(__file__),'created_at':time.time()};h.save(p,r)
        cmd=f'cd {ROOT} && exec /usr/bin/timeout --kill-after=10 3600 python3 -B -m macro_agent.hold_repair worker {phase}'
        v=subprocess.run(['tmux','new-session','-d','-s',r['job_id'],cmd],capture_output=True,text=True,timeout=10)
        if v.returncode:r.update(status='failed',error=v.stderr);h.save(p,r)
        return r

if __name__=='__main__':
    if sys.argv[1:2]==['worker']:worker(sys.argv[2])
    else:
        try:
            q=json.load(sys.stdin);print(json.dumps({'ok':True,'value':dispatch(q['operation'],q['phase'])}))
        except Exception as e:print(json.dumps({'ok':False,'error':str(e)}));sys.exit(1)

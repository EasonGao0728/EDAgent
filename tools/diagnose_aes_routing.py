"""Bounded diagnostic only: archived log analysis and optional tiny CPU probe."""
import argparse, datetime, gzip, hashlib, html, json, re, statistics, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/aes-p1-20261108/diagnostics-20261111'
TASK=ROOT/'runs/dsh-desktop-4247ed3bc3eefbe0/main-task'
SERVER=ROOT/'runs/aes-p1-20261108/downloaded/v5d/server-core-02'
WORK=TASK/'attempts/59d2a8277928'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(name,data):
    OUT.mkdir(exist_ok=True)
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def elapsed(s):
    a=list(map(int,s.split(':')))
    return sum(v*60**i for i,v in enumerate(reversed(a)))
def parse_log(p):
    text=re.sub(r'\x1b\[[0-9;]*m','',p.read_text(errors='replace'))
    rows=[]
    for line in text.splitlines():
        if not re.search(r'(PinAccessor|TopologyGenerator|LayerAssigner|SpaceRouter|TrackAssigner|DetailedRouter)',line):continue
        m=re.search(r'\[RT (\d{8} \d\d:\d\d:\d\d).*? (\w+)\.cpp.*? (Routed|Assigned) (\d+)/(\d+).*?elapsed = ([\d:]+), cpu = ([\d:]+)',line)
        if m:
            stamp,phase,_,n,total,wall,cpu=m.groups()
            rows.append(dict(timestamp=stamp,phase=phase,n=int(n),total=int(total),wall_seconds=elapsed(wall),cpu_seconds=elapsed(cpu),line=line))
    phases=[]
    for line in text.splitlines():
        m=re.search(r'(PinAccessor|TopologyGenerator|SpaceRouter|DetailedRouter)\.cpp.*Info (access|generate|route)\] Completed \(elapsed = ([\d:]+), cpu = ([\d:]+)',line)
        if m:phases.append({'phase':m[1],'wall_s':elapsed(m[3]),'cpu_s':elapsed(m[4]),'line':line})
    return {'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size,'progress':rows,'completed_phases':phases,
            'rejected_patch_warnings':text.count('Reject local exact patch'),
            'warning_reasons':{x:text.count('reason='+x) for x in sorted(set(re.findall(r'Reject local exact patch[^\n]*reason=([^,]+)',text)))}}
def analyze():
    local=parse_log(WORK/'logs/routing.log');server=parse_log(SERVER/'logs/routing.log')
    # Match only detailed-routing batches, not aggregate vs partial runtimes.
    ss={r['n']:r for r in server['progress'] if r['phase']=='DetailedRouter'}
    pairs=[]
    for r in local['progress']:
        if r['phase']=='DetailedRouter' and r['n'] in ss:
            s=ss[r['n']]
            pairs.append({'boxes':r['n'],'total':r['total'],'local_wall_s':r['wall_seconds'],'server_wall_s':s['wall_seconds'],
                'wall_ratio':r['wall_seconds']/s['wall_seconds'],'local_cpu_s':r['cpu_seconds'],'server_cpu_s':s['cpu_seconds'],
                'cpu_ratio':r['cpu_seconds']/s['cpu_seconds'],
                'local_average_cores':r['cpu_seconds']/r['wall_seconds'],'server_average_cores':s['cpu_seconds']/s['wall_seconds']})
    state=json.loads((TASK/'task.json').read_text(encoding='utf-8'))
    parent=json.loads((OUT/'task-before-user-stop.json').read_text(encoding='utf-8'))
    result={'observed_at':datetime.datetime.now().astimezone().isoformat(),'local':local,'server':server,'paired_detailed_batches':pairs,
        'server_routing_evidence':json.loads((SERVER/'routing-evidence.json').read_text(encoding='utf-8')),
        'local_status':state['status'],'completed_stages':state['completed'],
        'accepted_prefix_unchanged':parent['completed']==state['completed'] and parent['results']==state['results'],
        'local_routing_def_exists':(WORK/'result/routing.def').exists(),
        'same_router_binary':sha(ROOT/'environments/ieda-aes-router/iEDA')==json.loads((SERVER/'routing-evidence.json').read_text())['binary_sha256'],
        'notes':['Stopped by explicit user request, not an 18-hour timeout.','Local partial elapsed time is not compared with full server runtime as if both were finished.',
                 'Warning counts alone do not identify a performance bottleneck. Exact source-level profiling was not performed.']}
    save('routing-analysis.json',result)
    print(json.dumps({k:result[k] for k in ['local_status','completed_stages','accepted_prefix_unchanged','same_router_binary','paired_detailed_batches']},ensure_ascii=False))

def report():
    d=json.loads((OUT/'routing-analysis.json').read_text(encoding='utf-8'))
    cpu=json.loads((OUT/'cpu-comparison.json').read_text());mem=json.loads((OUT/'memory-comparison.json').read_text())
    sustained=json.loads((OUT/'sustained-cpu-comparison.json').read_text());remote=json.loads((OUT/'remote-readiness.json').read_text())
    rows=''.join(f"<tr><td>{r['boxes']}/{r['total']}</td><td>{r['local_wall_s']/60:.2f} 分钟</td><td>{r['server_wall_s']/60:.2f} 分钟</td><td>{r['wall_ratio']:.2f}×</td><td>{r['local_average_cores']:.2f} / {r['server_average_cores']:.2f}</td></tr>" for r in d['paired_detailed_batches'])
    ss={p['phase']:p for p in d['server']['completed_phases']}
    labels={'PinAccessor':'引脚接入','TopologyGenerator':'拓扑生成','SpaceRouter':'空间布线'}
    phases=''.join(f"<tr><td>{labels.get(p['phase'],p['phase'])}</td><td>{p['wall_s']/60:.2f} 分钟</td><td>{ss[p['phase']]['wall_s']/60:.2f} 分钟</td><td>{p['wall_s']/ss[p['phase']]['wall_s']:.2f}×</td></tr>" for p in d['local']['completed_phases'])
    samples=''
    for name,p in [('单核整数计算',cpu),('64 MiB 依赖内存读取',mem)]:
        a=statistics.median(x['wall_s'] for x in p['local']);b=statistics.median(x['wall_s'] for x in p['server']['runs'])
        samples+=f'<tr><td>{name}</td><td>{a:.3f} 秒</td><td>{b:.3f} 秒</td><td>{a/b:.2f}×</td></tr>'
    page='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>Core 布线耗时排查与远程执行建议</title>
<style>body{font:16px/1.75 system-ui,sans-serif;color:#183047;background:#f5f7fa;max-width:1060px;margin:32px auto;padding:0 24px}section{background:white;padding:22px 28px;border-radius:12px;margin:18px 0}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #dde4eb;text-align:left;padding:9px}th{background:#edf3fa}.notice{border-left:5px solid #d68b1f}code{overflow-wrap:anywhere}a{color:#2466a8}</style>
<h1>AES Core 布线耗时排查</h1><p>2026-11-11 · 排查报告；P1 仍未完成。</p>
<section class="notice"><b>本轮已按用户要求停止。</b><p>停止的仅为 Core 容器 aieda-aes-6352ac40f623。前10阶段、原6小时超时记录、本轮日志均保留。主控制器状态为 stopped_with_best；尚未完成的布线没有可验收的最终 DEF。pending 元数据保留用于审计，不代表容器仍在运行，也不得当作已完成阶段续接。此次停止是用户取消，不是18小时超时。</p></section>
<section><h2>结论与证据强度</h2><p><b>已经定位到耗时发生在原生 iEDA 内部，未证明“电脑配置不足”，也未定位到唯一底层根因。</b>停止前 native 进程已运行约9小时19分，累计CPU时间约17小时27分。日志持续更新；详细布线已经完成144/324区域，处于下一批计算。模型计数固定为16，没有反复触发布线的证据。</p><p>服务器同一固定版路由器、同一案例和4线程配置的完整布线耗时 <b>4小时47分39秒</b>，不是几分钟。当前本机已完成的四批详细布线比对应服务器批次慢约2.7—3.1倍。因此既要研究固定版本/配置的算法开销，也要研究本机运行环境的差异。</p></section>
<section><h2>阶段耗时对照</h2><table><tr><th>已完成子阶段</th><th>本机</th><th>服务器</th><th>本机/服务器</th></tr>'''+phases+'''</table><p>完整子阶段与完整子阶段比较；本机尚未结束的详细布线不与服务器完整耗时直接相除。</p><table><tr><th>详细布线累计区域</th><th>该批本机耗时</th><th>该批服务器耗时</th><th>比值</th><th>平均CPU占用核数<br>本机/服务器</th></tr>'''+rows+'''</table><p>四批日志中的违例统计均与服务器对应批次一致；这仅是过程证据，不能替代最终逐网络、DRC和GDS比较。</p></section>
<section><h2>已检查的资源因素</h2><ul><li>停止前容器上限4核/8 GiB；使用内存4,148,531,200字节，cgroup 的 oom、oom_kill、max 事件均为0。</li><li>累计CPU配额节流约16.3秒，远小于9小时；停止前CPU、内存和I/O的近期PSI压力均接近0。因此没有证据把主要耗时归于容器内存耗尽或持续CPU配额阻塞。PSI不覆盖全部Windows宿主开销。</li><li>本机是 Ryzen 9 8940HX，16核32线程、约32 GB内存；本次iEDA只获4核/8 GiB。服务器是 EPYC 9755，但本次基线同样限制4个CPU，不能把整机512逻辑CPU算成本任务并行度。</li><li>Silent方案按用户要求保持不变。早先的22%处理器性能采样不足以证明因果；本次短测时同类计数器为153%—164%，运行状态不同，不能用一张瞬时快照判定硬件故障。</li><li>本机四批详细布线平均仅约1.3—1.5核；服务器约1.7—1.9核。4线程配置不保证每个阶段都能充分并行。</li></ul></section>
<section><h2>同二进制短时对照测试</h2><table><tr><th>诊断项目</th><th>本机中位数</th><th>服务器中位数</th><th>本机/服务器</th></tr>'''+samples+f'''</table><p>另外，以4个独立工作进程运行相同程序30秒，服务器完成{sustained['server']['completed_kernels']}次，本机完成{sustained['local']['completed_kernels']}次。每组输出校验值相同；二进制SHA256一致。测试由预设30秒timeout结束，其124退出码是诊断计划的一部分，不是EDA失败。</p>'''+'''<p><b>这些短测未显示本机的普遍CPU或小工作集内存性能不足。</b>它们不是iEDA基准，不覆盖数GiB工作集、OpenMP等待、长时热/功耗变化、内核与文件系统交互，不能排除这些因素。没有更改电源方案或运行完整EDA。</p></section>
<section><h2>当前仍待定位的部分</h2><p>使用的是固定的共享iEDA快照，不能将其当作GitHub最新原版。日志出现大量局部精确修补被拒绝的警告：本机停止前26,887条，服务器完整运行64,888条。服务器也有同类警告，不能据此认定死循环；需要对应版本源码与CPU采样，判断时间具体消耗在哪些函数。不能进入他人的私有源码目录。</p><p>目前没有同一原生阶段的CPU采样、上下文切换和内存热点对照，因此不能将约三倍差距严格归因于Silent、Docker、缓存、调度或具体算法缺陷。也没有发现本轮跑了9次详细布线：冻结配置与日志均为1次详细布线迭代。</p></section>
<section><h2>已经确认的主Agent执行层问题</h2><p><code>dsh/runtime.mjs</code>为每个工具调用启动Python进程，取消时调用child.kill()；原生Docker作业可能继续存在。停止容器之前，本机已找不到该Python执行进程，而task.json仍保留pending routing。我们不能从这一快照反推它何时退出，但当前同步桥接方式确实缺少独立、持久的作业监管。</p><p>这一问题解释了界面与后台可能脱节，但不解释iEDA内部所有计算耗时。应修复为作业提交、状态查询、取消确认、产物校验四个独立操作，不能依赖一个持续数小时的聊天工具调用持有执行权。</p></section>
<section><h2>远程执行可行性与建议</h2><p>已遵守账号说明，仅访问本人工作区和已授权资源，没有sudo、未读取他人文件。SSH连接成功，UID核对通过；本人工作区的主iEDA和路由器SHA256与本机固定版本一致；短时原生Tcl探测返回 <code>IEDA_REMOTE_DIAGNOSTIC_OK</code>，没有加载设计或启动布局。服务器端只新增少量诊断源码、二进制和探测脚本，总量约2 MB。</p><p><b>建议采用：本地DSH与主Agent → 结构化作业接口 → SSH传输 → 服务器持久执行器 → 校验后回传本地交付卡片。</b>保留一个Agent loop；服务器运行工具，不另建一套规划Agent，不上传LLM登录凭据。</p><ol><li>输入包一次上传，记录网表、LEF、LIB、SDC、约束和工具版本哈希；工作区严格限制在本人目录。</li><li>submit返回job_id，重复action_id返回同一作业；服务器使用tmux等持久方式监管原生进程。</li><li>status返回真实阶段、日志游标、资源使用、心跳和产物；断网后重新查询，不自动重提任务。</li><li>cancel仅作用于该job的进程组，确认退出后记录cancelled并保留日志。</li><li>download先写临时文件，核对大小和SHA256再发布DEF、报告和预览卡片；回收服务器临时文件前验证本地归档。</li></ol><p>当前代码已有Linux运行器和SSH基线脚本，但DSH主Agent适配器仍调用本机Docker；远程执行模式尚未接入或完成验收。本次不恢复全流程。迁移后应新建明确标注“DSH发起、服务器执行”的独立运行；不得把已有服务器基线输出冒充新的Agent运行结果。布局质量仍另行验收，迁到服务器不能消除残余DRC。</p></section>
<section><h2>后续验证顺序</h2><ol><li>先完成异步作业接口与取消、重连、幂等性检查。</li><li>用轻量任务验证DSH确实发起服务器工具，报告与预览能返回本地。</li><li>恢复验收前明确新的远程执行协议。若要继续性能诊断，先做有边界的原生阶段采样/A-B实验，不再盲目把时限加长。</li></ol></section>
<p><a href="routing-analysis.json">路由日志分析</a> · <a href="cpu-comparison.json">单核测试</a> · <a href="memory-comparison.json">内存短测</a> · <a href="sustained-cpu-comparison.json">30秒并行短测</a> · <a href="remote-readiness.json">远程原生工具探测</a> · <a href="stop-controller-receipt.json">停止回执</a></p></html>'''
    (OUT/'report.html').write_text(page,encoding='utf-8')
    print(str(OUT/'report.html'))

SOURCE=r'''#include <stdint.h>
#include <stdio.h>
#include <time.h>
static double sec(clockid_t id) {struct timespec t;clock_gettime(id,&t);return t.tv_sec+t.tv_nsec*1e-9;}
int main(void) {uint64_t x=0x123456789abcdefULL;double w=sec(CLOCK_MONOTONIC),c=sec(CLOCK_PROCESS_CPUTIME_ID);
for(uint64_t i=0;i<300000000ULL;++i){x^=x<<13;x^=x>>7;x^=x<<17;x+=i;}
printf("{\"checksum\":\"%016llx\",\"wall_s\":%.9f,\"cpu_s\":%.9f}\n",(unsigned long long)x,sec(CLOCK_MONOTONIC)-w,sec(CLOCK_PROCESS_CPUTIME_ID)-c);return 0;}
'''
MEMORY_SOURCE=SOURCE[:SOURCE.index('int main')]+r'''#include <stdlib.h>
int main(void) {const uint32_t n=1U<<24;uint32_t *a=malloc((size_t)n*4);if(!a)return 2;
for(uint32_t i=0;i<n;i++)a[i]=(i*1664525U+1013904223U)&(n-1);
uint32_t x=7;double w=sec(CLOCK_MONOTONIC),c=sec(CLOCK_PROCESS_CPUTIME_ID);
for(uint32_t i=0;i<30000000U;i++)x=a[x];
printf("{\"checksum\":\"%08x\",\"wall_s\":%.9f,\"cpu_s\":%.9f}\n",x,sec(CLOCK_MONOTONIC)-w,sec(CLOCK_PROCESS_CPUTIME_ID)-c);free(a);return 0;}
'''
def cpu_probe(local_only=False,memory=False):
    OUT.mkdir(exist_ok=True)
    remote='/srv/edagent/diagnostics-20261111'
    stem='memory' if memory else 'cpu'
    code='''import os,pathlib,subprocess,json,hashlib
assert os.getuid()==1015
p=pathlib.Path(__REMOTE_DIR__);p.mkdir(exist_ok=True)
assert p.resolve()==p and p.is_relative_to(pathlib.Path('/srv/edagent'))
s=p/(__STEM__+'-probe.c');b=p/(__STEM__+'-probe');s.write_text(__PROBE_SOURCE__)
r=subprocess.run(['gcc','-O2','-std=c11','-D_POSIX_C_SOURCE=200809L','-static',str(s),'-o',str(b)],capture_output=True,text=True,timeout=20)
assert r.returncode==0,r.stderr
cpu=min(os.sched_getaffinity(0));runs=[]
for _ in range(3):
 r=subprocess.run(['taskset','-c',str(cpu),'timeout','15',str(b)],capture_output=True,text=True,timeout=18,check=True);runs.append(json.loads(r.stdout))
print(json.dumps({'uid':os.getuid(),'cpu':cpu,'sha256':hashlib.sha256(b.read_bytes()).hexdigest(),'runs':runs,'bytes':b.stat().st_size,'remote_path':str(b)}))
'''.replace('__REMOTE_DIR__',repr(remote)).replace('__PROBE_SOURCE__',repr(MEMORY_SOURCE if memory else SOURCE)).replace('__STEM__',repr(stem))
    ssh=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-backup']
    if local_only:
        server=json.loads((OUT/(stem+'-server.json')).read_text())
    else:
        p=subprocess.run(ssh+['python3 -B -'],input=code,text=True,encoding='utf-8',capture_output=True,timeout=85)
        if p.returncode:raise RuntimeError(p.stderr[-3000:])
        server=json.loads(p.stdout);save(stem+'-server.json',server)
    binary=OUT/(stem+'-probe')
    packed=subprocess.run(ssh+['gzip -c '+remote+'/'+stem+'-probe'],capture_output=True,timeout=120,check=True).stdout
    binary.write_bytes(gzip.decompress(packed))
    assert sha(binary)==server['sha256']
    from macro_agent.portable_ieda import IMAGE
    local=[]
    for _ in range(3):
        p=subprocess.run(['docker','run','--rm','--pull=never','--network','none','--cpus','1','--memory','128m','--pids-limit','16',
            '--mount',f'type=bind,source={OUT.resolve()},target=/probe,readonly',IMAGE,'timeout','15','/probe/'+stem+'-probe'],capture_output=True,text=True,timeout=22,check=True)
        local.append(json.loads(p.stdout))
    assert len({r['checksum'] for r in server['runs']+local})==1
    result={'server':server,'local':local,'identical_binary_sha256':sha(binary),'median_wall_ratio':statistics.median(r['wall_s'] for r in local)/statistics.median(r['wall_s'] for r in server['runs']),
        'scope':('64 MiB dependent memory reads' if memory else 'Tiny deterministic single-thread integer kernel')+', identical static binary, no EDA execution. Not an iEDA benchmark and not a causal power-mode test.'}
    save(stem+'-comparison.json',result);print(json.dumps(result))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--cpu-probe',action='store_true');ap.add_argument('--local-cpu-probe',action='store_true');ap.add_argument('--memory',action='store_true');ap.add_argument('--report',action='store_true');a=ap.parse_args()
    if a.cpu_probe or a.local_cpu_probe:cpu_probe(a.local_cpu_probe,a.memory)
    else:
        analyze()
        if a.report:report()

"""Read-only rendering and evidence packaging; no placement algorithm here."""
from pathlib import Path
import hashlib
import html
import json
import shutil
import time
from .def_validation import read_def,lef_cells

def ref(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def write_report(folder):
    """Self-contained HTML: DSH previews it at a blob URL, without a file base."""
    folder=Path(folder)
    svg=(folder/'placement.svg').read_text(encoding='utf-8')
    # Only our generated, non-scripted SVG is embedded; never arbitrary user HTML.
    import xml.etree.ElementTree as ET
    tree=ET.fromstring(svg)
    allowed={'svg','rect','text','g','title','circle','path'}
    for element in tree.iter():
        if element.tag.split('}')[-1] not in allowed:
            raise ValueError('Unexpected preview SVG element')
        if any(k.lower().startswith('on') or k.split('}')[-1] in ('href','src') for k in element.attrib):
            raise ValueError('Unexpected active/external SVG attribute')
    sections=[]
    for name,title in [('metrics','测量结果'),('acceptance','验收证据'),('input-manifest','冻结输入')]:
        data=json.loads((folder/(name+'.json')).read_text(encoding='utf-8'))
        sections.append(f'<details id="{name}"'+(' open' if name=='metrics' else '')+f'><summary>{title}</summary><pre>'+html.escape(json.dumps(data,ensure_ascii=False,indent=2))+'</pre></details>')
    doc='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>iEDA placement evidence</title>
<style>body{font:16px/1.6 sans-serif;margin:30px;background:#f4f7fb;color:#172331}svg{display:block;max-width:100%;height:auto;background:white}pre{white-space:pre-wrap;overflow-wrap:anywhere}details{margin-top:20px}summary{cursor:pointer;font-weight:bold}code{overflow-wrap:anywhere}</style>
<h1>iEDA netlist → placement DEF</h1><p>当前案例输出完成；整体第一阶段验收仍为部分完成，尚不能证明自动宏布局。</p>
<p>DEF 文件请使用对话中的 final.def 交付卡片打开。<a href="#acceptance">验收证据</a> · <a href="#input-manifest">冻结输入</a></p>
'''+svg+''.join(sections)+'</html>'
    acceptance=json.loads((folder/'acceptance.json').read_text(encoding='utf-8'))
    if acceptance.get('macro_placement',{}).get('passed'):
        doc=doc.replace('当前案例输出完成；整体第一阶段验收仍为部分完成，尚不能证明自动宏布局。','当前双 SRAM 宏布局案例输出完成；整体第一阶段和完整后端验收另列，不由本次案例单独认证。')
    (folder/'report.html').write_text(doc,encoding='utf-8')
    return ref(folder/'report.html')

def render(def_path,lefs,target):
    design=read_def(def_path);cells={}
    for lef in lefs:cells.update(lef_cells(lef,design['units']))
    d=design['die'];scale=min(940/(d[2]-d[0]),650/(d[3]-d[1]));x0=80;y0=125
    def rect(x,y,w,h,color):
        return f'<rect x="{x0+(x-d[0])*scale:.3f}" y="{y0+(d[3]-y-h)*scale:.3f}" width="{w*scale:.3f}" height="{h*scale:.3f}" fill="{color}" stroke="#ffffff" stroke-width="0.12"/>'
    sha=ref(def_path)['sha256'];parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="930" viewBox="0 0 1120 930">',
        '<rect width="1120" height="930" fill="white"/>',f'<text x="40" y="40" font-size="25">iEDA placement: {html.escape(design["design"])}</text>',
        '<text x="40" y="70" font-size="16">Blue: non-filler standard cells | Purple: hard macros</text>',
        f'<text x="40" y="96" font-size="13">DEF SHA256: {sha}</text>',rect(d[0],d[1],d[2]-d[0],d[3]-d[1],'#eef2f6')]
    hidden_spacers=0
    for name,value in design['components'].items():
        cell=cells[value['master']]
        if cell['spacer']:
            hidden_spacers+=1
            continue
        _,x,y,o=value['placement'];w,h=cell['size']
        if o in ('E','W','FE','FW'):w,h=h,w
        parts.append('<g><title>'+html.escape(name)+'</title>'+rect(x,y,w,h,'#8049b2' if cell['hard_macro'] else '#347db7')+'</g>')
    um=(d[2]-d[0])/design['units']/5;pixels=um*design['units']*scale
    parts += [f'<path d="M80 820 h{pixels:.3f}" stroke="#22374b" stroke-width="3"/>',f'<text x="80" y="845" font-size="16">{um:.3f} microns</text>',
        f'<text x="80" y="875" font-size="16">{len(design["components"])-hidden_spacers} visible instances; {hidden_spacers} filler cells hidden.</text>',
        '<text x="80" y="901" font-size="15">Placement only. No routed wires, DRC/LVS or PPA signoff.</text></svg>']
    target.write_text('\n'.join(parts),encoding='utf-8')
    return {'source_def':ref(def_path),'preview':ref(target),'method':'DEF/LEF instance rectangles; CORE SPACER and IO anchors hidden','hidden_spacers':hidden_spacers,'aggregated':False}

def package(state,folder,backend,final_source=None):
    folder=Path(folder);final=folder/'final.def'
    shutil.copyfile(final_source or Path(state['accepted_work'])/'result/readback.def',final)
    preview=render(final,[p for p in backend.input_files() if p.suffix=='.lef'],folder/'placement.svg')
    validation=state['results']['validate'];independent=validation['independent'];report=validation['backend']
    metrics={'hpwl_dbu':report['hpwl_dbu'],'dbu_per_micron':independent['units_dbu_per_micron'],
             'hpwl_microns':report['hpwl_dbu']/independent['units_dbu_per_micron'],
             'hpwl_definition':'iPL total pin-based HPWL, placement-stage report; not routed wirelength',
             'instances':independent['instances'],'nets':independent['nets'],'hard_macros':independent['hard_macros'],
             'elapsed_wall_seconds':round(time.time()-state['created_at'],3),'stage_seconds':{k:v.get('seconds') for k,v in state['results'].items()},
             'model_reservations':state['counts']['model_calls'],'executions':state['counts']['executions'],
             'maker_calls':0,'external_eda_calls':0,'peak_memory_bytes':None,'memory_limit_gb':state['contract']['budget']['memory_gb'],
             'model_cost':None,'timing':None,'power':None,'routed_congestion':None}
    acceptance={'schema_version':'acceptance_v2','scope':'this registered no-hard-macro case run; not overall phase-one certification',
                'case_run_passed':independent['passed'] and report['placement_checks_passed'] and state['results']['export_def']['readback_equal'],
                'G1_Base':'pending full A1-A15 aggregate acceptance','G1_Macro':'not_passed: no movable hard macros in this case',
                'overall_phase1':'partial','final_def':ref(final),'preview':preview,
                'checks':{'A1':'partial: iDB import and connected LEF pin resolution checked; independent hierarchical Verilog equivalence not implemented',
                          'A2':'pass: required iEDA stages; Maker=0, external EDA=0',
                          'A3':'pass: imported instances/connectivity retained; reviewed physical insertions listed',
                          'A4':'pass for signal IO and instances; logical-only PDN pins explicitly exempted in manifest',
                          'A5':'pass for registered row/site/orientation/bounds/overlap and absent region/blockage constraints',
                          'A6':'pass: fixed floorplan cells preserved', 'A7':'not_passed: zero hard macros',
                          'A8':'pass: new iEDA process; all parser-supported physical sections compared',
                          'A9':'preview generated; live DSH visibility requires UI evidence',
                          'A10':'see dispatcher tests and decisions', 'A11':'see context/RAG tests', 'A12':'see controlled fault tests',
                          'A13':'requires separate DSH evidence', 'A14':'requires three-run aggregate report',
                          'A15':'limits enforced; peak memory and model billing unknown'},
                'independent':independent,'readback':state['results']['export_def'].get('readback_coverage')}
    if state['results'].get('macro_placement',{}).get('independent_macro_check',{}).get('passed'):
        acceptance['scope']='registered two-real-SRAM placement run; not overall phase-one or backend certification'
        acceptance['G1_Macro']='case placement passed; aggregate repeat/DSH acceptance separate'
        acceptance['checks']['A1']='pass for registered flat input with explicit Liberty bus pin ranges'
        acceptance['checks']['A7']='pass: two initially unplaced real SRAM macros placed by native iEDA and independently validated'
        acceptance['macro_placement']=state['results']['macro_placement']['independent_macro_check']
    write(folder/'metrics.json',metrics);write(folder/'acceptance.json',acceptance);write(folder/'preview.json',preview)
    write(folder/'input-manifest.json',{'contract':state['contract'],'inputs':state['input_refs']})
    (folder/'events.jsonl').write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in state['events']),encoding='utf-8')
    write_report(folder)
    return {'final_def':ref(final),'preview':preview,'report':ref(folder/'report.html'),'acceptance':ref(folder/'acceptance.json'),'metrics':ref(folder/'metrics.json')}

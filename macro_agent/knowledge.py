"""Version-qualified, content-addressed keyword RAG; references never override state."""
from pathlib import Path
from . import main_task as task
from .common import digest


def retrieve(folder,state,query,version):
    backend_version=state['contract']['backend_version']
    if version and version!=backend_version:
        return {'status':'incompatible_version','hits':[],'backend_version':backend_version}
    source=task.ROOT/'dsh/knowledge/index.json'
    entries=task.load(source)['entries'] if source.is_file() else []
    aliases={'网表':'netlist','布局':'placement','回读':'readback','导出':'def','合法':'validation',
             '约束':'constraints','轨道':'tracks','质量':'quality','修复':'repair','短路':'short'}
    for cn,en in aliases.items():query=query.replace(cn,' '+en+' ')
    terms=query.lower().split();hits=[];excluded=[]
    for e in entries:
        if state['contract']['case_id'] not in e['case_ids']:continue
        if state['contract']['goal'] not in e['goals']:continue
        if backend_version not in e['backend_versions']:
            excluded.append({'source_ref':e['path'],'reason':'document_backend_incompatible'});continue
        path=(task.ROOT/e['path']).resolve()
        if not path.is_relative_to((task.ROOT/'dsh/knowledge').resolve()):raise ValueError('Knowledge path outside registry')
        if not path.exists() or task.file_ref(path)['sha256']!=e['sha256']:
            excluded.append({'source_ref':e['path'],'reason':'unreviewed_content_hash'});continue
        lines=path.read_text(encoding='utf-8').splitlines()
        for i in range(0,len(lines),14):
            text='\n'.join(lines[i:i+14]);score=sum(term in text.lower() for term in terms)
            if score:hits.append({'chunk_id':e['sha256']+':'+str(i+1),'source_ref':e['path'],
                'section_or_page':f'lines {i+1}-{min(i+14,len(lines))}','content_version':e['sha256'],
                'applicable_backend_versions':e['backend_versions'],'reviewed_at':e['reviewed_at'],
                'backend_version':backend_version,'text':text,'score':score})
    hits.sort(key=lambda h:-h['score']);total=len(hits)
    result={'status':'matched' if hits else 'no_match','hits':hits[:3],'total_matches':total,
            'truncated':total>3,'excluded':excluded,'authority':'reference_data_only',
            'backend_version':backend_version,'state_id':task.state_id(state)}
    directory=Path(folder)/'retrieval';directory.mkdir(exist_ok=True)
    target=directory/(digest(result)+'.json');task.save(target,result)
    return {**result,'evidence_ref':str(target)}

from pathlib import Path
import json
from macro_agent.remote_client import rpc
out=Path('runs/p1-feedback-20261114');out.mkdir(exist_ok=True)
for tid,kind in [('remote-e5c7f543bbce738395e58a0a','input'),('remote-e5c7f543bbce738395e58a0a','stage'),('remote-e5c7f543bbce738395e58a0a','quality'),('remote-0416695c41fde120d84bfdcf','quality')]:
 result=rpc({'task_id':tid,'operation':'feedback_inspect','kind':kind})
 (out/(tid+'-'+kind+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 facts=result['facts'];print(json.dumps({'task':tid,'kind':kind,'status':facts.get('status'),'metrics':facts.get('metrics'),'count':facts.get('count'),'located':facts.get('located_markers'),'example':facts.get('examples',[None])[:1]},ensure_ascii=True))

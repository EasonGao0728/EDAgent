"""Losslessly compact a stopped task, without deleting or accepting artifacts."""
import argparse, json, shutil, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from macro_agent.main_task import locked,load,save,file_ref,workspace_files,compact_verified

ap=argparse.ArgumentParser();ap.add_argument('--run',required=True);args=ap.parse_args()
folder=Path(args.run).resolve()
if not folder.is_relative_to(ROOT/'runs'):raise ValueError('Owned task folder required')
with locked(folder):
    state=load(folder/'task.json')
    if state['status'] not in ('stopped_with_best','failed','target_met') or state.get('pending'):
        raise ValueError('Only sealed non-running tasks may be compacted')
    before=file_ref(folder/'task.json');free=shutil.disk_usage(folder).free
    records=[]
    for p in workspace_files(folder/'attempts'):
        if compact_verified(p):
            records.append(file_ref(p))
            if len(records)%20==0:print(json.dumps({'compressed_files':len(records),'free_bytes':shutil.disk_usage(folder).free}),flush=True)
    if file_ref(folder/'task.json')!=before:raise ValueError('Task state changed during compression')
    result={'time':time.time(),'task':before,'compressed_files':records,'count':len(records),
            'contents_unchanged':True,'deleted_files':0,'free_bytes_before':free,'free_bytes_after':shutil.disk_usage(folder).free,
            'native_layout_executed':False,'method':'Windows NTFS LZX; per-file SHA256 before/after'}
    out=folder/'storage-recovery.json';save(out,result)
    print(json.dumps({k:v for k,v in result.items() if k!='compressed_files'}),flush=True)

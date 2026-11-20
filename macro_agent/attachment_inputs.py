"""Freeze chat-uploaded bytes into a reviewed case adapter's isolated input root."""
import hashlib
import json
from pathlib import Path
import shutil
import uuid
from . import ieda_stages


def freeze_attachments(folder, case_id, attachments):
    if case_id not in ('ibench_gcd_legacy','sky130_sram_pair','aes_sky130_t','aes_legacy','aes_core_sky130_t','swerv_nangate45'):
        raise ValueError('Attachment intake requires a registered HD GCD or SRAM case')
    reference, _ = ieda_stages.REGISTERED_CASES[case_id]
    m = ieda_stages.manifest(case_id)
    required = [m['netlist'], m['tech_lef'], *m['cell_lefs'], *m['libs'], m['sdc'], 'manifest.json', 'design.json']
    names = {Path(p).name:p for p in required}
    supplied = {}
    for item in attachments:
        name = item['name']
        if name not in names or name in supplied:
            raise ValueError('Unexpected or duplicate case attachment: '+name)
        data = Path(item['path']).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if sha != item['sha256'] or len(data) != item['bytes']:
            raise ValueError('Attachment integrity failure: '+name)
        if sha != hashlib.sha256((reference/names[name]).read_bytes()).hexdigest():
            raise ValueError('Attachment differs from reviewed case: '+name)
        supplied[name] = (data, item)
    if set(supplied) != set(names):
        raise ValueError('Missing case attachments: '+', '.join(sorted(set(names)-set(supplied))))
    # Only trusted scripts/config/provenance are copied from the reviewed adapter.
    # Every design/PDK/configuration input listed above comes from uploaded bytes.
    target = folder/('uploaded-inputs-'+uuid.uuid4().hex[:12])
    target.mkdir()
    for source in ieda_stages.input_files(case_id):
        rel = source.relative_to(reference)
        if rel.as_posix() in required:
            continue
        dest = target/rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    records = []
    for name, (data, item) in supplied.items():
        dest = target/names[name]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        records.append({**item, 'relative_path':names[name], 'frozen_path':str(dest)})
    receipt = {'input_root':str(target), 'source':'conversation_attachments',
               'reviewed_case_match':True, 'files':records,
               'adapter_source':str(reference), 'adapter_policy':'reviewed scripts/config/provenance; never execute uploaded scripts'}
    (target/'attachment-import.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt

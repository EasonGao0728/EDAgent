"""Bind saved native routing state to this exact build, circuit and route contract."""
import hashlib
import json
from pathlib import Path

from verify_pa import BASE, DEF_HASH, RUNS, save, sha


BINARY_SHA = '86665afd3583436bf90f421847887fa535f6b807f9ac427999fe49d3c2e438fe'
DR_SHA = 'a299a1d992acf5e9d56955d1ae111c8220803f62e4c4be55af6a1262e9679b0f'


def configure(work, source, binary, table, env):
    sample = RUNS.parent / 'bp-multi-compact-layer-test'
    direct, tg, la = (
        json.loads((sample / label / 'receipt.json').read_bytes())
        for label in ('direct', 'restore-TG', 'restore-LA')
    )
    for row in (direct, tg, la):
        if row['binary'] != BINARY_SHA or row['returncode'] != 25 or not row['ended']:
            raise ValueError('Native checkpoint sample not qualified')
    if tg['states'] != direct['states'] or la['states'] != {'LA': direct['states']['LA']}:
        raise ValueError('Native checkpoint sample states differ')
    if la['counts'] != dict(PA=0, SA=0, TG=0, LA=0) or tg['counts'] != dict(PA=0, SA=0, TG=0, LA=1):
        raise ValueError('Native checkpoint sample repeated an earlier module')
    contract = {
        'binary': sha(binary), 'legalized_def': sha(source), 'port_table': sha(table),
        'reference': json.loads((BASE / 'progress.json').read_bytes())['binding'],
        'route_tcl': sha(work / 'route.tcl'),
        'configuration': {str(p.relative_to(work)): sha(p) for p in sorted((work / 'config').rglob('*')) if p.is_file()},
        'route_environment': dict(env),
    }
    if contract['binary'] not in (BINARY_SHA, DR_SHA) or contract['legalized_def'] != DEF_HASH:
        raise ValueError('Whole-chip continuation identity mismatch')
    if contract['binary']==DR_SHA:
        checked=sample/'downstream-v11'
        audit=json.loads((checked/'physical-audit.json').read_bytes())
        native=json.loads((checked/'native-sample-graph.json').read_bytes())
        native_receipt=json.loads((checked/'routed-def-audit/receipt.json').read_bytes())
        if not (audit['binary']==DR_SHA and audit['source']==direct['input'] and audit['physical_unchanged']
                and audit['transformation']['passed'] and audit['graph']['passed'] and audit['graph']['pins']==494
                and native['passed'] and native['matched_receipt'] and native['audited_nets']==126
                and native['audit_sha256']==native_receipt['audit_sha256']==sha(checked/'routed-def-audit/connectivity_audit.json')
                and native_receipt['input_sha256']==native_receipt['input_sha256_after']==audit['artifact']==sha(checked/'result/routing.def')):
            raise ValueError('Detailed routing sample did not pass physical readback')
    canonical = json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    save(work / 'state-contract.json', dict(sha256=digest, contract=contract))
    env.update(IEDA_RT_SAVE_TG='/work/TG.bin', IEDA_RT_SAVE_LA='/work/LA.bin', IEDA_RT_STATE_BINDING=digest)


def record(work, receipt):
    if not (work / 'state-contract.json').is_file():
        return
    states = {}
    for stage in ('TG', 'LA'):
        path = work / (stage + '.bin')
        if path.is_file():
            states[stage] = dict(bytes=path.stat().st_size, sha256=sha(path))
    receipt['state_binding'] = json.loads((work / 'state-contract.json').read_bytes())['sha256']
    receipt['checkpoints'] = states

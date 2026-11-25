"""Check the real SRAM escape candidates together against fixed metal and one another."""
from collections import Counter
from sram_escape_check import (AUDITED_BINARY, DEF_HASH, RT, SOURCE, WORK, active_jobs, check_one,
                               json, marker_stream, read_def, remote_service, save, section, setup, sha)


def run():
    assert sha(SOURCE) == DEF_HASH and sha(RT / 'iEDA') == AUDITED_BINARY
    ref = setup()
    group = json.loads((WORK/'sram-eligibility.json').read_bytes())
    assert group['checkpoint'] == DEF_HASH and group['rows'] == len(group['pins']) == 179
    original = SOURCE.read_text()
    records = {r.split()[0]: r for r in section(original, 'NETS')}
    replacements = {}
    for row in group['pins']:
        px, py = row['P']
        ax, ay = row['A']
        bx, by = row['B']
        assert py == ay and ax == bx
        record = records[row['net']]
        assert 'ROUTED' not in record
        prefix = 'NEW' if row['net'] in replacements else '+ ROUTED'
        replacements[row['net']] = replacements.get(row['net'], '') + f' {prefix} metal3 ( {px} {py} ) ( {ax} * )\n   NEW metal3 ( {ax} {ay} ) ( * {by} )'
    # Match whole record only in NETS. Preserve all original bytes outside added wires.
    import re
    start, end = re.search(r'^NETS \d+ ;',original,re.M).end(), original.index('END NETS')
    matches = set()
    def add(m):
        name = m[1]
        if name not in replacements:
            return m[0]
        assert name not in matches
        matches.add(name)
        return m[0][:-1] + replacements[name] + ' ;'
    changed = re.sub(r'^- (\S+)\s+[^;]*;', add, original[start:end], flags=re.M)
    assert matches == set(replacements)
    path = WORK/'batch-abutment.def'
    contents = original[:start]+changed+original[end:]
    if not path.exists():
        path.write_text(contents)
    assert path.read_text() == contents and read_def(path) == read_def(SOURCE)
    receipt = check_one('batch-abutment',path,ref)
    assert receipt['reconciliation']['passed'] and not receipt['skipped'] and not receipt['refused']
    seen = Counter()
    examples = {}
    owner = {}
    for row in group['pins']:
        owner.setdefault(row['net'], []).append(row['terminal'])
    for kind, m in marker_stream(WORK/'batch-abutment/result/report/violations.json'):
        if kind != 'marker':
            continue
        key = m['canonical_key']
        nets = set(key.split('|')[-1].strip(',').split(','))
        contacts = nets & owner.keys()
        label = m['type']
        if len(contacts)==1 and nets == contacts | {'obs'} and label=='metal_short':
            x1,y1,x2,y2 = m['bbox']
            if any(y1==y2 and y1 in (ly,uy) and lx<=x1<=x2<=ux for lx,ly,ux,uy in owner[next(iter(contacts))]):
                label = 'own_pin_aperture_boundary_marker'
        seen[label]+=1
        if len(examples.setdefault(label,[]))<8:
            examples[label].append(key)
    result = dict(source=DEF_HASH, branch=sha(path), nets=len(matches), totals=dict(seen),
                  examples=examples, native=receipt['reconciliation']['final_violation_count'],
                  checked=receipt['checked'], unsupported=receipt['unsupported'])
    assert sum(seen.values()) == result['native']
    save(WORK/'batch-abutment-summary.json',result)
    print(json.dumps(result))

if __name__=='__main__':
    remote_service.init()
    with remote_service.gate():
        if active_jobs(): raise RuntimeError('Native job already active')
        run()

"""Compare a real half-width square cap against the saved same-checker positive control."""
from sram_escape_check import (
    AUDITED_BINARY, DEF_HASH, NET, PIN, RT, SOURCE, WIRE, WORK, active_jobs, check_one,
    json, marker_multiset, read_def, remote_service, save, section, setup, sha,
)


def run():
    assert sha(SOURCE) == DEF_HASH and sha(RT / 'iEDA') == AUDITED_BINARY
    previous = json.loads((WORK / 'controlled-comparison.json').read_bytes())
    base = WORK / 'flank-control.def'
    if not base.exists():
        original = SOURCE.read_text()
        control = next(r for r in section(original, 'NETS') if r.split()[0] == previous['control_net'])
        assert original.count(control) == 1
        base.write_text(original.replace(control, control + previous['control']))
    assert sha(base) == previous['trial']['flank-control']['def_sha256']
    text = base.read_text()
    record = next(r for r in section(text, 'NETS') if r.split()[0] == NET)
    assert text.count(record) == 1 and 'ROUTED' not in record
    ref = setup()
    a, outside, _ = marker_multiset(WORK / 'flank-control/result/report/violations.json')
    out = {}
    for label, x in [('square-edge', 1308110), ('square-gap', 1308100)]:
        wire = WIRE.replace('1308180', str(x), 1)
        path = WORK / (label + '.def')
        contents = text.replace(record, record + wire)
        if not path.exists():
            path.write_text(contents)
        assert path.read_text() == contents and read_def(path) == read_def(base)
        trial = check_one(label, path, ref)
        baseline = previous['trial']['flank-control']
        assert trial['returncode'] == 0 and trial['reconciliation']['passed']
        assert trial['checked'] == baseline['checked'] and trial['unsupported'] == baseline['unsupported']
        assert not trial['skipped'] and not trial['refused']
        b, outside_b, _ = marker_multiset(WORK / label / 'result/report/violations.json')
        out[label] = dict(input=sha(path), wire=wire, x_metal_edge=x+70,
                          target_pin_x=1308180, target_pin=PIN, expected_contact_length_dbu=140 if x+70==1308180 else 0,
                          count=trial['reconciliation']['final_violation_count'], new_local=dict(b-a),
                          removed_local=dict(a-b), outside_identical=outside_b==outside)
    save(WORK / 'square-endcap-comparison.json', out)
    print(json.dumps(out))


if __name__ == '__main__':
    remote_service.init()
    with remote_service.gate():
        if active_jobs():
            raise RuntimeError('Another native job is active')
        run()

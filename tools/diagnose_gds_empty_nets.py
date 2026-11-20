"""Reproduce an empty-net checker edge case without changing active inputs.

Synthetic GDS is a validator fixture only. It is never a native EDA output,
server baseline, or P1 acceptance artifact.
"""
import hashlib, json, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from macro_agent.native_gds import validate


def fixture(folder, terminals=False, geometry=False, reference=True):
    import klayout.db as db
    folder.mkdir()
    net = '( PIN in )' if terminals else ''
    pin_section = ('PINS 1 ;\n- in + NET test_net + DIRECTION INPUT '
                   '+ LAYER metal1 ( 0 0 ) ( 100 100 ) + PLACED ( 100 100 ) N ;\nEND PINS\n'
                   if terminals else 'PINS 0 ;\nEND PINS\n')
    (folder / 'design.def').write_text(
        'VERSION 5.8 ;\nDESIGN probe ;\nUNITS DISTANCE MICRONS 1000 ;\n'
        'DIEAREA ( 0 0 ) ( 10000 10000 ) ;\nCOMPONENTS 0 ;\nEND COMPONENTS\n'
        + pin_section +
        f'NETS 1 ;\n- test_net {net} ;\nEND NETS\nEND DESIGN\n', encoding='utf-8')
    (folder / 'tech.lef').write_text('LAYER metal1\n TYPE ROUTING ;\nEND metal1\n', encoding='utf-8')
    layout = db.Layout()
    layout.dbu = .001
    top = layout.create_cell('probe')
    top.shapes(layout.layer(0, 2)).insert(db.Box(0, 0, 10000, 10000))
    pins = layout.create_cell('PINS')
    if terminals:
        pins.shapes(layout.layer(0, 0)).insert(db.Box(100, 100, 200, 200))
    top.insert(db.CellInstArray(pins.cell_index(), db.Trans()))
    if reference:
        cell = layout.create_cell('test_net')
        if geometry:
            cell.shapes(layout.layer(0, 0)).insert(db.Box(100, 100, 200, 200))
        top.insert(db.CellInstArray(cell.cell_index(), db.Trans()))
    layout.write(str(folder / 'fixture.gds'))
    return validate(folder / 'fixture.gds', folder / 'design.def', folder / 'tech.lef', [])


def main():
    scenarios = {
        'declared_empty_referenced': {},
        'connected_without_geometry': {'terminals': True},
        'connected_with_geometry': {'terminals': True, 'geometry': True},
        'missing_net_cell': {'reference': False},
    }
    result = {'time': time.time(), 'kind': 'synthetic_validator_diagnostic_only',
              'native_layout_executed': False, 'production_source_changed': False,
              'checker_sha256': hashlib.sha256((ROOT / 'macro_agent/native_gds.py').read_bytes()).hexdigest(),
              'scenarios': {}}
    with tempfile.TemporaryDirectory(prefix='gds-checker-') as temporary:
        for name, options in scenarios.items():
            check = fixture(Path(temporary) / name, **options)
            result['scenarios'][name] = {key: check[key] for key in ('passed', 'errors', 'routed_nets_checked')}
    result['empty_net_false_positive_reproduced'] = (
        result['scenarios']['declared_empty_referenced']['errors'] == ['missing_routed_net:test_net']
        and result['scenarios']['connected_with_geometry']['passed'])
    result['connected_and_missing_net_guards_active'] = all(
        not result['scenarios'][name]['passed'] for name in ('connected_without_geometry', 'missing_net_cell'))
    output = ROOT / 'runs/aes-p1-20261108/gds-empty-net-diagnostic.json'
    output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()

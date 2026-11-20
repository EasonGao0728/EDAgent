"""Convert iEDA DEF plus frozen LEFs to a readable abstract GDS, without changing DEF."""
import argparse
import json
from pathlib import Path
import klayout.db as db


def export(work):
    work=Path(work)
    opts=db.LoadLayoutOptions();cfg=opts.lefdef_config
    cfg.lef_files=[str(work/'input/pdk/lef/sky130_fd_sc_hd.tlef'),str(work/'input/pdk/lef/sky130_fd_sc_hd_merged.lef')]
    opts.lefdef_config=cfg
    layout=db.Layout();layout.read(str(work/'result/filler.def'),opts)
    top=layout.cell('gcd')
    if top is None or top.bbox().empty():raise ValueError('DEF has no nonempty gcd top')
    layout.write(str(work/'result/final.gds'))
    check=db.Layout();check.read(str(work/'result/final.gds'));restored=check.cell('gcd')
    passed=restored is not None and restored.bbox()==top.bbox() and abs(check.dbu-layout.dbu)<1e-12
    if not passed:raise ValueError('GDS readback mismatch')
    result={'producer':'KLayout 0.29.12','readback_passed':passed,'dbu_um':check.dbu,'bbox_dbu':str(restored.bbox()),
            'top':'gcd','cells':check.cells(),'layers':check.layers(),'signoff_clean':False,
            'limitations':['LEF abstract geometry; transistor-level library GDS not merged','Automatic layer mapping; foundry mapping unverified']}
    (work/'result/report/gds_validation.json').write_text(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('work');a=ap.parse_args();print(json.dumps(export(a.work)))

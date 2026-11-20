"""Render a public, path-free coverage table from the catalog and qualification receipts."""
import argparse
import json
import re
from pathlib import Path


def snapshot(catalog, evidence):
    cases=json.loads(catalog.read_bytes())
    matrix={row["id"]:row for row in json.loads((evidence/"input-matrix.json").read_bytes())}
    if set(matrix)!={case["id"] for case in cases} or len(matrix)!=len(cases):
        raise ValueError("case catalog and input audit do not match")
    content=[
        "# Case coverage", "",
        "Each row identifies a design and its original process. Cell counts are catalog values before any documented tie-cell normalization. The profile column describes the production workbench. The last column describes this qualification campaign on the research worker. [Evidence definitions and process-library sources](QUALIFICATION.md)", "",
        "| Design | PDK | Standard cells | Hard macros | Workbench profile | Latest qualification evidence |",
        "|---|---|---:|---:|---|---|"
    ]
    for case in cases:
        ident=case["id"]
        profile={"full_backend":"Full back end", "placement_def":"Placement DEF","input_audit":"Input audit"}[case["goal"]]
        status=matrix[ident]["status"]
        if status.startswith("registered_"):
            observed="Existing profile; original results retained"
        elif status=="missing_inputs":
            observed="Waiting for matching "+case["pdk"].upper()+" libraries"
        else:
            observed="Declared inputs located"
            raw=evidence/("import-"+ident+".json")
            error=evidence/("import-"+ident+".error.txt")
            if raw.is_file():
                receipt=json.loads(raw.read_bytes())
                if receipt["case"]!=ident or receipt["stage"]!="import_netlist" or receipt["instances"]!=case["cells"]+case["macros"]:
                    raise ValueError("invalid import receipt for "+ident)
                observed="Native import DEF, "+format(receipt["nets"],",")+" nets"
            elif error.is_file():
                match=re.search(r"native import exited (\d+)",error.read_bytes().decode(errors="replace"))
                observed="Native import failed"+(" (exit "+match[1]+")" if match else "")
            structural=evidence/("structural-"+ident+".json")
            if structural.is_file():
                normalized=json.loads(structural.read_bytes())
                if normalized["case"]!=ident or normalized["normalized_import"]["passed"] is not True:
                    raise ValueError("invalid normalized receipt for "+ident)
                observed+="; normalized endpoints matched"
            elif (evidence/("structural-"+ident+".error.txt")).exists():
                observed+="; normalized qualification unsuccessful"
        content.append(f"| {ident} | {case['pdk']} | {case['cells']:,} | {case['macros']} | {profile} | {observed} |")
    return "\n".join(content)+"\n"


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for field in ["catalog","evidence","output"]:
        p.add_argument(field,type=Path)
    args=p.parse_args()
    args.output.write_text(snapshot(args.catalog,args.evidence),encoding="utf-8")

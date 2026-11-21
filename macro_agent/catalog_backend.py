"""Qualified Nangate45 catalog profiles sharing the existing native executor."""
import copy
import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from . import swerv_backend as native

CASES = ("bp_be", "bp_fe", "bp_multi", "s35932_nangate45_t", "tinyram")
ROOT = native.ROOT
VERSION = "catalog-nangate-full-v1"
COMPATIBLE = {"macro_placement", "fanout", "placement", "export_def", "cts",
              "to_drv", "to_hold", "legalization", "timing"}


def require_qualification(case_id):
    if case_id not in CASES:
        raise ValueError("Unknown catalog flow profile")
    reference = ROOT / "cases/ibench" / case_id
    receipt = json.loads((reference / "qualification.json").read_bytes())
    if receipt.get("case_id") != case_id or receipt.get("status") != "passed":
        raise ValueError("CATALOG_FLOW_NOT_QUALIFIED")
    for relative, expected in receipt["input_sha256"].items():
        source = (reference / relative).resolve()
        if not source.is_relative_to(reference.resolve()) or native.sha(source) != expected:
            raise ValueError("CATALOG_QUALIFIED_INPUT_CHANGED")
    for relative, expected in receipt["implementation_sha256"].items():
        if native.sha(ROOT / relative) != expected:
            raise ValueError("CATALOG_QUALIFIED_IMPLEMENTATION_CHANGED")
    evidence = Path(receipt["evidence"]["path"])
    if not evidence.resolve().is_relative_to((ROOT / "runs").resolve()):
        raise ValueError("CATALOG_EVIDENCE_OUTSIDE_WORKSPACE")
    if native.sha(evidence) != receipt["evidence"]["sha256"]:
        raise ValueError("CATALOG_QUALIFICATION_EVIDENCE_CHANGED")
    if receipt.get("validation_update"):
        update=receipt["validation_update"]
        if native.sha(Path(update["path"]))!=update["sha256"]:
            raise ValueError("CATALOG_VALIDATION_UPDATE_CHANGED")
    return receipt


def for_case(case_id, reference_root=None):
    if case_id not in CASES:
        raise ValueError("Unsupported catalog case")
    reference = Path(reference_root) if reference_root else ROOT / "cases/ibench" / case_id
    manifest = lambda: native.manifest(reference)
    m = manifest()
    spec = importlib.util.spec_from_file_location("macro_agent.catalog_native_" + case_id, native.__file__)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    from . import def_io_compat
    from .native_gds import input_files as exporter_files
    stages = [s for s in native.STAGES if s != "macro_placement" or m["expected_macro_masters"]]

    def files():
        sources = sorted(p for p in reference.rglob("*") if p.is_file())
        implementations = [Path(__file__), Path(native.__file__), Path(def_io_compat.__file__)]
        implementations += [ROOT / "macro_agent" / (name + ".py") for name in
                            ("aes_netlist", "aes_transforms", "liberty_buses", "macro_stages")]
        implementations += [ROOT / "environments/ieda-aes-router/iEDA",
                            ROOT / "environments/ieda-aes-router/manifest.json",
                            ROOT / "environments/ieda-swerv-cts/iEDA"]
        if m.get('hold_compatibility_guard'):
            implementations += [ROOT/'environments/ieda-hold-guard-v1'/n for n in ('iEDA','manifest.json')]
        return sources + implementations + exporter_files()

    def setup(work):
        from .aes_netlist import parse
        cells, buses = native.cells_and_buses(reference, m)
        source = parse(reference / m["netlist"], buses)
        macros = {n: master for n, master in source["components"].items() if cells[master]["hard_macro"]}
        if len(source["components"]) != m["expected_instances"] or macros != m["expected_macro_masters"]:
            raise ValueError("Catalog input identity changed")
        work = Path(work)
        shutil.copytree(reference / "config", work / "config")
        for name in ("logs", "report", "pl", "cts", "no", "to", "to_drv", "to_hold", "rt", "drc", "timing"):
            (work / ("logs" if name == "logs" else "result/" + name)).mkdir(parents=True, exist_ok=True)
        import time
        native.write(work / "run-start.json", {"time": time.time(), "case_id": case_id})

    def execute(stage, work):
        if stage in COMPATIBLE:
            return def_io_compat.execute(stage, work, reference, backend=engine)
        return engine.execute(stage, work, reference)

    return SimpleNamespace(rt=native.rt, BACKEND_VERSION=VERSION, STAGES=stages,
                           manifest=manifest, input_files=files, setup=setup,
                           execute=execute, package=package)


def package(state, folder, backend):
    from .task_artifacts import package as basic, ref, write_report
    folder = Path(folder)
    work = Path(state["accepted_work"])
    shadow = copy.deepcopy(state)
    shadow["results"]["export_def"] = state["results"]["routed_readback"]
    shadow["results"]["validate"]["independent"] = state["results"]["routed_readback"]["geometry"]
    output = basic(shadow, folder, backend, final_source=work / "result/routed_readback.def")
    preview=folder/"placement.svg"
    picture=preview.read_text(encoding="utf-8")
    picture=picture.replace("iEDA placement:", "iEDA routed DEF:")
    picture=picture.replace("Placement only. No routed wires, DRC/LVS or PPA signoff.",
                            "Final routed DEF instance geometry. Routed wires are available in final.def.")
    preview.write_text(picture,encoding="utf-8")
    output["preview"]["preview"]=ref(preview)
    native.write(folder/"preview.json",output["preview"])
    for kind, filename, source in (("final_gds", "final.gds", "final.gds"),
                                   ("final_netlist", "final.v", "routed_readback.v")):
        shutil.copyfile(work / "result" / source, folder / filename)
        output[kind] = ref(folder / filename)
    m = backend.manifest()
    drc = state["results"]["drc"]["drc_gate"]
    macro_check = state["results"].get("macro_placement", {}).get("independent_macro_check")
    a = json.loads((folder / "acceptance.json").read_bytes())
    a["preview"]=output["preview"]
    a.update(scope="Catalog netlist to routed DEF and abstract GDS",
             case_id=m["case_id"], hard_macros=len(m["expected_macro_masters"]),
             initial_standard_cells=m["expected_instances"] - len(m["expected_macro_masters"]),
             full_backend_workflow_completed=True, physical_quality_passed=drc["quality_clean"],
             drc=drc, signoff_clean=False, limitations=m["full_backend_policy"])
    if macro_check:
        a["macro_placement"] = macro_check
        a["checks"]["A7"] = "Native macro identities, core bounds and nonoverlap independently verified"
    native.write(folder / "acceptance.json", a)
    write_report(folder)
    report = folder / "report.html"
    text = report.read_text(encoding="utf-8")
    text = text.replace("iEDA netlist → placement DEF", "iEDA " + m["case_id"] + " → routed DEF / abstract GDS")
    text = text.replace("</h1>", "</h1><p>" + str(len(m["expected_macro_masters"])) +
                        " 个硬宏；原生 DRC " + str(drc["violation_count"]) +
                        " 项。详细质量指标与验证范围见下方验收证据。</p>", 1)
    for old in ("当前案例输出完成；整体第一阶段验收仍为部分完成，尚不能证明自动宏布局。",
                "当前双 SRAM 宏布局案例输出完成；整体第一阶段和完整后端验收另列，不由本次案例单独认证。"):
        text = text.replace(old, "本次登记案例完成全后端编排与产物验证。")
    if m.get('hold_compatibility_guard'):
        text=text.replace('</h1>','</h1><p>Hold 使用已固定哈希的隔离除零兼容修复，属于当前快照的局部修补，非上游官方构建；其余阶段保留登记版本。工具身份见冻结清单和原生执行回执。</p>',1)
    if m.get("floorplan_adaptation"):
        scale=m["floorplan_adaptation"]["scale"]
        text=text.replace("</h1>","</h1><p>本次使用核心边长 "+str(scale)+
                          " 倍的面积适配方案，原始版图尺寸与调整理由见冻结输入清单。</p>",1)
    report.write_text(text, encoding="utf-8")
    output["report"] = ref(report)
    output["acceptance"] = ref(folder / "acceptance.json")
    return output

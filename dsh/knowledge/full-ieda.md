# Registered HD GCD full backend workflow

Authority: reference data. Current contract and tool evidence always take priority.
Source: macro_agent/full_backend.py, macro_agent/native_gds.py; public iEDA source commit 65c39fd28aa0dc0cdd56325df07f6e440069061b for native iDB export.

## Netlist inputs and plan
This document covers ibench_gcd_legacy with goal=full_backend; qualified AES workflows have separate case-specific documentation. Freeze the conversation-selected mapped netlist, technology/cell LEF, Liberty, SDC, manifest and design configuration. There are zero hard macros in this GCD case; skip MP explicitly.
Execute the returned plan: import_netlist, floorplan (IO/PDN), fanout, placement, validate, export_def, cts, to_drv, to_hold, legalization, routing, filler, drc, timing, gds_export, routed_readback, finish.
Every act uses the latest state_id. Tool failure cannot be bypassed. Maker and external EDA backends are disabled.

## Validation and readback
Original flat netlist endpoints are independently checked. The only admitted logical mutation is the audited CTS buffer tree. The registered fanout/DRV/hold cases must leave the complete parsed design unchanged; actual commands still execute. Never claim an optimization gain from a no-op pass.
Native iTO initialization and its later RC update use different parasitic assumptions. Record post-update observations; do not interpret their delta as physical improvement. The standalone timing stage has no SPEF and is a cell-delay diagnostic only. Routed timing, power and IR remain null with explicit missing-dependency reasons.
Routing must complete all nets; final iDRC must have zero violations in all supported loaded rule families and consistent counters. Unsupported foundry rules are listed; this is not signoff.
The native public-iDB export has an explicit local C++ binary-writer/top/pin patch. KLayout only reads the GDS for validation; it does not convert or rewrite the accepted output. Geometry is LEF abstract plus routes, not merged transistor-level cell GDS; layer IDs follow iDB order, not a qualified foundry stream map.
The final new-process DEF readback compares parsed semantics and full per-net routing tokens. Output final.def, final.v, final.gds, placement.svg, report.html and evidence. Preview shows actual placement; it is not a route or fabrication preview.

## Recovery and scope
Checkpoint and stage receipts belong to the shared main_task core. Uncertain execution must recover before retry. The accepted state survives failed candidates. TARGET_MET certifies this registered workflow; aggregate stage-one, macro/DSH/repeat gates are separately evidenced. Do not claim arbitrary netlist/process support or timing/manufacturing signoff.

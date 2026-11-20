# Medium AES registered native backend

Reference data only. Current contract and actual evidence take priority.
Implementation: macro_agent/aes_flow.py and aes_backend.py; same native per-stage runner as the Linux baseline.

## Inputs and scope
Cases aes_sky130_t (AES Cipher, 9434 cells), aes_legacy (AES wrapper, 18646 cells), aes_core_sky130_t (AES Core, 20092 cells) use the public Sky130 HD library. All have zero hard macros. They are different netlists, not different seeds. Do not claim macro acceptance from these cases.
Start requires a complete matching server qualification receipt. Missing or stale qualification fails closed. Seven conversation file references freeze design.v, design.sdc, technology/cell LEF, Liberty, manifest.json and original design.json. Reviewed scripts and provenance remain host-controlled. No reference DEF is used.

## Plan and evidence
Use goal=full_backend and execute returned allowed actions with the latest state_id. Sixteen stages: import_netlist, floorplan, fanout, placement, validate, export_def, cts, to_drv, to_hold, legalization, routing, filler, drc, timing, gds_export, routed_readback; then finish.
Import validates cells, top ports and electrical endpoint partitions including bit-exact wire aliases. Fanout/CTS/DRV/hold may insert only approved non-inverting buffers; original logic cells must remain unchanged. Buffer contraction must preserve all original endpoints. Other stages cannot reconnect logic. Each candidate must pass its own checks.
Routing requires every net completed and no incomplete native substage. iDRC must execute supported rules and report consistent counters. Per the user's explicit acceptance choice, execution reproduction and physical quality are separate: nonzero DRC may be reported as a completed workflow but MUST remain physical_quality_passed=false, displayed prominently. Missing nets, skipped work, timeouts or conflicting counters cannot be accepted. Native iDB GDS is independently read by KLayout; no conversion substitutes. New-process DEF readback must preserve all parsed semantics and routing tokens.

## Budgets and limitations
4 CPU threads, 8 GiB memory, 1800 seconds for non-routing native stages, 21600 seconds for routing, 22 executions, 40 model calls, 32400 seconds per task. The bridge and pending-action recovery honor the longer registered stage bound. Failed or uncertain actions preserve the last accepted state. Never lower gates to finish.
No qualified SPEF, activity, IR or foundry stream map: timing is a cell-delay diagnostic, GDS contains LEF abstracts and routes, and no manufacturing signoff is claimed. P1 acceptance additionally needs actual DSH execution and a server-versus-desktop comparison; one case target_met is not aggregate certification.

The router is separately pinned to 9f6c91ac6a58a00feaa63ba5eef37cfd240a4b60dd1fedba0654439763a3a6f8, matching the shared AES baseline router; the original d9ae2896 iEDA runtime remains the producer for other stages. The 15 snapshot shared libraries are identical. Exact hashes and per-case routing graph are frozen.

The historical V4 recipe requested IEDA_RT_MAX_ITERATIONS=1. The effective iteration schedule must be verified against native logs; one round is not evidence of DRC closure. Native layer-track handling, graph-mode switches and the internal memory ceiling are UNVERIFIED: environment variables alone do not prove these capabilities. The server independently imposes CPU affinity and per-process RLIMIT_AS; this does not verify an internal router limit. Use current routing_capabilities.observed and quality_feedback as authoritative facts. The interrupted V3 result remains failed and is never substituted for a completed run.

The current V5 profile preserves those routing settings. Its storage policy allows 1 GiB per native output file and 4 GiB per attempt workspace, because the first V4 AES DRC report exceeded the earlier 256 MiB file ceiling. Full violation details are retained; there is no truncated-detail acceptance. CPU, memory, stage deadlines, rule coverage and quality criteria are unchanged. V4 remains a failed run; V5 establishes a fresh full baseline. Windows new-run directories use lossless NTFS compression to reduce repeated artifact storage without changing their bytes or hashes.

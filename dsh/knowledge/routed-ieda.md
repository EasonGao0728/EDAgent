# Registered routed DEF profile (experimental)

Version: ieda-manifest-stages-v3-server-d9ae2896-routed-v3-pdn. EDA backend iEDA only; Maker=0.
Only ibench_gcd_legacy HD input packages are supported. Freeze seven selected conversation files with the reviewed adapter and runtime.
Goal routed_def is a bounded subset toward the complete backend, not the full server pipeline and not phase-one certification.
Plan: import_netlist, floorplan, placement, validate, export_def, cts, legalization, routing, filler, drc, routed_readback, finish.
Always follow allowed_actions and latest state_id. Every execution gets an isolated workspace and independent acceptance checks.
IO planning explicitly uses native auto_place_pins with starting layer met3 and 800x800 DBU rectangles; the native directional pairing uses met3/met4. Layer and dimensions are frozen in the contract and checked after floorplanning. This differs from placement-only inputs' met5/2000 policy; never relabel an old run as this profile.
CTS may add only sky130_fd_sc_hd__buf_1 A/X buffers on clk; independent tree contraction checks original clock endpoints and all data nets.
PDN widths are frozen at met1=460 DBU and met4/met5=3200 DBU; native generation is checked against these widths. Earlier 480/1600 profiles produced PG DRC violations. Do not change an old task's contract. Electrical power connectivity, current capacity and IR adequacy are not certified by this width check.
Legalization may move nonfixed cells. Original fixed cells stay fixed. Routing preserves instances, positions and logical connections.
Routing requires route_complete=true and consistent routed/total net counts. Exit 0 or output files alone do not pass.
Filler permits only registered fill_1/2/4/8 physical cells. DRC must actually run, report zero violations and enumerate rule coverage.
Unsupported DRC families remain explicit and never imply signoff. Fresh readback compares full per-net route tokens and physical sections.
On BACKEND_ACCEPTANCE_FAILED preserve the prior accepted stage, report failed work and backend-checks.json. Do not skip, edit metrics, relax gates, or invoke a different EDA backend.
Two failures stop; unknown capabilities stop. No native GDS claim, RC extraction, STA, full fanout/DRV/hold parity or macro-case acceptance yet.
Preview displays DEF/LEF cell geometry, not routed metal geometry. HPWL in report is the placement-stage metric, not routed wirelength.

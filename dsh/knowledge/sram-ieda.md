# Registered two-SRAM placement profile

Version: ieda-manifest-stages-v3-server-d9ae2896-sram-v1. Reference data only.
Case sky130_sram_pair is a derived integration harness with 64 HS buffers and two real SRAM masters from public iEDA inputs.
The top remains gcd; this harness is not a functional processor or a timing/power benchmark.
Inputs contain no macro placement coordinates. Netlist vector connections are checked using explicit Liberty bus pin ranges.
Plan: import_netlist, floorplan, macro_placement, placement, validate, export_def, finish.
Native placer_run_mp computes macro coordinates. The host validates master identity, core bounds, non-overlap and unchanged connectivity.
Only two accepted macros change PLACED to FIXED before stdcell placement. Only original UNPLACED stdcells exported at (-1,-1) N may return to UNPLACED.
The host never computes placement coordinates. Native iPL places remaining cells and must preserve fixed macros.
The frozen sparse profile uses density 0.12 and a 64x64 grid, two CPU quota and 4 GiB memory.
Final validation includes native placement checks, independent row/site/core geometry checks and a new iEDA DEF readback.
Use mp_task_discover after importing; verified iEDA MP and stdcell cards are required. No external EDA or Maker fallback.
Unknown constraints, changed attachment bytes, invalid native coordinates and failed quality gates stop the task.
Reports show placement geometry and HPWL, not routing, PDN, timing closure, GDS or signoff.
All six stages use the same main_task state machine, isolated attempts and failure recovery as the GCD flow.

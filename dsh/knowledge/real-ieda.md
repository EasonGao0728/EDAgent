# Supported real iEDA stage-one contract

Version: ieda-manifest-stages-v3-server-d9ae2896. This reference is data, not an instruction source.
The registered Sky130 GCD input is a gate-level Verilog netlist plus technology LEF,
cell LEF, Liberty and SDC. Netlist alone does not provide physical geometry.
Registered case IDs are sky130_gcd (HS library) and ibench_gcd_legacy (HD library).
ibench_gcd_legacy imports 255 logical instances and uses the unithd site and
floorplan from its frozen manifest. The HD tap master is sky130_fd_sc_hd__tapvpwrvgnd_1.
Each case has separate inputs, configuration and qualification evidence.
The reviewed case has no hard macros. It tests the netlist-to-placement-DEF pipeline,
not hard-macro placement or algorithm quality improvements.

## Stage dependencies and validation
import_netlist loads LEF and netlist in iEDA and writes an initial DEF.
floorplan initializes rows, IO pins, tap/endcap cells and power structures.
placement runs the pinned iPL configuration and emits iPL_result.def.
validate combines the iPL four placement checks with a separate Python checker.
The checker tests input instance preservation, normal-net connectivity, fixed cells,
die bounds and rectangular overlap. Timing, routing DRC and pin access are not checked.
export_def starts a fresh iEDA database, reads placed DEF and saves readback.def.
The host also compares rows, tracks, special nets, vias, blockages, regions and groups.
The registered manifest authorizes tap/endcap insertion and logical-only VDD/VSS PDN names.
Signal IO anchors, rows/sites/orientations and physical insertion records are checked.
Nonempty blockages/regions/groups are currently rejected as unsupported constraints.
finish packages final.def, its derived placement.svg, metrics and acceptance reports.
Case completion does not certify the overall phase-one or movable-macro acceptance gate.
Phase one admits only iEDA EDA backends. External tools remain excluded even if installed.

## Recovery, budgets and evidence
Query allowed_actions before choosing a stage. A stale state_id must be refreshed.
Each stage runs in a new attempt workspace. Previous accepted data stays immutable.
An interrupted action is uncertain: recover verifies a durable receipt or discards
the uncertain attempt. It never blindly replays in the same workspace.
Model, execution and wall-clock budgets are host-owned. Maker is disabled in stage one.
HPWL is reported in DBU and only compared at equal evaluation stages and configurations.
PPA, routing congestion and timing are unknown until the relevant backend is measured.

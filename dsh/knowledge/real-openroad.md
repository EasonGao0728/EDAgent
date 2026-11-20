# Real macro integration backend: nangate-macro-smoke-v1

This registered derived integration fixture starts from gate-level Verilog and
Nangate45 technology/standard-cell LEF and Liberty plus OpenROAD fake macro data.
Ten hard macros and eight inserted BUF_X1 cells exercise the handoff; this is not
an industrial benchmark and results do not establish PPA improvement.

Allowed stages: import_netlist → floorplan → macro_placement → placement →
validate → export_def → finish. OpenROAD Hier-RTLMP places initially unplaced
macros; host checks macro geometry then fixes them. iEDA iPL places standard
cells. Independent validation checks preserved fixed macros, connectivity,
instances, rectangular bounds and overlap. A fresh OpenDB database reads iEDA's
DEF and writes it again; host compares the supported semantic fields.

Dispatcher requires installed and verified tool cards compatible with this
adapter and required constraints. Unsupported halo/fence/blockage requirements
are capability gaps, not silently dropped. First phase never invokes Maker.
Only accepted state is current evidence; logs/old receipts are historical data.
Units come from DEF. Timing, power and routed congestion are unavailable.

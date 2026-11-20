# Deployment and data

The open source checkout contains application and test source. The browser workbench uses pinned DSH packages from npm. For integration with an installed DSH desktop, tools/prepare_dsh_runtime.py can read its app.asar. The server uses an SSH alias, an account-owned workspace, a pinned iEDA binary, an independently checked exporter and an isolated native worker. The research deployment admits one job at a time, uses at most four CPU threads and an 8 GiB per-process address-space limit. Each installation must review the host, account identity, input roots and executable pins before enabling remote execution.

- [iEDA](https://github.com/OSCC-Project/iEDA) supplies native physical design tools. The project's tested binary is a specific snapshot; source compatibility with upstream HEAD is unverified.
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) supplies the agent framework. Supply the runtime that corresponds to the API used by this checkout (development environment: 0.2.0-rc.2).
- [OpenROAD-flow-scripts](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts) provides public research library inputs for selected technology profiles. Keep upstream notices and verify the pinned versions.
- The shared iBench benchmark netlists, lab PDKs, native executables and signoff collateral require their own access and applicable permissions. The catalog describes them; the application license covers original project code only.

For an actual design, use a technology-mapped Verilog netlist, matching technology and cell LEFs, corner-matched Liberty, SDC, and matching macro LEF/Liberty when the design contains macros. The lab's registered-input procedure also requires a design manifest and design metadata. An input check does not grant full-flow qualification. Faults in timing coverage, DRC or macro geometry must stay visible.

Historical reproduction tools under tools/ may depend on artifacts from a particular experiment. The portable offline example and CI exercise the parts reproducible from a clean clone.

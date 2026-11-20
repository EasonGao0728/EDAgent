# EDAgent

[中文使用说明](docs/README.zh-CN.md) · [Case coverage](docs/CASE_MATRIX.md) · [Development roadmap](ROADMAP.md)

EDAgent is a research workbench for running digital chip physical-design experiments. Its local agent selects tools and interprets evidence. A Linux worker executes iEDA and preserves checkpoints. A completed design can deliver a routed DEF, an abstract GDS, a layout preview and a report of rule violations.

**Current coverage** · The development workbench lists 50 designs. Five have a registered full-backend profile, two have placement profiles, and 43 are being brought up. Seven of those 43 use ICS55 and await authorized PDK access. A working profile, a reproduced run and a clean physical design are three different milestones. See [case coverage](docs/CASE_MATRIX.md).

## Try it in a minute

From a source checkout, with Python 3.11 or later:

```sh
python examples/placement_metrics.py
```

The example reads a small bundled macro placement with eight weighted nets and computes its half-perimeter wirelength. The expected result is **2145 model units**. It requires no account, server or EDA installation. The production flow uses mapped Verilog, LEF, Liberty and SDC and computes physical measurements on the server.

## How a design moves through the system

```text
Workbench → design contract and input checks → tool selection → SSH job
       ↑                                                        ↓
 report, preview and hashes ← acceptance checks ← iEDA checkpoints
```

The agent can inspect a checkpoint, compare measurements and try a scoped adjustment on a branch. The parent result remains available for comparison. DRC counts accompany the result even when the flow itself completed.

| Directory | Responsibility |
| --- | --- |
| ic-workbench/ | Local chat UI, case selector, file intake, tool library and artifact delivery |
| dsh/ | Agent integration, model adapters, context management and tool dispatch |
| macro_agent/ | Task contracts, remote execution, independent checks and quality feedback |
| tools/ | Runtime preparation, evidence inspection, research experiments and acceptance utilities |
| environments/ | Build sources and configuration for native tools |
| tests/ | Regression tests for placement, metrics, input binding and execution |

## Run the workbench

On Windows use Python 3.11+, Node.js 24 and npm. From the checkout:

```powershell
py -3.11 -m venv .venv-agent
.\.venv-agent\Scripts\python.exe -m pip install -e ".[chatgpt]"
npm ci --ignore-scripts
.\tools\start-silicon-workbench.ps1 -Open
```

The workbench listens on [localhost](http://127.0.0.1:4173/). **选择现有案例** opens the server catalog. **自定义输入案例** lists the mapped netlist, technology and library files, timing constraints and manifests expected by the importer. The model connection dialog supports a user-supplied endpoint and key.

Physical execution requires your own authorized Linux worker, pinned native binaries and compatible design libraries. The lab deployment is installation-specific; a fresh clone alone cannot reproduce all physical runs. See [deployment and third-party inputs](docs/DEPLOYMENT.md).

## Contribute

A useful bug report identifies the case, PDK revision, failed stage and observed versus expected result. Share a minimal reproducible input you may redistribute. For a new full-flow profile, include the frozen inputs and build identities, route-completion checks, DRC report, DEF readback and GDS evidence. [Roadmap](ROADMAP.md)

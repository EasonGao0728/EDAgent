# bp_multi routing and local repair

The main agent calls the Linux worker over SSH. These research tools bind each operation to the 26-macro Nangate45 testcase, its legalization checkpoint, router build, parent DEF and qualification evidence.

| Source | Purpose |
| --- | --- |
| `official-build/` | Build helpers and versioned iRT patches against upstream iEDA commit `65c39fd28aa0dc0cdd56325df07f6e440069061b`. Individual patches depend on their parent revisions and include experimental alternatives. |
| `tg-study/` | Pin access, topology sampling, checkpoint recovery, backend delivery, short attribution and local repair. |
| `bp_multi_official/` | Independent verification of routed geometry and pin connectivity. |
| `bp_multi_drv/` | Qualification adapter for the pre-route checkpoint. |
| `profiling/`, `official-port/` | Sampling and geometry diagnostics. |

### Connecting to an existing qualified run

Use the [deployment guide](../../docs/DEPLOYMENT.md) to connect to a provisioned worker. The worker entry points are `qualification-evidence/catalog-v1/tg-study/workbench_route.py` and `bp_short_agent.py`. The public layout uses `/srv/edagent/main-agent-remote-v1`, with the study, verifier and DRV adapter under `qualification-evidence/catalog-v1/`. Operators supply the pinned binaries, build and input manifests, native libraries, benchmark files and checkpoints separately. A new deployment must qualify its own inputs and evidence.

In the workbench, `mp_bp_multi_route` with `status` reads the existing job. `start` can resume a qualified checkpoint. `delivery` verifies the returned files. In a completed delivery conversation, request a short diagnosis, inspect the proposal, then request repair. The worker binds the edit to that proposal, writes a separate candidate and checks full-chip DRC and connectivity.

### Recorded experiment

| Measurement | Original | Candidate |
| --- | ---: | ---: |
| Native DRC markers after deduplication | 339,643 | 339,623 |
| Metal shorts | 213,494 | 213,473 |
| Disconnected routed nets | 0 | 0 |

The candidate moves an 11.2 µm wire interval from metal6 to metal5 and adds two vias. It removes 24 original shorts and introduces three shorts and one spacing marker. The connectivity check covers 78,493 routed nets and 270,267 pins. Substantial residual DRC remains. Portable CI exercises the software interfaces. Reproducing the physical run requires the corresponding worker artifacts.

The iEDA-derived router patches and native source portions retain the upstream notices and [iEDA license](LICENSE-iEDA). See the [upstream source revision](https://github.com/OSCC-Project/iEDA/tree/65c39fd28aa0dc0cdd56325df07f6e440069061b).

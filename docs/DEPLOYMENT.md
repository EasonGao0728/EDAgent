# Deploying EDAgent

## Windows workstation

Follow the [PowerShell install commands](../README.md#1-install-and-open-the-workbench) from the repository root. The model adapter looks for Python at `.venv-agent/Scripts/python.exe`. The standalone workbench loads its pinned DeepSeek Harness packages from npm. A separate DSH desktop installation is optional. On subsequent launches, run `npm.cmd start` from the same checkout and open `http://127.0.0.1:4173/`.

Check the UI process and the worker separately from a second PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:4173/api/health
Invoke-RestMethod http://127.0.0.1:4173/api/remote-status
```

The first response should contain `ok: true` and `source: shared-dsh-main-agent`. The second reports `online`, available case IDs and current jobs. Before worker configuration, `online: false` is expected even when the UI opens normally.

## Connecting to an existing worker

1. Ask the operator which Linux host and non-root account already have access to the deployment and your case. In `%USERPROFILE%\.ssh\config`, map the supported alias to that machine, replacing the two sample values below.

   ```sshconfig
   Host eda-worker
       HostName worker.example.org
       User your-linux-account
   ```

2. Verify the host fingerprint with the operator on first connection. Run `ssh eda-worker id -u`, then `ssh -o BatchMode=yes eda-worker id -u`. Both should return the same nonzero UID. The second command checks that the workbench can connect without an interactive password prompt.
3. Edit [environments/remote-server.json](../environments/remote-server.json) on your workstation. Use the literal alias `eda-worker`, the project root `/srv/edagent/main-agent-remote-v1`, the numeric Linux UID for `server_uid`, and `enabled: true`. Keep `local_fallback: false`. The operator must configure the same authorized UID and enable the worker profile. The public transport validates the alias and root.
4. Recheck `/api/remote-status` after the status cache refreshes (about 20 seconds). Confirm that the desired full-backend case is included in `cases`. Then select it in the workbench and submit the task.

## Provisioning a new Linux worker

The public checkout contains the controller, adapters, validation code and case catalog. A new worker also needs these operator-provided components:

| Component | Expected location or check |
| --- | --- |
| Worker source and jobs | Install this checkout at `/srv/edagent/main-agent-remote-v1`. Give the authorized account space to create its run directories and preserve checkpoints. |
| Execution environment | Provide SSH, Python and the unprivileged Linux `bwrap` runtime used by [the native adapter](../macro_agent/remote_native.py). Long jobs use tmux. The research profile admits one job at a time with four CPU threads and an 8 GiB per-process address-space limit. |
| Native binaries | The worker checks the primary iEDA binary in `/srv/edagent/portable-runtime-v1` against its pinned digest. Full-flow profiles also check their router, CTS and native GDS exporter components under `environments/`. See [the Nangate45 backend](../macro_agent/swerv_backend.py) for the SWERV paths and checks. |
| Registered design | For the walkthrough, provision `cases/ibench/swerv_nangate45/` in the worker checkout with its manifest, netlist, SDC, configuration, matching technology/standard-cell/macro LEFs, Liberty files, macro-placement dependency and source provenance. The preflight checks the registered inputs. |
| Additional benchmark catalog | The input-audit probe uses `/srv/benchmarks/iBench/benchmarks`. The [case matrix](CASE_MATRIX.md) records the qualification level of individual designs. |

The Python and npm install commands install the desktop software. Provisioning a fresh worker still requires the compatible binaries and original design packages. The public source distribution includes neither the lab's registered SWERV bundle nor a ready-made worker image. Operators with their own build or netlist must qualify that combination before offering it as a full-backend profile. Pin source revisions and retain matching input and output digests.

## Upstream resources and data rights

- [iEDA](https://github.com/OSCC-Project/iEDA) supplies the native physical-design tools. The tested research deployment uses a specific build.
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) supplies the agent runtime. The desktop npm versions are pinned in the lockfile.
- [OpenROAD-flow-scripts](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts) provides selected public research libraries. [Library receipts](public-library-receipts.json) list exact revisions and hashes.
- Benchmark netlists, macro models, PDKs and executables have their own access and redistribution terms. The MIT license applies to original EDAgent code.

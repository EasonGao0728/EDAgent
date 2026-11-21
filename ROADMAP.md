# Roadmap

| Milestone | Work | Acceptance |
| --- | --- | --- |
| 1 · Reproducible tool use | Port the deployment configuration, qualify the original 50 inputs by PDK, and connect qualified profiles to the workbench. Preserve exceptional cases such as missing ICS55 libraries. | Each case has a fresh native result or a specific blocker. Successful runs retain input hashes, structural checks, route evidence, DRC, timing diagnostics, GDS and DEF readback. |
| 2 · Tool design from observed gaps | The placement agent identifies an uncovered operation. A separate algorithm agent receives the design requirements and creates a candidate tool. | Run the candidate against a fixed baseline with the same inputs and resource budget. Record runtime, physical metrics, failure cases and reuse. |
| 3 · Tool evolution and agent self-improvement | Upgrade existing tools for new designs, then evaluate changes to the algorithm agent's own tool-design process. | Preserve older versions, test held-out designs and previous successes, compare cost and quality, and support rollback. |

The stage-one physical-design work takes priority. The algorithm agent and its self-improvement experiments remain research work.

## First public distribution

The first packaging milestone targets a new user completing a real design. The Windows client and Linux worker have different installation requirements.

1. **Source pre-release.** Tag a tested revision, describe the Windows prerequisites and worker dependency, and link the case coverage and known limitations. GitHub supplies source archives for the tag.
2. **Reproducible worker and design.** Publish versioned worker provisioning instructions or an image for the tested iEDA build. Include a redistributable full-flow case, its licensed process inputs or permitted download instructions, an input manifest, and reference outputs with their quality results.
3. **Downloadable Windows client.** Package the launcher and desktop dependencies, add an SSH and worker-health check, and publish the artifact with its SHA-256 checksum. Test it on a Windows machine without the development checkout. From chat, submit the reference design to a separately provisioned worker, then open the report and layout preview and verify the routed DEF and GDS.

These are release criteria. Published results for the laboratory worker are tracked in the [case matrix](docs/CASE_MATRIX.md).

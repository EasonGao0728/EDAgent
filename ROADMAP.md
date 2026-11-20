# Roadmap

| Milestone | Work | Acceptance |
| --- | --- | --- |
| 1 · Reproducible tool use | Port the deployment configuration, qualify the original 50 inputs by PDK, and connect qualified profiles to the workbench. Preserve exceptional cases such as missing ICS55 libraries. | Each case has a fresh native result or a specific blocker. Successful runs retain input hashes, structural checks, route evidence, DRC, timing diagnostics, GDS and DEF readback. |
| 2 · Tool design from observed gaps | The placement agent identifies an uncovered operation. A separate algorithm agent receives the design requirements and creates a candidate tool. | Run the candidate against a fixed baseline with the same inputs and resource budget. Record runtime, physical metrics, failure cases and reuse. |
| 3 · Tool evolution and agent self-improvement | Upgrade existing tools for new designs, then evaluate changes to the algorithm agent's own tool-design process. | Preserve older versions, test held-out designs and previous successes, compare cost and quality, and support rollback. |

The stage-one physical-design work takes priority. The algorithm agent and its self-improvement experiments remain research work.

# Qualifying a physical design

A case is identified by its mapped netlist, constraints and process revision. The case picker can list a design before a backend supports every stage. The [case matrix](CASE_MATRIX.md) records both the production profile and the highest independently verified result.

## Recreate the input audit

Run the following on your approved Linux worker from the project root. Set the benchmark, project and PDK roots to directories you are allowed to use. The case catalog contains metadata and digests. Obtain the original design inputs with permission.

```sh
python3 tools/audit_catalog_flow_inputs.py --catalog ic-workbench/case-packages.json \
  --benchmarks "$BENCHMARKS" --project . --pdks "$PDKS" > matrix-before.json
python3 tools/fetch_catalog_public_libraries.py matrix-before.json "$PDKS" > public-libraries.json
python3 tools/audit_catalog_flow_inputs.py --catalog ic-workbench/case-packages.json \
  --benchmarks "$BENCHMARKS" --project . --pdks "$PDKS" > matrix-after.json
```

The public-library helper uses the GitHub CLI and verifies the exact blob against a pinned OpenROAD-flow-scripts tree. The audit preserves all missing files. The [21 library receipts](public-library-receipts.json) record content hashes and source URLs. Nangate45 and ASAP7 inputs come from different commits. Inputs such as a macro timing model must match the master names, pins and revision expected by the netlist. Each upstream platform or library keeps its own license.

## Read the evidence

- **Inputs located** means every declared physical input is available. The audit does no placement or routing.
- **Imported DEF** means a native iEDA process read that netlist, LEF and constraints, exported DEF, and the checker verified the top, actual component records and nonempty net section. It records the input, binary and artifact hashes.
- **Endpoint match** compares electrical partitions independently. For a normalized source, it first checks the original netlist hash, normalization record, reported tie-cell delta and normalized payload hash. Generated tie cells can change component counts.
- **Full back end** additionally requires checkpoints through placement, routing, DRC, timing, abstract GDS and routed DEF readback. Read the actual DRC and timing results to judge quality.

For a deployed worker with its native binaries and compatible benchmark archive, use `tools/qualify_catalog_native_import.py` with the same four root options and the case ID. Add `--structural` for a hash-bound normalized input. The experimental Nangate45 stage driver `tools/qualify_catalog_nangate.py` starts from a verified import and reads the actual single-clock SDC. It retains stage receipts. Its `--resume` option checks their artifacts, stage sequence and input identity before advancing. A case must qualify and be integrated into the workbench before it is advertised as runnable there.

The seven ICS55 rows still need the matching technology LEF, standard-cell LEF and timing Liberty. Their existing macro models alone do not define a complete process. They stay in the catalog pending access.
## Native pilot

The [s35932 result](pilot-s35932_nangate45_t.json) comes from the server-side EDAgent stage executor. This standard-cell design reached routed DEF readback and produced a 22,714,208-byte abstract GDS. Detailed routing took 295.587 seconds. Native DRC reported **48 violations**. The timing report uses diagnostic parasitics. The workbench exposes this qualification result in its full-backend entry.

The original hierarchical Vortex import exhausted the worker address-space limit. The original WUKONG import stopped in the Verilog expression parser. Both normalized attempts reached allocation failures in the same 8 GiB envelope. Two Nangate45 Ariane raw imports also crashed; retained normalized DEFs independently matched their source endpoints after the checker learned to retain pinless physical tap-cell instances. These results preserve the original failed paths.

The shared archive lists 21 of the 43 additional cases with audited routing and 22 without a routing result. All 43 mark GDS as `NOT_GENERATED_BY_2D_BASELINE`. The archived routing column is separate from native EDAgent receipts.

Across all 36 additional cases with complete physical inputs, the native raw-netlist path produced 31 DEFs. Counting normalized inputs with verified ancestry, **34 designs passed independent endpoint comparison**, including all three public-process variants of the 220-macro BP Quad. The endpoint checker supports their bidirectional DDR ports, and rechecks used the retained DEFs. Vortex and WUKONG are the two outstanding imports. One of these 36 designs has full server-stage evidence (s35932). Registration and current run eligibility are separate; the worker recomputes eligibility from retained evidence.

## Workbench admission

The 50-design inventory includes profiles still undergoing qualification. A row's metadata alone cannot enable its Run button. The worker returns a separate list of cases with intact full-backend evidence. The browser enables those rows, the submission endpoint checks the worker again, and the remote task service enforces the same admission before starting a full-backend task. Offline or missing evidence leaves a case unavailable. Native DRC counts are displayed with the qualification result.

The catalog backend shares the existing iEDA executor and independently checks source imports, macro geometry, buffer endpoint contractions, placement, route completion, rule-report consistency, GDS export and routed DEF readback. A scoped floorplan adaptation must appear in the frozen manifest and report. The BP front-end study preserves the original 11-macro floorplan failure and evaluates a separate branch with both core dimensions scaled by 1.6, snapped to the site grid. This expands nominal core area by approximately 2.56. The branch becomes selectable only after its complete qualification.

The original IO adapter scanned the entire DEF for each pin. The updated adapter rewrites the PINS section in one pass and retains semantic checks. Buffer-insertion validation permits a port NET rename only when pin attributes are preserved, its declared NET agrees with NETS, and contraction of the approved buffers preserves all original terminal partitions. The regression tests also reject physical pin movement, stale declarations and disconnected buffers.

Historical complete runs must match the current input and implementation digests and fit the current CPU, memory and time profile. A run completed under a six-hour routing exception does not qualify a new ninety-minute routing budget. Such a case stays disabled until the current profile is qualified.

### November 21 macro qualification

The original BP front end has 24,562 standard cells and 11 hard macros. Its original native macro placement failed. A separate, site-aligned profile enlarged each core dimension by 1.6. Macro placement and the subsequent stages through legalization passed, but routing timed out after 5,400.676 seconds in topology generation (last logged 28,000 / 29,276 nets). This branch is **not full-flow qualified** and stays unavailable in the picker.

The smaller tinyram processor has 2,983 original standard cells and two research SRAM macros. The audited normalization adds 68 tie cells, yielding 3,053 input instances. Its default hold executable crashed with SIGFPE. Qualification resumed only that failed stage using the existing hash-pinned `ieda-hold-guard-v1` compatibility variant (`f881cd0b…df6abd`). The variant clamps the progress-report divisor, preserves the original optimizer, and is explicitly not an upstream rebuild. The base executable and failed receipt remain retained. This opt-in tool identity is part of the profile and task input digests; other profiles keep their original default.

The qualified tinyram profile completed routing, DRC, diagnostic timing, abstract GDS export and final DEF readback. Native DRC reported **1,041 violations**, so physical quality did not pass. Workbench and Agent-loop validation is tracked separately from this native qualification. This is a two-macro demonstration; it does not qualify the eleven-macro BP branch or all fifty inventory entries.

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

The [s35932 result](pilot-s35932_nangate45_t.json) comes from the server-side EDAgent stage executor. This standard-cell design reached routed DEF readback and produced a 22,714,208-byte abstract GDS. Detailed routing took 295.587 seconds. Native DRC reported **48 violations**. The timing report uses diagnostic parasitics. The workbench exposes this qualification result alongside its current input-audit entry.

The original hierarchical Vortex import exhausted the worker address-space limit. The original WUKONG import stopped in the Verilog expression parser. Both normalized attempts reached allocation failures in the same 8 GiB envelope. Two Nangate45 Ariane raw imports also crashed; retained normalized DEFs independently matched their source endpoints after the checker learned to retain pinless physical tap-cell instances. These results preserve the original failed paths.

The shared archive lists 21 of the 43 additional cases with audited routing and 22 without a routing result. All 43 mark GDS as `NOT_GENERATED_BY_2D_BASELINE`. The archived routing column is separate from native EDAgent receipts.

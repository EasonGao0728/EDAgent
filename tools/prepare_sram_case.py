"""Materialize a reproducible two-real-SRAM input fixture, never placement results."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
target=ROOT/'cases/sky130_sram_pair'
if target.exists():raise ValueError('Refuse to overwrite registered case')
target.mkdir()
source=ROOT/'third_party/ieda-reference'
probe=ROOT/'runs/stage1-native-macro-20261106-01'
for directory in ('netlist','pdk/lef','pdk/lib','sdc','tools','provenance'):(target/directory).mkdir(parents=True,exist_ok=True)
shutil.copyfile(probe/'gcd_sram.v',target/'netlist/gcd_sram.v')
for name in ('sky130_fd_sc_hs.tlef','sky130_fd_sc_hs_merged.lef','sky130_sram_1rw1r_44x64_8.lef'):
    shutil.copyfile(source/'scripts/foundry/sky130/lef'/name,target/'pdk/lef'/name)
for name in ('sky130_fd_sc_hs__tt_025C_1v80.lib','sky130_sram_1rw1r_44x64_8_TT_1p8V_25C.lib'):
    shutil.copyfile(source/'scripts/foundry/sky130/lib'/name,target/'pdk/lib'/name)
shutil.copyfile(source/'scripts/foundry/sky130/sdc/gcd.sdc',target/'sdc/gcd.sdc')
shutil.copyfile(source/'src/third_party/hmetis/hmetis2.0pre1',target/'tools/hmetis2.0pre1')
shutil.copytree(probe/'script',target/'script')
shutil.copytree(probe/'config',target/'config')
manifest={'schema_version':'ieda_case_v1','case_id':'sky130_sram_pair','format_id':'sky130_sram_pair_v1',
    'backend':'iEDA','top':'gcd','input_kind':'mapped_gate_level_verilog','reference_revision':json.loads((source/'manifest.json').read_text()).get('revision','see provenance'),
    'netlist':'netlist/gcd_sram.v','tech_lef':'pdk/lef/sky130_fd_sc_hs.tlef',
    'cell_lefs':['pdk/lef/sky130_fd_sc_hs_merged.lef','pdk/lef/sky130_sram_1rw1r_44x64_8.lef'],
    'libs':['pdk/lib/sky130_fd_sc_hs__tt_025C_1v80.lib','pdk/lib/sky130_sram_1rw1r_44x64_8_TT_1p8V_25C.lib'],
    'sram_bus_lib':'pdk/lib/sky130_sram_1rw1r_44x64_8_TT_1p8V_25C.lib','sdc':'sdc/gcd.sdc',
    'scripts_dir':'script','config_dir':'config','foundry_dir':'pdk','die_area_microns':[0,0,1500,1500],
    'core_area_microns':[10,10,1490,1490],'core_site':'unit','planning_source':'explicit sparse integration-test floorplan; no reference coordinates',
    'io_rule':{'method':'auto_place_pins','layer':'met5','width_dbu':2000,'height_dbu':2000},
    'mandatory_constraints':['fixed_instances','die_bounds','nonoverlap','row_site_alignment'],
    'allowed_physical_insertions':[],'allowed_power_pins':{},'logical_only_pdn_pins':[],
    'macro_placement':{'command':'placer_run_mp','macros':['mem0','mem1'],'hmetis':'tools/hmetis2.0pre1',
        'freeze_after_native_mp':True,'sentinel_policy':'only originally UNPLACED stdcells at native (-1,-1) N may return to UNPLACED'},
    'placement_profile':{'target_density':0.12,'bin_cnt_x':64,'bin_cnt_y':64},
    'hidden_reference_coordinates':False,'scripts_are_reviewed_case_adapters':True,
    'budget':{'executions':10,'model_calls':28,'wall_seconds':2400,'cpu_threads':2,'memory_gb':4,'container_seconds':120,'host_seconds':140},
    'scope':'derived integration harness: two real public Sky130 SRAM masters and 64 mapped HS buffers; placement goal, no PDN or timing closure claim',
    'provenance':['design.json','provenance/sources.json','tools/hmetis2.0pre1']}
(target/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
(target/'design.json').write_text(json.dumps({'name':'sky130_sram_pair','top':'gcd','construction':'two unplaced memory macros plus 64-buffer chain; all signal pins connected','not_a_functional_processor':True,'placement_solution_in_input':False},indent=2))
files=[{'path':p.relative_to(target).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in target.rglob('*') if p.is_file()]
(target/'provenance/sources.json').write_text(json.dumps({'upstream':'https://github.com/OSCC-Project/iEDA','upstream_manifest':json.loads((source/'manifest.json').read_text()),'derived_netlist_source':str(probe/'gcd_sram.v'),'files':files,'hmetis_license':'upstream bundled dependency; separate license, not an iEDA license claim'},indent=2))
print(target)

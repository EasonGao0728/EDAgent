"""Independent, fail-closed validation of the supported flat placement DEF subset."""
from decimal import Decimal
from pathlib import Path
import re


def section(text, name):
    found = re.search(r'^' + name + r'\s+(\d+)\s*;(.*?)^END ' + name + r'\s*$', text, re.M | re.S)
    if not found:
        if name in ('NETS','PINS','SPECIALNETS','BLOCKAGES','REGIONS','GROUPS','VIAS') and not re.search(r'^'+name+r'\b',text,re.M): return []
        raise ValueError('Missing DEF section: ' + name)
    rows = re.findall(r'^\s*-\s+(.*?)\s*;', found[2], re.M | re.S)
    if len(rows) != int(found[1]):
        raise ValueError('DEF section count mismatch: ' + name)
    return rows


def read_def(path):
    text = Path(path).read_text(encoding='utf-8')
    if not re.search(r'END DESIGN\s*$', text):
        raise ValueError('Incomplete DEF')
    design = re.search(r'^DESIGN\s+(\S+)\s*;', text, re.M)
    units = re.search(r'UNITS DISTANCE MICRONS (\d+)\s*;', text)
    if not design or not units:
        raise ValueError('Missing design or units')
    die = re.search(r'DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*;', text)
    components = {}
    for row in section(text, 'COMPONENTS'):
        name, master = row.split()[:2]
        if name in components:
            raise ValueError('Duplicate component')
        place = re.search(r'\+\s+(PLACED|FIXED|COVER)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\S+)', row)
        components[name] = {'master': master, 'placement': [place[1], int(place[2]), int(place[3]), place[4]] if place else None}
    nets = {}
    for row in section(text, 'NETS'):
        name = row.split()[0]
        if name in nets:
            raise ValueError('Duplicate net')
        nets[name] = sorted(re.findall(r'\(\s*(\S+)\s+(\S+)\s*\)', row.split('+', 1)[0]))
    pins = {}
    for row in section(text, 'PINS'):
        name = row.split()[0]
        if name in pins:
            raise ValueError('Duplicate pin')
        pins[name] = ' '.join(row.split())
    physical={name:sorted(' '.join(r.split()) for r in section(text,name)) for name in ('SPECIALNETS','BLOCKAGES','REGIONS','GROUPS','VIAS')}
    physical['ROWS']=sorted(' '.join(r.split()) for r in re.findall(r'^ROW\s+([^;]+);',text,re.M))
    physical['TRACKS']=sorted(' '.join(r.split()) for r in re.findall(r'^TRACKS\s+([^;]+);',text,re.M))
    return {'design': design[1], 'units': int(units[1]), 'die': list(map(int, die.groups())) if die else None,
            'components': components, 'nets': nets, 'pins': pins,'physical':physical}


def lef_cells(path, units):
    text = Path(path).read_text(encoding='utf-8')
    cells = {}
    for match in re.finditer(r'^MACRO (\S+)\s*$(.*?)^END \1\s*$', text, re.M | re.S):
        size = re.search(r'\bSIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;', match[2])
        origin = re.search(r'\bORIGIN\s+(-?[\d.]+)\s+(-?[\d.]+)\s*;', match[2])
        if not size or (origin and any(Decimal(v) != 0 for v in origin.groups())):
            raise ValueError('Unsupported LEF size/origin')
        cells[match[1]] = {'size': [int(Decimal(v)*units) for v in size.groups()],
                          'hard_macro': bool(re.search(r'CLASS\s+BLOCK\b', match[2])),
                          'pins':re.findall(r'^\s*PIN\s+(\S+)\s*$',match[2],re.M),
                          'site':(re.search(r'\bSITE\s+(\S+)\s*;',match[2]) or [None,None])[1],
                          'symmetry':(re.search(r'\bSYMMETRY\s+([^;]+);',match[2]) or [None,''])[1].split()}
    return cells


def validate_placement(loaded, floorplan, placed, lef, policy=None):
    cells = {}
    for path in (lef if isinstance(lef,(list,tuple)) else [lef]):
        cells.update(lef_cells(path, placed['units']))
    errors = []
    policy=policy or {}
    additions=[]
    for name,value in placed['components'].items():
        if name not in loaded['components']:
            additions.append({'instance':name,'master':value['master'],'stage':'floorplan','reason':'reviewed physical insertion'})
            if value['master'] not in policy.get('allowed_physical_insertions',[]) or floorplan['components'].get(name)!=value:
                errors.append('unauthorized_physical_insertion:'+name)
    for net,terminals in loaded['nets'].items():
        for inst,pin in terminals:
            if inst=='PIN':valid=pin in loaded['pins']
            else:valid=pin in cells.get(loaded['components'].get(inst,{}).get('master'),{}).get('pins',[])
            if not valid:errors.append('unresolved_terminal:'+inst+'/'+pin)
    for name,value in loaded['components'].items():
        if value['master'] not in cells:errors.append('unresolved_input_master:'+name)
    if loaded['design'] != placed['design'] or loaded['units'] != placed['units']:
        errors.append('design_or_units_changed')
    if loaded['nets'] != placed['nets']:
        errors.append('net_connectivity_changed')
    added_pins=set(placed['pins'])-set(loaded['pins'])
    allowed_power_pins=policy.get('allowed_power_pins',{})
    if set(loaded['pins'])-set(placed['pins']) or any(
        name not in allowed_power_pins or '+ USE '+allowed_power_pins[name] not in placed['pins'][name]
        for name in added_pins):
        errors.append('top_level_pins_changed')
    for name, value in loaded['components'].items():
        if placed['components'].get(name, {}).get('master') != value['master']:
            errors.append('missing_or_changed_input_instance:' + name)
    for name, value in floorplan['components'].items():
        if value['placement'] and value['placement'][0] == 'FIXED' and placed['components'].get(name) != value:
            errors.append('fixed_instance_changed:' + name)
    if floorplan['die'] != placed['die'] or not placed['die']:
        errors.append('die_changed_or_missing')
    boxes = []
    hard_macros = 0
    physical=placed.get('physical',{})
    for kind in ('BLOCKAGES','REGIONS','GROUPS'):
        if physical.get(kind):errors.append('unsupported_mandatory_constraint:'+kind)
    if floorplan.get('physical')!=physical:errors.append('floorplan_physical_constraints_changed')
    rows=[]
    for record in physical.get('ROWS',[]):
        m=re.fullmatch(r'(\S+) (\S+) (-?\d+) (-?\d+) (\S+) DO (\d+) BY (\d+) STEP (\d+) (\d+)',record)
        if not m or int(m[7])!=1 or int(m[9])!=0:
            errors.append('unsupported_row:'+record);continue
        rows.append({'site':m[2],'x':int(m[3]),'y':int(m[4]),'orient':m[5],'count':int(m[6]),'step':int(m[8])})
    die=placed['die']
    for name,pin in placed['pins'].items():
        if name in policy.get('logical_only_pdn_pins',[]) and '+ SPECIAL' in pin and any(r.startswith(name+' ') for r in physical.get('SPECIALNETS',[])):
            continue  # Frozen fixture PDN names, not physical signal IO terminals.
        p=re.search(r'\+ (PLACED|FIXED|COVER) \( (-?\d+) (-?\d+) \) (\S+)',pin)
        if not p or p[4] not in ('N','S','E','W','FN','FS','FE','FW'):
            errors.append('unplaced_or_invalid_io:'+name)
        elif die and not (die[0]<=int(p[2])<=die[2] and die[1]<=int(p[3])<=die[3]):errors.append('io_anchor_outside_die:'+name)
    for name, value in placed['components'].items():
        cell = cells.get(value['master'])
        if not cell or not value['placement']:
            errors.append('unknown_master_or_unplaced:' + name)
            continue
        hard_macros += int(cell['hard_macro'])
        _, x, y, orient = value['placement']
        if orient not in ('N','S','E','W','FN','FS','FE','FW'):
            errors.append('unsupported_orientation:' + name)
            continue
        w, h = cell['size']
        if not cell['hard_macro']:
            fits=[r for r in rows if r['site']==cell['site'] and y==r['y'] and r['step']>0 and x>=r['x'] and (x-r['x'])%r['step']==0 and x+w<=r['x']+r['count']*r['step']]
            if not fits:errors.append('row_site_violation:'+name)
            elif not any(orient in ({'N','FN'} if r['orient']=='N' else {'FS','S'} if r['orient']=='FS' else {r['orient']}) for r in fits):errors.append('row_orientation_violation:'+name)
        if orient in ('E','W','FE','FW'):
            w, h = h, w
        die = placed['die']
        if die and not (die[0] <= x and die[1] <= y and x+w <= die[2] and y+h <= die[3]):
            errors.append('outside_die:' + name)
        boxes.append((x,y,x+w,y+h,name))
    active = []
    for box in sorted(boxes):
        active = [old for old in active if old[2] > box[0]]
        for old in active:
            if min(box[3],old[3]) > max(box[1],old[1]):
                errors.append('overlap:' + old[4] + ':' + box[4])
        active.append(box)
    return {'passed': not errors, 'errors': errors[:30], 'error_count': len(errors), 'hard_macros': hard_macros,
            'reviewed_pdn_pin_additions':sorted(added_pins),
            'physical_insertions':additions,
            'logical_only_pdn_pins':policy.get('logical_only_pdn_pins',[]),
            'instances': len(placed['components']), 'nets': len(placed['nets']), 'units_dbu_per_micron': placed['units'],
            'coverage': ['input_instances','master_and_connected_pin_resolution','normal_net_connectivity','top_pin_names','io_placement','fixed_instances','die_bounds','rectangle_overlap','physical_insertions','rows_site_orientation','absent_blockages_regions_groups'],
            'not_checked': ['routing_DRC','timing','power','pin_access','routing_congestion']}

"""Explicit single-cell Liberty bus types, checked against physical LEF pins."""
import re
from pathlib import Path

def read_buses(libs, cells):
    result={}
    for path in libs:
        text=Path(path).read_text(encoding='utf-8')
        if not re.search(r'\bbus\s*\(',text):continue
        masters=re.findall(r'\bcell\s*\(\s*([^\s()]+)\s*\)\s*\{',text)
        if len(masters)!=1:raise ValueError('Bus library must have one explicit cell')
        types={}
        for name,body in re.findall(r'\btype\s*\(\s*([^\s()]+)\s*\)\s*\{([^{}]*)\}',text):
            vals={k:int(v) for k,v in re.findall(r'\b(bit_from|bit_to|bit_width)\s*:\s*(\d+)',body)}
            if set(vals)!={'bit_from','bit_to','bit_width'}:raise ValueError('Incomplete Liberty bus range')
            a,b=vals['bit_from'],vals['bit_to'];indexes=list(range(a,b+(-1 if a>b else 1),-1 if a>b else 1))
            if len(indexes)!=vals['bit_width']:raise ValueError('Inconsistent Liberty bus width')
            types[name]=indexes
        buses={}
        for name,typ in re.findall(r'\bbus\s*\(\s*([^\s()]+)\s*\)\s*\{\s*bus_type\s*:\s*([^\s;]+)',text):
            if typ not in types or name in buses:raise ValueError('Unknown or duplicate Liberty bus')
            pins=[f'{name}[{i}]' for i in types[typ]]
            if not set(pins)<=set(cells[masters[0]]['pins']):raise ValueError('Bus pin absent from LEF')
            buses[name]=pins
        if len(buses)!=len(re.findall(r'\bbus\s*\(',text)):raise ValueError('Unsupported Liberty bus declaration')
        result[masters[0]]=buses
    return result

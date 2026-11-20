"""Independent parser for the registered flat, named-port mapped Verilog subset.

Reject unsupported syntax instead of guessing elaboration. Not a general Verilog frontend.
"""
from pathlib import Path
import re
from .def_validation import read_def

TOKEN=re.compile(r'\s+|//[^\n]*|/\*.*?\*/|\\[^\s]+|[A-Za-z_$][A-Za-z0-9_$]*|[0-9]+|[(),;:.\[\]]',re.S)

def liberty_bus_ports(path):
    """Read explicitly ranged bus pins from a single-cell SRAM Liberty fixture.

    This intentionally refuses multi-cell libraries, duplicate/ragged ranges and
    bus types without an explicit pin range; it is not a Liberty parser.
    """
    text=Path(path).read_text(encoding='utf-8')
    cells=re.findall(r'^\s*cell\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*\{',text,re.M)
    if len(cells)!=1:raise ValueError('Single-cell SRAM Liberty required')
    buses=re.findall(r'^\s*bus\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*\{',text,re.M)
    pins=re.findall(r'^\s*pin\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\[(\d+):(\d+)\]\s*\)\s*\{',text,re.M)
    ranges={}
    for name,left,right in pins:
        if name in ranges:raise ValueError('Duplicate Liberty bus pin range')
        a,b=int(left),int(right)
        ranges[name]=[f'{name}[{n}]' for n in range(a,b+(-1 if a>b else 1),-1 if a>b else 1)]
    if len(buses)!=len(set(buses)) or set(buses)!=set(ranges):
        raise ValueError('Explicit Liberty bus/pin ranges do not match')
    if not ranges:raise ValueError('No explicit bus pins')
    return {cells[0]:ranges}


def parse_flat(path,port_buses=None):
    text=Path(path).read_text(encoding='utf-8');tokens=[];pos=0
    while pos<len(text):
        m=TOKEN.match(text,pos)
        if not m:raise ValueError('unsupported Verilog token at '+str(pos))
        t=m[0];pos=m.end()
        if not t.isspace() and not t.startswith(('//','/*')):tokens.append(t)
    i=0
    def take(expected=None):
        nonlocal i
        if i>=len(tokens):raise ValueError('truncated Verilog')
        t=tokens[i];i+=1
        if expected is not None and t!=expected:raise ValueError('expected '+expected+', got '+t)
        return t
    def ident():
        t=take()
        if t.startswith('\\'):return t[1:]
        if not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*',t):raise ValueError('expected identifier')
        return t
    take('module');top=ident();take('(');header=[]
    while True:
        header.append(ident());t=take()
        if t==')':break
        if t!=',':raise ValueError('unsupported module header')
    take(';');declared={};ports=set();components={};nets={};vectors=set()
    while tokens[i] in ('input','output','wire'):
        kind=take();bounds=None
        if tokens[i]=='[':
            take('[');a=int(take());take(':');b=int(take());take(']');bounds=range(a,b+(-1 if a>b else 1),-1 if a>b else 1)
        while True:
            name=ident();bits=[name] if bounds is None else [f'{name}[{n}]' for n in bounds]
            if name in declared:raise ValueError('duplicate declaration: '+name)
            declared[name]=bits
            if bounds is not None:vectors.add(name)
            for bit in bits:
                nets[bit]=[]
                if kind!='wire':ports.add(bit);nets[bit].append(('PIN',bit))
            t=take()
            if t==';':break
            if t!=',':raise ValueError('unsupported declaration')
    declared_ports={n for n,bits in declared.items() if any(b in ports for b in bits)}
    if set(header)!=declared_ports or len(header)!=len(set(header)):raise ValueError('module port declaration mismatch')
    while tokens[i]!='endmodule':
        master=ident();name=ident()
        if name in components:raise ValueError('duplicate instance')
        components[name]={'master':master};take('(');pins=set()
        while True:
            take('.');pin=ident()
            if pin in pins:raise ValueError('duplicate pin')
            pins.add(pin);take('(');net=ident()
            selected=False
            if tokens[i]=='[':
                take('[');index=int(take());take(']');bit=f'{net}[{index}]'
                selected=True
            else:bit=net
            if net not in declared:raise ValueError('unresolved net: '+net)
            bus=(port_buses or {}).get(master,{}).get(pin)
            if net in vectors and not selected:
                if bus is None or len(bus)!=len(declared[net]):raise ValueError('bus width/schema mismatch: '+master+'/'+pin)
                for net_bit,pin_bit in zip(declared[net],bus):nets[net_bit].append((name,pin_bit))
            else:
                if bit not in declared[net] or (bus is not None and len(bus)!=1):raise ValueError('unresolved or unsupported net: '+bit)
                nets[bit].append((name,bus[0] if bus else pin))
            take(')');t=take()
            if t==')':break
            if t!=',':raise ValueError('unsupported connection')
        take(';')
    take('endmodule')
    if i!=len(tokens):raise ValueError('multiple modules or trailing syntax unsupported')
    return {'design':top,'components':components,'pins':ports,'nets':{n:sorted(p) for n,p in nets.items() if p}}

def verify_import(netlist,def_path,port_buses=None):
    source=parse_flat(netlist,port_buses);actual=read_def(def_path);errors=[]
    if source['design']!=actual['design']:errors.append('top_changed')
    if source['components']!={n:{'master':v['master']} for n,v in actual['components'].items()}:errors.append('instance_master_mismatch')
    if source['pins']!=set(actual['pins']):errors.append('top_ports_mismatch')
    if source['nets']!=actual['nets']:errors.append('net_endpoints_mismatch')
    return {'passed':not errors,'errors':errors,'source_instances':len(source['components']),'source_nets':len(source['nets']),
        'scope':'independent registered flat mapped-Verilog subset; optional explicit Liberty bus pin ranges; no hierarchy/assign/RTL support'}

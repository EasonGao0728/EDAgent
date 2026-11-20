"""Independent flat structural Verilog audit, including bit-exact wire aliases.

No evaluation of RTL, expressions, constants, hierarchy or guessed bus widths.
Comparison uses endpoint partitions so harmless alias names do not change nets.
"""
from collections import Counter
from pathlib import Path
import re
from .def_validation import read_def

TOKEN=re.compile(r'\s+|//[^\n]*|/\*.*?\*/|\\[^\s]+|[A-Za-z_$][A-Za-z0-9_$]*|[0-9]+|[(),;:.\[\]{}=]',re.S)

def parse(path, port_buses=None):
    text=Path(path).read_text(encoding='utf-8'); tokens=[]; pos=0
    while pos<len(text):
        m=TOKEN.match(text,pos)
        if not m:raise ValueError('Unsupported structural Verilog at '+str(pos))
        t=m[0];pos=m.end()
        if not t.isspace() and not t.startswith(('//','/*')):tokens.append(t)
    i=0
    def take(want=None):
        nonlocal i
        if i>=len(tokens):raise ValueError('Truncated netlist')
        t=tokens[i];i+=1
        if want is not None and t!=want:raise ValueError('Expected '+want+', got '+t)
        return t
    def ident():
        t=take()
        if t.startswith('\\'):return t[1:]
        if not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*',t):raise ValueError('Expected identifier: '+t)
        return t
    def sequence(a,b):return list(range(a,b+(-1 if a>b else 1),-1 if a>b else 1))
    take('module');top=ident();take('(');header=[]
    while True:
        header.append(ident());t=take()
        if t==')':break
        if t!=',':raise ValueError('Unsupported header')
    take(';');decl={};kinds={};ports={};ends={};parents={};components={};aliases=[]
    def root(x):
        while parents[x]!=x:
            parents[x]=parents[parents[x]];x=parents[x]
        return x
    def expression():
        if tokens[i]=='{':
            take('{');value=[]
            while True:
                value+=expression();sep=take()
                if sep=='}':return value
                if sep!=',':raise ValueError('Unsupported concatenation')
        n=ident()
        if n not in decl:raise ValueError('Undeclared net: '+n)
        bits=decl[n]
        if tokens[i]=='[':
            take('[');a=int(take());b=a
            if tokens[i]==':':take(':');b=int(take())
            take(']');bits=[f'{n}[{v}]' for v in sequence(a,b)]
            if any(v not in decl[n] for v in bits):raise ValueError('Out-of-range selection')
        return bits
    while tokens[i]!='endmodule':
        if tokens[i] in ('input','output','inout','wire'):
            kind=take();rng=None
            if tokens[i]=='[':
                take('[');a=int(take());take(':');b=int(take());take(']');rng=sequence(a,b)
            while True:
                n=ident();bits=[n] if rng is None else [f'{n}[{v}]' for v in rng]
                previous=kinds.setdefault(n,set())
                if n in decl and (decl[n]!=bits or kind in previous or (kind!='wire' and previous-{'wire'})):
                    raise ValueError('Conflicting declaration: '+n)
                decl[n]=bits;previous.add(kind)
                for bit in bits:
                    ends.setdefault(bit,[]);parents.setdefault(bit,bit)
                    if kind!='wire':ports[bit]=kind;ends[bit].append(('PIN',bit))
                sep=take()
                if sep==';':break
                if sep!=',':raise ValueError('Unsupported declaration')
        elif tokens[i]=='assign':
            take('assign');left=expression();take('=');right=expression();take(';')
            if len(left)!=len(right):raise ValueError('Alias width mismatch')
            aliases.extend(zip(left,right))
        else:
            master=ident();name=ident()
            if name in components:raise ValueError('Duplicate instance')
            components[name]=master;take('(');seen=set()
            # Physical-only instances such as tap cells can have no signal pins.
            # Keep their instance/master identity for comparison with DEF.
            if i<len(tokens) and tokens[i]==')':
                take(')');take(';');continue
            while True:
                take('.');pin=ident()
                if pin in seen:raise ValueError('Duplicate terminal')
                seen.add(pin);take('(');bits=expression();take(')')
                expanded=(port_buses or {}).get(master,{}).get(pin)
                if expanded is not None:
                    if len(bits)!=len(expanded) or len(set(expanded))!=len(expanded):raise ValueError('Cell bus width mismatch: '+master+'/'+pin)
                    for bit,terminal in zip(bits,expanded):ends[bit].append((name,terminal))
                else:
                    if len(bits)!=1:raise ValueError('Unknown multi-bit cell terminal: '+master+'/'+pin)
                    ends[bits[0]].append((name,pin))
                sep=take()
                if sep==')':break
                if sep!=',':raise ValueError('Unsupported instance')
            take(';')
    take('endmodule')
    if i!=len(tokens):raise ValueError('Multiple modules/trailing syntax')
    actual={n for n in decl if kinds[n]-{'wire'}}
    if actual!=set(header) or len(set(header))!=len(header):raise ValueError('Port declaration mismatch')
    for a,b in aliases:parents[root(a)]=root(b)
    merged={}
    for n,values in ends.items():merged.setdefault(root(n),set()).update(values)
    return {'design':top,'components':components,'ports':ports,
            'partitions':Counter(tuple(sorted(v)) for v in merged.values() if v),
            'aliases_checked':len(aliases)}

def verify(netlist,artifact,port_buses=None):
    src=parse(netlist,port_buses);dst=read_def(artifact);errors=[]
    if src['design']!=dst['design']:errors.append('design_mismatch')
    if src['components']!={n:c['master'] for n,c in dst['components'].items()}:errors.append('instance_master_mismatch')
    if set(src['ports'])!=set(dst['pins']):errors.append('port_mismatch')
    for n,d in src['ports'].items():
        if '+ DIRECTION '+d.upper() not in dst['pins'].get(n,''):errors.append('port_direction_mismatch:'+n)
    partitions=Counter(tuple(sorted(v)) for v in dst['nets'].values() if v)
    if src['partitions']!=partitions:errors.append('electrical_endpoint_partition_mismatch')
    return {'passed':not errors,'errors':errors,'source_instances':len(src['components']),
            'source_nets':sum(src['partitions'].values()),'aliases_checked':src['aliases_checked'],
            'scope':'Flat structural netlist and bit-exact wire aliases; not RTL/formal functional equivalence'}

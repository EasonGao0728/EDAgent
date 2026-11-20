"""Check every original terminal after approved non-inverting buffer contraction."""
from collections import Counter
import re

BUFFERS={'sky130_fd_sc_hd__buf_1':('A','X'),'sky130_fd_sc_hd__buf_8':('A','X')}
VALIDATION_VERSION='aes-endpoint-partitions-v2-preserve-declared-empty-nets'

def check(before,after,stage,buffer_masters=None,filler_pattern=r'sky130_fd_sc_hd__fill_(1|2|4|8)'):
    errors=[];old=before['components'];new=after['components'];added=set(new)-set(old)
    for k in ('design','units','die','pins'):
        if before[k]!=after[k]:errors.append('changed_'+k)
    for n,c in old.items():
        if new.get(n,{}).get('master')!=c['master']:errors.append('changed_original:'+n)
        elif c['placement'] and c['placement'][0]=='FIXED' and c!=new[n]:errors.append('changed_fixed:'+n)
        elif stage in ('routing','filler','drc','timing','routed_readback') and c!=new[n]:errors.append('changed_placed:'+n)
    if stage not in ('fanout','cts','to_drv','to_hold'):
        if before['nets']!=after['nets']:errors.append('logical_connectivity_changed')
        if stage=='filler':
            if any(not re.fullmatch(filler_pattern,new[n]['master']) for n in added):errors.append('unapproved_filler')
        elif added:errors.append('unapproved_instances')
    else:
        nets=after['nets'];parents={n:n for n in nets};terms={}
        for net,pins in nets.items():
            for p in pins:terms.setdefault(tuple(p),[]).append(net)
        def root(n):
            while parents[n]!=n:parents[n]=parents[parents[n]];n=parents[n]
            return n
        for n in added:
            spec=(BUFFERS if buffer_masters is None else buffer_masters).get(new[n]['master'])
            if spec is None:errors.append('unapproved_logic_cell:'+n);continue
            a,b=(terms.get((n,p),[]) for p in spec)
            actual={p for inst,p in terms if inst==n}
            if len(a)!=1 or len(b)!=1 or actual!=set(spec):errors.append('invalid_buffer_terminals:'+n);continue
            x,y=root(a[0]),root(b[0])
            if x==y:errors.append('buffer_cycle:'+n);continue
            parents[y]=x
        collapsed={}
        for net,pins in nets.items():collapsed.setdefault(root(net),set()).update(tuple(p) for p in pins if p[0] not in added)
        # A declared but unused wire can be exported as an empty DEF net. It
        # must retain the same name and stay empty; a newly introduced empty
        # net or a buffer-only component remains an error.
        old_empty={n for n,pins in before['nets'].items() if not pins}
        new_empty={n for n,pins in nets.items() if not pins}
        if old_empty!=new_empty:errors.append('changed_declared_empty_networks')
        if any(not pins and n not in old_empty for n,pins in collapsed.items()):errors.append('floating_added_network')
        expected=Counter(tuple(sorted(p)) for p in before['nets'].values() if p)
        actual=Counter(tuple(sorted(p)) for p in collapsed.values() if p)
        if actual!=expected:errors.append('original_endpoint_partition_changed')
    return {'passed':not errors,'errors':errors[:30],'error_count':len(errors),'validation_version':VALIDATION_VERSION,
            'added_instances':len(added),'added_master_counts':dict(Counter(new[n]['master'] for n in added)),
            'scope':'Original cells and electrical endpoints modulo approved non-inverting buffers; not formal RTL equivalence'}

"""Fixed, bounded PDK-template substitution. No generated code or learned algorithm."""

def select_template(vias, shapes, markers, region):
    def intersect(a,b):return a[0]<=b[2] and a[2]>=b[0] and a[1]<=b[3] and a[3]>=b[1]
    def absolute(rects,xy):return [[x+xy[0],y+xy[1],u+xy[0],v+xy[1]] for x,y,u,v in rects]
    def inside(shape,xy):return all(region[0]<=a<=c<=region[2] and region[1]<=b<=d<=region[3] for rects in shape.values() for a,b,c,d in absolute(rects,xy))
    choices=[]
    for key,old in vias.items():
        net,layer,x,y=key;old_shape=shapes.get(old)
        if not old_shape or not inside(old_shape,[x,y]):continue
        relevant=[m for m in markers if m['type'] in ('metal_short','parallel_run_length_spacing') and net in (m.get('net_ids') or []) and m['layer'] in old_shape]
        if not relevant:continue
        for name,new_shape in shapes.items():
            if name==old or set(old_shape)!=set(new_shape) or not inside(new_shape,[x,y]):continue
            # Keep cut rectangles exactly unchanged; change only metal enclosure template.
            cut=[l for l in old_shape if not l.startswith('met') and l!='li1']
            if len(cut)!=1 or old_shape[cut[0]]!=new_shape[cut[0]]:continue
            avoided=[]
            for m in relevant:
                if any(intersect(b,m['bbox']) for b in absolute(old_shape[m['layer']],[x,y])) and not any(intersect(b,m['bbox']) for b in absolute(new_shape[m['layer']],[x,y])):avoided.append(m)
            if avoided:choices.append({'key':list(key),'before':old,'after':name,'proxy_avoided_marker_count':len(avoided),'marker_examples':avoided[:6],
                                       'scope':'geometric hypothesis only; not a DRC result or connectivity proof','cut_geometry_unchanged':True})
    return sorted(choices,key=lambda c:(-c['proxy_avoided_marker_count'],c['key'],c['after']))[0] if choices else None

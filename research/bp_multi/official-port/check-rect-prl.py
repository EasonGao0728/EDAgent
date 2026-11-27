"""Compare the via-pad PRL rule against the frozen deck; no EDA stage is run."""
import hashlib
import json
import re
from bisect import bisect_right
from decimal import Decimal
from pathlib import Path

root = Path(__file__).resolve().parents[4]
deck = root / "cases/ibench/swerv_nangate45/pdk/lef/NangateOpenCellLibrary.tech.lef"
assert hashlib.sha256(deck.read_bytes()).hexdigest() == "834a79295054cd4209178d1bade67c353863c47bb4b3c22ee38b862b7cec37f2"
layer = re.search(r'^LAYER metal2\s+(.*?)^END metal2',deck.read_text(),re.S|re.M).group(1)
def dbu(text):
    return int(Decimal(text)*2000)
lookup = re.search(r'PARALLELRUNLENGTH(.*?);',layer,re.S).group(1).split('WIDTH')
prls = list(map(dbu,lookup[0].split()))
widths = []
table = []
for row in lookup[1:]:
    width,*entries=map(dbu,row.split())
    widths.append(width)
    table.append(entries)
def actual(width,prl):
    return table[bisect_right(widths,width)-1][bisect_right(prls,prl)-1]
def reference(width,prl):
    # Direct implementation of idrc::ParallelRunLengthSpacingRule::getSpacing.
    i=next(i for i in reversed(range(len(widths))) if widths[i] <= width)
    j=next(j for j in reversed(range(len(prls))) if prls[j] <= prl)
    return table[i][j]
def delta(v):
    return {max(0,t+off) for t in v for off in (-1,0,1)} | {100000}
width_queries=delta(widths)
run_queries=delta(prls)
for w in width_queries:
    for run in run_queries:
        assert actual(w,run)==reference(w,run)
a=(465620,362320,465760,362600)
b=(463694,122360,693974,360360)
def spacing(a,b):
    overlaps=[min(a[d+2],b[d+2])-max(a[d],b[d]) for d in (0,1)]
    prl=max(0,*overlaps)
    width=max(min(box[2]-box[0],box[3]-box[1]) for box in (a,b))
    return actual(width,prl)
def clear(a,b):
    # Conservative square distance: same as the iRT fixed-shape filter.
    return max(max(a[d],b[d])-min(a[d+2],b[d+2]) for d in (0,1))>=spacing(a,b)
assert spacing(a,b)==140 and clear(a,b)
assert spacing(b,a)==140 and clear(b,a)
# Wide conductor keeps longest-column 3,000 DBU when the facing run reaches
# 8,000 DBU. A short pad keeps the true minimum spacing; equality is legal.
for run,expected in ((140,140),(599,140),(600,180),(1799,180),(1800,540),(3599,540),(3600,1000),(5399,1000),(5400,1800),(7999,1800),(8000,3000)):
    for gap in (0,expected-1,expected,expected+1):
        fixed=(0,0,12000,4000)
        other=(100,4000+gap,100+run,4000+gap+140)
        assert spacing(fixed,other)==expected
        assert clear(fixed,other) == (gap>=expected)
receipt=dict(scope='Independent arithmetic model against actual frozen Nangate45 M2 table and iDRC threshold policy; native process checked separately',tech_sha256=hashlib.sha256(deck.read_bytes()).hexdigest(),width_run_threshold_pairs=len(width_queries)*len(run_queries),spacing_threshold_and_touch_checks=44,frozen_pair=dict(pad=a,obstacle=b,parallel_run_dbu=140,distance_dbu=1960,required_dbu=140,prior_dbu=3000),failure_count=0)
print(json.dumps(receipt,indent=2))

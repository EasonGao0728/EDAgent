"""Offline regression of the observer only. No layout stages are executed."""
from tempfile import TemporaryDirectory
from pathlib import Path

from verify_pa import pa_check


def main():
    example = {'nets':{'clock':[('PIN','clk'),('buf','A')]}, 'die':[0,0,100,100],
               'physical':{'TRACKS':['X 0 DO 11 STEP 10 LAYER metal1','Y 0 DO 6 STEP 20 LAYER metal1']}}
    valid = "net_idx\tnet\tpin_idx\tpin\tlayer\tx\ty\n0\tclock\t0\tclk\tmetal1\t10\t20\n0\tclock\t1\tbuf:A\tmetal1\t30\t40\n"
    native = 'EDA_DEF_TRACK layer=metal1 axis=X start=0 count=11 pitch=10\nEDA_DEF_TRACK layer=metal1 axis=Y start=0 count=6 pitch=20\nEDA_PA_COVERAGE expected=2 resolved=2\n'
    shapes=lambda i,p,l,x,y: (x,y)==((10,20) if i=='PIN' else (30,40))
    with TemporaryDirectory() as tmp:
        w=Path(tmp)
        (w/'result/rt').mkdir(parents=True)
        for name,t,log,rss,ok in [
            ('complete',valid,native,2048,True),
            ('missing pin',valid.split('0\tclock\t1')[0],native,2048,False),
            ('duplicate',valid.replace('buf:A','clk'),native,2048,False),
            ('unmatched metal pitch',valid,native.replace('pitch=20','pitch=10'),2048,False),
            ('unattached coordinate',valid.replace('30\t40','31\t40'),native,2048,False),
            ('no memory sample',valid,native,0,False),
        ]:
            (w/'pa.tsv').write_text(t)
            (w/'result/rt/rt.log').write_text(log)
            try: passed=pa_check(w,example,rss,4096,shapes)['passed']
            except ValueError:passed=False
            if passed!=ok:raise AssertionError(name)
            print(name, 'OK')


if __name__=='__main__':main()

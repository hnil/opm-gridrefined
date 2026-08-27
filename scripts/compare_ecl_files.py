"""Array-by-array comparison of two ECL binary files, section aware.

An LGR header opens a section; ENDLGR (EGRID) or LGRSGONE (INIT) closes it.
Arrays are paired by (section, name, order of appearance) so that a name which
occurs at two lengths in one file -- as the region arrays do -- pairs correctly.
"""
import sys, collections, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ecl_binary import records

OPEN  = ('LGR','LGRNAME')
CLOSE = ('ENDLGR','LGRSGONE')

def sections(path):
    secs=collections.OrderedDict(); cur='FILE'; secs[cur]=[]
    for name,cnt,typ,d in records(path):
        if name in OPEN:
            cur = 'LGR:' + (d[0].strip() if d else '?')
            secs.setdefault(cur,[]); continue
        if name in CLOSE:
            cur='FILE'; continue
        if name in ('LGRHEADI','LGRHEADQ','LGRHEADD'):
            continue
        secs[cur].append((name,cnt,typ,d))
    return secs

def bucket(arrs):
    b=collections.OrderedDict()
    for name,cnt,typ,d in arrs:
        b.setdefault(name,[]).append((cnt,typ,d))
    return b

# REAL arrays are single precision, so anything under ~2e-6 relative is the
# storage format, not a difference. DOUB has room for a much tighter check.
TOL = {'REAL': 1e-5, 'DOUB': 1e-9}

def diff(typ,a,b):
    if typ in ('INTE','LOGI','CHAR') or (a and isinstance(a[0],str)):
        bad=sum(1 for x,y in zip(a,b) if x!=y)
        return bad,len(a),None
    tol=TOL.get(typ,1e-5)
    bad=0; ratios=[]
    for x,y in zip(a,b):
        if x==0.0 and y==0.0: continue
        if abs(x-y) > tol*max(abs(x),abs(y)): bad+=1
        if abs(x)>0.0: ratios.append(y/x)
    ratios.sort()
    pc=None
    if ratios:
        pc=(ratios[len(ratios)//100], ratios[len(ratios)//2], ratios[-len(ratios)//100-1])
    return bad,len(a),pc

NNCSET = {'NNC1','NNC2','NNCL','NNCG','TRANNNC','TRANGL'}

def nnc_report(ba, bb, sec):
    """NNC arrays are lists whose order is the writer's choice, so compare the
    connections as sets of cell pairs rather than element by element."""
    def pairs(b, k1, k2, val=None):
        if k1 not in b or k2 not in b: return None
        out=[]
        for i,(c1,_,d1) in enumerate(b[k1]):
            if i>=len(b[k2]): break
            d2=b[k2][i][2]
            v = b[val][i][2] if (val in b and i < len(b[val])) else None
            # the two writers order the pair oppositely, so key on the sorted pair
            out.append({(min(x,y),max(x,y)): (v[j] if v else None) for j,(x,y) in enumerate(zip(d1,d2))})
        return out
    for k1,k2,val,lab in (('NNC1','NNC2','TRANNNC','internal NNC'),
                          ('NNCL','NNCG','TRANGL','LGR<->global NNC')):
        pa=pairs(ba,k1,k2,val); pb=pairs(bb,k1,k2,val)
        if not pa or not pb: continue
        for i in range(min(len(pa),len(pb))):
            A,B=pa[i],pb[i]
            only_a=set(A)-set(B); only_b=set(B)-set(A); both=set(A)&set(B)
            line=(f"   {lab} #{i+1}: reference {len(A)}, run {len(B)}; "
                  f"shared {len(both)}, only-reference {len(only_a)}, only-run {len(only_b)}")
            vals=[(A[p],B[p]) for p in both if A[p] is not None and B[p] is not None and A[p]!=0.0]
            if vals:
                r=sorted(y/x for x,y in vals)
                bad=sum(1 for x,y in vals if abs(y-x)>1e-5*max(abs(x),abs(y)))
                line+=(f"; of the shared, {bad} transmissibilities differ"
                       f" (p1 {r[len(r)//100]:.4f} med {r[len(r)//2]:.4f} p99 {r[-len(r)//100-1]:.4f})")
            print(line)


def compare(ref, run, label, skip=('INTEHEAD','LOGIHEAD','DOUBHEAD','FILEHEAD')):
    A=sections(ref); B=sections(run)
    print(f"\n{'='*78}\n{label}\n{'='*78}")
    for sec in list(A)+[s for s in B if s not in A]:
        ba=bucket(A.get(sec,[])); bb=bucket(B.get(sec,[]))
        print(f"\n-- {sec}: reference {sum(len(v) for v in ba.values())} arrays, "
              f"run {sum(len(v) for v in bb.values())}")
        only_ref=[n for n in ba if n not in bb]
        only_run=[n for n in bb if n not in ba]
        if only_ref: print(f"   MISSING FROM RUN ({len(only_ref)}): {' '.join(sorted(only_ref))}")
        if only_run: print(f"   only in run      ({len(only_run)}): {' '.join(sorted(only_run))}")
        nnc_report(ba, bb, sec)
        same=[]
        for n in ba:
            if n not in bb or n in skip or n in NNCSET: continue
            for k,(ca,ta,xa) in enumerate(ba[n]):
                if k>=len(bb[n]):
                    print(f"   {n:<10} reference has {len(ba[n])} copies, run {len(bb[n])}"); break
                cb,tb,xb = bb[n][k]
                if ca!=cb:
                    print(f"   {n:<10} LENGTH differs: reference {ca}  run {cb}")
                    continue
                if ca==0: continue
                nbad,ntot,pc = diff(ta,xa,xb)
                if nbad:
                    s=f"   {n:<10}[{ca:>7}] {nbad:>8} differ ({100.0*nbad/ntot:5.1f}%)"
                    if pc: s+=f"  run/ref p1 {pc[0]:.4f} med {pc[1]:.4f} p99 {pc[2]:.4f}"
                    print(s)
                else:
                    same.append(f"{n}[{ca}]")
        if same: print(f"   IDENTICAL ({len(same)}): {' '.join(same)}")

if __name__=='__main__':
    compare(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv)>3 else '')

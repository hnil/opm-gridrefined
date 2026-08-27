"""Compare NNC transmissibilities between two runs, matching by cell pair.

NNC1/NNC2 live in the EGRID and TRANNNC/TRANGL in the INIT; the lists are in
whatever order the writer chose and the two writers order each pair oppositely,
so match on the sorted pair rather than by position.
"""
import sys, collections, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ecl_binary import records

def blocks(p):
    out=[]; cur='FILE'
    for name,cnt,typ,d in records(p):
        if name in ('LGR','LGRNAME'): cur='LGR:'+(d[0].strip() if d else '?'); continue
        if name in ('LGRSGONE','ENDLGR'): cur='FILE'; continue
        out.append((cur,name,cnt,d))
    return out

def lists(egrid, init):
    b=blocks(egrid); i=blocks(init)
    n1=[d for _,n,_,d in b if n=='NNC1']; n2=[d for _,n,_,d in b if n=='NNC2']
    nl=[d for _,n,_,d in b if n=='NNCL']; ng=[d for _,n,_,d in b if n=='NNCG']
    tn=[d for _,n,_,d in i if n=='TRANNNC']; tg=[d for _,n,_,d in i if n=='TRANGL']
    out=[]
    for k in range(min(len(n1),len(n2))):
        t = tn[k] if k < len(tn) else None
        out.append(('NNC', {(min(a,b),max(a,b)): (t[j] if t else None)
                            for j,(a,b) in enumerate(zip(n1[k],n2[k]))}))
    for k in range(min(len(nl),len(ng))):
        t = tg[k] if k < len(tg) else None
        out.append(('NNCLG', {(a,b): (t[j] if t else None)
                              for j,(a,b) in enumerate(zip(nl[k],ng[k]))}))
    return out

def go(refE, refI, runE, runI, label):
    A=lists(refE,refI); B=lists(runE,runI)
    print(f"\n-- {label}")
    for k in range(max(len(A),len(B))):
        if k>=len(A): print(f"   list #{k+1}: only the run has it ({B[k][0]}, {len(B[k][1])})"); continue
        if k>=len(B): print(f"   list #{k+1}: MISSING FROM RUN ({A[k][0]}, {len(A[k][1])})"); continue
        ta,a=A[k]; tb,b=B[k]
        shared=set(a)&set(b)
        vals=[(a[p],b[p]) for p in shared if a[p] not in (None,0.0) and b[p] is not None]
        s=f"   list #{k+1} [{ta}]: reference {len(a)}, run {len(b)}, shared {len(shared)}, only-ref {len(set(a)-set(b))}, only-run {len(set(b)-set(a))}"
        if vals:
            r=sorted(y/x for x,y in vals)
            bad=sum(1 for x,y in vals if abs(y-x)>1e-5*max(abs(x),abs(y)))
            s+=f"\n        of {len(vals)} shared transmissibilities, {bad} differ: p1 {r[len(r)//100]:.4f} med {r[len(r)//2]:.4f} p99 {r[-len(r)//100-1]:.4f}"
        print(s)

if __name__=='__main__':
    go(*sys.argv[1:6])

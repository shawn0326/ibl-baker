"""Compare full-chain factorial runs, separating convolution and encoding errors."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode=True
import experiment as e


def reference(case,size,probes):
    if case=="constant":
        roughnesses=sorted({i/20 for i in range(21)}|{(i+.5)/(size.bit_length()-1) for i in range(size.bit_length()-1)})
        return [dict(roughness=r,rgb=np.broadcast_to([.25,1.,4.],probes.shape).tolist(),spread=[0.]*len(probes),converged=[True]*len(probes)) for r in roughnesses]
    path=e.previous.OUT/"reference"/str(size)/f"{case}.json"
    data=json.loads(path.read_text())
    if not np.array_equal(probes,np.asarray(data["identity"]["probes"])): raise ValueError("Reference probe set changed")
    return data["rows"]


def metrics(case,size,policies,codecs):
    probes=e.previous.directions();references=reference(case,size,probes);rows=[];encoding=[]
    for policy in policies:
        rawdir=e.OUT/"raw"/str(size)/case/policy
        raw=e.previous.levels(rawdir)
        chains={"float":raw,"ibla":a.decode(rawdir,"ibla")}
        for codec in codecs:
            chains[codec]=a.decode(e.OUT/"encoded"/str(size)/case/policy/codec,"ktx2")
        for label,chain in chains.items():
            if label=="float":continue
            errors=[]
            for mip,(original,decoded) in enumerate(zip(raw,chain)):
                limit=255. if label=="ibla" else 65504.
                bounded=np.clip(original.faces,0,limit)
                errors.append(dict(mip=mip,size=original.size,components=original.faces.size,
                    squared_error=float(np.sum((decoded.faces-bounded)**2)),
                    squared_reference=float(np.sum(bounded**2)),
                    clipping_squared_error=float(np.sum((original.faces-bounded)**2)),
                    clipped_pixels=int(np.any(original.faces!=bounded,axis=-1).sum()),
                    max_absolute=float(np.max(np.abs(decoded.faces-bounded)))))
            encoding.append(dict(case=case,size=size,policy=policy,codec=label,levels=errors,
                whole_relative_rmse=(sum(x["squared_error"] for x in errors)/max(sum(x["squared_reference"] for x in errors),1e-30))**.5))
        for ref in references:
            r=ref["roughness"];expected=np.asarray(ref["rgb"]);original=e.previous.sample(raw,probes,r)
            bright=np.argsort(expected@np.array([.2126,.7152,.0722]))[-max(1,math.ceil(.05*len(probes))):]
            groups=[("all",np.arange(len(probes))),("uniform",np.arange(32)),("axes-edges-corners",np.arange(32,58)),("lamp-local",np.arange(58,len(probes))),("bright",bright)]
            for label,chain in chains.items():
                actual=e.previous.sample(chain,probes,r)
                for group,index in groups:
                    scale=max(float(np.sqrt(np.mean(expected[index]**2))),1e-6)
                    rows.append(dict(case=case,size=size,policy=policy,codec=label,roughness=r,group=group,
                        relative_rmse=float(np.sqrt(np.mean((actual[index]-expected[index])**2))/scale),
                        encoding_rmse=float(np.sqrt(np.mean((actual[index]-original[index])**2))),
                        reference_envelope=float(np.sqrt(np.mean(np.asarray(ref["spread"])[index]**2))/scale),
                        qualified=bool(np.all(np.asarray(ref["converged"])[index]))))
        print("analyzed",size,case,policy,flush=True)
    return rows,encoding


def summarize(rows,encoding):
    key=lambda r:(r["case"],r["size"],r["roughness"],r["group"])
    baseline={key(r):r for r in rows if r["policy"]=="quadratic" and r["codec"]=="basic-black"}
    float_base={key(r):r for r in rows if r["policy"]=="quadratic" and r["codec"]=="float"}
    ibla_base={key(r):r for r in rows if r["policy"]=="quadratic" and r["codec"]=="ibla"}
    summaries=[]
    for policy,label in sorted({(r["policy"],r["codec"]) for r in rows}):
        selected=[r for r in rows if (r["policy"],r["codec"])==(policy,label)]
        regressions=[]
        for row in selected:
            base=(float_base if label=="float" else ibla_base if label=="ibla" else baseline)[key(row)]
            tolerance=max(.05*base["relative_rmse"],5*max(base["reference_envelope"],row["reference_envelope"]),1e-4)
            if row["qualified"] and base["qualified"] and row["relative_rmse"]>base["relative_rmse"]+tolerance:
                regressions.append(row|dict(baseline=base["relative_rmse"],tolerance=tolerance))
        allrows=[r for r in selected if r["group"]=="all"]
        means={case:float(np.mean([r["relative_rmse"] for r in allrows if r["case"]==case])) for case in sorted({r["case"] for r in allrows})}
        summaries.append(dict(policy=policy,codec=label,qualified_regressions=len(regressions),
            worst=max(regressions,key=lambda r:r["relative_rmse"]-r["baseline"]-r["tolerance"],default=None),
            unqualified_rows=sum(not r["qualified"] for r in selected),scene_means=means,
            interpretation="Scene means include uncertain rows as descriptive data; not an adoption claim"))
    return summaries


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-packages",type=Path,action="append",default=[])
    parser.add_argument("--size",type=int,default=128)
    parser.add_argument("--cases",default="constant,hemisphere-0,hemisphere-1,hemisphere-2")
    parser.add_argument("--policies",default=",".join(e.POLICIES))
    parser.add_argument("--codecs",default=",".join(e.CODECS))
    args=parser.parse_args();e.initialize(args.python_packages)
    global np,a
    import numpy as np
    a=e.module("previous_analysis",e.ROOT/"scripts/quality-optimization/analyze.py");a.np=np
    rows=[];encoding=[]
    for case in args.cases.split(","):
        r,c=metrics(case,args.size,args.policies.split(","),args.codecs.split(","));rows.extend(r);encoding.extend(c)
    summary=summarize(rows,encoding)
    e.save(e.OUT/f"analysis-{args.size}.json",dict(metrics=rows,encoding=encoding,summary=summary,
        scope="Incremental full-chain experiment; legacy 1x1 endpoint limitation is retained",baseline=e.BASELINE))
    for r in summary:print(r["policy"],r["codec"],r["qualified_regressions"],r["scene_means"],flush=True)

if __name__=="__main__":main()

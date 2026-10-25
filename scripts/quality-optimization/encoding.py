"""Separate clipping loss and encoding loss without claiming reference convergence."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import study as s
import analyze as a


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-packages",type=Path,action="append",default=[])
    args=parser.parse_args()
    for p in reversed(args.python_packages): sys.path.insert(0,str(p.resolve()))
    import numpy as np
    s.np=np;a.np=np;s.quality=s.module("encoding_quality",s.ROOT/"scripts/source-sampling/quality.py");s.quality.np=np
    probes=s.directions();rows=[]
    for case in ["constant","pisa","footprint","qwantani"]:
        for variant in ["baseline","combined-8--1.82575-2048","combined-16--1.82575-2048"]:
            directory=s.OUT/"runs/128"/case/variant;raw=s.levels(directory)
            for encoding,limit in [("ibla",255.),("ktx2",65504.)]:
                decoded=a.decode(directory,encoding)
                clipped=[s.quality.Cubemap(np.clip(c.faces,0,limit)) for c in raw]
                count=sum(int(np.any((c.faces<0)|(c.faces>limit),axis=-1).sum()) for c in raw)
                samples=[]
                for r in [i/20 for i in range(21)]:
                    original=s.sample(raw,probes,r);bounded=s.sample(clipped,probes,r);actual=s.sample(decoded,probes,r)
                    if not np.isfinite(actual).all(): raise ValueError("Non-finite decoded output")
                    samples.append(dict(roughness=r,clipping_rmse=float(np.sqrt(np.mean((bounded-original)**2))),
                        encoding_rmse=float(np.sqrt(np.mean((actual-bounded)**2))),
                        total_rmse=float(np.sqrt(np.mean((actual-original)**2))),
                        original_rms=float(np.sqrt(np.mean(original**2)))))
                rows.append(dict(case=case,variant=variant,encoding=encoding,clipped_pixels=count,
                    total_pixels=sum(6*c.size*c.size for c in raw),samples=samples,
                    generation_sha256=s.digest(directory/"generation.json")))
    s.save(s.OUT/"encoding.json",dict(rows=rows,size=128,
        interpretation="Decode texels before interpolation. Compare decoded output to clipped raw reconstruction separately from clipping loss. RMSE components are not additive; no claim of prefilter reference convergence."))
    print("Separated clipping/encoding diagnostics written")

if __name__=="__main__":main()

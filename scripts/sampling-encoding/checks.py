"""Check factorial invariants and valid-texel BC6H error, including partial blocks."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode=True
import experiment as e


def factorial():
    rows=[]
    for size in (128,256,512):
        for case in ("hemisphere-0","hemisphere-1","hemisphere-2"):
            root=e.OUT/"raw"/str(size)/case
            metadata={name:json.loads((root/name/"metadata.json").read_text())["levels"] for name in ("quadratic","linear","sample-only","footprint-only")}
            counts=lambda name,key:[row[key] for row in metadata[name]]
            for key,left,right in [("samples","quadratic","footprint-only"),("samples","linear","sample-only"),
                ("footprint_samples","quadratic","sample-only"),("footprint_samples","linear","footprint-only")]:
                if counts(left,key)!=counts(right,key):raise AssertionError(f"Factorial count mismatch: {size} {case} {key}")
            for name,levels in metadata.items():
                if [v["size"] for v in levels]!=[size>>i for i in range(size.bit_length())]:raise AssertionError("Truncated or altered chain")
                if any(v["samples"]>1024 or v["footprint_samples"]>1024 for v in levels):raise AssertionError("Budget exceeded")
                for face in e.FACES:
                    if e.digest(root/name/f"m0_{face}.f32")!=e.digest(root/"quadratic"/f"m0_{face}.f32"):raise AssertionError("Mip zero changed")
            old=e.previous.OUT/"runs"/str(size)/case/"baseline"
            files=list(old.glob("m*_*.f32"))
            if len(files)!=6*size.bit_length():raise AssertionError("Earlier frozen control is missing float levels")
            bitwise=all(e.digest(root/"quadratic"/p.name)==e.digest(p) for p in files)
            rows.append(dict(case=case,size=size,levels=metadata,baseline_float_bytes_match_previous_study=bitwise))
    return rows


def encoding():
    rows=[]
    for source in sorted((e.OUT/"raw").glob("*/*/quadratic")):
        size=int(source.parent.parent.name);case=source.parent.name
        raw=e.previous.levels(source);chains={}
        for codec in ("basic-black","basic-edge","single-texel-edge"):
            directory=e.OUT/"encoded"/str(size)/case/source.name/codec
            if codec!="single-texel-edge":directory=e.encode(source,size,codec)
            chains[codec]=a.decode(directory,"ktx2")
        for mip,cube in enumerate(raw):
            bounded=np.clip(cube.faces,0,65504)
            if not all(np.isfinite(chain[mip].faces).all() for chain in chains.values()):raise AssertionError("Non-finite BC6H output")
            data={label:float(np.sum((chain[mip].faces-bounded)**2)) for label,chain in chains.items()}
            if cube.size%4==0 and not np.array_equal(chains["basic-black"][mip].faces,chains["basic-edge"][mip].faces):
                raise AssertionError("Aligned BC6H level changed")
            if cube.size!=1 and not np.array_equal(chains["basic-black"][mip].faces,chains["single-texel-edge"][mip].faces):
                raise AssertionError("Uniform-1x1 candidate changed a larger level")
            rows.append(dict(case=case,base=size,mip=mip,size=cube.size,pixels=6*cube.size*cube.size,
                squared_error=data,squared_reference=float(np.sum(bounded**2)),clipped_pixels=int(np.any(cube.faces!=bounded,axis=-1).sum())))
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-packages",type=Path,action="append",default=[])
    args=parser.parse_args();e.initialize(args.python_packages)
    global np,a
    import numpy as np
    a=e.module("checked_decoder",e.ROOT/"scripts/quality-optimization/analyze.py");a.np=np
    factors=factorial();encoded=encoding()
    e.save(e.OUT/"checks.json",dict(factorial=factors,encoding=encoded,method=e.digest(__file__)))
    print("Factorial controls, full chains, source budgets, mip-zero identity and unchanged non-1x1 BC6H levels passed",flush=True)

if __name__=="__main__":main()

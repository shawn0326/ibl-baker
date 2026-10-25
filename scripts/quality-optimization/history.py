"""Compare the real 0.2.3 release separately from the optimization baseline."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import zipfile

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
    import OpenEXR
    s.np=np;a.np=np;s.quality=s.module("history_quality",s.ROOT/"scripts/source-sampling/quality.py");s.quality.np=np
    root=s.OUT/"history";root.mkdir(parents=True,exist_ok=True)
    archive=s.ROOT/"target/binaries/ibl-baker-v0.2.3-windows-x64.zip"
    expected=json.loads((archive.parent/"windows-x64.json").read_text())
    if s.digest(archive)!=expected["sha256"]: raise ValueError("Release archive hash mismatch")
    binary=root/"released-0.2.3.exe"
    with zipfile.ZipFile(archive) as z:
        names=[n for n in z.namelist() if n.endswith("ibl-baker.exe")]
        if len(names)!=1: raise ValueError("Ambiguous release binary")
        binary.write_bytes(z.read(names[0]))
    if s.digest(binary)!=expected["binarySha256"]: raise ValueError("Release binary hash mismatch")
    rows=[]
    for n in (3,17):
        source=root/f"directional-{n}";source.mkdir(exist_ok=True)
        u,v=np.meshgrid((np.arange(n)+.5)/n*2-1,(np.arange(n)+.5)/n*2-1)
        for face,label in enumerate(s.FACES):
            rgb=np.ascontiguousarray(.5+.5*s.quality.face_direction(face,u,v),dtype=np.float32)
            OpenEXR.File({"compression":OpenEXR.ZIP_COMPRESSION},{"RGB":rgb}).write(str(source/f"{label}.exr"))
        probes=s.directions();expected_rgb=.5+.5*probes
        for method,exe in [("release-0.2.3",binary),("optimization-baseline",s.OUT/"baseline/ibl-baker.exe")]:
            out=root/f"{n}-{method}"
            s.run([exe,"bake",source,"--out-dir",out,"--target","specular","--size","128","--samples","1024","--output-format","ibla"],out/"run.log",dict(os.environ,RAYON_NUM_THREADS="4"))
            actual=a.decode(out,"ibla")[0].sample(probes)
            rows.append(dict(source_size=n,method=method,mip=0,binary=s.digest(exe),
                max_absolute=float(np.max(np.abs(actual-expected_rgb))),rmse=float(np.sqrt(np.mean((actual-expected_rgb)**2))),
                source_sha256={f:s.digest(source/f"{f}.exr") for f in s.FACES}))
    s.save(root/"report.json",dict(rows=rows,release=expected,
        interpretation="Decoded RGBD mip-zero resampling of a continuous direction field at fixed axes/edges/corners/uniform/local probes. Includes projection and quantization error; not an optimization gain, general radiometric proof, or full historical quality matrix."))
    print(json.dumps(rows,indent=2))

if __name__=="__main__": main()

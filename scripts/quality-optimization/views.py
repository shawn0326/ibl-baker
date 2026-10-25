"""Fixed material comparisons and an analytic rough-tail error separation."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import study as s


def tail_diagnostics():
    _, _, axes=s.inputs(); probes=s.directions(); rows=[]
    for size in (128,256,512):
        for case,axis in enumerate(axes):
            for variant in s.variants():
                directory=s.OUT/"runs"/str(size)/f"hemisphere-{case}"/variant
                chain=s.levels(directory); tail=chain[-1]; n=tail.size
                u,v=np.meshgrid((np.arange(n)+.5)/n*2-1,(np.arange(n)+.5)/n*2-1)
                normals=np.stack([s.quality.face_direction(f,u,v) for f in range(6)])
                red=(1+normals@axis)/2
                ideal=s.quality.Cubemap(np.stack([red,np.zeros_like(red),1-red],axis=-1))
                red=(1+probes@axis)/2; expected=np.stack([red,np.zeros_like(red),1-red],axis=-1)
                rows.append(dict(size=size,case=f"hemisphere-{case}",variant=variant,tail_size=n,
                    direct_texel_rmse=float(np.sqrt(np.mean((tail.faces-ideal.faces)**2))),
                    ideal_grid_rmse=float(np.sqrt(np.mean((ideal.sample(probes)-expected)**2))),
                    final_sample_rmse=float(np.sqrt(np.mean((tail.sample(probes)-expected)**2))),
                    source_record_sha256=s.digest(directory/"generation.json")))
    s.save(s.OUT/"tail-decomposition.json",dict(rows=rows,roughness=1,
        interpretation="Direct prefilter texels versus closed-form integral; ideal output-grid reconstruction; actual final sampling. These RMSE values are not additive."))


def views():
    paths,_,_=s.inputs(); q=s.quality
    mask,normals,reflected,nv=q.sphere_geometry(128)
    variants=["baseline","combined-8--1.82575-2048","combined-16--1.82575-2048"]
    roughnesses=[.05,.3,.5,.7,1.]; records=[]
    for case in ["hemisphere-1","directional","lamp-edge-1.2","pisa","footprint","qwantani"]:
        common=s.OUT/"views"/case/"common"
        command=[s.OUT/"baseline/source_sampling_export.exe",paths[case],common,"--size","128","--irradiance-size","32","--samples","1024"]
        s.run(command,common/"run.log",dict(os.environ,RAYON_NUM_THREADS="4"))
        diffuse=q.Cubemap([np.fromfile(common/f"irradiance_{f}.f32",dtype="<f4").reshape(32,32,3) for f in s.FACES]).sample(normals)
        lut=np.asarray(Image.open(common/"brdf-lut.png").convert("RGB"),dtype=float)/255
        chains={v:s.levels(s.OUT/"runs/128"/case/v) for v in variants}
        luma=s.sample(chains["baseline"],s.directions(),1.)@np.array([.2126,.7152,.0722])
        exposure=float(.18/max(np.exp(np.mean(np.log(np.maximum(luma,1e-6)))),1e-6))
        for material in ("reflection","metal","dielectric"):
            sheet=Image.new("RGB",(170+5*136,66+3*156),(18,21,27)); draw=ImageDraw.Draw(sheet)
            draw.text((8,8),f"{case} / {material} / fixed exposure {exposure:.6g}",fill="white")
            draw.text((8,26),"Rejected candidates: visual diagnostic, not a physical-reference renderer",fill="white")
            for col,r in enumerate(roughnesses):
                draw.text((170+col*136,48),f"r={r:g}",fill="white")
                sampled_lut=q.sample_lut(lut,nv,r)
                for row,variant in enumerate(variants):
                    image=q.shade(s.sample(chains[variant],reflected,r),diffuse,sampled_lut,nv,material)
                    tile=np.full((*mask.shape,3),[18,21,27],dtype=np.uint8)
                    tile[mask]=np.round(q.tonemap(image,exposure)*255).astype(np.uint8)
                    sheet.paste(Image.fromarray(tile),(170+col*136,66+row*156))
                    draw.text((8,110+row*156),["baseline / tail 1","candidate / tail 8","candidate / tail 16"][row],fill="white")
                    np.save(common.parent/f"{material}-{variant}-{r:g}.npy",image)
            sheet.save(common.parent/f"{material}.png")
        records.append(dict(case=case,exposure=exposure,common_command=list(map(str,command)),
            common_exporter=s.digest(command[0]),lut=s.digest(common/"brdf-lut.png"),
            generations={v:json.loads((s.OUT/"runs/128"/case/v/"generation.json").read_text()) for v in variants},
            levels={v:json.loads((s.OUT/"runs/128"/case/v/"metadata.json").read_text())["levels"] for v in variants}))
        print("rendered",case,flush=True)
    s.save(s.OUT/"views/metadata.json",dict(cases=records,roughnesses=roughnesses,
        camera="128-pixel orthographic sphere, yaw 35 degrees",material="Shared baseline production LUT and irradiance, no direct lighting; gold metal F0=(.95,.64,.54), dielectric F0=.04/albedo=.6",
        interpretation="Fixed split-sum material diagnostic; independent prefilter reference is reported separately"))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-packages",type=Path,action="append",default=[])
    args=parser.parse_args()
    for path in reversed(args.python_packages): sys.path.insert(0,str(path.resolve()))
    global np,Image,ImageDraw
    import numpy as np
    import OpenEXR
    from PIL import Image,ImageDraw
    s.np=np;s.OpenEXR=OpenEXR;s.quality=s.module("quality_views",s.ROOT/"scripts/source-sampling/quality.py");s.quality.np=np
    tail_diagnostics();views()

if __name__=="__main__": main()

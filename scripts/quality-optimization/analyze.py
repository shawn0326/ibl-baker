"""Independent reference, output reconstruction and encoding diagnostics for study.py."""
from __future__ import annotations
import argparse
import io
import json
import math
from pathlib import Path
import struct
import sys
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import study as s


def decode(directory, kind):
    from PIL import Image
    if kind == "ibla":
        data = (directory / "specular.ibla").read_bytes()
        manifest_len, table_len = struct.unpack_from("<II", data, 8)
        meta = json.loads(data[16:16+manifest_len])
        offset = 16 + manifest_len + table_len
        result = []
        for mip in range(meta["mipCount"]):
            faces = []
            for face in range(6):
                length = struct.unpack_from("<Q", data, 16+manifest_len+8*(mip*6+face))[0]
                pixels = np.asarray(Image.open(io.BytesIO(data[offset:offset+length])), dtype=float)/255
                offset += length
                rgb = pixels[..., :3]
                if meta["encoding"] != "linear": rgb = np.where(rgb <= .04045, rgb/12.92, ((rgb+.055)/1.055)**2.4)
                if meta["encoding"] == "rgbd-srgb": rgb = rgb/np.maximum(pixels[..., 3:4], 1/255)
                faces.append(rgb)
            result.append(s.quality.Cubemap(faces))
        if offset != len(data): raise ValueError("IBLA payload was not consumed exactly")
        return result
    import imagecodecs
    import zstandard
    data = (directory / "specular.ktx2").read_bytes()
    width = struct.unpack_from("<I", data, 20)[0]
    count = struct.unpack_from("<I", data, 40)[0]
    result = []
    for mip in range(count):
        offset, length, raw_length = struct.unpack_from("<QQQ", data, 80+24*mip)
        raw = zstandard.ZstdDecompressor().decompress(data[offset:offset+length], max_output_size=raw_length)
        n = max(1, width >> mip); padded = ((n+3)//4)*4; face_bytes = padded*padded
        if len(raw) != 6*face_bytes: raise ValueError("Unexpected BC6H face stride")
        faces = [imagecodecs.bcn_decode(raw[i*face_bytes:(i+1)*face_bytes], 6, shape=(padded,padded,3))[:n,:n,:].astype(float) for i in range(6)]
        result.append(s.quality.Cubemap(faces))
    return result


def hemisphere_reference(probes, axis, r, order):
    # Integrate the exact azimuthal coverage of a half sphere. Splitting at
    # mu=sqrt(1-dot(axis,n)^2) resolves its endpoint independently of any cubemap.
    if r == 0: return np.where((probes @ axis > 0)[:,None], [1.,0,0], [0.,0,1.])
    if r == 1:
        blue = (1-probes@axis)/2
        return np.stack([1-blue, np.zeros_like(blue), blue], axis=-1)
    x, w = np.polynomial.legendre.leggauss(order)
    values = []
    for n in probes:
        t = np.clip(n@axis, -1, 1); boundary = np.sqrt(max(0., 1-t*t))
        numerator = denominator = 0.
        for low, high in [(0., boundary), (boundary, 1.)]:
            if high-low < 1e-12: continue
            mu = low+(x+1)*(high-low)/2; weight = w*(high-low)/2
            a2 = r**4; ndoth2 = (1+mu)/2
            kernel = mu*a2/(1+(a2-1)*ndoth2)**2
            q = -t*mu/np.maximum(np.sqrt(max(0.,1-t*t))*np.sqrt(1-mu*mu),1e-30)
            red = np.arccos(np.clip(q,-1,1))/np.pi
            numerator += np.sum(weight*kernel*red); denominator += np.sum(weight*kernel)
        red = numerator/denominator
        values.append([red,0.,1-red])
    return np.asarray(values)


def reference(name, size, probes, roughnesses, analytic, axes, baseline):
    identity = dict(name=name, size=size, probes=probes.tolist(), roughnesses=roughnesses,
                    algorithm=s.digest(__file__), source=s.digest(baseline / "generation.json"),
                    reference_module=s.digest(s.ROOT / "scripts/mip-weighting/reference.py"))
    cache = s.OUT / "reference" / str(size) / f"{name}.json"
    if cache.exists():
        result = json.loads(cache.read_text())
        if result["identity"] == identity: return result
    ref = s.module("independent_reference", s.ROOT / "scripts/mip-weighting/reference.py")
    cube = s.levels(baseline)[0]
    evaluate = analytic.get(name, cube.sample)
    rows = []
    hdr_support = ref.select_highlight_support(cube.faces)["regions"] if name not in analytic else None
    for r in roughnesses:
        if name.startswith("hemisphere-"):
            axis = axes[int(name[-1])]
            ladder = [hemisphere_reference(probes,axis,r,order) for order in [128,256,512]]
            spread = np.maximum(np.max(np.abs(ladder[2]-ladder[1]),axis=-1),np.max(np.abs(ladder[1]-ladder[0]),axis=-1))
            values = ladder[-1]; converged = spread <= 1e-4
        elif r == 0:
            values = evaluate(probes); spread = np.zeros(len(probes)); converged = np.ones(len(probes),dtype=bool)
        elif name == "constant":
            values = evaluate(probes); spread = np.zeros(len(probes)); converged = np.ones(len(probes),dtype=bool)
        else:
            values, spread, converged = [], [], []
            diagnostics = []
            for n in probes:
                result = ref.evaluate_reference(evaluate, n, r,
                    source_faces=cube.faces if name not in analytic else None,
                    support_regions=hdr_support,
                    label="continuous_analytic" if name in analytic else "shared_mip0", seconds=10.)
                values.append(result["rgb"] or [0.,0.,0.])
                traces = result["levels"]
                error = max([np.max(np.abs(np.asarray(traces[i]["rgb"])-traces[i-1]["rgb"])) for i in range(max(1,len(traces)-2),len(traces))] or [1e30])
                if traces:
                    error = max(error,np.max(np.abs(np.asarray(traces[-1]["phases"][0]["rgb"])-traces[-1]["phases"][1]["rgb"])))
                local = None
                if name not in analytic:
                    local = ref.crosscheck_highlight_support(cube.faces,evaluate,n,r,result,seconds=10.)
                    error = max(error, max(local.get("observed_low_high_error_rgb", [0.])))
                spread.append(float(error))
                converged.append(result["status"] == "converged_diagnostic" and
                    (local is None or local["status"] == "consistent_local_diagnostic"))
                diagnostics.append(dict(primary=result,local=local))
            values, spread, converged = np.asarray(values), np.asarray(spread), np.asarray(converged)
            s.save(s.OUT / "reference" / str(size) / name / f"{r:.9f}.json", diagnostics)
        rows.append(dict(roughness=r,rgb=values.tolist(),spread=spread.tolist(),converged=converged.tolist()))
        print(f"reference {size} {name} r={r:g}: {int(np.sum(converged))}/{len(probes)}",flush=True)
    result = dict(identity=identity, rows=rows,
                  local_hdr_crosscheck_complete=True,
                  target="continuous_analytic" if name in analytic else "shared_mip0",
                  limitation="Bounded diagnostics, not strict error bounds; unresolved primary or local checks remain unqualified")
    s.save(cache,result)
    return result


def analyze(size, names, variant_names, endpoints_only=False):
    paths, analytic, axes = s.inputs(); probes=s.directions(); variants=s.variants()
    chosen = ["baseline", *(variant_names or [v for v in variants if v != "baseline"])]
    metrics=[]
    for name in names:
        available=[v for v in chosen if (s.OUT / "runs" / str(size) / name / v / "metadata.json").exists()]
        if available != chosen: raise ValueError(f"Missing generation for {name}: {set(chosen)-set(available)}")
        base=s.OUT / "runs" / str(size) / name / "baseline"
        roughnesses={i/20 for i in range(21)}
        for v in available:
            chain=s.levels(base.parent/v)
            roughnesses.update((i+.5)/(len(chain)-1) for i in range(len(chain)-1))
        roughnesses=[1.] if endpoints_only else sorted(roughnesses)
        references=reference(name,size,probes,roughnesses,analytic,axes,base)
        for variant in available:
            directory=base.parent/variant
            chains={"float":s.levels(directory),"ibla":decode(directory,"ibla"),"ktx2":decode(directory,"ktx2")}
            raw=chains["float"]
            clipped={kind:sum(int(np.any((c.faces<0)|(c.faces>limit),axis=-1).sum()) for c in raw)
                     for kind,limit in [("ibla",255), ("ktx2",65504)]}
            for record in references["rows"]:
                r=record["roughness"]; expected=np.asarray(record["rgb"])
                # Fixed groups are never silently replaced with only converged probes.
                bright=np.argsort(np.max(expected,axis=-1))[-max(1,math.ceil(.05*len(probes))):]
                for group,index in [("all",np.arange(len(probes))),("uniform",np.arange(32)),("edges-corners",np.arange(32,58)),("lamp-local",np.arange(58,len(probes))),("bright",bright)]:
                    scale=max(float(np.sqrt(np.mean(expected[index]**2))),1e-6)
                    for encoding,chain in chains.items():
                        actual=s.sample(chain,probes,r)
                        error=actual[index]-expected[index]
                        metrics.append(dict(case=name,size=size,variant=variant,roughness=r,group=group,encoding=encoding,
                            relative_rmse=float(np.sqrt(np.mean(error**2))/scale),max_absolute=float(np.max(np.abs(error))),
                            reference_envelope=float(np.sqrt(np.mean(np.asarray(record["spread"])[index]**2))/scale),
                            qualified=bool(np.all(np.asarray(record["converged"])[index])) and references["local_hdr_crosscheck_complete"],
                            clipped_pixels=clipped.get(encoding,0),
                            encoding_rmse=float(np.sqrt(np.mean((actual[index]-s.sample(raw,probes,r)[index])**2)))))
        report=dict(metrics=metrics,adoption=False,scope="endpoint" if endpoints_only else "full roughness grid",
                    cases=names,size=size,variants=chosen,probes=probes.tolist(),
                    required_for_adoption="All sizes/cases, converged HDR local checks, performance and visual review")
        s.save(s.OUT / f"analysis-{size}-{'endpoint' if endpoints_only else 'grid'}.json",report)
        print(f"analyzed {size} {name}",flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-packages",type=Path,action="append",default=[])
    parser.add_argument("--size",type=int,default=128)
    parser.add_argument("--cases",default="hemisphere-0,hemisphere-1,hemisphere-2")
    parser.add_argument("--variants")
    parser.add_argument("--endpoints-only",action="store_true")
    args=parser.parse_args()
    for p in reversed(args.python_packages): sys.path.insert(0,str(p.resolve()))
    global np
    import numpy as np
    import OpenEXR
    s.np=np; s.OpenEXR=OpenEXR; s.quality=s.module("quality_common",s.ROOT/"scripts/source-sampling/quality.py");s.quality.np=np
    analyze(args.size,args.cases.split(","),args.variants.split(",") if args.variants else None,args.endpoints_only)

if __name__ == "__main__": main()

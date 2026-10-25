"""Collect compact numerical evidence; retain full arrays and process logs locally."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode=True
import experiment as e


def collect():
    paths=sorted(e.OUT.glob("analysis-*-analytic*.json"))+sorted(e.OUT.glob("analysis-*-hdr*.json"))
    merged={};encodings={}
    for path in paths:
        data=json.loads(path.read_text())
        for row in data["metrics"]:
            key=tuple(row[k] for k in ("case","size","policy","codec","roughness","group"));merged[key]=row
        for row in data["encoding"]:encodings[(row["case"],row["size"],row["policy"],row["codec"])]=row
    rows=list(merged.values());encoding=list(encodings.values())
    summaries=a.summarize(rows,encoding)
    accepted=next(r for r in summaries if r["policy"]=="quadratic" and r["codec"]=="single-texel-edge")
    if accepted["qualified_regressions"]:raise AssertionError("Accepted encoder has a confirmed subgroup regression")
    for row in rows:
        if row["policy"]!="quadratic" or row["codec"]!="single-texel-edge":continue
        last=row["size"].bit_length()-1
        if row["roughness"]>(last-1)/max(1,last) and not row["qualified"]:
            raise AssertionError("Reference remains uncertain where the adopted encoder can change a query")
    references={}
    for case in ("pisa","footprint","qwantani"):
        path=e.OUT/"reference/128"/f"{case}.json";data=json.loads(path.read_text())
        if not all(all(r["converged"]) for r in data["rows"]):raise AssertionError("HDR reference remains uncertain")
        reference_rows=[]
        for row in data["rows"]:
            scale=max(float(a.np.sqrt(a.np.mean(a.np.asarray(row["rgb"])**2))),1e-6)
            reference_rows.append(dict(roughness=row["roughness"],directions=len(row["converged"]),qualified=sum(row["converged"]),
                relative_rms_envelope=float(a.np.sqrt(a.np.mean(a.np.asarray(row["spread"])**2)))/scale,
                max_normalizer_error=max(row["normalizer_error"])))
        repairs=[{k:r[k] for k in ("roughness","indices","orders","method")} for r in data.get("repairs",[])]
        references[case]=dict(sha256=e.digest(path),identity=data["identity"],rows=reference_rows,repairs=repairs,
            extension_sha256=[hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest() for r in data.get("extensions",[])],
            trace="Original uncertainties, RGB arrays and all refinement levels are retained in the hashed local reference file")
    checks=json.loads((e.OUT/"checks.json").read_text())
    if not all(r["baseline_float_bytes_match_previous_study"] for r in checks["factorial"]):raise AssertionError("Frozen float control changed")
    import zstandard
    production_checks=[]
    for size in (1,3,31,128,255):
        paths=[e.OUT/"compatibility"/f"{size}-None/edge/specular.ktx2",
            e.OUT/"encoded"/str(size)/"pisa/quadratic/single-texel-edge/specular.ktx2"]
        documents=[p.read_bytes() for p in paths]
        count=struct.unpack_from("<I",documents[0],40)[0]
        for mip in range(count):
            blocks=[]
            for data in documents:
                offset,length,uncompressed=struct.unpack_from("<QQQ",data,80+24*mip)
                blocks.append(zstandard.ZstdDecompressor().decompress(data[offset:offset+length],max_output_size=uncompressed))
            if blocks[0]!=blocks[1]:raise AssertionError("Production differs from the quality-tested BC6H control")
        production_checks.append(dict(size=size,all_level_blocks_match_private_control=True,sha256=[e.digest(p) for p in paths]))
    result=dict(baseline=e.BASELINE,adopted="Quadratic sampling, original coupled footprint, basic BC6H with uniform 1x1 input blocks only",
        analysis_files={p.name:e.digest(p) for p in paths},summaries=summaries,references=references,checks=checks,
        compatibility=json.loads((e.OUT/"compatibility.json").read_text()),
        production_control_checks=production_checks,
        preparation=json.loads((e.OUT/"preparation.json").read_text()),
        timing_preparation=json.loads((e.OUT/"timing-preparation.json").read_text()),
        rejected_full_edge_benchmark_sha256=e.digest(e.OUT/"all-edge-benchmark.json"),
        generation_records={str(p.relative_to(e.OUT)):e.digest(p) for p in sorted((e.OUT/"raw").glob("*/*/*/generation.json"))},
        tool_hashes={p.name:e.digest(p) for p in Path(__file__).parent.iterdir() if p.is_file()},
        limitations=["Legacy 1x1 rough-end resolution remains", "Linear candidates remain rejected on quality", "Converged HDR reference is scoped to 128", "No new Linux/macOS CI results"])
    if (e.OUT/"plot-generation.json").exists():result["figure"]=json.loads((e.OUT/"plot-generation.json").read_text())
    for filename in ("benchmark.json","linear-benchmark.json"):
        path=e.OUT/filename
        if not path.exists():raise ValueError(f"Missing completed benchmark: {filename}")
        data=json.loads(path.read_text());compact=[]
        expected=27 if filename=="benchmark.json" else 9
        if len(data["rows"])!=expected:raise ValueError(f"Incomplete benchmark: {filename}")
        if filename=="benchmark.json" and any(c["gate"]!="pass" for row in data["rows"] for c in row["comparisons"].values()):
            raise AssertionError("Production performance gate remains failed or uncertain")
        for row in data["rows"]:
            record={k:row[k] for k in ("case","size","format")}
            for key in ("comparisons","ratio","medians","interval","gate","output_bytes"):
                if key in row:record[key]=row[key]
            record["samples"]={profile:dict(seconds=[r["seconds"] for r in runs],peak_commit_bytes=[r["peak_commit_bytes"] for r in runs]) for profile,runs in row["runs"].items()}
            compact.append(record)
        result[filename.removesuffix(".json")]=dict(sha256=e.digest(path),binaries=data["binaries"],rows=compact,
            threads=data["threads"],warmups=data["warmups"],rounds=data["rounds"],machine=data["machine"])
    linear_ibla=[e.OUT/"linear-benchmark/qwantani-128-both/linear/specular.ibla",e.OUT/"raw/128/qwantani/linear/specular.ibla"]
    if e.digest(linear_ibla[0])!=e.digest(linear_ibla[1]):raise AssertionError("Static linear candidate differs from the quality-tested sample policy")
    result["static_linear_control"]=dict(ibla_bytes_match_private_control=True,sha256=e.digest(linear_ibla[0]))
    e.save(e.OUT/"evidence.json",result)
    print("Evidence rows",len(rows),"HDR queries",sum(r["directions"] for d in references.values() for r in d["rows"]))
    for row in summaries:
        if row["policy"] in ("quadratic","linear","sample-only","footprint-only","linear-footprint-25") and row["codec"] in ("float","ibla","basic-edge","single-texel-edge","portfolio-edge"):
            print(row["policy"],row["codec"],row["qualified_regressions"])


def plot():
    os.environ.setdefault("MPLCONFIGDIR",str(e.OUT/"matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    data=json.loads((e.OUT/"analysis-128-hdr.json").read_text())["metrics"]
    checks=json.loads((e.OUT/"checks.json").read_text())["encoding"]
    fig,axes=plt.subplots(1,2,figsize=(11,4.2),layout="constrained")
    for policy,label in [("quadratic","Baseline"),("linear","Linear / coupled"),("linear-footprint-25","Linear / 25% count blend")]:
        selected=sorted([r for r in data if r["case"]=="qwantani" and r["policy"]==policy and r["codec"]=="float" and r["group"]=="bright"],key=lambda r:r["roughness"])
        axes[0].plot([r["roughness"] for r in selected],[100*r["relative_rmse"] for r in selected],"o-",label=label)
    axes[0].set(xlabel="Perceptual roughness",ylabel="Relative RMSE (%)",yscale="log",title="Strong sun: raw float bright probes")
    axes[0].legend(fontsize=8);axes[0].grid(alpha=.25)
    for index,case in enumerate(("pisa","footprint","qwantani")):
        selected=[r for r in checks if r["case"]==case and r["base"]==128 and r["size"]==1]
        pixels=sum(r["pixels"] for r in selected)
        for j,(codec,color) in enumerate((("basic-black","#a44a3f"),("single-texel-edge","#287271"))):
            rmse=(sum(r["squared_error"][codec] for r in selected)/(3*pixels))**.5
            axes[1].bar(index+(j-.5)*.34,rmse,width=.34,color=color,label=("Black padding" if j==0 else "Uniform block") if index==0 else None)
    axes[1].set(xticks=range(3),xticklabels=["Pisa","Footprint","Qwantani"],ylabel="Stored-texel linear RGB RMSE",title="Same float input: 1x1 BC6H tail")
    axes[1].legend(fontsize=8);axes[1].grid(axis="y",alpha=.25)
    fig.suptitle("Full mip chains retained; convolution reference and encoding loss measured separately",fontsize=11)
    fig.savefig(e.OUT/"sampling-encoding.png",dpi=160)
    plt.close(fig)
    e.save(e.OUT/"plot-generation.json",dict(method=e.digest(__file__),sha256=e.digest(e.OUT/"sampling-encoding.png"),
        matplotlib=matplotlib.__version__,python=sys.version,inputs={name:e.digest(e.OUT/name) for name in ("analysis-128-hdr.json","checks.json")}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-packages",type=Path,action="append",default=[])
    parser.add_argument("--plot",action="store_true")
    parser.add_argument("--plot-only",action="store_true",help="Render completed JSON using an interpreter with matplotlib; skip numeric collection")
    args=parser.parse_args()
    if args.plot_only:plot();return
    e.initialize(args.python_packages)
    global a
    import numpy as np
    a=e.module("evidence_analysis",Path(__file__).with_name("analyze.py"));a.np=np
    collect()
    if args.plot:plot()

if __name__=="__main__":main()

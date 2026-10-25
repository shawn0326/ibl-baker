"""Production compatibility and paired timing against the shared-bake baseline."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import statistics
import struct
import sys

sys.dont_write_bytecode=True
import experiment as e


def binaries():
    return dict(baseline=e.OUT/"baseline/ibl-baker.exe",edge=e.ROOT/"target/release/ibl-baker.exe",
        linear=e.OUT/"build/release/ibl-baker.exe")


def command(binary,source,output,size,fmt,minimum=None):
    result=[str(binary),"bake",str(source),"--out-dir",str(output),"--size",str(size),
        "--samples","1024","--quality","medium","--output-format",fmt]
    if minimum is not None:result.extend(["--specular-min-size",str(minimum)])
    return result


def compatibility():
    old=e.module("actual_parsers",e.ROOT/"scripts/quality-optimization/acceptance.py")
    source=e.ROOT/"fixtures/inputs/pisa.hdr";records=[]
    for size,minimum in [(1,None),(3,None),(5,None),(31,None),(128,None),(255,None),(128,8),(255,16)]:
        root=e.OUT/"compatibility"/f"{size}-{minimum}"
        for profile in ("baseline","edge"):
            output=root/profile
            e.run(command(binaries()[profile],source,output,size,"both",minimum),output/"run.log",dict(os.environ,RAYON_NUM_THREADS="4"))
        for name in ("specular.ibla","irradiance.ibla","brdf-lut.png"):
            if e.digest(root/"baseline"/name)!=e.digest(root/"edge"/name):raise AssertionError(f"Unexpected floating bake change: {size} {name}")
        parsed=old.parsers(root/"edge")
        baseline=(root/"baseline/specular.ktx2").read_bytes();candidate=(root/"edge/specular.ktx2").read_bytes()
        count=struct.unpack_from("<I",baseline,40)[0]
        for mip in range(count):
            if max(1,size>>mip)==1:continue
            payloads=[]
            for data in (baseline,candidate):
                offset,length,_=struct.unpack_from("<QQQ",data,80+24*mip);payloads.append(data[offset:offset+length])
            if payloads[0]!=payloads[1]:raise AssertionError("Production BC6H changed a non-1x1 level")
        records.append(dict(size=size,minimum=minimum,parsers=parsed,ibla_lut_byte_identical=True,
            non_single_texel_payloads_byte_identical=True,
            baseline_ktx2=e.digest(root/"baseline/specular.ktx2"),candidate_ktx2=e.digest(root/"edge/specular.ktx2")))
    if records[-2]["baseline_ktx2"]!=records[-2]["candidate_ktx2"]:raise AssertionError("Block-aligned truncated output changed")
    e.save(e.OUT/"compatibility.json",dict(records=records,binaries={k:e.digest(v) for k,v in binaries().items()}))
    print("IBLA/LUT byte parity, complete/truncated/NPOT parser checks passed",flush=True)


def benchmark(sizes,rounds):
    process=e.module("paired_process",e.ROOT/"scripts/source-sampling/benchmark.py")
    paths={"pisa":e.ROOT/"fixtures/inputs/pisa.hdr","footprint":e.ROOT/"fixtures/inputs/footprint_court.hdr",
        "qwantani":e.ROOT/"target/ibl-comparison/inputs/qwantani_noon_puresky_1k.hdr"}
    bins={k:v for k,v in binaries().items() if k!="linear"};identities={k:e.digest(v) for k,v in bins.items()};results=[]
    machine=process.machine_metadata()
    # Both production binaries have no experiment switches.
    for name in ("IBL_SAMPLE_LINEAR","IBL_FOOTPRINT_LINEAR","IBL_CODEC","IBL_CODEC_EDGE"):os.environ.pop(name,None)
    for size in sizes:
        for case,source in paths.items():
            for fmt in ("ibla","ktx2","both"):
                names=["baseline","edge"]
                root=e.OUT/"benchmark"/f"{case}-{size}-{fmt}";root.mkdir(parents=True,exist_ok=True)
                runs={name:[] for name in names}
                for iteration in range(-2,rounds):
                    for name in (names if iteration%2==0 else names[::-1]):
                        record=process.run_process(command(bins[name],source,root/name,size,fmt),root/f"{iteration}-{name}.log",e.ROOT,4)
                        if iteration>=0:runs[name].append(record)
                comparisons={}
                for name in names[1:]:
                    noise=process.summarize_runs(dict(baseline=runs["baseline"],candidate=runs[name]),rounds)
                    interval=noise["paired_median_ratio_bootstrap_95pct"]["seconds"]
                    ratio=noise["ratios"]["seconds"]
                    comparisons[name]=dict(ratio=ratio,medians=noise["medians"],interval=interval,
                        gate="needs_15_rounds" if interval[0]<=2.<interval[1] and rounds<15 else "uncertain" if interval[0]<=2.<interval[1] else "pass" if ratio<=2 else "fail")
                rows=dict(case=case,size=size,format=fmt,runs=runs,comparisons=comparisons,
                    input_sha256=e.digest(source),output_bytes={name:sum(p.stat().st_size for p in (root/name).iterdir() if p.suffix in (".ibla",".ktx2",".png")) for name in names})
                results.append(rows)
                e.save(e.OUT/"benchmark.json",dict(baseline=e.BASELINE,binaries=identities,machine=machine,threads=4,warmups=2,rounds=rounds,
                    targets="all",quality="medium",samples=1024,rows=results,
                    scope="Production uniform-1x1 candidate: 27 cells."))
                print(case,size,fmt," ".join(f"{name}={value['ratio']:.3f}x" for name,value in comparisons.items()),flush=True)
    if identities!={k:e.digest(v) for k,v in bins.items()}:raise ValueError("Binaries changed during benchmark")


def linear_benchmark(sizes,rounds):
    process=e.module("static_linear_process",e.ROOT/"scripts/source-sampling/benchmark.py")
    source=e.ROOT/"target/ibl-comparison/inputs/qwantani_noon_puresky_1k.hdr"
    bins=dict(baseline=binaries()["baseline"],linear=e.OUT/"timing-build/release/ibl-baker.exe")
    identities={k:e.digest(v) for k,v in bins.items()};rows=[]
    for name in ("IBL_SAMPLE_LINEAR","IBL_FOOTPRINT_LINEAR","IBL_CODEC","IBL_CODEC_EDGE"):os.environ.pop(name,None)
    machine=process.machine_metadata()
    for size in sizes:
        for fmt in ("ibla","ktx2","both"):
            root=e.OUT/"linear-benchmark"/f"qwantani-{size}-{fmt}";root.mkdir(parents=True,exist_ok=True)
            runs={name:[] for name in bins}
            for iteration in range(-2,rounds):
                order=list(bins) if iteration%2==0 else list(bins)[::-1]
                for name in order:
                    record=process.run_process(command(bins[name],source,root/name,size,fmt),root/f"{iteration}-{name}.log",e.ROOT,4)
                    if iteration>=0:runs[name].append(record)
            noise=process.summarize_runs(dict(baseline=runs["baseline"],candidate=runs["linear"]),rounds)
            interval=noise["paired_median_ratio_bootstrap_95pct"]["seconds"];ratio=noise["ratios"]["seconds"]
            rows.append(dict(case="qwantani",size=size,format=fmt,runs=runs,ratio=ratio,medians=noise["medians"],interval=interval,
                output_bytes={name:sum(p.stat().st_size for p in (root/name).iterdir() if p.suffix in (".ibla",".ktx2",".png")) for name in bins},
                gate="needs_15_rounds" if interval[0]<=2.<interval[1] and rounds<15 else "uncertain" if interval[0]<=2.<interval[1] else "pass" if ratio<=2 else "fail"))
            e.save(e.OUT/"linear-benchmark.json",dict(binaries=identities,machine=machine,warmups=2,rounds=rounds,threads=4,
                input_sha256=e.digest(source),quality="medium",samples=1024,targets="all",rows=rows,
                scope="Static coupled-linear implementation without experiment hooks; diagnostic timing of a rejected quality candidate"))
            print("static linear",size,fmt,f"{ratio:.3f}x",flush=True)
    if identities!={k:e.digest(v) for k,v in bins.items()}:raise ValueError("Binaries changed during benchmark")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["compatibility","benchmark","linear-benchmark"])
    parser.add_argument("--sizes",default="128,256,512")
    parser.add_argument("--rounds",type=int,choices=[7,15],default=7)
    args=parser.parse_args()
    if args.command=="compatibility":compatibility()
    elif args.command=="linear-benchmark":linear_benchmark(list(map(int,args.sizes.split(","))),args.rounds)
    else:benchmark(list(map(int,args.sizes.split(","))),args.rounds)

if __name__=="__main__":main()

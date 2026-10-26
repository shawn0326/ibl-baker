"""Production CLI parity, real parser checks, and paired process benchmarks."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import study as s


def command(binary, source, output, size, fmt, minimum=None, all_targets=False):
    args=[str(binary),"bake",str(source),"--out-dir",str(output),"--size",str(size),
          "--samples","1024","--quality","medium","--output-format",fmt]
    if not all_targets: args += ["--target","specular"]
    if minimum is not None: args += ["--specular-min-size",str(minimum)]
    return args


def parsers(directory):
    # Use the actual public parser implementations; tsx is not required because
    # the repository's Node version supports stripped TypeScript.
    code='''import fs from 'node:fs';
import {parseIBLA} from './packages/ibla-loader/src/index.ts';
import {parseKTX2IBL} from './packages/ktx2-loader/src/index.ts';
const dir=process.argv[1];
const a=parseIBLA(fs.readFileSync(dir+'/specular.ibla'));
const b=parseKTX2IBL(fs.readFileSync(dir+'/specular.ktx2'));
if(a.manifest.mipCount!==b.header.levelCount) throw Error('Mismatched mip counts');
if(a.manifest.width!==b.header.pixelWidth) throw Error('Mismatched width');
console.log(JSON.stringify({width:a.manifest.width,levels:a.manifest.mipCount}));
'''
    return json.loads(subprocess.check_output(["node","--input-type=module","-e",code,str(directory)],cwd=s.ROOT,text=True))


def parity():
    binaries={"baseline":s.OUT/"baseline/ibl-baker.exe","candidate":s.ROOT/"target/release/ibl-baker.exe"}
    source=s.ROOT/"fixtures/inputs/pisa.hdr"
    rows=[]
    for size in [1,3,31,128]:
        for fmt in ["ibla","ktx2","both"]:
            for name,binary in binaries.items():
                output=s.OUT/"parity"/str(size)/fmt/name
                s.run(command(binary,source,output,size,fmt),output/"run.log",dict(os.environ,RAYON_NUM_THREADS="4"))
            base=s.OUT/"parity"/str(size)/fmt/"baseline"
            candidate=base.parent/"candidate"
            for extension in (["ibla","ktx2"] if fmt=="both" else [fmt]):
                file=f"specular.{extension}"
                if s.digest(base/file)!=s.digest(candidate/file): raise AssertionError(f"Changed default output: {size} {fmt} {file}")
            rows.append(dict(size=size,format=fmt,byte_identical=True))
    for size,minimum in [(1,1),(3,1),(31,8),(128,8),(128,16),(255,16)]:
        output=s.OUT/"parity"/f"truncated-{size}-{minimum}"
        s.run(command(binaries["candidate"],source,output,size,"both",minimum),output/"run.log",dict(os.environ,RAYON_NUM_THREADS="4"))
        rows.append(dict(size=size,minimum=minimum,parsers=parsers(output)))
    s.save(s.OUT/"parity.json",dict(rows=rows,binaries={k:s.digest(v) for k,v in binaries.items()}))
    print("Production parity and real parser checks passed",flush=True)


def benchmark(sizes,rounds):
    bench=s.module("process_benchmark",s.ROOT/"scripts/source-sampling/benchmark.py")
    binaries={"baseline":s.OUT/"baseline/ibl-baker.exe","candidate":s.ROOT/"target/release/ibl-baker.exe"}
    inputs={"pisa":s.ROOT/"fixtures/inputs/pisa.hdr","footprint":s.ROOT/"fixtures/inputs/footprint_court.hdr",
            "qwantani":s.ROOT/"target/ibl-comparison/inputs/qwantani_noon_puresky_1k.hdr"}
    identities={k:s.digest(v) for k,v in binaries.items()}; results=[]
    for size in sizes:
        for case,source in inputs.items():
            for fmt in ["ibla","ktx2","both"]:
                root=s.OUT/"benchmark"/f"{case}-{size}-{fmt}"
                root.mkdir(parents=True,exist_ok=True)
                runs={name:[] for name in binaries}
                for iteration in range(-2,rounds):
                    order=list(binaries) if iteration%2==0 else list(reversed(binaries))
                    for name in order:
                        record=bench.run_process(command(binaries[name],source,root/name,size,fmt,all_targets=True),root/f"{iteration}-{name}.log",s.ROOT,4)
                        if iteration>=0: runs[name].append(record)
                medians={name:statistics.median(r["seconds"] for r in values) for name,values in runs.items()}
                diagnostics=bench.summarize_runs(runs,rounds)
                # Reuse only the noise estimator, not the older study's 1.05x gate.
                interval=diagnostics["paired_median_ratio_bootstrap_95pct"]["seconds"]
                diagnostics={key:diagnostics[key] for key in ["medians","ratios","paired_time_ratio_range","paired_median_ratio_bootstrap_95pct","noise_diagnostic"]}
                row=dict(case=case,size=size,format=fmt,runs=runs,medians=medians,
                         ratio=medians["candidate"]/medians["baseline"],noise=diagnostics,
                         time_limit=2.,time_gate="needs_15_rounds" if interval[0]<=2.<interval[1] and rounds<15 else "uncertain" if interval[0]<=2.<interval[1] else "pass" if medians["candidate"]<=2*medians["baseline"] else "fail",
                         input_sha256=s.digest(source),output_bytes={name:sum(p.stat().st_size for p in (root/name).iterdir() if p.suffix in (".ibla",".ktx2",".png")) for name in runs})
                results.append(row)
                s.save(s.OUT/"benchmark.json",dict(binaries=identities,machine=bench.machine_metadata(),rounds=rounds,warmups=2,threads=4,targets="all",quality="medium",samples=1024,rows=results))
                print(f"{case} {size} {fmt}: {row['ratio']:.3f}x",flush=True)
    if identities!={k:s.digest(v) for k,v in binaries.items()}: raise ValueError("Binaries changed during benchmark")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["parity","benchmark"])
    parser.add_argument("--sizes",default="128,256,512")
    parser.add_argument("--rounds",type=int,choices=[7,15],default=7)
    args=parser.parse_args()
    if args.command=="parity": parity()
    else: benchmark(list(map(int,args.sizes.split(","))),args.rounds)

if __name__=="__main__": main()

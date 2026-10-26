"""Source-LOD precomputation study, reusing the byte-parity performance harness."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("lod_pipeline_study",ROOT/"scripts/pipeline-performance/study.py")
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

p.BASELINE="a306d63"
p.OUT=ROOT/"target/lod-performance"
OUT=p.OUT
BASELINE=p.BASELINE


def freeze():
    subprocess.run(["git","diff","--exit-code",p.BASELINE,"--","crates","Cargo.toml","Cargo.lock","rust-toolchain.toml"],cwd=ROOT,check=True)
    previous=json.loads((ROOT/"docs/pipeline-performance-evidence.json").read_text())
    binary=ROOT/"target/release/ibl-baker.exe"
    if p.digest(binary)!=previous["benchmark"]["binaries"]["candidate"]:raise AssertionError("Current executable is not the accepted baseline")
    for name,sha in previous["benchmark"]["candidate_source"]["files_sha256"].items():
        if p.digest(ROOT/name)!=sha:raise AssertionError(f"Baseline source changed: {name}")
    destination=p.OUT/"baseline-build/release/ibl-baker.exe";destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(binary,destination)
    p.save(p.OUT/"baseline.json",dict(commit=subprocess.check_output(["git","rev-parse",p.BASELINE],cwd=ROOT,text=True).strip(),
        binary_sha256=p.digest(destination),prior_evidence_sha256=p.digest(ROOT/"docs/pipeline-performance-evidence.json"),
        prior_source=previous["benchmark"]["candidate_source"],method="Reuse the previously measured and source-verified production executable"))
    print("Frozen source-verified baseline",p.digest(destination),flush=True)


def pilot():
    process=p.module("lod_pilot_process",ROOT/"scripts/source-sampling/benchmark.py")
    bins=dict(baseline=p.OUT/"baseline-build/release/ibl-baker.exe",candidate=ROOT/"target/release/ibl-baker.exe")
    hashes={k:p.digest(v) for k,v in bins.items()};rows=[]
    for target in ("specular","irradiance"):
        root=p.OUT/"pilot"/target;root.mkdir(parents=True,exist_ok=True)
        measured={k:[] for k in bins}
        for iteration in range(-2,7):
            for name in (list(bins) if iteration%2==0 else list(bins)[::-1]):
                command=p.command(bins[name],p.SOURCES["pisa"],root/name,512,"ktx2")+["--target",target]
                value=process.run_process(command,root/f"{iteration}-{name}.log",ROOT,4)
                if iteration>=0:measured[name].append(value)
            if p.outputs(root/"baseline")!=p.outputs(root/"candidate"):raise AssertionError("Pilot output bytes changed")
        summary=process.summarize_runs(measured,7)
        rows.append(dict(target=target,runs=measured,summary=summary,outputs=p.outputs(root/"candidate")))
        p.save(p.OUT/"pilot.json",dict(baseline=p.BASELINE,binaries=hashes,rows=rows,threads=4,warmups=2,rounds=7,quality="medium",samples=1024))
        print("pilot",target,summary["ratios"],summary["paired_median_ratio_bootstrap_95pct"],flush=True)
    if hashes!={k:p.digest(v) for k,v in bins.items()}:raise AssertionError("Pilot binary changed")


def profile(candidate):
    # One representative environment suffices to attribute the already measured
    # production change; end-to-end acceptance still covers all three inputs.
    p.SOURCES={"pisa":p.SOURCES["pisa"]}
    p.profile([512],3,candidate)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["freeze","pilot","benchmark","benchmark-confirm","compatibility","prepare-profile","prepare-profile-candidate","profile","profile-candidate"])
    args=parser.parse_args()
    if args.command=="freeze":freeze()
    elif args.command=="pilot":pilot()
    elif args.command=="benchmark":p.benchmark([512],7)
    elif args.command=="benchmark-confirm":p.confirm_noisy()
    elif args.command=="compatibility":p.compatibility()
    elif args.command=="prepare-profile":p.prepare(True)
    elif args.command=="prepare-profile-candidate":p.prepare(True,True)
    else:profile(args.command=="profile-candidate")

if __name__=="__main__":main()

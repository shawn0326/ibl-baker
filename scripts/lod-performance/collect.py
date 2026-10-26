"""Collect source-LOD precomputation parity, timing and memory evidence."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode=True
import study

p=study.p
helpers=p.module("lod_phase_groups",p.ROOT/"scripts/pipeline-performance/collect.py")


def read(name):return json.loads((p.OUT/name).read_text())


def collect():
    baseline=read("baseline.json");pilot=read("pilot.json")
    benchmark=read("benchmark.json");confirmation=read("confirmation.json")
    binaries=dict(baseline=p.OUT/"baseline-build/release/ibl-baker.exe",candidate=p.ROOT/"target/release/ibl-baker.exe")
    if {k:p.digest(v) for k,v in binaries.items()}!=benchmark["binaries"]:raise AssertionError("Measured executable changed")
    if baseline["binary_sha256"]!=benchmark["binaries"]["baseline"]:raise AssertionError("Baseline receipt differs")
    if pilot["binaries"]!=benchmark["binaries"]:raise AssertionError("Pilot executables differ")
    for name,sha in benchmark["candidate_source"]["files_sha256"].items():
        if p.digest(p.ROOT/name)!=sha:raise AssertionError(f"Measured source changed: {name}")
    if len(benchmark["rows"])!=9:raise AssertionError("Incomplete production matrix")
    if confirmation["initial_sha256"]!=p.digest(p.OUT/"benchmark.json"):raise AssertionError("Original matrix changed")
    if confirmation["binaries"]!=benchmark["binaries"]:raise AssertionError("Confirmation executables differ")
    rows={helpers.key(r):r for r in benchmark["rows"]}
    for row in confirmation["rows"]:rows[helpers.key(row)]=rows[helpers.key(row)]|row
    for row in rows.values():
        if row["summary"]["acceptance_status"]!="pass":raise AssertionError("Timing/memory diagnostic remains unresolved")
        for name in binaries:
            root=p.OUT/"benchmark"/f"{row['case']}-{row['size']}-{row['format']}"/name
            if p.outputs(root)!=row["outputs"]:raise AssertionError("Measured output changed")
    phases={}
    for variant in binaries:
        raw=read(f"phases-{variant}.json")
        if len(raw["rows"])!=1:raise AssertionError("Expected one representative phase case")
        compact=[]
        for row in raw["rows"]:
            if row["outputs"]!=rows[(row["case"],row["size"],"both")]["outputs"]:raise AssertionError("Profiled artifact differs")
            if not {"filter_specular","filter_irradiance","filter_lut","png","package_ibla","write_ktx2","write_lut"}.issubset(row["summary"]):raise AssertionError("Incomplete phase coverage")
            if any(sum(r["name"]=="load" for r in trial)!=1 for trial in row["runs"]):raise AssertionError("Source decode count changed")
            compact.append(dict(case=row["case"],size=row["size"],summary=row["summary"],groups=helpers.group_phases(row["runs"])))
        phases[variant]=dict(sha256=p.digest(p.OUT/f"phases-{variant}.json"),binaries=raw["binaries"],rows=compact)
    compatibility=read("compatibility.json")
    if compatibility["binaries"]!=benchmark["binaries"] or len(compatibility["rows"])!=8:raise AssertionError("Incomplete compatibility matrix")
    tools=list(Path(__file__).parent.glob("*"))+[
        p.ROOT/"scripts/pipeline-performance"/name for name in ("study.py","profile.rs","collect.py")]
    tools+=[p.ROOT/"scripts/source-sampling/benchmark.py",p.ROOT/"scripts/quality-optimization/acceptance.py"]
    data=dict(baseline=baseline,adopted=["Prepare source LOD and neighboring mip indices/fraction once per filtering pass"],
        benchmark={k:v for k,v in benchmark.items() if k!="rows"},
        pilot=dict(metadata={k:v for k,v in pilot.items() if k!="rows"},rows=pilot["rows"]),
        original_trials=[helpers.compact(r) for r in benchmark["rows"]],
        confirmation=dict(sha256=p.digest(p.OUT/"confirmation.json"),rows=[helpers.compact(r) for r in confirmation["rows"]]),
        effective_trials=[helpers.compact(r) for r in rows.values()],phases=phases,compatibility=compatibility,
        preparation={name:read(name+".json") for name in ("profile-baseline","profile-candidate")},
        tool_hashes={str(file.relative_to(p.ROOT)):p.digest(file) for file in tools if file.is_file()},
        limitations=["Windows, four Rayon threads, measured output size 512 only", "Instrumented phase times are diagnostic, not production speed claims", "Phase process memory is sampled and can miss short peaks", "Requested-live Rust heap excludes native malloc, allocator overhead and realloc transients", "Prepared kernel adds O(sample-count) temporary storage per pass", "Cross-platform CI is recorded separately from the native performance study"])
    p.save(p.OUT/"evidence.json",data)
    print("Qualified nine byte-identical production cells and representative phase profiles",flush=True)
    return data


def plot(data):
    os.environ.setdefault("MPLCONFIGDIR",str(p.OUT/"matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(11,4.3),layout="constrained")
    for index,fmt in enumerate(("ibla","ktx2","both")):
        rows=[next(r for r in data["effective_trials"] if r["case"]==case and r["format"]==fmt) for case in ("pisa","spruit","bridge")]
        ratios=[r["summary"]["ratios"]["seconds"] for r in rows]
        axes[0].bar([i+(index-1)*.25 for i in range(3)],ratios,width=.25,label=fmt.upper())
    axes[0].axhline(1,color="black",linewidth=1,linestyle="--")
    axes[0].set(xticks=range(3),xticklabels=["HDR","2K JPEG","Six-face JPEG"],ylabel="Candidate / baseline seconds",title="Uninstrumented production time",ylim=(0,1.1))
    labels=["load","projection/preparation","filter","encode/write"]
    for index,variant in enumerate(("baseline","candidate")):
        row=data["phases"][variant]["rows"][0]
        axes[1].bar([i+(index-.5)*.36 for i in range(4)],[row["groups"][k]["medians"]["seconds"] for k in labels],width=.36,label=variant.title())
    axes[1].set(xticks=range(4),xticklabels=["Load","Projection\n+ preparation","Filter","Encode\n+ write"],ylabel="Seconds",title="Pisa HDR: instrumented phase time")
    for axis in axes:axis.legend();axis.grid(axis="y",alpha=.25)
    fig.suptitle("512 px per face, medium / 1024, four threads; all output bytes preserved",fontsize=11)
    fig.savefig(p.OUT/"lod-performance.png",dpi=160);plt.close(fig)
    data["figure"]=dict(sha256=p.digest(p.OUT/"lod-performance.png"),matplotlib=matplotlib.__version__,python=sys.version)
    p.save(p.OUT/"evidence.json",data)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--plot",action="store_true")
    args=parser.parse_args();data=collect()
    if args.plot:plot(data)

if __name__=="__main__":main()

"""Collect compact evidence and an optional phase/memory figure."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import statistics
import sys

sys.dont_write_bytecode=True
import study as s


def read(name):return json.loads((s.OUT/name).read_text())
def key(row):return row["case"],row["size"],row["format"]
def compact(row):
    result={k:row[k] for k in ("case","size","format","summary")}
    result["samples"]={name:{field:[r[field] for r in values] for field in ("seconds","peak_commit_bytes")} for name,values in row["runs"].items()}
    if "outputs" in row:result["outputs"]=row["outputs"]
    return result


def category(name):
    if name=="load":return "load"
    if name in ("projection","source_mips","source_borders"):return "projection/preparation"
    if name.startswith("filter_"):return "filter"
    if name.startswith(("encode_","write_","package_")) or name in ("png","ktx2_rgb_pack","bc6h","zstd"):return "encode/write"
    if name=="process":return "other"
    raise ValueError(f"Unclassified phase: {name}")


def group_phases(trials):
    groups={}
    for trial in trials:
        children={r["id"]:0. for r in trial}
        for row in trial:
            if row["parent"]:children[row["parent"]]+=row["seconds"]
        times={};heaps={};commits={}
        for row in trial:
            label=category(row["name"])
            exclusive=row["seconds"]-children[row["id"]]
            if exclusive < -1e-6:raise AssertionError("Phase nesting overlaps")
            times[label]=times.get(label,0)+max(0,exclusive)
            if row["name"]!="process":
                heaps[label]=max(heaps.get(label,0),row["heap_peak"])
                commits[label]=max(commits.get(label,0),row["commit_peak"])
        for label in times:
            group=groups.setdefault(label,dict(seconds=[],heap_peak=[],sampled_commit_peak=[]))
            group["seconds"].append(times[label])
            if label in heaps:
                group["heap_peak"].append(heaps[label]);group["sampled_commit_peak"].append(commits[label])
    return {label:dict(samples=values,medians={k:statistics.median(v) if v else None for k,v in values.items()}) for label,values in groups.items()}


def collect():
    benchmark=read("benchmark.json");confirmation=read("confirmation.json")
    if len(benchmark["rows"])!=9:raise AssertionError("Incomplete production matrix")
    if confirmation["initial_sha256"]!=s.digest(s.OUT/"benchmark.json"):raise AssertionError("Confirmation baseline changed")
    if confirmation["binaries"]!=benchmark["binaries"]:raise AssertionError("Confirmation binaries differ")
    rows={key(r):r for r in benchmark["rows"]}
    for row in confirmation["rows"]:rows[key(row)]=rows[key(row)]|row
    for row in rows.values():
        if row["summary"]["acceptance_status"]!="pass":raise AssertionError("Production timing/memory diagnostic remains unresolved")
        for label in ("baseline","candidate"):
            root=s.OUT/"benchmark"/f"{row['case']}-{row['size']}-{row['format']}"/label
            if s.outputs(root)!=row["outputs"]:raise AssertionError("Measured output artifact changed")
    if s.digest(s.ROOT/"target/release/ibl-baker.exe")!=benchmark["binaries"]["candidate"]:raise AssertionError("Candidate executable changed")
    phases={}
    for variant,loads in (("baseline",3),("candidate",1)):
        raw=read(f"phases-{variant}.json")
        if len(raw["rows"])!=3:raise AssertionError("Incomplete phase matrix")
        compact_rows=[]
        for row in raw["rows"]:
            if row["outputs"]!=rows[(row["case"],row["size"],"both")]["outputs"]:raise AssertionError("Profiled artifact differs")
            if not {"png","package_ibla","write_ktx2","write_lut"}.issubset(row["summary"]):raise AssertionError("Phase coverage is incomplete")
            if any(sum(r["name"]=="load" for r in trial)!=loads for trial in row["runs"]):raise AssertionError("Unexpected source decode count")
            compact_rows.append(dict(case=row["case"],size=row["size"],summary=row["summary"],groups=group_phases(row["runs"])))
        phases[variant]=dict(sha256=s.digest(s.OUT/f"phases-{variant}.json"),binaries=raw["binaries"],rows=compact_rows)
    result=dict(baseline=s.BASELINE,adopted=["Reuse one decoded environment per CLI job", "Move base cubemaps into source mips and finished output", "Borrow LUT PNG bytes when writing"],
        benchmark={k:v for k,v in benchmark.items() if k!="rows"},original_trials=[compact(r) for r in benchmark["rows"]],
        confirmation=dict(sha256=s.digest(s.OUT/"confirmation.json"),rows=[compact(r) for r in confirmation["rows"]]),
        effective_trials=[compact(r) for r in rows.values()],phases=phases,compatibility=read("compatibility.json"),
        preparation={name:read(name+".json") for name in ("baseline-source","profile-baseline","profile-candidate")},
        tool_hashes={p.name:s.digest(p) for p in Path(__file__).parent.iterdir() if p.is_file()},
        limitations=["Windows, four Rayon threads, measured output size 512 only", "Instrumented phase times are diagnostic", "Phase process memory is sampled, not an exact native high-water mark", "Requested-live Rust heap excludes native malloc, arena overhead and realloc transient copies", "Input reuse retains decoded pixels during encoding", "No new Linux/macOS CI results"])
    s.save(s.OUT/"evidence.json",result)
    print("Qualified nine production cells, complete phase matrices and unchanged output artifacts",flush=True)
    return result


def plot(data):
    os.environ.setdefault("MPLCONFIGDIR",str(s.OUT/"matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(11,4.3),layout="constrained")
    labels=["load","projection/preparation","filter","encode/write"]
    for index,variant in enumerate(("baseline","candidate")):
        row=next(r for r in data["phases"][variant]["rows"] if r["case"]=="bridge")
        axes[0].bar([i+(index-.5)*.36 for i in range(4)],[row["groups"][k]["medians"]["seconds"] for k in labels],width=.36,label=variant.title())
        rows=[next(r for r in data["effective_trials"] if r["case"]==case and r["format"]=="both") for case in ("pisa","spruit","bridge")]
        axes[1].bar([i+(index-.5)*.36 for i in range(3)],[r["summary"]["medians"][variant]["peak_commit_bytes"]/2**20 for r in rows],width=.36,label=variant.title())
    axes[0].set(xticks=range(4),xticklabels=["Load","Projection\n+ preparation","Filter","Encode\n+ write"],ylabel="Seconds",title="Six-face JPEG: phase time (instrumented)")
    axes[1].set(xticks=range(3),xticklabels=["HDR","2K JPEG","Six-face JPEG"],ylabel="MiB private commit",title="Production process peak: both formats")
    for axis in axes:axis.legend();axis.grid(axis="y",alpha=.25)
    fig.suptitle("512 px per face, medium / 1024, four threads; all output bytes preserved",fontsize=11)
    fig.savefig(s.OUT/"pipeline-performance.png",dpi=160);plt.close(fig)
    data["figure"]=dict(sha256=s.digest(s.OUT/"pipeline-performance.png"),matplotlib=matplotlib.__version__,python=sys.version)
    s.save(s.OUT/"evidence.json",data)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--plot",action="store_true")
    args=parser.parse_args();data=collect()
    if args.plot:plot(data)

if __name__=="__main__":main()

"""Collect compact review evidence; large raw outputs remain under target."""
from __future__ import annotations
import json
from pathlib import Path
import sys

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import study as s


def main():
    read=lambda name:json.loads((s.OUT/name).read_text())
    benchmark=read("benchmark.json")
    if len(benchmark["rows"])!=27: raise ValueError("Incomplete production performance matrix")
    parity=[]
    for row in benchmark["rows"]:
        directory=s.OUT/"benchmark"/f"{row['case']}-{row['size']}-{row['format']}"
        files=sorted(p.name for p in (directory/"baseline").iterdir() if p.suffix in (".ibla",".ktx2",".png"))
        hashes={name:s.digest(directory/"baseline"/name) for name in files}
        if hashes!={name:s.digest(directory/"candidate"/name) for name in files}:
            raise ValueError(f"Default encoded outputs differ: {directory}")
        parity.append(dict(case=row["case"],size=row["size"],format=row["format"],sha256=hashes))
    analysis={}
    for size in (128,256,512):
        path=s.OUT/f"analysis-{size}-grid.json";data=json.loads(path.read_text())
        analysis[str(size)]=dict(sha256=s.digest(path),rows=len(data["metrics"]),
            unqualified_rows=sum(not r["qualified"] for r in data["metrics"]),cases=data["cases"],
            roughness_count=len({r["roughness"] for r in data["metrics"]}),
            reference_identities={case:read(f"reference/{size}/{case}.json")["identity"] for case in data["cases"]})
    result=dict(baseline_commit=s.BASELINE,implementation_commit="c7a393e",
        preparation=read("preparation.json"),decision=read("decision.json"),benchmark=benchmark,
        parity=read("parity.json"),full_matrix_byte_parity=parity,
        encoding=read("encoding.json"),history=read("history/report.json"),
        optional_hdr_reference=read("reference/128/pisa.json") if (s.OUT/"reference/128/pisa.json").exists() else None,
        tail=read("tail-decomposition.json"),analysis=analysis,
        generation_records={str(p.relative_to(s.OUT)):s.digest(p) for p in sorted((s.OUT/"runs").rglob("generation.json"))},
        level_budgets={str(size):{v:read(f"runs/{size}/hemisphere-0/{v}/metadata.json")["levels"] for v in s.variants()} for size in (128,256,512)},
        tool_hashes={p.name:s.digest(p) for p in Path(__file__).parent.iterdir() if p.is_file()},
        limits=["Rejected candidates did not enter a full HDR reference/adoption matrix", "References with failed convergence remain unqualified", "Fresh Linux/macOS CI is still required"])
    s.save(s.OUT/"evidence.json",result)
    lines=["| Scene / size | IBLA seconds (old -> new) | KTX2 seconds (old -> new) | Both seconds (old -> new) | Candidate peak commit MiB (IBLA / KTX2 / both) |", "| --- | ---: | ---: | ---: | ---: |"]
    for size in (128,256,512):
        for case in ("pisa","footprint","qwantani"):
            rows=[next(r for r in benchmark["rows"] if r["size"]==size and r["case"]==case and r["format"]==fmt) for fmt in ("ibla","ktx2","both")]
            timings=[f"{r['medians']['baseline']:.3f} -> {r['medians']['candidate']:.3f}" for r in rows]
            memory=" / ".join(f"{r['noise']['medians']['candidate']['peak_commit_bytes']/1048576:.1f}" for r in rows)
            lines.append(f"| {case} / {size} | " + " | ".join(timings) + f" | {memory} |")
    print("\n".join(lines))
    print("Byte-identical assets across all 27 full-target runs")

if __name__=="__main__":main()

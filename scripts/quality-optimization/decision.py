"""Summarize necessary-gate failures without treating incomplete evidence as a pass."""
from __future__ import annotations
import json
from pathlib import Path
import statistics
import sys

sys.dont_write_bytecode = True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import study as s


def compare(metrics):
    key = lambda row: tuple(row[k] for k in ("case","size","roughness","group","encoding"))
    baseline = {key(row): row for row in metrics if row["variant"] == "baseline"}
    summaries = []
    for variant in sorted({row["variant"] for row in metrics} - {"baseline"}):
        rows = [row for row in metrics if row["variant"] == variant]
        failures = []; endpoints = []
        for row in rows:
            base = baseline[key(row)]
            tolerance = max(.05*base["relative_rmse"],5*max(base["reference_envelope"],row["reference_envelope"]),1e-4)
            if row["qualified"] and base["qualified"] and row["relative_rmse"] > base["relative_rmse"]+tolerance:
                failures.append({k:row[k] for k in ("case","size","roughness","group","encoding","relative_rmse")} |
                    dict(baseline=base["relative_rmse"],tolerance=tolerance))
            if row["case"].startswith("hemisphere-") and row["roughness"] == 1 and row["encoding"] == "float" and row["group"] == "all":
                endpoints.append({k:row[k] for k in ("case","size","max_absolute")})
        witnesses = {}
        for encoding in ("float","ibla","ktx2"):
            values = [r for r in failures if r["encoding"] == encoding]
            witnesses[encoding] = max(values,key=lambda r:r["relative_rmse"]-r["baseline"]-r["tolerance"],default=None)
        endpoint_failure = any(r["max_absolute"] > .01 for r in endpoints)
        summaries.append(dict(variant=variant,status="rejected" if failures or endpoint_failure else "incomplete",
            endpoint_maxima=endpoints,qualified_regression_count=len(failures),regression_witnesses=witnesses,
            unqualified_row_count=sum(not r["qualified"] for r in rows),
            reason="A necessary quality gate failed" if failures or endpoint_failure else "Full converged HDR, visual and performance evidence still required"))
    return summaries


def main():
    paths=sorted(s.OUT.glob("analysis-*-grid.json"))
    if not paths: raise ValueError("Run the independent analysis first")
    metrics=[row for path in paths for row in json.loads(path.read_text())["metrics"]]
    result=dict(baseline=s.BASELINE,analysis_files={str(p.relative_to(s.ROOT)):s.digest(p) for p in paths},
        candidates=compare(metrics),adoption=False,default_minimum=1,
        policy="A confirmed failure can reject early. Missing or uncertain cases can never approve a default.",
        outstanding_adoption_gates=["All nonconstant synthetic and real HDR cases at all sizes", "Equal-scene relative RMSE improvement >=15%", "Two nonconstant cases including real HDR each improve >=10%", "Converged direct and interpolation diagnostics", "Encoded quality and clipping", "Per-case per-format paired process performance", "Fixed material visual review"])
    s.save(s.OUT/"decision.json",result)
    for row in result["candidates"]: print(row["variant"],row["status"],row["qualified_regression_count"])

if __name__ == "__main__": main()

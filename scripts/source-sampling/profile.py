"""Instrument task-owned source copies to measure bake stages without shipped logs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from benchmark import digest, machine_metadata, source_identity, source_snapshot, utc_now


def insert_timer(code, name, label):
    marker = f"fn {name}("
    position = code.index(marker)
    brace = code.index("{", position)
    if name == "render_cubemap_faces":
        # Candidate's six-face input border cache is reported separately. Keep
        # projection timing exclusive of that preparation so the two add up.
        prefix = re.match(r"\s*let sampler = EnvironmentSampler::new\(source\);", code[brace + 1:])
        if prefix:
            brace += prefix.end()
    return code[:brace + 1] + f'\n    let _stage_timer = StageTimer::new("{label}");' + code[brace + 1:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-source", type=Path, default=Path("target/source-sampling-baseline"))
    parser.add_argument("--candidate-source", type=Path, default=Path("."))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--target", choices=("specular", "irradiance"), default="specular")
    parser.add_argument("--rotation", default="0")
    parser.add_argument("--output", type=Path, default=Path("target/source-sampling-stages"))
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.size < 1 or args.threads < 1:
        raise ValueError("Expected positive size and thread count")
    args.output = args.output.resolve()
    if not args.output.is_relative_to(root / "target"):
        raise ValueError("Stage copies must stay under repository target/")
    args.output.mkdir(parents=True, exist_ok=True)
    input_identity = source_identity(args.input)
    records = {}
    summary = {"schema_version": 2, "started_at_utc": utc_now(), "input": input_identity,
               "machine": machine_metadata(), "threads": args.threads,
               "tool_sha256": digest(__file__), "cases": records,
               "measurement_scope": "Single instrumented diagnostic per version; no warmups or paired gate; do not use as performance acceptance"}
    for name, source in [("baseline", args.baseline_source.resolve()), ("candidate", args.candidate_source.resolve())]:
        copied = args.output / name
        if source.is_relative_to(args.output):
            raise ValueError("Input source checkout must not be inside task-owned profiling output")
        original_identity = source_snapshot(source)
        copied.mkdir(exist_ok=True)
        if (copied / "crates").exists():
            shutil.rmtree(copied / "crates")
        for file in ("Cargo.toml", "Cargo.lock"):
            shutil.copy2(source / file, copied / file)
        for crate in ("ibl_core", "ibl_cli", "ktx2_writer"):
            shutil.copytree(source / "crates" / crate, copied / "crates" / crate,
                            dirs_exist_ok=True, ignore=shutil.ignore_patterns("examples", "__pycache__"))
        pipeline_path = copied / "crates/ibl_core/src/bake_pipeline.rs"
        code = pipeline_path.read_text()
        timer = '''
struct StageTimer { name: &'static str, started: std::time::Instant }
impl StageTimer {
    fn new(name: &'static str) -> Self { Self { name, started: std::time::Instant::now() } }
}
impl Drop for StageTimer {
    fn drop(&mut self) {
        eprintln!("STAGE {} {:.9}", self.name, self.started.elapsed().as_secs_f64());
    }
}
'''
        for function, label in [("render_cubemap_faces", "projection"),
                                ("build_cubemap_mip_chain", "source_mips"),
                                ("render_filtered_faces", "filter"),
                                ("build_brdf_lut", "brdf_lut"),
                                ("encode_cubemap_mips", "png_encode"),
                                ("encode_mip_chain_to_ktx2", "ktx2_encode")]:
            code = insert_timer(code, function, label)
        pipeline_path.write_text(code + timer)
        cubemap = copied / "crates/ibl_core/src/cubemap.rs"
        if cubemap.exists():
            border_code = insert_timer(cubemap.read_text(), "new", "border_cache")
            cubemap.write_text(border_code + timer)
        source_image_path = copied / "crates/ibl_core/src/source_image.rs"
        source_image_path.write_text(insert_timer(source_image_path.read_text(), "load_source_image", "source_load") + timer)
        build = args.output / "build" / name
        command = ["cargo", "build", "--release", "--locked", "--offline", "-p", "ibl_cli",
                   "--manifest-path", str(copied / "Cargo.toml"), "--target-dir", str(build)]
        build_command = command
        subprocess.run(build_command, check=True, cwd=root)
        binary = build / "release" / ("ibl-baker.exe" if os.name == "nt" else "ibl-baker")
        destination = copied / "outputs"
        command = [str(binary), "bake", str(args.input.resolve()), "--out-dir", str(destination),
                   "--size", str(args.size), "--target", args.target, "--output-format", "both",
                   "--quality", "high", "--samples", "1024", "--rotation", args.rotation]
        binary_sha256 = digest(binary)
        run_started = utc_now()
        started = time.perf_counter()
        result = subprocess.run(command, check=True, text=True, capture_output=True,
                                env=dict(os.environ, RAYON_NUM_THREADS=str(args.threads)), cwd=root)
        total_seconds = time.perf_counter() - started
        (copied / "stage.log").write_text(result.stdout + result.stderr)
        stages = {}
        for line in result.stderr.splitlines():
            match = re.fullmatch(r"STAGE (\w+) ([0-9.]+)", line)
            if match:
                stages[match[1]] = stages.get(match[1], 0.0) + float(match[2])
        if digest(binary) != binary_sha256 or source_snapshot(source) != original_identity:
            raise RuntimeError("Binary or original source changed during diagnostic profiling")
        records[name] = {"command": command, "build_command": build_command, "seconds": stages,
                         "total_process_seconds": total_seconds, "started_at_utc": run_started,
                         "completed_at_utc": utc_now(), "binary_sha256": binary_sha256,
                         "source_snapshot": original_identity, "instrumented_snapshot": source_snapshot(copied),
                         "stage_log_sha256": digest(copied / "stage.log"),
                         "scope": "Stage sums include both CLI output bakes. Projection excludes six-face input border preparation; border_cache includes input and source mip rings. Source load excludes outer environment validation. Filter includes direction/kernel cache preparation. File writes, startup and manifest construction are part of total_process_seconds only."}
    if source_identity(args.input) != input_identity:
        raise RuntimeError("Input changed during diagnostic profiling")
    summary["completed_at_utc"] = utc_now()
    (args.output / "stages.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

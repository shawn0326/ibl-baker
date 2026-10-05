"""Record a post-measurement, cache-preserving build recheck.

This is not an original compilation log. Run only after performance measurements
have finished. Sources, helpers and binary locations are never changed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
BASELINE_COMMIT = "59af9cc5cacebb16b0f4243b85384a0f8d8651c8"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binary_identity(path):
    if not path.is_file():
        return {"path": str(path), "exists": False, "sha256": None}
    return {"path": str(path), "exists": True, "bytes": path.stat().st_size,
            "sha256": sha256(path)}


def snapshot(directory):
    paths = [directory / name for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml")]
    paths.extend(sorted((directory / "crates").glob("*/Cargo.toml")))
    paths.extend(sorted((directory / "crates").glob("*/build.rs")))
    paths.extend(sorted((directory / "crates").glob("*/src/**/*.rs")))
    paths.extend(sorted((directory / "crates").glob("*/examples/source_sampling_export.rs")))
    paths.extend(sorted((directory / ".cargo").glob("*.toml")))
    files = {str(path.relative_to(directory)).replace("\\", "/"): sha256(path)
             for path in sorted(set(paths)) if path.is_file()}
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"directory": str(directory), "files_sha256": files,
            "sha256": hashlib.sha256(payload).hexdigest()}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def command_record(command, environment):
    started_at = utc_now()
    started = time.perf_counter()
    result = subprocess.run(command, cwd=ROOT, env=environment,
                            capture_output=True, text=True, errors="replace", check=False)
    return {"command": command, "cwd": str(ROOT), "started_at_utc": started_at,
            "completed_at_utc": utc_now(), "seconds": time.perf_counter() - started,
            "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def historical_hashes():
    quality_path = ROOT / "target/source-sampling-quality/commands.json"
    benchmark_path = ROOT / "target/source-sampling-performance/benchmark.json"
    expected = {"baseline_cli": set(), "candidate_cli": set(),
                "baseline_exporter": set(), "candidate_exporter": set()}
    evidence = {}
    if quality_path.is_file():
        evidence["quality_commands"] = {"path": str(quality_path), "sha256": sha256(quality_path)}
        for record in json.loads(quality_path.read_text(encoding="utf-8")):
            identity = record.get("identity", {})
            method = identity.get("tool")
            if method in ("baseline", "candidate"):
                expected[method + "_exporter"].add(identity.get("producer_sha256"))
    if benchmark_path.is_file():
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        evidence["production_benchmark"] = {"path": str(benchmark_path),
                                             "sha256": sha256(benchmark_path),
                                             "state": benchmark.get("state")}
        if benchmark.get("state") != "complete":
            raise ValueError("Production benchmark must be complete before this recheck")
        for method in ("baseline", "candidate"):
            expected[method + "_cli"].add(benchmark["executables"][method]["sha256"])
    for name, values in expected.items():
        if None in values or len(values) != 1:
            raise ValueError(f"Expected exactly one existing measurement producer hash for {name}: {values}")
    return {name: next(iter(values)) for name, values in expected.items()}, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "target/source-sampling-checks/build-provenance.json")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "target").resolve()):
        raise ValueError("Output must remain under repository target/")
    output.parent.mkdir(parents=True, exist_ok=True)
    baseline = ROOT / "target/source-sampling-baseline"
    toolchain_path = ROOT / "rust-toolchain.toml"
    toolchain = tomllib.loads(toolchain_path.read_text(encoding="utf-8"))["toolchain"]["channel"]
    environment = {**os.environ, "RUSTUP_TOOLCHAIN": toolchain}
    build_environment_keys = ("RUSTUP_TOOLCHAIN", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS",
                              "CARGO_BUILD_TARGET", "CARGO_BUILD_RUSTFLAGS", "CARGO_TARGET_DIR",
                              "CARGO_PROFILE_RELEASE_OPT_LEVEL", "CARGO_PROFILE_RELEASE_LTO",
                              "CARGO_PROFILE_RELEASE_CODEGEN_UNITS", "CARGO_PROFILE_RELEASE_DEBUG",
                              "CARGO_PROFILE_RELEASE_STRIP", "CARGO_PROFILE_RELEASE_PANIC",
                              "CARGO_PROFILE_RELEASE_INCREMENTAL", "CC", "CXX", "AR")
    expected, historical_evidence = historical_hashes()
    record = {"schema_version": 1, "scope": "post_measurement_recheck",
              "claim": "Actual cache-preserving build recheck commands; original historical compilation stdout was not preserved. This is not a first-compilation record.",
              "started_at_utc": utc_now(), "state": "running", "baseline_commit": BASELINE_COMMIT,
              "selected_toolchain": toolchain,
              "build_environment": {name: environment[name] for name in build_environment_keys if name in environment},
              "historical_evidence": historical_evidence, "expected_measured_producer_sha256": expected,
              "shared_cargo_config": snapshot(ROOT)["files_sha256"].get(".cargo/config.toml"),
              "rustc_inventory": command_record(["rustc", "-vV"], environment),
              "cargo_inventory": command_record(["cargo", "-V"], environment), "builds": []}
    save(output, record)
    if record["rustc_inventory"]["returncode"] or record["cargo_inventory"]["returncode"]:
        raise RuntimeError("Could not record the active build toolchain")
    executable = "ibl-baker.exe" if os.name == "nt" else "ibl-baker"
    exporter_name = "source_sampling_export.exe" if os.name == "nt" else "source_sampling_export"
    jobs = (
        ("baseline_cli", baseline, ROOT / "target/source-sampling-baseline-build", False),
        ("candidate_cli", ROOT, ROOT / "target", False),
        ("baseline_exporter", baseline, ROOT / "target/source-sampling-baseline-build", True),
        ("candidate_exporter", ROOT, ROOT / "target", True),
    )
    for name, sources, target, is_exporter in jobs:
        binary = target / "release" / ("examples/" + exporter_name if is_exporter else executable)
        before = binary_identity(binary)
        source_before = snapshot(sources)
        helper = sources / "crates/ibl_core/examples/source_sampling_export.rs"
        command = ["cargo", "build", "--release", "--locked", "--offline",
                   "--manifest-path", str(sources / "Cargo.toml"), "--target-dir", str(target),
                   "-p", "ibl_core" if is_exporter else "ibl_cli"]
        if is_exporter:
            command.extend(["--example", "source_sampling_export"])
        print(f"Running post-measurement recheck: {name}", flush=True)
        build = command_record(command, environment)
        after = binary_identity(binary)
        source_after = snapshot(sources)
        combined = build["stdout"] + build["stderr"]
        up_to_date = build["returncode"] == 0 and "Finished" in combined and "Compiling " not in combined
        unchanged = before["sha256"] is not None and before["sha256"] == after["sha256"]
        matches_historical = before["sha256"] == expected[name] and after["sha256"] == expected[name]
        source_unchanged = source_before["sha256"] == source_after["sha256"]
        log_path = output.parent / f"build-provenance-{name}.log"
        log_path.write_text("COMMAND: " + subprocess.list2cmdline(command) + "\n"
                            + "STDOUT:\n" + build["stdout"] + "\nSTDERR:\n" + build["stderr"], encoding="utf-8")
        build.update({"name": name, "manifest_path": str(sources / "Cargo.toml"),
                      "manifest_sha256": source_before["files_sha256"]["Cargo.toml"],
                      "source_before": source_before, "source_after": source_after,
                      "helper_path": str(helper), "helper_sha256": sha256(helper),
                      "binary_before": before, "binary_after": after,
                      "cargo_up_to_date_no_compilation": up_to_date,
                      "binary_sha256_unchanged": unchanged, "source_snapshot_unchanged": source_unchanged,
                      "matches_existing_measurement_producer": matches_historical,
                      "existing_measurement_binding_verified": up_to_date and unchanged and matches_historical and source_unchanged,
                      "log": str(log_path), "log_sha256": sha256(log_path)})
        record["builds"].append(build)
        save(output, record)
        print(f"{name}: exit={build['returncode']}, up_to_date={up_to_date}, bytes_unchanged={unchanged}, historical_match={matches_historical}", flush=True)
        if build["returncode"]:
            record["state"] = "failed"
            record["completed_at_utc"] = utc_now()
            save(output, record)
            return 1
    record["completed_at_utc"] = utc_now()
    record["state"] = "complete"
    record["all_builds_pass"] = all(build["returncode"] == 0 for build in record["builds"])
    record["all_existing_measurements_bound"] = all(build["existing_measurement_binding_verified"] for build in record["builds"])
    record["rustc_inventory_after"] = command_record(["rustc", "-vV"], environment)
    save(output, record)
    print(f"Wrote {output}; historical producer binding={record['all_existing_measurements_bound']}", flush=True)
    return 0 if record["all_existing_measurements_bound"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

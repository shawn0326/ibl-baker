"""Freeze and build private box/solid-angle experiment snapshots under target/."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tarfile
import time

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "3fafed3598374e8be47922069576a558e224fcaf"
HELPERS = ("solid_angle_mips.rs", "probe_adapter.rs", "mip_probe_export.rs")
PIPELINE = "crates/ibl_core/src/bake_pipeline.rs"
BOX_BUILDER = """fn build_cubemap_mip_chain(base_faces: &CubemapFaces) -> Vec<CubemapFaces> {
    let mut levels = vec![base_faces.clone()];
    loop {
        let prev = levels.last().expect("base cubemap mip should exist");
        if prev[0].width <= 1 && prev[0].height <= 1 {
            break;
        }
        let weights = BoxDownsampleWeights::new(prev[0].width, prev[0].height);
        levels.push(array::from_fn(|index| {
            downsample_half(&prev[index], weights.as_ref())
        }));
    }
    levels
}"""
WEIGHTED_BUILDER = """fn build_cubemap_mip_chain(base_faces: &CubemapFaces) -> Vec<CubemapFaces> {
    build_solid_angle_cubemap_mip_chain(base_faces)
}"""
INCLUDES = '\n// Private experiment helpers, injected into task-owned snapshots only.\ninclude!("solid_angle_mips.rs");\ninclude!("probe_adapter.rs");\n'


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def under_target(path):
    resolved = Path(path).resolve()
    target = (ROOT / "target").resolve()
    if resolved == target or not resolved.is_relative_to(target):
        raise ValueError(f"Experiment output must be a child of repository target/: {resolved}")
    return resolved


def write_bytes(path, data):
    path = under_target(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_json(path, value):
    write_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def inventory(directory):
    result = {}
    for path in sorted(Path(directory).rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Unexpected symlink in experiment sources: {path}")
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = sha256(path)
    return result


def input_identity(path):
    path = Path(path).resolve(strict=True)
    if path.is_file():
        files = {path.name: sha256(path)}
    elif path.is_dir():
        files = inventory(path)
        if not files:
            raise ValueError(f"Input directory is empty: {path}")
    else:
        raise ValueError(f"Unsupported input path: {path}")
    return {"path": str(path), "kind": "directory" if path.is_dir() else "file",
            "files": files, "sha256": canonical_hash(files)}


def capture(command):
    return subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def run_logged(command, path, environment):
    started = utc_now()
    timer = time.perf_counter()
    path = under_target(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        completed = subprocess.run(command, cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT)
    record = {"command": command, "cwd": str(ROOT), "started_at_utc": started,
              "seconds": time.perf_counter() - timer, "returncode": completed.returncode,
              "log_path": str(path), "log_sha256": sha256(path)}
    if completed.returncode:
        raise RuntimeError(f"Command failed with exit code {completed.returncode}; inspect {path}")
    return record


def check_production_sources():
    # A fresh tool checkout may have documentation or experiment edits. The
    # production Rust/dependency inputs must still be the frozen baseline.
    names = capture(["git", "diff", "--name-only", BASELINE, "--", "crates", "Cargo.toml", "Cargo.lock"]).splitlines()
    changed = [name for name in names if name.endswith(".rs") or name.endswith("Cargo.toml") or name == "Cargo.lock"]
    if changed:
        raise ValueError(f"Production Rust/dependency sources differ from frozen baseline: {changed}")


def expected_snapshot(archive, helpers, candidate):
    files = {}
    with tarfile.open(archive) as stream:
        for member in stream.getmembers():
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts or member.issym() or member.islnk():
                raise ValueError(f"Unsafe archive entry: {member.name}")
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError(f"Unsupported archive entry: {member.name}")
            source = stream.extractfile(member)
            if source is None:
                raise ValueError(f"Archive file cannot be read: {member.name}")
            files[relative.as_posix()] = source.read()
    original = files[PIPELINE].decode("utf-8")
    if original.count(BOX_BUILDER) != 1 or 'include!("solid_angle_mips.rs")' in original:
        raise ValueError("Frozen pipeline does not match the exact expected source-mip builder anchor")
    code = original.replace(BOX_BUILDER, WEIGHTED_BUILDER, 1) if candidate else original
    files[PIPELINE] = (code + INCLUDES).encode("utf-8")
    for name in HELPERS[:2]:
        files[f"crates/ibl_core/src/{name}"] = helpers[name]
    files["crates/ibl_core/examples/mip_probe_export.rs"] = helpers["mip_probe_export.rs"]
    return files


def materialize(directory, files):
    expected = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    if directory.exists():
        if inventory(directory) != expected:
            raise ValueError(f"Existing frozen source snapshot has drifted: {directory}")
        return expected
    directory = under_target(directory)
    directory.mkdir(parents=True)
    for name, data in files.items():
        write_bytes(directory / name, data)
    if inventory(directory) != expected:
        raise ValueError(f"Frozen source snapshot failed verification: {directory}")
    return expected


def verify_cached(manifest, identity):
    if manifest.get("identity") != identity or manifest.get("state") != "built":
        return False
    for label in ("archive", "candidate_patch"):
        record = manifest[label]
        if sha256(under_target(record["path"])) != record["sha256"]:
            raise ValueError(f"Cached {label} has drifted")
    for side in ("baseline", "candidate"):
        record = manifest["versions"][side]
        if inventory(under_target(record["source"])) != record["source_files"]:
            raise ValueError(f"Cached {side} source snapshot has drifted")
        for label in ("cli", "exporter"):
            path = under_target(record[label])
            if not path.is_file() or sha256(path) != record[f"{label}_sha256"]:
                raise ValueError(f"Cached {side} {label} binary is missing or has drifted")
        for command in record["commands"]:
            if sha256(under_target(command["log_path"])) != command["log_sha256"]:
                raise ValueError(f"Cached build/test log has drifted: {command['log_path']}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "target/mip-weighting")
    parser.add_argument("--input", action="append", type=Path, default=[], help="Record fixed input files or directories")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--no-build", action="store_true", help="Prepare and verify source snapshots without compiling")
    parser.add_argument("--rebuild", action="store_true", help="Repeat builds/tests for verified source snapshots")
    args = parser.parse_args()
    if args.threads < 1:
        raise ValueError("Thread count must be positive")
    output = under_target(args.out)
    output.mkdir(parents=True, exist_ok=True)
    resolved_commit = capture(["git", "rev-parse", f"{BASELINE}^{{commit}}"])
    if resolved_commit != BASELINE:
        raise ValueError("Baseline commit did not resolve to its pinned full SHA")
    check_production_sources()
    helper_directory = Path(__file__).resolve().parent
    helpers = {name: (helper_directory / name).read_bytes() for name in HELPERS}
    environment = dict(os.environ, RAYON_NUM_THREADS=str(args.threads), CARGO_INCREMENTAL="0")
    build_variables = set(name for name in environment if name.startswith(("CARGO_PROFILE_", "CARGO_TARGET_", "CARGO_BUILD_")))
    build_variables.update((
        "RAYON_NUM_THREADS", "CARGO_INCREMENTAL", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS",
        "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "CARGO_BUILD_TARGET", "CARGO_BUILD_RUSTFLAGS",
        "CC", "CXX", "AR", "CFLAGS", "CXXFLAGS", "CL", "_CL_"))
    build_environment = {name: environment.get(name) for name in sorted(build_variables)}
    cargo_config = ROOT / ".cargo/config.toml"
    identity = {"schema_version": 1, "baseline_commit": BASELINE, "prepare_sha256": sha256(__file__),
                "helpers_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in helpers.items()},
                "inputs": [input_identity(path) for path in args.input], "build_environment": build_environment,
                "rustc": capture(["rustc", "-vV"]), "cargo": capture(["cargo", "-vV"]),
                "cargo_config_sha256": sha256(cargo_config) if cargo_config.exists() else None,
                "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()}}
    generation = under_target(output / "prepared" / canonical_hash(identity)[:20])
    generation.mkdir(parents=True, exist_ok=True)
    generation_manifest = generation / "preparation.json"
    root_manifest = output / "preparation.json"
    if generation_manifest.exists() and not args.rebuild:
        previous = json.loads(generation_manifest.read_text())
        if verify_cached(previous, identity):
            write_json(root_manifest, previous)
            print(f"Verified cached experiment builds: {root_manifest}", flush=True)
            return
    archive = generation / "baseline.tar"
    archive_command = ["git", "archive", "--format=tar", f"--output={archive}", BASELINE]
    archive_log = run_logged(archive_command, generation / "logs/archive.log", environment)
    sources = {}
    files = {}
    for side in ("baseline", "candidate"):
        files[side] = expected_snapshot(archive, helpers, side == "candidate")
        source = generation / "src" / side
        sources[side] = {"source": str(source), "source_files": materialize(source, files[side])}
    differences = {name for name in files["baseline"] if files["baseline"][name] != files["candidate"][name]}
    if differences != {PIPELINE}:
        raise ValueError(f"Unexpected baseline/candidate source differences: {sorted(differences)}")
    patch = "".join(difflib.unified_diff(files["baseline"][PIPELINE].decode().splitlines(True),
                                       files["candidate"][PIPELINE].decode().splitlines(True),
                                       fromfile=f"baseline/{PIPELINE}", tofile=f"candidate/{PIPELINE}"))
    patch_path = generation / "candidate.patch"
    write_bytes(patch_path, patch.encode())
    manifest = {"schema_version": 1, "state": "prepared", "started_at_utc": utc_now(), "identity": identity,
                "archive": {"path": str(archive), "sha256": sha256(archive), "command": archive_log},
                "candidate_patch": {"path": str(patch_path), "sha256": sha256(patch_path)},
                "difference_scope": "Only the source-mip builder body differs; private helpers/exporter are identical",
                "candidate_test_scope": "Only mip_weighting_ tests; legacy cube-UV mean tests apply to the box baseline",
                "private_clippy_exception": "Both snapshots use -D warnings -A dead_code: candidate's original box helpers are intentionally unreachable; production checks remain strict",
                "versions": sources}
    write_json(generation_manifest, manifest)
    write_json(root_manifest, manifest)
    if args.no_build:
        print(f"Prepared verified experiment sources: {root_manifest}", flush=True)
        return
    executable_suffix = ".exe" if os.name == "nt" else ""
    for side in ("baseline", "candidate"):
        source = Path(sources[side]["source"])
        build = generation / "build" / side
        common = ["--release", "--locked", "--offline", "--manifest-path", str(source / "Cargo.toml"),
                  "--target-dir", str(build)]
        commands = [(["cargo", "fmt", "--manifest-path", str(source / "Cargo.toml"), "--all", "--check"], "fmt"),
                    (["rustfmt", "--edition", "2021", "--check", *[str(source / path) for path in (
                        "crates/ibl_core/src/solid_angle_mips.rs", "crates/ibl_core/src/probe_adapter.rs",
                        "crates/ibl_core/examples/mip_probe_export.rs")]], "fmt-helpers"),
                    (["cargo", "build", *common, "-p", "ibl_cli"], "build-cli"),
                    (["cargo", "build", *common, "-p", "ibl_core", "--example", "mip_probe_export"], "build-exporter")]
        test_command = ["cargo", "test", *common, "-p", "ibl_core", "--lib"]
        if side == "candidate":
            test_command.append("mip_weighting_")
        commands.append((test_command, "test-private" if side == "candidate" else "test-box"))
        commands.append((["cargo", "clippy", *common, "--workspace", "--all-targets", "--", "-D", "warnings", "-A", "dead_code"], "clippy"))
        records = []
        for command, label in commands:
            print(f"{side}: {label}", flush=True)
            record = run_logged(command, generation / "logs" / f"{side}-{label}.log", environment)
            if command[1] == "test":
                log = Path(record["log_path"]).read_text(errors="replace")
                result = re.search(r"test result: ok\. (\d+) passed;", log)
                if result is None or int(result.group(1)) < 1:
                    raise ValueError(f"Test command did not run a nonempty passing suite: {record['log_path']}")
                record["tests_passed"] = int(result.group(1))
            records.append(record)
            manifest["versions"][side]["commands"] = records
            write_json(generation_manifest, manifest)
            write_json(root_manifest, manifest)
        for label, relative in (("cli", f"ibl-baker{executable_suffix}"),
                                ("exporter", f"examples/mip_probe_export{executable_suffix}")):
            binary = build / "release" / relative
            if not binary.is_file():
                raise ValueError(f"Expected release executable missing: {binary}")
            manifest["versions"][side][label] = str(binary)
            manifest["versions"][side][f"{label}_sha256"] = sha256(binary)
        if inventory(source) != sources[side]["source_files"]:
            raise ValueError(f"Source drift during {side} builds/tests")
        print(f"{side}: verified release binaries and tests", flush=True)
    if {name: (helper_directory / name).read_bytes() for name in HELPERS} != helpers:
        raise ValueError("Private helper sources changed during preparation")
    if [input_identity(path) for path in args.input] != identity["inputs"]:
        raise ValueError("Recorded experiment inputs changed during preparation")
    if sha256(__file__) != identity["prepare_sha256"]:
        raise ValueError("Preparation tool changed during the build")
    check_production_sources()
    manifest.update(state="built", completed_at_utc=utc_now())
    write_json(generation_manifest, manifest)
    write_json(root_manifest, manifest)
    print(f"Prepared experiment manifest: {root_manifest}", flush=True)


if __name__ == "__main__":
    main()

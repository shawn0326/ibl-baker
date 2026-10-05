"""Check private mip policies against the production CLI and real parser consumers.

This is an output compatibility check, not a performance measurement. Every bake,
generated input, loader result, log, and manifest stays below repository target/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
FACES = ("px", "nx", "py", "ny", "pz", "nz")
OUTPUTS = ("specular.ibla", "irradiance.ibla", "specular.ktx2", "irradiance.ktx2", "brdf-lut.png")
PARSERS = (ROOT / "packages/ibla-loader/src/index.ts", ROOT / "packages/ktx2-loader/src/index.ts")

NODE_CONSUMER = r"""
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [directory, iblaPath, ktxPath] = process.argv.slice(1);
const {parseIBLA} = await import(pathToFileURL(iblaPath).href);
const {parseKTX2IBL} = await import(pathToFileURL(ktxPath).href);
const assets = {};
for (const name of ['specular', 'irradiance']) {
  const ibla = parseIBLA(fs.readFileSync(path.join(directory, name + '.ibla')));
  assets[name + '.ibla'] = {
    header: ibla.header,
    manifest: {encoding: ibla.manifest.encoding, container: ibla.manifest.container,
      width: ibla.manifest.width, height: ibla.manifest.height,
      mipCount: ibla.manifest.mipCount, faceCount: ibla.manifest.faceCount,
      build: ibla.manifest.build},
    chunkCount: ibla.chunks.length,
    pixelCount: ibla.chunks.reduce((sum, chunk) => sum + chunk.width * chunk.height, 0),
    chunks: ibla.chunks.map(({mipLevel, face, width, height}) => ({mipLevel, face, width, height}))
  };
  const ktx = parseKTX2IBL(fs.readFileSync(path.join(directory, name + '.ktx2')));
  assets[name + '.ktx2'] = {
    header: ktx.header, format: ktx.format,
    pixelCount: ktx.levels.reduce((sum, level) => sum + level.width * level.height * level.faces.length, 0),
    levels: ktx.levels.map(({mipLevel, width, height, uncompressedByteLength, faces}) => ({
      mipLevel, width, height, uncompressedByteLength,
      faces: faces.map(({face, width, height, uncompressedByteOffset, uncompressedByteLength}) => ({
        face, width, height, uncompressedByteOffset, uncompressedByteLength
      }))
    }))
  };
}
const png = fs.readFileSync(path.join(directory, 'brdf-lut.png'));
if (!png.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
  throw new Error('Invalid BRDF LUT PNG signature');
}
assets['brdf-lut.png'] = {width: png.readUInt32BE(16), height: png.readUInt32BE(20)};
console.log(JSON.stringify(assets));
"""

WARNING = re.compile(
    r"^Warning: (?P<path>.+) \((?P<encoding>[^)]+)\): "
    r"(?P<clipped>\d+) of (?P<total>\d+) pixels had RGB channels clamped to "
    r"\[0, (?P<upper>[^]]+)\] \(pre-clip RGB range: \[(?P<min>[^,]+), (?P<max>[^]]+)\]\)\.$"
)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def below_target(path):
    path = Path(path).resolve()
    target = (ROOT / "target").resolve()
    if path == target or not path.is_relative_to(target):
        raise ValueError(f"Compatibility output must be below repository target/: {path}")
    return path


def run_logged(command, log, *, cwd=ROOT):
    log = below_target(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    result = subprocess.run([str(value) for value in command], cwd=cwd,
                            env=dict(os.environ, RAYON_NUM_THREADS="4"),
                            capture_output=True, text=True, check=False)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    record = {"command": [str(value) for value in command], "cwd": str(cwd),
              "environment": {"RAYON_NUM_THREADS": "4"}, "returncode": result.returncode,
              "elapsed_seconds_diagnostic_only": time.perf_counter() - started,
              "log": str(log), "log_sha256": digest(log),
              "stdout": result.stdout, "stderr": result.stderr}
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {log}")
    return record


def inventory(directory):
    return {path.relative_to(directory).as_posix(): digest(path)
            for path in sorted(directory.rglob("*")) if path.is_file()}


def production_source_inventory():
    paths = {ROOT / "Cargo.toml", ROOT / "Cargo.lock"}
    for name in ("ibl_core", "ibl_cli", "ktx2_writer"):
        directory = ROOT / "crates" / name
        paths.add(directory / "Cargo.toml")
        paths.update((directory / "src").rglob("*.rs"))
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(paths)}


def setup_packages(package_paths):
    for path in reversed(package_paths):
        sys.path.insert(0, str(path.resolve()))
    global np, OpenEXR
    import numpy as np
    import OpenEXR
    return {"numpy": np.__version__, "OpenEXR": OpenEXR.__version__}


def face_direction(face, u, v):
    one = np.ones_like(u)
    coordinates = ((one, -v, -u), (-one, -v, u), (u, one, v),
                   (u, -one, -v), (u, -v, one), (-u, -v, -one))[face]
    directions = np.stack(coordinates, axis=-1)
    return directions / np.linalg.norm(directions, axis=-1, keepdims=True)


def create_case_inputs(directory, case):
    size = case["source_size"]
    directory.mkdir(parents=True, exist_ok=True)
    q = (np.arange(size, dtype=np.float64) + .5) * 2 / size - 1
    u, v = np.meshgrid(q, q)
    for face, name in enumerate(FACES):
        if case["signal"] == "constant":
            pixels = np.broadcast_to([.25, 1., 4.], (size, size, 3))
        elif case["signal"] == "clipped_constant":
            pixels = np.broadcast_to([.25, 2., 600.], (size, size, 3))
        else:
            pixels = .5 + .5 * face_direction(face, u, v)
        OpenEXR.File({"compression": OpenEXR.ZIP_COMPRESSION},
                     {"RGB": np.ascontiguousarray(pixels, dtype=np.float32)}).write(str(directory / f"{name}.exr"))


def clipping_reports(stderr):
    reports = []
    for line in stderr.splitlines():
        if not line.startswith("Warning:"):
            if line.strip():
                raise ValueError(f"Unexpected CLI stderr during compatibility check: {line}")
            continue
        match = WARNING.fullmatch(line)
        if match is None:
            raise ValueError(f"Unrecognized clipping report: {line}")
        value = match.groupdict()
        reports.append({"file": Path(value["path"]).name, "encoding": value["encoding"],
                        "clipped_pixels": int(value["clipped"]), "total_pixels": int(value["total"]),
                        "upper_bound": float(value["upper"]), "min_rgb": float(value["min"]),
                        "max_rgb": float(value["max"])})
    return reports


def check_topology(assets, case):
    size = case["output_size"]
    specular_sizes = []
    while True:
        specular_sizes.append(size)
        if size == 1:
            break
        size = max(1, size // 2)
    for name, dimensions in (("specular", specular_sizes), ("irradiance", [case["irradiance_size"]])):
        ibla, ktx = assets[f"{name}.ibla"], assets[f"{name}.ktx2"]
        expected_chunks = [{"mipLevel": level, "face": face, "width": size, "height": size}
                           for level, size in enumerate(dimensions) for face in FACES]
        assert ibla["chunks"] == expected_chunks, f"Invalid ordered IBLA chunks: {name}"
        assert ibla["chunkCount"] == len(dimensions) * 6
        assert ibla["manifest"]["faceCount"] == 6
        assert ibla["manifest"]["mipCount"] == len(dimensions)
        assert ibla["manifest"]["width"] == ibla["manifest"]["height"] == dimensions[0]
        assert ktx["header"]["faceCount"] == 6
        assert ktx["header"]["levelCount"] == len(dimensions)
        assert ktx["header"]["pixelWidth"] == ktx["header"]["pixelHeight"] == dimensions[0]
        assert len(ktx["levels"]) == len(dimensions)
        for level, (record, size) in enumerate(zip(ktx["levels"], dimensions)):
            assert record["mipLevel"] == level and record["width"] == record["height"] == size
            assert [face["face"] for face in record["faces"]] == list(FACES)
            assert all(face["width"] == face["height"] == size for face in record["faces"])
        expected_pixels = sum(6 * size * size for size in dimensions)
        assert ibla["pixelCount"] == ktx["pixelCount"] == expected_pixels
    assert assets["brdf-lut.png"] == {"width": 256, "height": 256}


def run_checks(args):
    if not __debug__:
        raise ValueError("Compatibility assertions require Python without -O")
    out = below_target(args.out)
    preparation = json.loads(args.build_manifest.read_text(encoding="utf-8"))
    if preparation.get("state") != "built":
        raise ValueError("The preparation manifest must contain completed, verified builds")
    versions = preparation["versions"]
    binaries = {name: Path(versions[name]["cli"]).resolve(strict=True)
                for name in ("baseline", "candidate")}
    binaries["production"] = args.production_cli.resolve(strict=True)
    binary_hashes = {name: digest(path) for name, path in binaries.items()}
    for name in ("baseline", "candidate"):
        if binary_hashes[name] != versions[name]["cli_sha256"]:
            raise ValueError(f"Prepared CLI hash mismatch: {name}")
    packages = setup_packages(args.python_packages)
    node_path = Path(shutil.which(args.node) or args.node).resolve(strict=True)
    node_version = subprocess.run([str(node_path), "--version"], capture_output=True,
                                  text=True, check=True).stdout.strip()
    identity = {"script_sha256": digest(__file__), "build_manifest_sha256": digest(args.build_manifest),
                "cli_sha256": binary_hashes, "parsers": {str(p.relative_to(ROOT)): digest(p) for p in PARSERS},
                "node_version": node_version, "node_sha256": digest(node_path),
                "production_source_files_sha256": production_source_inventory(),
                "python": sys.version, "packages": packages}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    generation = out / "generations" / key
    manifest = generation / "compatibility.json"
    if manifest.exists():
        previous = json.loads(manifest.read_text(encoding="utf-8"))
        observed = inventory(generation)
        observed.pop("compatibility.json", None)
        if previous.get("identity") != identity or previous.get("files") != observed:
            raise ValueError(f"Modified cached compatibility generation: {generation}")
        save(out / "compatibility.json", previous)
        print(f"Verified cached compatibility results: {out / 'compatibility.json'}")
        return
    if generation.exists() and any(generation.iterdir()):
        raise ValueError(f"Incomplete compatibility generation; choose a fresh --out: {generation}")
    generation.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "state": "running", "identity": identity,
              "started_at_utc": utc_now(), "baseline_commit": preparation["identity"]["baseline_commit"],
              "scope": "Deterministic native CLI outputs and parser topology; no performance claim",
              "production_default": "unchanged cube-UV box", "cases": []}
    cases = [
        {"name": "constant", "signal": "constant", "source_size": 16, "output_size": 16, "irradiance_size": 4, "rotation_radians": 0.},
        {"name": "clipped-constant", "signal": "clipped_constant", "source_size": 16, "output_size": 16, "irradiance_size": 4, "rotation_radians": 0.},
        {"name": "directional-rotated", "signal": "directional", "source_size": 16, "output_size": 16, "irradiance_size": 4, "rotation_radians": math.radians(37.)},
        {"name": "directional-npot3", "signal": "directional", "source_size": 3, "output_size": 3, "irradiance_size": 3, "rotation_radians": 0.},
    ]
    for case in cases:
        print(f"Checking CLI/parser compatibility: {case['name']}", flush=True)
        inputs = generation / "inputs" / case["name"]
        create_case_inputs(inputs, case)
        record = {"case": case, "input_files_sha256": inventory(inputs), "versions": {}}
        for name in ("production", "baseline", "candidate"):
            directory = generation / "runs" / case["name"] / name
            directory.mkdir(parents=True, exist_ok=True)
            command = [binaries[name], "bake", inputs, "--out-dir", directory,
                       "--output-format", "both", "--size", str(case["output_size"]),
                       "--irradiance-size", str(case["irradiance_size"]), "--samples", "256",
                       "--quality", "high", "--rotation", repr(case["rotation_radians"])]
            cli_record = run_logged(command, generation / "logs" / f"{case['name']}-{name}-cli.log")
            observed = sorted(path.name for path in directory.iterdir() if path.is_file())
            if observed != sorted(OUTPUTS):
                raise ValueError(f"Unexpected native CLI output inventory: {directory}: {observed}")
            loader_command = [node_path, "--experimental-strip-types", "--input-type=module", "--eval",
                              NODE_CONSUMER, directory, *PARSERS]
            loader_record = run_logged(loader_command, generation / "logs" / f"{case['name']}-{name}-loaders.log")
            assets = json.loads(loader_record["stdout"])
            check_topology(assets, case)
            reports = clipping_reports(cli_record["stderr"])
            for warning in reports:
                if warning["total_pixels"] != assets[warning["file"]]["pixelCount"]:
                    raise ValueError(f"Report counted non-output pixels: {name}/{case['name']}/{warning['file']}")
            if case["signal"] == "clipped_constant":
                if {warning["file"] for warning in reports} != {"specular.ibla", "irradiance.ibla"}:
                    raise ValueError("Clipped constant must report both RGBD assets and no KTX2 clipping")
                if any(warning["clipped_pixels"] != warning["total_pixels"] for warning in reports):
                    raise ValueError("All clipped constant output pixels must participate in the report")
            elif reports:
                raise ValueError(f"Unexpected clipping of bounded compatibility input: {name}/{case['name']}")
            record["versions"][name] = {"cli": cli_record, "loaders": loader_record,
                                        "topology": assets, "clipping_reports": reports,
                                        "normalized_stdout_summary": cli_record["stdout"].replace(directory.as_posix(), "<OUTPUT_DIRECTORY>"),
                                        "output_files_sha256": inventory(directory)}
        production, baseline, candidate = (record["versions"][name]
                                            for name in ("production", "baseline", "candidate"))
        if production["output_files_sha256"] != baseline["output_files_sha256"]:
            raise ValueError(f"Box snapshot changes production output bytes: {case['name']}")
        if production["clipping_reports"] != baseline["clipping_reports"]:
            raise ValueError(f"Box snapshot changes production clipping reports: {case['name']}")
        if production["normalized_stdout_summary"] != baseline["normalized_stdout_summary"]:
            raise ValueError(f"Box snapshot changes production output summary: {case['name']}")
        if production["topology"] != baseline["topology"] or baseline["topology"] != candidate["topology"]:
            raise ValueError(f"Candidate changes loader topology: {case['name']}")
        if baseline["output_files_sha256"]["brdf-lut.png"] != candidate["output_files_sha256"]["brdf-lut.png"]:
            raise ValueError(f"Candidate changes BRDF LUT bytes: {case['name']}")
        if inventory(inputs) != record["input_files_sha256"]:
            raise ValueError(f"Compatibility input changed while baking: {case['name']}")
        record["checks"] = {"production_box_all_output_bytes_equal": True,
                            "production_box_clipping_reports_equal": True,
                            "three_versions_loader_topology_equal": True,
                            "all_brdf_lut_bytes_equal": True,
                            "clipping_report_counts_match_output_pixels": True}
        report["cases"].append(record)
    if {name: digest(path) for name, path in binaries.items()} != binary_hashes:
        raise ValueError("CLI binaries changed while checking compatibility")
    if {str(p.relative_to(ROOT)): digest(p) for p in PARSERS} != identity["parsers"]:
        raise ValueError("Parser sources changed while checking compatibility")
    if production_source_inventory() != identity["production_source_files_sha256"]:
        raise ValueError("Production Rust sources changed while checking compatibility")
    if digest(node_path) != identity["node_sha256"]:
        raise ValueError("Node executable changed while checking compatibility")
    if digest(__file__) != identity["script_sha256"] or digest(args.build_manifest) != identity["build_manifest_sha256"]:
        raise ValueError("Compatibility tool or preparation manifest changed while running")
    report.update(state="passed", completed_at_utc=utc_now(), files=inventory(generation))
    save(manifest, report)
    save(out / "compatibility.json", report)
    print(f"Passed four cases, twelve CLI bakes, and actual IBLA/KTX2 consumers: {out / 'compatibility.json'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-manifest", type=Path, default=ROOT / "target/mip-weighting/preparation.json")
    suffix = ".exe" if os.name == "nt" else ""
    parser.add_argument("--production-cli", type=Path, default=ROOT / f"target/release/ibl-baker{suffix}")
    parser.add_argument("--out", type=Path, default=ROOT / "target/mip-weighting/compatibility")
    parser.add_argument("--python-packages", type=Path, action="append", default=[])
    parser.add_argument("--node", default="node")
    args = parser.parse_args()
    run_checks(args)


if __name__ == "__main__":
    main()

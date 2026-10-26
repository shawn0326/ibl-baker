"""Reproducible quality experiments; production algorithms have no experiment switches."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "target/quality-optimization"
BASELINE = "8330953082f11ce9b0a7a0908b8ddfb3675deb4e"
FACES = ("px", "nx", "py", "ny", "pz", "nz")

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

def run(command, log, env=None, cwd=ROOT):
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        subprocess.run(list(map(str, command)), cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)

def prepare():
    snapshot = OUT / "snapshot"
    names = subprocess.check_output(["git", "ls-files", "crates", "Cargo.toml", "Cargo.lock", "rust-toolchain.toml"], cwd=ROOT, text=True).splitlines()
    hashes = {}
    for name in names:
        src = ROOT / name
        if src.is_file():
            dst = snapshot / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            hashes[name] = digest(src)
    pipeline = snapshot / "crates/ibl_core/src/bake_pipeline.rs"
    text = pipeline.read_text(encoding="utf-8")
    replacements = {
        "fn effective_specular_sample_count(": "pub(crate) fn effective_specular_sample_count(",
        "(0.5 * texel_ratio.max(1.0).log2()).clamp(0.0, max_lod)": "(0.5 * texel_ratio.log2() + quality_experiment_value(0)).clamp(0.0, max_lod)",
        "roughness.clamp(0.0, 1.0).powi(2)": "match quality_experiment_value(1) as u32 { 2 => roughness.clamp(0.0, 1.0).powi(2), 1 => roughness.clamp(0.0, 1.0), 0 => 1.0, _ => unreachable!() }",
    }
    for old, new in replacements.items():
        if text.count(old) != 1: raise ValueError(f"Missing/ambiguous injection point: {old}")
        text = text.replace(old, new)
    text += '''
fn quality_experiment_value(index: usize) -> f32 {
    static VALUES: std::sync::OnceLock<[f32; 2]> = std::sync::OnceLock::new();
    VALUES.get_or_init(|| [
        std::env::var("IBL_STUDY_LOD").unwrap_or_else(|_| "0".into()).parse().unwrap(),
        std::env::var("IBL_STUDY_EXPONENT").unwrap_or_else(|_| "2".into()).parse().unwrap(),
    ])[index]
}
'''
    pipeline.write_text(text, encoding="utf-8")
    shutil.copyfile(Path(__file__).with_name("export.rs"), snapshot / "crates/ibl_core/examples/quality_export.rs")
    config = snapshot / ".cargo/config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('[source.crates-io]\nreplace-with="pnpm-crates-io"\n[source.pnpm-crates-io]\ndirectory=' + json.dumps(str(ROOT / ".pnpm/crates/crates-io")) + '\n', encoding="utf-8")
    env = dict(os.environ, CARGO_TARGET_DIR=str(OUT / "build"))
    command = ["cargo", "build", "--locked", "--offline", "--release", "--manifest-path", snapshot / "Cargo.toml", "-p", "ibl_core", "--example", "quality_export"]
    run(command, OUT / "prepare.log", env, snapshot)
    save(OUT / "preparation.json", dict(baseline=BASELINE, sources=hashes,
        exporter=digest(OUT / "build/release/examples/quality_export.exe"), helper=digest(Path(__file__).with_name("export.rs")),
        script=digest(__file__), modified_pipeline=digest(pipeline), command=list(map(str, command))))

def unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)

def inputs():
    axes = [unit([0, 1, 0]), unit([1, 2, 3]), unit([-2, 1, 1])]
    result = {"constant": lambda d: np.broadcast_to([.25, 1., 4.], d.shape), "directional": lambda d: .5 + .5 * d}
    for i, axis in enumerate(axes):
        result[f"hemisphere-{i}"] = lambda d, a=axis: np.where((d @ a > 0)[..., None], [1., 0, 0], [0., 0, 1.])
    for name, axis in [("face", [1, 0, 0]), ("edge", [1, 0, 1]), ("corner", [1, 1, 1])]:
        for width in [1.2, 8.]:
            result[f"lamp-{name}-{width:g}"] = lambda d, a=unit(axis), w=math.radians(width): .02 + np.exp(-.5 * (np.arccos(np.clip(d @ a, -1, 1)) / w) ** 2)[..., None] * np.array([8., 2., 1.])
    n = 512
    u, v = np.meshgrid((np.arange(n) + .5) / n * 2 - 1, (np.arange(n) + .5) / n * 2 - 1)
    paths = {}
    for name, evaluate in result.items():
        path = OUT / "inputs" / name
        path.mkdir(parents=True, exist_ok=True)
        for face, label in enumerate(FACES):
            output = path / f"{label}.exr"
            if not output.exists():
                pixels = np.ascontiguousarray(evaluate(quality.face_direction(face, u, v)), dtype=np.float32)
                OpenEXR.File({"compression": OpenEXR.ZIP_COMPRESSION}, {"RGB": pixels}).write(str(output))
        paths[name] = path
    for name, path in [("pisa", ROOT / "fixtures/inputs/pisa.hdr"), ("footprint", ROOT / "fixtures/inputs/footprint_court.hdr"),
                       ("qwantani", ROOT / "target/ibl-comparison/inputs/qwantani_noon_puresky_1k.hdr")]:
        paths[name] = path
    return paths, result, axes

def directions():
    i = np.arange(32); y = 1 - 2 * (i + .5) / len(i); phi = i * math.pi * (3 - math.sqrt(5))
    uniform = np.stack([np.sqrt(1-y*y)*np.cos(phi), y, np.sqrt(1-y*y)*np.sin(phi)], axis=-1)
    special = unit([[x, y, z] for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1) if x or y or z])
    local = []
    for axis in [unit([1, 0, 0]), unit([1, 0, 1]), unit([1, 1, 1])]:
        for offset in [-.03, 0, .03]:
            local.extend([unit(axis + [0, offset, 0]), unit(axis + [0, 0, offset])])
    return np.concatenate([uniform, special, local])

def variants():
    base = dict(lod=0., exponent=2, samples=1024, minimum=1)
    values = {"baseline": base}
    for key, choices in [("lod", [-.5*math.log2(4*math.pi), 1-.5*math.log2(4*math.pi)]),
                         ("exponent", [1, 0]), ("samples", [2048, 4096]), ("minimum", [4, 8, 16])]:
        for value in choices: values[f"{key}-{value:g}"] = base | {key: value}
    for minimum in [8, 16]:
        for lod in [-.5*math.log2(4*math.pi), 1-.5*math.log2(4*math.pi)]:
            for samples in [2048, 4096]:
                values[f"combined-{minimum}-{lod:g}-{samples}"] = dict(lod=lod, exponent=1, samples=samples, minimum=minimum)
    return values

def bake(name, path, size, variant_name, variant):
    directory = OUT / "runs" / str(size) / name / variant_name
    exe = OUT / "build/release/examples/quality_export.exe"
    files = sorted(path.glob("*.exr")) if path.is_dir() else [path]
    identity = dict(input={str(p): digest(p) for p in files}, binary=digest(exe), size=size, variant=variant)
    cache = directory / "generation.json"
    if cache.exists():
        record = json.loads(cache.read_text())
        if record["identity"] == identity and all((directory / p).is_file() and digest(directory / p) == h for p, h in record["outputs"].items()): return directory
    env = dict(os.environ, RAYON_NUM_THREADS="4", IBL_STUDY_LOD=str(variant["lod"]), IBL_STUDY_EXPONENT=str(variant["exponent"]))
    run([exe, path, directory, size, variant["minimum"], variant["samples"]], directory / "run.log", env)
    save(cache, dict(identity=identity, outputs={p.name: digest(p) for p in directory.iterdir() if p.suffix in (".f32", ".ibla", ".ktx2") or p.name == "metadata.json"}))
    return directory

def levels(directory):
    meta = json.loads((directory / "metadata.json").read_text())
    return [quality.Cubemap([np.fromfile(directory / f"m{row['mip']}_{f}.f32", dtype="<f4").reshape(row["size"], row["size"], 3) for f in FACES]) for row in meta["levels"]]

def sample(chain, probes, r):
    lod = r * (len(chain)-1); lo = int(math.floor(lod)); hi = min(lo+1, len(chain)-1)
    return chain[lo].sample(probes)*(1-lod+lo) + chain[hi].sample(probes)*(lod-lo)

def screen(sizes, case_names, variant_names):
    paths, analytic, axes = inputs(); probes = directions(); selected = variants()
    if variant_names: selected = {k: selected[k] for k in ["baseline", *variant_names]}
    cases = case_names or list(paths); rows = []
    for size in sizes:
        for name in cases:
            for variant_name, variant in selected.items():
                directory = bake(name, paths[name], size, variant_name, variant); chain = levels(directory)
                if name.startswith("hemisphere-"):
                    expected = (1-probes@axes[int(name[-1])])/2
                    actual = sample(chain, probes, 1.)[:, 2]
                    rows.append(dict(size=size, case=name, variant=variant_name, tail_max_error=float(np.max(np.abs(actual-expected))), tail_rmse=float(np.sqrt(np.mean((actual-expected)**2)))))
                print(f"baked {size} {name} {variant_name}", flush=True)
                save(OUT / ("screen-" + "-".join(map(str,sizes)) + ".json"), dict(rows=rows, sizes=sizes, cases=cases, variants=selected,
                    scope="Analytic hemisphere endpoint only; not the complete adoption gate", adoption=False,
                    remaining="Intermediate roughness, HDR references, encoding and performance"))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "screen"])
    parser.add_argument("--python-packages", type=Path, action="append", default=[])
    parser.add_argument("--sizes", default="128,256,512"); parser.add_argument("--cases"); parser.add_argument("--variants")
    args = parser.parse_args()
    for path in reversed(args.python_packages): sys.path.insert(0, str(path.resolve()))
    if args.command == "prepare": prepare(); return
    global np, OpenEXR, quality
    import numpy as np
    import OpenEXR
    quality = module("quality_common", ROOT / "scripts/source-sampling/quality.py"); quality.np = np
    screen(list(map(int, args.sizes.split(","))), args.cases.split(",") if args.cases else None, args.variants.split(",") if args.variants else None)

if __name__ == "__main__": main()

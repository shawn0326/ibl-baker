"""Bounded, private solid-angle mip feasibility screen; never changes production defaults."""
from __future__ import annotations

import argparse
import csv
from functools import lru_cache
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FACES = ("px", "nx", "py", "ny", "pz", "nz")
ROUGHNESSES = (.05, .2, .5, .7, 1.)
LAMP_CENTERS = {"lamp-center": [1., 0., 0.], "lamp-edge": [1., 0., 1.],
                "lamp-corner": [1., 1., 1.]}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def dependencies(package_paths):
    for path in reversed(package_paths):
        sys.path.insert(0, str(path.resolve()))
    global np, quality, reference
    import numpy as np
    import OpenEXR
    from PIL import Image, ImageDraw
    quality = load_module("phase_two_quality", ROOT / "scripts/source-sampling/quality.py")
    quality.np, quality.OpenEXR = np, OpenEXR
    quality.Image, quality.ImageDraw = Image, ImageDraw
    quality.LUMA = np.array([.2126, .7152, .0722])
    reference = load_module("mip_weighting_reference", HERE / "reference.py")


def analytic(name, directions):
    if name == "constant":
        return np.broadcast_to(np.array([.25, 1., 4.]), directions.shape).copy()
    if name.startswith("directional"):
        if name.endswith("rotated"):
            angle = math.radians(37.)
            x, y, z = np.moveaxis(directions, -1, 0)
            directions = np.stack([math.cos(angle) * x - math.sin(angle) * z, y,
                                   math.sin(angle) * x + math.cos(angle) * z], axis=-1)
        return .5 + .5 * directions
    center = quality.normalize(np.asarray(LAMP_CENTERS[name]))
    angle = np.arccos(np.clip(directions @ center, -1., 1.))
    return .025 + np.exp(-.5 * (angle / np.deg2rad(1.2)) ** 2)[..., None] * np.array([600., 300., 90.])


def make_inputs(out, size, cases):
    result = {}
    q = (np.arange(size) + .5) / size * 2 - 1
    u, v = np.meshgrid(q, q)
    for case in cases:
        if case in ("pisa", "qwantani"):
            path = ROOT / ("fixtures/inputs/pisa.hdr" if case == "pisa" else
                           "target/ibl-comparison/inputs/qwantani_noon_puresky_1k.hdr")
            if not path.is_file():
                raise FileNotFoundError(f"Supply the pinned local HDR input: {path}")
        else:
            path = out / "inputs" / str(size) / case
            # Rotation is performed only by the production projection path.
            signal = "directional" if case == "directional-rotated" else case
            for face, label in enumerate(FACES):
                quality.write_exr(path / f"{label}.exr", analytic(signal, quality.face_direction(face, u, v)))
        result[case] = path
    return result


def identity(path):
    return ({"path": str(path), "sha256": digest(path)} if path.is_file() else
            {"path": str(path), "files": {p.name: digest(p) for p in sorted(path.glob("*.exr"))}})


def probe_table():
    groups = {"uniform": quality.fibonacci(64)}
    directions = []
    for x in (-1., 0., 1.):
        for y in (-1., 0., 1.):
            for z in (-1., 0., 1.):
                if x or y or z:
                    directions.append([x, y, z])
    groups["axes_edges_corners"] = quality.normalize(np.asarray(directions))
    lamps = []
    for center in LAMP_CENTERS.values():
        center = quality.normalize(np.asarray(center))
        up = np.array([0., 1., 0.])
        tangent = quality.normalize(np.cross(up, center))
        bitangent = np.cross(center, tangent)
        lamps.append(center)
        for phi in np.arange(8) * math.pi / 4:
            a = math.radians(1.2)
            lamps.append(center * math.cos(a) + math.sin(a) *
                         (tangent * math.cos(phi) + bitangent * math.sin(phi)))
    groups["lamp_neighborhoods"] = np.asarray(lamps)
    return groups


def write_probes(path, groups):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["x", "y", "z"])
        for direction in np.concatenate(list(groups.values())):
            writer.writerow([format(value, ".17g") for value in direction])


def inventory(directory):
    return {str(path.relative_to(directory)).replace("\\", "/"): digest(path)
            for path in sorted(directory.rglob("*")) if path.is_file() and path.name != "generation.json"}


def export(executable, source, directory, size, rotation, probes):
    command = [str(executable), str(source), str(directory), "--size", str(size),
               "--rotation", str(rotation), "--probes", str(probes)]
    expected = {"schema": 1, "producer": digest(executable), "input": identity(source),
                "size": size, "rotation": rotation, "probes_sha256": digest(probes)}
    manifest = directory / "generation.json"
    if manifest.exists():
        previous = json.loads(manifest.read_text())
        if previous.get("identity") == expected and previous.get("files") == inventory(directory):
            return previous
        raise ValueError(f"Stale or modified export; use a fresh output directory: {directory}")
    if directory.exists() and any(directory.iterdir()):
        raise ValueError(f"Unrecorded export directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    env = dict(os.environ, RAYON_NUM_THREADS="4")
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    (directory / "export.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Exporter failed ({result.returncode}): {directory / 'export.log'}")
    if digest(executable) != expected["producer"] or identity(source) != expected["input"]:
        raise ValueError("Producer/input changed while exporting")
    record = {"identity": expected, "command": command, "seconds": time.perf_counter() - started,
              "files": inventory(directory)}
    save(manifest, record)
    return record


def source_faces(directory, size):
    faces = np.array([np.fromfile(directory / f"source_m0_{face}.f32", dtype="<f4")
                      .reshape(size, size, 3) for face in FACES], dtype=np.float64)
    if not np.isfinite(faces).all():
        raise ValueError("Non-finite exported mip0")
    return faces


def mip_diagnostics(directory, size):
    rows = []
    level = 0
    while True:
        faces = np.asarray([np.fromfile(directory / f"source_m{level}_{face}.f32", dtype="<f4")
                            .reshape(size, size, 3) for face in FACES], dtype=np.float64)
        bounds = np.linspace(-1., 1., size + 1)
        u, v = np.meshgrid(bounds, bounds)
        primitive = np.arctan2(u * v, np.sqrt(1 + u*u + v*v))
        areas = primitive[1:, 1:] - primitive[:-1, 1:] - primitive[1:, :-1] + primitive[:-1, :-1]
        energy = np.sum(faces * areas[None, :, :, None], axis=(1, 2))
        rows.append({"level": level, "size": size, "cube_solid_angle": float(areas.sum()*6),
                     "discrete_integral_per_face_rgb": energy.tolist(),
                     "discrete_integral_rgb": energy.sum(axis=0).tolist(),
                     "cube_uv_mean_rgb": faces.mean(axis=(0, 1, 2)).tolist()})
        if size == 1:
            break
        size, level = max(1, size//2), level + 1
    return rows


@lru_cache(maxsize=12)
def directional_coefficients(roughness, distribution):
    """Independent one-dimensional oracle; azimuthal terms cancel by symmetry."""
    coefficients = []
    for order in (32, 64, 128, 256):
        nodes, weights = np.polynomial.legendre.leggauss(order)
        if distribution == "lambert":
            mu = (nodes + 1) * .5
            coefficient = np.sum(weights * mu * mu) / np.sum(weights * mu)
        else:
            alpha_squared = roughness ** 4
            u = (nodes + 1) * .5 / (1 + alpha_squared)
            mu = (1 - (1 + alpha_squared)*u) / (1 + (alpha_squared - 1)*u)
            coefficient = np.sum(weights * mu * mu) / np.sum(weights * mu)
        coefficients.append(float(coefficient))
    return coefficients


def continuous_directional(directions, roughness, distribution, case):
    """Diagnose projection and source-mip error together, separately from shared mip0."""
    coefficients = directional_coefficients(roughness, distribution)
    rotated = 2 * analytic(case, quality.normalize(directions)) - 1
    values = .5 + .5 * coefficients[-1] * rotated
    return values, {"target": "continuous affine direction field; includes projection error",
                    "coefficients": coefficients, "last_change": abs(coefficients[-1]-coefficients[-2]),
                    "r1_closed_form_coefficient": 2/3 if roughness == 1 else None}


def read_batch(directory, distribution, samples, roughness_index, count):
    name = (f"probes_ggx_s{samples}_r{roughness_index}.f32" if distribution == "ggx" else
            f"probes_lambert_s{samples}.f32")
    value = np.fromfile(directory / name, dtype="<f4").reshape(-1, 3).astype(np.float64)
    if value.shape != (count, 3) or not np.isfinite(value).all():
        raise ValueError(f"Invalid probe batch: {directory / name}")
    return value


def reference_rgb(record):
    return np.asarray(record["rgb"], dtype=np.float64)


def run_screen(args):
    out = args.out.resolve()
    if not out.is_relative_to((ROOT / "target").resolve()):
        raise ValueError("All outputs must be under repository target/")
    out.mkdir(parents=True, exist_ok=True)
    preparation = json.loads(args.build_manifest.read_text())
    if preparation.get("state") != "built":
        raise ValueError("Prepare and verify both release producers before screening")
    versions = preparation["versions"]
    for record in versions.values():
        if digest(record["exporter"]) != record["exporter_sha256"]:
            raise ValueError("Prepared exporter identity has drifted")
    cases = args.cases.split(",")
    if set(cases) - {"constant", "directional", "directional-rotated", "pisa", "qwantani", *LAMP_CENTERS}:
        raise ValueError("Unknown pilot case")
    groups = probe_table()
    probes = np.concatenate(list(groups.values()))
    probe_path = out / "probes.csv"
    write_probes(probe_path, groups)
    group_ranges = {}
    offset = 0
    for name, values in groups.items():
        group_ranges[name] = [offset, offset + len(values)]
        offset += len(values)
    paths = make_inputs(out, args.size, cases)
    report = {"schema": 1, "baseline_commit": preparation["identity"]["baseline_commit"],
              "production_default": "unchanged cube-UV box", "size": args.size,
              "screen_only": True, "reference_scope": "normalized N=V GGX prefilter and normalized Lambert; not a full physical material renderer",
              "proposals": [256, 1024], "roughnesses": list(ROUGHNESSES), "probe_groups": group_ranges,
              "reference_budget_seconds": args.reference_minutes * 60,
              "reference_tolerance": 1e-4, "quality_gate": {"relative_rmse_reduction": .05,
              "uncertainty_multiplier": 5,
              "required_nonconstant_cases": 2, "required_hdr_cases": 1, "required_roughnesses": 2,
              "required_proposals": [256, 1024]}, "cases": [],
              "not_run": ["512 confirmation", "full cmgen/material matrix", "production-process performance matrix"],
              "tools": {str(p.relative_to(ROOT)): digest(p) for p in
                        (HERE / "screen.py", HERE / "reference.py", ROOT / "scripts/source-sampling/quality.py")},
              "preparation_sha256": digest(args.build_manifest), "state": "running"}
    save(out / "screen.json", report)
    reference_used = 0.
    for case in cases:
        print(f"Exporting {case} source={args.size}", flush=True)
        rotation = 37. if case == "directional-rotated" else 0.
        runs = {name: out / "runs" / case / name for name in ("baseline", "candidate")}
        generations = {name: export(Path(versions[name]["exporter"]), paths[case], runs[name],
                                    args.size, rotation, probe_path) for name in runs}
        metadata = {name: json.loads((runs[name] / "metadata.json").read_text()) for name in runs}
        if metadata["baseline"]["directions"] != metadata["candidate"]["directions"]:
            raise ValueError("Different actual probe directions invalidate the comparison")
        if metadata["baseline"]["probe_batches"] != metadata["candidate"]["probe_batches"]:
            raise ValueError("Different kernel or accepted sample identities invalidate the comparison")
        actual_probes = np.asarray(metadata["baseline"]["directions"], dtype=np.float64)
        a, b = (source_faces(runs[name], args.size) for name in runs)
        if not np.array_equal(a, b):
            raise ValueError(f"Different mip0 invalidates isolated comparison: {case}")
        sampler = quality.Cubemap(a)
        case_record = {"case": case, "input": identity(paths[case]), "rotation": rotation,
                       "mip0_bitwise_equal": True, "generations": generations, "batches": [],
                       "source_mip_diagnostics": {name: mip_diagnostics(runs[name], args.size) for name in runs}}
        sensitive = None
        if case in ("pisa", "qwantani"):
            # Bright output and largest A/B differences are chosen before reference integration.
            xa = read_batch(runs["baseline"], "ggx", 1024, 2, len(probes))
            xb = read_batch(runs["candidate"], "ggx", 1024, 2, len(probes))
            sensitive = sorted(set(np.argsort(xa @ quality.LUMA)[-4:].tolist() +
                                   np.argsort(np.linalg.norm(xb - xa, axis=1))[-4:].tolist()))
            case_record["sensitive_probe_indices"] = sensitive
        for distribution, index, roughness in [("ggx", i, r) for i, r in enumerate(ROUGHNESSES)] + [("lambert", 0, 1.)]:
            print(f"Reference {case} {distribution} r={roughness:g}, remaining={max(0., args.reference_minutes*60-reference_used):.0f}s", flush=True)
            records = []
            start = time.perf_counter()
            deadline = start + max(0., args.reference_minutes * 60 - reference_used)
            actual_batches = [b for b in metadata["baseline"]["probe_batches"]
                              if b["distribution"] == distribution and b["requested_proposals"] == 256]
            actual_roughness = float(np.asarray([actual_batches[index]["roughness_f32_bits"]], dtype=np.uint32).view(np.float32)[0])
            for probe_index, normal in enumerate(actual_probes):
                if case == "constant" and np.array_equal(a, np.broadcast_to(a[0, 0, 0], a.shape)):
                    record = {"rgb": a[0, 0, 0].tolist(), "status": "exact_constant",
                              "target": "shared_mip0", "levels": [], "strict_error_bound": True}
                else:
                    record = reference.evaluate_reference(sampler.sample, normal, actual_roughness, distribution,
                            source_faces=a if sensitive is not None and probe_index in sensitive else None,
                            deadline=deadline, label="shared_mip0")
                if sensitive is not None and probe_index in sensitive and record.get("rgb") is not None:
                    record["highlight_crosscheck"] = reference.crosscheck_highlight_support(
                        a, sampler.sample, normal, actual_roughness, record, distribution=distribution, deadline=deadline)
                records.append(record)
            reference_used += time.perf_counter() - start
            reference_file = out / "references" / case / f"{distribution}_r{index}.json"
            save(reference_file, records)
            valid = np.array([r.get("status") in ("converged_diagnostic", "exact_constant") for r in records])
            values = np.array([reference_rgb(r) if r.get("rgb") is not None else [0., 0., 0.] for r in records])
            batch = {"distribution": distribution, "roughness": roughness,
                     "actual_roughness": actual_roughness,
                     "reference_file": str(reference_file), "reference_sha256": digest(reference_file),
                     "reference_converged_probes": int(valid.sum()), "total_probes": len(probes),
                     "reference_elapsed_seconds": reference_used, "metrics": []}
            for samples in (256, 1024):
                xa = read_batch(runs["baseline"], distribution, samples, index, len(probes))
                xb = read_batch(runs["candidate"], distribution, samples, index, len(probes))
                for group, (first, last) in group_ranges.items():
                    mask = valid[first:last]
                    entry = {"proposals": samples, "group": group, "all_probes_converged": bool(mask.all()),
                             "converged_probes": int(mask.sum()), "count": last-first,
                             "candidate_baseline": quality.metrics(xb[first:last], xa[first:last])}
                    if mask.any():
                        indices = np.arange(first, last)[mask]
                        entry["baseline_reference"] = quality.metrics(xa[indices], values[indices])
                        entry["candidate_reference"] = quality.metrics(xb[indices], values[indices])
                    if case.startswith("directional"):
                        continuous, oracle = continuous_directional(actual_probes[first:last], actual_roughness,
                                                                    distribution, case)
                        entry["continuous_directional_diagnostic"] = {"oracle": oracle,
                              "baseline": quality.metrics(xa[first:last], continuous),
                              "candidate": quality.metrics(xb[first:last], continuous)}
                    batch["metrics"].append(entry)
            case_record["batches"].append(batch)
            report["reference_seconds_used"] = reference_used
            save(out / "screen.json", report | {"cases": report["cases"] + [case_record]})
        report["cases"].append(case_record)
        if any(digest(ROOT / path) != value for path, value in report["tools"].items()):
            raise ValueError("Numerical tool changed during screening")
        if digest(args.build_manifest) != report["preparation_sha256"]:
            raise ValueError("Build manifest changed during screening")
        save(out / "screen.json", report)
    report["state"] = "complete"
    report["screen_decision"] = "pending analyze.py conservatively verified gate analysis"
    save(out / "screen.json", report)
    print(f"Saved bounded pilot: {out / 'screen.json'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-manifest", type=Path, default=ROOT / "target/mip-weighting/preparation.json")
    parser.add_argument("--out", type=Path, default=ROOT / "target/mip-weighting/pilot")
    parser.add_argument("--python-packages", type=Path, action="append", default=[])
    parser.add_argument("--cases", default="constant,directional,pisa,qwantani,lamp-center,lamp-edge,lamp-corner,directional-rotated")
    parser.add_argument("--size", type=int, choices=(256, 512), default=256)
    parser.add_argument("--reference-minutes", type=float, default=30.)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if not 0 < args.reference_minutes <= 30:
        raise ValueError("Reference budget must be positive and at most 30 minutes")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    dependencies(args.python_packages)
    if args.self_check:
        print(json.dumps(reference.run_self_checks(), indent=2, allow_nan=False))
    else:
        run_screen(args)


if __name__ == "__main__":
    main()

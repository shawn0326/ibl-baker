"""Private phase-two raw-HDR comparison against actual cmgen v1.77.2.

This is an engineering comparison, not a physical ground truth renderer.
All sphere views share the baseline's actual BRDF PNG and material parameters.
Each method supplies its own specular and diffuse bake.
The diffuse bake is additionally compared separately on uniform sphere probes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
FACES = ("px", "nx", "py", "ny", "pz", "nz")
ROUGHNESSES = (.05, .2, .5, .7, 1.)
CMGEN_SHA256 = "4151702aa949a081809c3d775250c01dafb76d98ac9830882a7b610815a100e3"


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-exporter", type=Path)
    parser.add_argument("--candidate-exporter", type=Path)
    parser.add_argument("--cmgen", type=Path, default=ROOT / "target/ibl-comparison/tools/filament-v1.77.2/bin/cmgen.exe")
    parser.add_argument("--out", type=Path, default=ROOT / "target/source-sampling-quality")
    parser.add_argument("--python-packages", type=Path, action="append", default=[])
    parser.add_argument("--cases", default="constant,directional,lamps,pisa,footprint,qwantani")
    parser.add_argument("--sizes", default="256,512")
    parser.add_argument("--sphere-size", type=int, default=128)
    parser.add_argument("--samples", type=int, default=1024)
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument("--generate-inputs-only", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    return parser.parse_args()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def normalize(d):
    return d / np.maximum(np.linalg.norm(d, axis=-1, keepdims=True), 1e-20)


def face_direction(face, u, v):
    one = np.ones_like(u)
    values = ([one, -v, -u], [-one, -v, u], [u, one, v],
              [u, -one, -v], [u, -v, one], [-u, -v, -one])
    return normalize(np.stack(values[face], axis=-1))


def direction_to_face_uv(d):
    major = np.argmax(np.abs(d), axis=-1)
    positive = np.take_along_axis(d, major[..., None], axis=-1)[..., 0] >= 0
    face = major * 2 + (~positive)
    x, y, z = d[..., 0], d[..., 1], d[..., 2]
    u = np.select([face == i for i in range(5)], [-z, z, x, x, x], default=-x)
    v = np.select([face == i for i in range(5)], [-y, -y, z, -z, -y], default=-y)
    scale = np.max(np.abs(d), axis=-1)
    return face.astype(np.int32), (u / scale + 1) * .5, (v / scale + 1) * .5


class Cubemap:
    """Common CPU reconstruction, including three-face corner averaging."""
    def __init__(self, faces):
        self.faces = np.asarray(faces, dtype=np.float64)
        if self.faces.ndim != 4 or self.faces.shape[0] != 6 or self.faces.shape[-1] != 3:
            raise ValueError("Expected six RGB faces")
        n = self.faces.shape[1]
        if self.faces.shape[2] != n or not np.isfinite(self.faces).all():
            raise ValueError("Expected finite square faces")
        self.size = n
        q = (np.arange(-1, n + 1) + .5) / n * 2 - 1
        u, v = np.meshgrid(q, q)
        padded = []
        for face in range(6):
            f, s, t = direction_to_face_uv(face_direction(face, u, v))
            x = np.clip(np.floor(s * n).astype(int), 0, n - 1)
            y = np.clip(np.floor(t * n).astype(int), 0, n - 1)
            pixels = self.faces[f, y, x].copy()
            # Project the mathematical cube corner onto all three incident faces.
            for iy in (0, n + 1):
                for ix in (0, n + 1):
                    d = face_direction(face, np.array(-1. if ix == 0 else 1.),
                                       np.array(-1. if iy == 0 else 1.))
                    colors = []
                    for axis in range(3):
                        ray = d.copy()
                        ray[axis] *= 1.000001
                        cf, cu, cv = direction_to_face_uv(ray)
                        colors.append(self.faces[cf, min(int(cv * n), n - 1), min(int(cu * n), n - 1)])
                    pixels[iy, ix] = np.mean(colors, axis=0)
            padded.append(pixels)
        self.padded = np.asarray(padded)

    def sample(self, directions):
        f, u, v = direction_to_face_uv(directions)
        x, y = u * self.size - .5, v * self.size - .5
        ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
        tx, ty = (x - ix)[..., None], (y - iy)[..., None]
        a, b = self.padded[f, iy + 1, ix + 1], self.padded[f, iy + 1, ix + 2]
        c, e = self.padded[f, iy + 2, ix + 1], self.padded[f, iy + 2, ix + 2]
        return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + e * tx) * ty


def read_psd32(path):
    """Narrow decoder for cmgen's raw planar big-endian f32 PSD profile."""
    data = path.read_bytes()
    if len(data) < 26 or data[:4] != b"8BPS":
        raise ValueError(f"Invalid PSD header: {path}")
    version = struct.unpack_from(">H", data, 4)[0]
    channels, height, width, depth, mode = struct.unpack_from(">HIIHH", data, 12)
    if (version, channels, depth, mode) != (1, 3, 32, 3):
        raise ValueError(f"Expected raw RGB PSD32: {path}")
    offset = 26
    for _ in range(3):
        if offset + 4 > len(data):
            raise ValueError(f"Truncated PSD section: {path}")
        offset += 4 + struct.unpack_from(">I", data, offset)[0]
    if offset + 2 > len(data) or struct.unpack_from(">H", data, offset)[0] != 0:
        raise ValueError(f"Expected uncompressed PSD planes: {path}")
    offset += 2
    if width == 0 or height == 0 or len(data) != offset + channels * height * width * 4:
        raise ValueError(f"PSD dimensions/payload mismatch: {path}")
    result = np.frombuffer(data, dtype=">f4", offset=offset).astype(np.float32).reshape(3, height, width)
    if not np.isfinite(result).all():
        raise ValueError(f"Non-finite PSD pixels: {path}")
    return result.transpose(1, 2, 0)


class Asset:
    def __init__(self, directory, cmgen=False):
        self.cmgen = cmgen
        if cmgen:
            levels = sorted(int(p.stem.split("_")[0][1:]) for p in directory.glob("m*_px.psd"))
            if not levels or levels != list(range(len(levels))):
                raise ValueError(f"Missing/invalid actual cmgen mip chain: {directory}")
            self.levels = [Cubemap([read_psd32(directory / f"m{i}_{f}.psd") for f in FACES]) for i in levels]
            self.irradiance = Cubemap([read_psd32(directory / f"i_{f}.psd") for f in FACES])
        else:
            metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
            if metadata["storage"] != "little-endian interleaved RGB IEEE754 f32" or metadata["clamping"] != "none":
                raise ValueError("Expected unencoded production raw f32")
            def read(prefix, n):
                return Cubemap([np.fromfile(directory / f"{prefix}{f}.f32", dtype="<f4").reshape(n, n, 3) for f in FACES])
            self.levels = [read(f"m{level['mip']}_", level["size"]) for level in metadata["levels"]]
            self.irradiance = read("irradiance_", metadata["irradiance_size"])

    def transform(self, directions):
        return directions[..., [2, 1, 0]] if self.cmgen else directions

    def sample(self, directions, roughness):
        lod = (roughness * (2 - roughness) if self.cmgen else roughness) * (len(self.levels) - 1)
        low, high = int(math.floor(lod)), min(int(math.floor(lod)) + 1, len(self.levels) - 1)
        d = self.transform(directions)
        return self.levels[low].sample(d) * (1 - lod + low) + self.levels[high].sample(d) * (lod - low)


def analytic_colors(d, name):
    if name == "constant":
        return np.broadcast_to(np.array([.25, 1., 4.]), d.shape).copy()
    if name == "directional":
        return .5 + .5 * d
    result = np.full(d.shape, .025)
    # Sources centered exactly on one edge and one corner, with contrasting colors.
    for axis, color in (([1., .15, 1.], [600., 300., 90.]), ([1., 1., 1.], [80., 240., 600.])):
        center = normalize(np.asarray(axis))
        angle = np.arccos(np.clip(d @ center, -1, 1))
        result += np.exp(-.5 * (angle / np.deg2rad(1.2)) ** 2)[..., None] * np.asarray(color)
    return result


def write_exr(path, pixels):
    path.parent.mkdir(parents=True, exist_ok=True)
    OpenEXR.File({"compression": OpenEXR.ZIP_COMPRESSION},
                 {"RGB": np.asarray(pixels, dtype=np.float32)}).write(str(path))


def generate_inputs(output):
    paths = {}
    h, w = 512, 1024
    u, v = np.meshgrid((np.arange(w) + .5) / w, (np.arange(h) + .5) / h)
    theta, phi = (u - .5) * 2 * np.pi, v * np.pi
    directions = np.stack([np.cos(theta) * np.sin(phi), np.cos(phi), np.sin(theta) * np.sin(phi)], axis=-1)
    for name in ("constant", "directional", "lamps"):
        path = output / "inputs" / f"{name}.exr"
        write_exr(path, analytic_colors(directions, name))
        paths[name] = path
    for n in (256, 512):
        q = (np.arange(n) + .5) / n * 2 - 1
        u, v = np.meshgrid(q, q)
        for face, label in enumerate(FACES):
            write_exr(output / "inputs/six-face-lamps" / str(n) / f"{label}.exr",
                      analytic_colors(face_direction(face, u, v), "lamps"))
    paths.update(pisa=ROOT / "fixtures/inputs/pisa.hdr",
                 footprint=ROOT / "fixtures/inputs/footprint_court.hdr",
                 qwantani=ROOT / "target/ibl-comparison/inputs/qwantani_noon_puresky_1k.hdr")
    return paths


def run_cached(command, directory, identity):
    record_path = directory / "generation.json"
    if record_path.exists():
        old = json.loads(record_path.read_text(encoding="utf-8"))
        if old.get("identity") == identity and old.get("returncode") == 0:
            try:
                verify_output_inventory(directory, old.get("outputs_sha256", {}))
            except (ValueError, OSError) as error:
                print(f"Invalid generation cache; regenerating {directory}: {error}", flush=True)
            else:
                print(f"Reusing verified output: {directory}", flush=True)
                return old
    if directory.exists():
        # Callers supply only task-owned generation directories beneath target/.
        if not directory.resolve().is_relative_to((ROOT / "target").resolve()):
            raise ValueError(f"Refusing to replace generation directory outside target: {directory}")
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    print("Running: " + subprocess.list2cmdline(command), flush=True)
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    record = {"identity": identity, "command": command, "elapsed_seconds": time.perf_counter() - started,
              "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
    if completed.returncode:
        save_json(record_path, record)
        raise RuntimeError(f"Generation failed; see {record_path}: {completed.stderr}")
    record["outputs_sha256"] = {str(p.relative_to(directory)): digest(p) for p in sorted(directory.rglob("*")) if p.is_file()}
    save_json(record_path, record)
    return record


def valid_sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def verify_output_inventory(directory, hashes):
    """Reject extra unrecorded faces as well as changed or missing artifacts."""
    if not isinstance(hashes, dict) or not hashes or any(
            not isinstance(path, str) or not valid_sha256(value) for path, value in hashes.items()):
        raise ValueError("Expected nonempty output inventory with canonical SHA-256 values")
    normalized = {path.replace("\\", "/"): value for path, value in hashes.items()}
    actual = {path.relative_to(directory).as_posix(): path for path in directory.rglob("*")
              if path.is_file() and path != directory / "generation.json"}
    if len(normalized) != len(hashes) or set(normalized) != set(actual):
        raise ValueError("Saved output inventory differs from exact directory contents excluding generation.json")
    if any(digest(actual[path]) != value for path, value in normalized.items()):
        raise ValueError("Saved output artifact hash changed")
    return len(normalized)


def verify_saved_generation(directory, source_sha256, size, samples, name, producer_sha256=None):
    """Verify stored producer identities and raw bytes without rebuilding tools."""
    path = directory / "generation.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    expected = {"source_sha256": source_sha256, "size": size, "samples": samples, "tool": name}
    identity = record.get("identity", {})
    if not isinstance(identity, dict) or type(identity.get("schema")) is not int or identity.get("schema") != 1:
        raise ValueError(f"Expected generation schema 1: {path}")
    if not valid_sha256(identity.get("producer_sha256")) or not valid_sha256(identity.get("source_sha256")):
        raise ValueError(f"Saved generation is missing valid producer/source SHA-256 identities: {path}")
    if record.get("returncode") != 0 or any(identity.get(k) != v for k, v in expected.items()):
        raise ValueError(f"Saved generation identity differs from requested analysis: {path}")
    if producer_sha256 is not None and identity["producer_sha256"] != producer_sha256:
        raise ValueError(f"Producer executable identity differs across matrix cases or supplied binary: {path}")
    if name == "cmgen" and (identity.get("producer_sha256") != CMGEN_SHA256 or identity.get("cmgen_version") != "v1.77.2"):
        raise ValueError(f"Saved reference was not produced by pinned actual cmgen: {path}")
    hashes = record.get("outputs_sha256", {})
    count = verify_output_inventory(directory, hashes)
    return {"generation_record_sha256": digest(path), "identity": identity,
            "verified_output_count": count, "exact_output_inventory_and_hashes_match": True}


def generate(args, paths, cases, sizes):
    if not args.baseline_exporter or not args.candidate_exporter:
        raise ValueError("Supply --baseline-exporter and --candidate-exporter")
    producers = {"baseline": args.baseline_exporter.resolve(), "candidate": args.candidate_exporter.resolve(),
                 "cmgen": args.cmgen.resolve()}
    for producer in producers.values():
        if not producer.is_file():
            raise FileNotFoundError(producer)
    if digest(producers["cmgen"]) != CMGEN_SHA256:
        raise ValueError("cmgen executable differs from pinned Windows v1.77.2 archive identity")
    records = []
    for case in cases:
        source = paths[case].resolve()
        input_sha256 = digest(source)
        for size in sizes:
            for name, exporter in producers.items():
                directory = args.out / "runs" / case / str(size) / name
                identity = {"source_sha256": input_sha256, "producer_sha256": digest(exporter),
                            "size": size, "samples": args.samples, "tool": name,
                            "schema": 1, "cmgen_version": "v1.77.2" if name == "cmgen" else None}
                if name == "cmgen":
                    command = [str(exporter), "--quiet", "--no-mirror", "--type=cubemap", "--format=psd",
                               "--compression=32", f"--size={size}", f"--ibl-samples={args.samples}",
                               f"--ibl-ld={directory}", f"--ibl-irradiance={directory}", str(source)]
                else:
                    command = [str(exporter), str(source), str(directory), "--size", str(size),
                               "--irradiance-size", "32", "--samples", str(args.samples)]
                records.append(run_cached(command, directory, identity))
    save_json(args.out / "commands.json", records)


def fibonacci(n):
    i = np.arange(n)
    y = 1 - 2 * (i + .5) / n
    phi = i * np.pi * (3 - math.sqrt(5))
    radius = np.sqrt(1 - y * y)
    return np.stack([radius * np.cos(phi), y, radius * np.sin(phi)], axis=-1)


def sphere_geometry(size):
    q = (np.arange(size) + .5) / size * 2 - 1
    x, y = np.meshgrid(q, -q)
    mask = x * x + y * y < 1
    z = np.sqrt(np.maximum(0, 1 - x * x - y * y))
    normals = np.stack([x[mask], y[mask], z[mask]], axis=-1)
    reflected = 2 * normals[:, 2:3] * normals - np.array([0., 0., 1.])
    angle = np.deg2rad(35.)
    rotation = np.array([[np.cos(angle), 0, np.sin(angle)], [0, 1, 0], [-np.sin(angle), 0, np.cos(angle)]])
    return mask, normals @ rotation.T, normalize(reflected @ rotation.T), normals[:, 2]


def sample_lut(image, nv, roughness):
    h, w = image.shape[:2]
    x, y = np.clip(nv * w - .5, 0, w - 1), np.clip(roughness * h - .5, 0, h - 1)
    ix, iy = np.floor(x).astype(int), int(np.floor(y))
    ax, ay = (x - ix)[:, None], y - iy
    a, b = image[iy, ix], image[iy, np.minimum(ix + 1, w - 1)]
    c, d = image[min(iy + 1, h - 1), ix], image[min(iy + 1, h - 1), np.minimum(ix + 1, w - 1)]
    return (a * (1 - ax) + b * ax) * (1 - ay) + (c * (1 - ax) + d * ax) * ay


def metrics(candidate, reference):
    luma = reference @ LUMA
    bright = luma >= np.quantile(luma, .95)
    def errors(a, b):
        rmse = float(np.sqrt(np.mean((a - b) ** 2)))
        return {"rmse": rmse, "relative_rmse": rmse / max(float(np.sqrt(np.mean(b ** 2))), 1e-12),
                "mean_luma_ratio": float(np.mean(a @ LUMA) / max(float(np.mean(b @ LUMA)), 1e-12)),
                "max_absolute_error": float(np.max(np.abs(a - b)))}
    return {"all": errors(candidate, reference), "brightest_5pct_reference": errors(candidate[bright], reference[bright]),
            "bright_probe_count": int(np.sum(bright))}


def synthetic_diagnostics(case, assets, runs, probes):
    """Closed-form checks for these analytic signals, not a general renderer."""
    if case not in ("constant", "directional", "lamps"):
        return None
    mip0 = {face: {name: digest(runs / name / f"m0_{face}.f32") for name in ("baseline", "candidate")}
            for face in FACES}
    result = {"mip0_sha256": mip0,
              "mip0_baseline_candidate_bitwise_equal": all(v["baseline"] == v["candidate"] for v in mip0.values())}
    if case == "directional":
        # (1/pi) integral_{n.l>0} (0.5+0.5*l) (n.l) dOmega = 0.5+n/3.
        # The analytic source is continuous; stored latlong texels approximate it.
        reference = .5 + probes / 3
        values = {name: asset.sample(probes, 1.) for name, asset in assets.items()}
        design = np.concatenate((np.ones((len(probes), 1)), probes), axis=1)
        fits = {}
        for r in (.05, 1.):
            fits[str(r)] = {}
            for name, asset in assets.items():
                colors = values[name] if r == 1. else asset.sample(probes, r)
                coefficients = np.linalg.lstsq(design, colors, rcond=None)[0]
                matrix = coefficients[1:]
                diagonal = np.diag(matrix)
                off_diagonal = matrix - np.diag(diagonal)
                fits[str(r)][name] = {
                    "coefficients_constant_x_y_z_rows_rgb_columns": coefficients.tolist(),
                    "max_abs_off_diagonal": float(np.max(np.abs(off_diagonal))),
                    "positive_dominant_diagonal": bool(np.all(diagonal > 0) and
                                                      np.min(diagonal) > np.max(np.abs(off_diagonal))),
                    "fit_relative_rms_residual": metrics(colors, design @ coefficients)["all"]["relative_rmse"],
                }
        result["r1_closed_form_normalized_cosine"] = {
            "source_function": "L(direction)=0.5+0.5*direction, independently in RGB",
            "reference_function": "normalized cosine convolution=0.5+normal/3",
            "formula": "(1/pi) integral over normal.light>0 of L(light)*(normal.light)*dOmega",
            "scope": "Exact for this continuous analytic field and normalized cosine kernel only; r=1 N=V normalized GGX prefilter has this kernel. Does not validate a full physical BRDF renderer. Measured error also includes discrete input projection, output grids and common cubemap reconstruction.",
            "vs_continuous_analytic_reference": {name: metrics(v, reference) for name, v in values.items()},
            "candidate_vs_baseline": metrics(values["candidate"], values["baseline"]),
        }
        ideal_tails = {}
        for name, asset in assets.items():
            n = asset.levels[-1].size
            q = (np.arange(n) + .5) / n * 2 - 1
            u, v = np.meshgrid(q, q)
            # Store exact closed-form center values in this asset's cube space;
            # the x/z swap is its own inverse for the real cmgen panorama path.
            faces = [.5 + asset.transform(face_direction(face, u, v)) / 3 for face in range(6)]
            ideal = Cubemap(faces).sample(asset.transform(probes))
            ideal_tails[name] = {
                "tail_face_size": n,
                "center_values": "exact continuous normalized-cosine field at each texel center, aligned to the method's stored cube orientation",
                "ideal_tail_reconstruction_vs_closed_form": metrics(ideal, reference),
                "actual_tail_vs_ideal_tail_reconstruction": metrics(values[name], ideal),
            }
        result["r1_ideal_tail_only_model"] = {
            "construction": "Evaluate 0.5+direction/3 at actual tail face texel centers, then reconstruct the six ideal faces with the same common Cubemap sampler at the same 4096 directions",
            "scope": "Isolates output-grid reconstruction in this idealized analytic model; no bake, source mips or FIS. These errors are not an additive attribution of total production error: source/filter/grid errors can cancel or compound.",
            "methods": ideal_tails,
        }
        result["directional_affine_fits"] = {
            "interpretation": "Positive dominant RGB-axis diagonal supports unchanged axis orientation for this signal; fitting does not prove correctness for arbitrary illumination.",
            "roughnesses": fits,
        }
    elif case == "lamps":
        lamps = []
        for center in ([1., .15, 1.], [1., 1., 1.]):
            axis = normalize(np.asarray(center))
            tangent = normalize(np.cross(np.array([0., 1., 0.]), axis))
            bitangent = np.cross(axis, tangent)
            u, v = np.meshgrid(np.deg2rad(np.linspace(-4.5, 4.5, 31)),
                               np.deg2rad(np.linspace(-4.5, 4.5, 31)))
            rays = normalize(axis + np.tan(u.reshape(-1, 1)) * tangent + np.tan(v.reshape(-1, 1)) * bitangent)
            maxima = {}
            for name, asset in assets.items():
                rgb = asset.sample(rays, .05)
                luma = rgb @ LUMA
                index = int(np.argmax(luma))
                maxima[name] = {"grid_index": index, "direction": rays[index].tolist(), "peak_luma": float(luma[index]),
                                "center_luma": float(asset.sample(axis[None, :], .05)[0] @ LUMA)}
            same = maxima["baseline"]["grid_index"] == maxima["candidate"]["grid_index"]
            angle = 0. if same else float(np.rad2deg(np.arccos(np.clip(np.dot(
                maxima["baseline"]["direction"], maxima["candidate"]["direction"]), -1, 1))))
            lamps.append({"center_direction": axis.tolist(), "actual_outputs": maxima,
                          "baseline_candidate_peak_equal_on_grid": same,
                          "candidate_baseline_peak_angle_degrees": angle,
                          "candidate_baseline_peak_luma_ratio": maxima["candidate"]["peak_luma"] / max(maxima["baseline"]["peak_luma"], 1e-12)})
        result["r005_local_lamp_peaks"] = {
            "roughness": .05, "grid": "31x31 tangent-angle grid, +/-4.5 degrees on each axis, 0.3 degree step",
            "scope": "Peak locations are compared on this finite grid; equality does not bound a sub-grid peak displacement. Peak values are linear luminance before exposure or encoding.",
            "lamps": lamps,
        }
    return result


def tonemap(rgb, exposure):
    x = np.maximum(rgb * exposure, 0)
    mapped = np.clip(x * (2.51 * x + .03) / (x * (2.43 * x + .59) + .14), 0, 1)
    return np.where(mapped <= .0031308, mapped * 12.92, 1.055 * mapped ** (1 / 2.4) - .055)


def shade(prefiltered, diffuse, lut, nv, material):
    if material == "reflection":
        return prefiltered
    f0 = np.array([.95, .64, .54]) if material == "metal" else np.full(3, .04)
    result = prefiltered * (f0 * lut[:, 0:1] + lut[:, 1:2])
    if material == "dielectric":
        fresnel = f0 + (1 - f0) * (1 - nv[:, None]) ** 5
        result += diffuse * np.array([.6, .6, .6]) * (1 - fresnel)
    return result


def contact_sheet(path, title, images, mask, exposure):
    n = mask.shape[0]
    left, gap, top = 170, 8, 64
    canvas = Image.new("RGB", (left + len(ROUGHNESSES) * (n + gap), top + 3 * (n + 26)), (18, 21, 27))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 8), title, fill="white")
    draw.text((8, 25), f"Shared baseline LUT/material; exposure={exposure:.6g}; engineering comparison", fill=(190, 198, 210))
    for col, r in enumerate(ROUGHNESSES):
        draw.text((left + col * (n + gap), 46), f"r={r:g}", fill="white")
    for row, name in enumerate(("baseline", "candidate", "cmgen")):
        draw.text((8, top + row * (n + 26) + n // 2), "cmgen v1.77.2 (actual)" if name == "cmgen" else name, fill="white")
        for col, r in enumerate(ROUGHNESSES):
            tile = np.full((n, n, 3), [18, 21, 27], dtype=np.uint8)
            tile[mask] = np.round(tonemap(images[r][name], exposure) * 255).astype(np.uint8)
            canvas.paste(Image.fromarray(tile), (left + col * (n + gap), top + row * (n + 26)))
    canvas.save(path)


def linear_error_maps(directory, images, mask):
    """Lossless signed linear errors plus common-scale diagnostic previews."""
    maps = {}
    scale = max(float(np.sqrt(np.mean(images[r]["cmgen"] ** 2))) for r in ROUGHNESSES)
    for r in ROUGHNESSES:
        for name, ref in (("baseline-vs-cmgen", "cmgen"), ("candidate-vs-cmgen", "cmgen"), ("candidate-vs-baseline", "baseline")):
            method = "baseline" if name.startswith("baseline") else "candidate"
            difference = np.full((*mask.shape, 3), np.nan, dtype=np.float32)
            difference[mask] = images[r][method] - images[r][ref]
            np.save(directory / f"r{r:g}-{name}-linear.npy", difference)
            magnitude = np.sqrt(np.mean(difference[mask].astype(float) ** 2, axis=-1)) / max(scale, 1e-12)
            value = np.clip((np.log10(np.maximum(magnitude, 1e-4)) + 4) / 4, 0, 1)
            rgb = np.stack([np.clip(value * 3, 0, 1), np.clip(value * 3 - 1, 0, 1), np.clip(value * 3 - 2, 0, 1)], axis=-1)
            tile = np.zeros((*mask.shape, 3), dtype=np.uint8)
            tile[mask] = np.round(rgb * 255).astype(np.uint8)
            Image.fromarray(tile).save(directory / f"r{r:g}-{name}-error.png")
            maps[f"r{r:g}-{name}"] = {"reference_rms_scale": scale, "png_scale": "log10 normalized RGB RMS error 1e-4..1; black/red/yellow/white", "numeric_file": "signed RGB linear HDR .npy; NaN outside sphere"}
    save_json(directory / "linear-error-map-metadata.json", maps)


def analyze(args, paths, cases, sizes):
    probes = fibonacci(4096)
    mask, normals, reflected, nv = sphere_geometry(args.sphere_size)
    rows, cases_report, regressions = [], [], []
    producer_hashes = {"cmgen": CMGEN_SHA256}
    for name, binary in (("baseline", args.baseline_exporter), ("candidate", args.candidate_exporter)):
        if binary is not None:
            producer_hashes[name] = digest(binary.resolve())
    for case in cases:
        for size in sizes:
            runs = args.out / "runs" / case / str(size)
            source_sha256 = digest(paths[case])
            verified = {}
            for name in ("baseline", "candidate", "cmgen"):
                verified[name] = verify_saved_generation(runs / name, source_sha256, size, args.samples,
                                                         name, producer_hashes.get(name))
                producer_hashes.setdefault(name, verified[name]["identity"]["producer_sha256"])
            assets = {name: Asset(runs / name / paths[case].stem if name == "cmgen" else runs / name, name == "cmgen")
                      for name in ("baseline", "candidate", "cmgen")}
            baseline_lut = runs / "baseline/brdf-lut.png"
            if digest(baseline_lut) != digest(runs / "candidate/brdf-lut.png"):
                raise ValueError("BRDF LUT changed between baseline and candidate")
            lut_image = np.asarray(Image.open(baseline_lut).convert("RGB"), dtype=float) / 255
            diffuse = {name: asset.irradiance.sample(asset.transform(normals)) for name, asset in assets.items()}
            views = {material: {} for material in ("reflection", "metal", "dielectric")}
            diagnostics = []
            for r in ROUGHNESSES:
                sampled = {name: asset.sample(probes, r) for name, asset in assets.items()}
                for name in ("baseline", "candidate"):
                    value = metrics(sampled[name], sampled["cmgen"])
                    diagnostics.append({"roughness": r, "method": name, "vs_actual_cmgen": value})
                    for region in ("all", "brightest_5pct_reference"):
                        rows.append({"case": case, "size": size, "material": "uniform-specular-probes", "roughness": r,
                                     "method": name, "reference": "actual-cmgen-v1.77.2", "region": region, **value[region]})
                old, new = diagnostics[-2]["vs_actual_cmgen"], diagnostics[-1]["vs_actual_cmgen"]
                for region in ("all", "brightest_5pct_reference"):
                    a, b = old[region]["relative_rmse"], new[region]["relative_rmse"]
                    if b > a + max(1e-7, a * .001):
                        regressions.append({"case": case, "size": size, "roughness": r, "region": region,
                                            "baseline_relative_rmse": a, "candidate_relative_rmse": b,
                                            "status": "Requires explanation; cmgen is diagnostic, not a pass/fail physical oracle"})
                lut = sample_lut(lut_image, nv, r)
                for material in views:
                    images = {name: shade(asset.sample(reflected, r), diffuse[name], lut, nv, material) for name, asset in assets.items()}
                    views[material][r] = images
                    for name in ("baseline", "candidate"):
                        value = metrics(images[name], images["cmgen"])
                        for region in ("all", "brightest_5pct_reference"):
                            rows.append({"case": case, "size": size, "material": material, "roughness": r,
                                         "method": name, "reference": "actual-cmgen-v1.77.2", "region": region, **value[region]})
            irrigation = {name: metrics(asset.irradiance.sample(asset.transform(probes)),
                                       assets["cmgen"].irradiance.sample(assets["cmgen"].transform(probes)))
                          for name, asset in assets.items() if name != "cmgen"}
            # Use one exposure for all methods, roughnesses and materials in a case.
            light = assets["baseline"].sample(probes, 1.) @ LUMA
            exposure = float(.18 / max(float(np.exp(np.mean(np.log(np.maximum(light, 1e-6))))), 1e-6))
            directory = args.out / "analysis" / case / str(size)
            directory.mkdir(parents=True, exist_ok=True)
            for material, images in views.items():
                contact_sheet(directory / f"{material}-contact.png", f"{case}, {size}: {material}", images, mask, exposure)
                subdir = directory / material
                subdir.mkdir(exist_ok=True)
                linear_error_maps(subdir, images, mask)
            details = {"case": case, "size": size, "source_sha256": digest(paths[case]), "brdf_png_sha256": digest(baseline_lut),
                       "exposure": exposure, "specular": diagnostics, "diffuse_vs_actual_cmgen": irrigation,
                       "verified_generation": verified,
                       "synthetic_diagnostics": synthetic_diagnostics(case, assets, runs, probes),
                       "level_dimensions": {name: [level.size for level in asset.levels] for name, asset in assets.items()}}
            save_json(directory / "metrics.json", details)
            cases_report.append(details)
    with (args.out / "metrics.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = {"schema_version": 1, "reference": "actual cmgen v1.77.2 PSD32, unencoded/unclipped float RGB",
              "correctness_scope": "Engineering comparison only; no claim of exact physical light integration",
              "runtime_reconstruction": "Same seam-aware bilinear/trilinear CPU sampler for all outputs",
              "directions": "cmgen --no-mirror panorama output sampled at [current.z,current.y,current.x]",
              "roughness": "actual current linear r*(levels-1); actual cmgen r*(2-r)*(levels-1), min face size 16",
              "material": "ordinary split-sum; shared actual baseline production PNG LUT/material; each method's actual diffuse; no direct light; orthographic sphere yaw35",
              "analysis_tool_sha256": digest(Path(__file__)),
              "analysis_dependencies": {"numpy": np.__version__, "OpenEXR": OpenEXR.__version__, "Pillow": Image.__version__},
              "verified_producer_hashes_fixed_across_matrix": producer_hashes,
              "bright_region": "top 5% reference luminance, reported separately from all probes; ties can exceed 5%",
              "sphere_size": args.sphere_size, "uniform_probe_count": len(probes), "roughnesses": ROUGHNESSES,
              "cases": cases_report, "observed_regressions": regressions,
              "artifacts_sha256": {str(p.relative_to(args.out)): digest(p) for p in sorted(args.out.rglob("*"))
                                   if p.is_file() and p.name not in ("report.json", "report.md")}}
    save_json(args.out / "report.json", report)
    summary = ["# Source sampling phase-two quality acceptance", "", report["reference"], "", report["correctness_scope"], "",
               "## Comparison conditions", "", report["runtime_reconstruction"], report["directions"], report["roughness"],
               report["material"], "", "## Observed regressions", "",
               "Every recorded increase below is preserved for inspection. A lower cmgen difference alone is not physical correctness.", ""]
    summary += [f"- {item['case']} {item['size']} r={item['roughness']:g} {item['region']}: {item['baseline_relative_rmse']:.6%} -> {item['candidate_relative_rmse']:.6%}." for item in regressions]
    if not regressions:
        summary.append("No increases above the reporting floor (0.1% relative or 1e-7 absolute) in uniform specular probe RMSE.")
    synthetic = [case for case in cases_report if case["synthetic_diagnostics"] is not None]
    if synthetic:
        summary += ["", "## Independent synthetic diagnostics", "",
                    "These checks apply to the known analytic signals only; they are not a full physical BRDF reference renderer."]
        for case in synthetic:
            diagnostics = case["synthetic_diagnostics"]
            summary.append(f"- {case['case']} {case['size']}: mip0 baseline/candidate float bytes equal: {diagnostics['mip0_baseline_candidate_bitwise_equal']}.")
            if "r1_closed_form_normalized_cosine" in diagnostics:
                reference = diagnostics["r1_closed_form_normalized_cosine"]
                values = reference["vs_continuous_analytic_reference"]
                summary.append(f"- Directional {case['size']} r=1 against exact continuous normalized-cosine field 0.5+n/3: baseline {values['baseline']['all']['relative_rmse']:.6%}, candidate {values['candidate']['all']['relative_rmse']:.6%}, actual cmgen {values['cmgen']['all']['relative_rmse']:.6%}. Candidate/baseline change {reference['candidate_vs_baseline']['all']['relative_rmse']:.6%}.")
                fits = diagnostics["directional_affine_fits"]["roughnesses"]
                summary.append(f"- Directional {case['size']} candidate affine RGB-axis fit positive/dominant: r=.05 {fits['0.05']['candidate']['positive_dominant_diagonal']}, r=1 {fits['1.0']['candidate']['positive_dominant_diagonal']}. Full coefficients/residuals are in report.json.")
                tails = diagnostics["r1_ideal_tail_only_model"]["methods"]
                summary.append(f"- Directional {case['size']} ideal tail-only reconstruction versus closed form: candidate {tails['candidate']['tail_face_size']}x{tails['candidate']['tail_face_size']} {tails['candidate']['ideal_tail_reconstruction_vs_closed_form']['all']['relative_rmse']:.6%}; cmgen {tails['cmgen']['tail_face_size']}x{tails['cmgen']['tail_face_size']} {tails['cmgen']['ideal_tail_reconstruction_vs_closed_form']['all']['relative_rmse']:.6%}. This isolates an ideal grid model and does not additively attribute the production error.")
            if "r005_local_lamp_peaks" in diagnostics:
                for index, lamp in enumerate(diagnostics["r005_local_lamp_peaks"]["lamps"]):
                    summary.append(f"- Lamps {case['size']} r=.05 lamp {index}: baseline/candidate peak positions equal on 0.3-degree grid: {lamp['baseline_candidate_peak_equal_on_grid']}; peak luminance ratio {lamp['candidate_baseline_peak_luma_ratio']:.9f}.")
        summary += ["", "The continuous analytic cosine check includes the pipeline's discrete projection and output-grid reconstruction error. A small analytic regression is a real deterministic difference and must not be relabeled random noise. Fixed minimum output size and source-FIS conventions remain outside this phase."]
    summary += ["", "## Completion status", "", "This report records diagnostics. Visual inspection, analytic correctness tests and separate production-process performance gates must all pass before phase two is marked complete."]
    (args.out / "report.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(f"Wrote {args.out / 'report.md'}; preserved {len(regressions)} diagnostic regressions", flush=True)


def self_check():
    uniform_rays = fibonacci(300)
    for n in (1, 2, 3, 16):
        cube = Cubemap(np.broadcast_to([.25, 1., 4.], (6, n, n, 3)))
        assert np.max(np.abs(cube.sample(uniform_rays) - [.25, 1., 4.])) < 1e-12
        q = (np.arange(n) + .5) / n * 2 - 1
        u, v = np.meshgrid(q, q)
        cube = Cubemap([face_direction(f, u, v) * .5 + .5 for f in range(6)])
        for f in range(6):
            assert np.max(np.abs(cube.sample(face_direction(f, u, v)) - cube.faces[f])) < 1e-12
        for signs in ((a, b, c) for a in (-1, 1) for b in (-1, 1) for c in (-1, 1)):
            point = np.array(signs, dtype=float)
            rays = np.array([normalize(point * (1 + np.eye(3)[i] * 1e-6)) for i in range(3)])
            colors = cube.sample(rays)
            assert np.max(np.ptp(colors, axis=0)) < 1e-5
    value = metrics(np.ones((100, 3)), np.ones((100, 3)))
    assert value["all"]["rmse"] == 0 and value["all"]["mean_luma_ratio"] == 1
    saved_generation_self_check()
    print("Self-check passed: common cubemap orientation, centers, constants, corners, metrics and saved-generation integrity")


def saved_generation_self_check():
    """Tiny integrity regressions, isolated in a cleaned task-owned target dir."""
    target = (ROOT / "target").resolve()
    if not target.is_relative_to(ROOT.resolve()):
        raise ValueError("Self-check temporary directory must stay inside the repository")
    target.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="source-sampling-selfcheck-", dir=target) as temporary:
        directory = Path(temporary).resolve()
        if not directory.is_relative_to(target):
            raise ValueError("Unexpected self-check temporary path")
        raw_path = directory / "m0_px.f32"
        original_raw = struct.pack("<3f", .25, 1., 4.)
        raw_path.write_bytes(original_raw)
        source_sha256, producer_sha256 = "a" * 64, "b" * 64
        record = {"identity": {"schema": 1, "source_sha256": source_sha256,
                               "producer_sha256": producer_sha256, "size": 1, "samples": 32, "tool": "baseline"},
                  "returncode": 0, "outputs_sha256": {raw_path.name: digest(raw_path)}}
        manifest = directory / "generation.json"

        def write_record(value=record):
            save_json(manifest, value)

        def verify():
            return verify_saved_generation(directory, source_sha256, 1, 32, "baseline", producer_sha256)

        def expect_rejected(label):
            try:
                verify()
            except (ValueError, OSError):
                return
            raise AssertionError(f"Saved-generation self-check accepted {label}")

        write_record()
        checked = verify()
        assert checked["verified_output_count"] == 1 and checked["exact_output_inventory_and_hashes_match"]
        for key in ("producer_sha256", "schema"):
            missing = json.loads(json.dumps(record))
            del missing["identity"][key]
            write_record(missing)
            expect_rejected(f"missing {key}")
        for key, value in (("schema", 2), ("schema", True), ("producer_sha256", "not-a-sha256"),
                           ("producer_sha256", None), ("producer_sha256", "c" * 64)):
            invalid = json.loads(json.dumps(record))
            invalid["identity"][key] = value
            write_record(invalid)
            expect_rejected(f"invalid or cross-case mismatched {key}={value!r}")
        write_record()
        extra = directory / "m1_px.f32"
        extra.write_bytes(original_raw)
        expect_rejected("extra unrecorded mip")
        extra.unlink()
        raw_path.write_bytes(struct.pack("<3f", .5, 1., 4.))
        expect_rejected("modified recorded raw bytes")
        raw_path.unlink()
        expect_rejected("missing recorded raw file")
        raw_path.write_bytes(original_raw)
        assert verify()["exact_output_inventory_and_hashes_match"]


def main():
    global np, OpenEXR, Image, ImageDraw, LUMA
    args = arguments()
    for directory in reversed(args.python_packages):
        sys.path.insert(0, str(directory.resolve()))
    import numpy as np
    import OpenEXR
    from PIL import Image, ImageDraw
    LUMA = np.array([.2126, .7152, .0722])
    if args.self_check:
        self_check()
        return
    args.out = args.out.resolve()
    if not args.out.is_relative_to((ROOT / "target").resolve()):
        raise ValueError("--out must be a task-owned directory under repository target/")
    cases = [name.strip() for name in args.cases.split(",") if name.strip()]
    sizes = [int(value) for value in args.sizes.split(",")]
    if not cases or not sizes or args.sphere_size < 8 or args.samples < 1 or any(n < 16 or not (n & (n - 1) == 0) for n in sizes):
        raise ValueError("Expected cases, power-of-two sizes >=16, sphere size >=8 and positive samples")
    paths = generate_inputs(args.out)
    if args.generate_inputs_only:
        save_json(args.out / "inputs/manifest.json", {name: {"path": str(path), "sha256": digest(path)}
                                                     for name, path in paths.items() if path.is_file()})
        print(f"Generated analytic panoramas and six-face lamps: {args.out / 'inputs'}")
        return
    for case in cases:
        if case not in paths:
            raise ValueError(f"Unknown case: {case}")
        if not paths[case].is_file():
            raise FileNotFoundError(f"Supply local acceptance input: {paths[case]}")
    if not args.analyze_only:
        generate(args, paths, cases, sizes)
    analyze(args, paths, cases, sizes)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Quality acceptance failed: {error}", file=sys.stderr)
        sys.exit(1)

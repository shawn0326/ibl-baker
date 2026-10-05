"""Independent continuous axial Gaussian-lamp control for the saved private pilot."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
ORDERS = (32, 64, 128)
BACKGROUND = .025
AMPLITUDE = (600., 300., 90.)
SIGMA_DEGREES = 1.2


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def split_intervals(sigma, alpha):
    # Resolve the two known axial scales without inspecting a baked result.
    cuts = [0., math.pi / 2]
    for scale in (sigma, alpha):
        cuts.extend(scale * multiple for multiple in (.25, .5, 1., 2., 4., 8.)
                    if 0. < scale * multiple < math.pi / 2)
    cuts = sorted(set(cuts))
    if len(cuts) - 1 > 16:
        raise ValueError("Analytic control exceeded its fixed sixteen-segment budget")
    return cuts


def integrate(distribution, roughness, sigma, order):
    if distribution not in ("ggx", "lambert") or not 0. < roughness <= 1. or sigma <= 0.:
        raise ValueError("Expected GGX/Lambert, roughness in (0,1], and positive angular width")
    alpha = roughness * roughness
    alpha_squared = alpha * alpha
    cuts = split_intervals(sigma, alpha)
    nodes, weights = np.polynomial.legendre.leggauss(order)
    numerator = denominator = 0.
    for start, end in zip(cuts[:-1], cuts[1:]):
        theta = (start + end) * .5 + (end - start) * .5 * nodes
        measure = (end - start) * .5 * weights * np.cos(theta) * np.sin(theta)
        if distribution == "ggx":
            # D(sqrt((1+cos(theta))/2)), evaluated with a stable half-angle
            # denominator rather than subtracting nearly equal numbers.
            factor = np.sin(theta * .5) ** 2 + alpha_squared * np.cos(theta * .5) ** 2
            measure *= alpha_squared / (math.pi * factor * factor)
        numerator += float(np.sum(measure * np.exp(-.5 * (theta / sigma) ** 2)))
        denominator += float(np.sum(measure))
    gain = numerator / denominator
    if not math.isfinite(gain) or not 0. <= gain <= 1. + 1e-13:
        raise ValueError("Analytic Gaussian control returned an invalid normalized gain")
    return {"order_per_segment": order, "segments": len(cuts) - 1,
            "quadrature_nodes": order * (len(cuts) - 1), "cuts_radians": cuts,
            "numerator": numerator, "denominator": denominator, "gain": gain,
            "rgb": (BACKGROUND + gain * np.asarray(AMPLITUDE)).tolist()}


def closed_normalizer(distribution, roughness):
    if distribution == "lambert":
        return .5
    a = roughness ** 4
    if a == 1.:
        return 1. / (2. * math.pi)
    return (4. * a * math.log(2. * a / (1. + a)) + 2. * (1. - a)) / (math.pi * (1. - a) ** 2)


def oracle(distribution, roughness, sigma):
    levels = [integrate(distribution, roughness, sigma, order) for order in ORDERS]
    expected_normalizer = closed_normalizer(distribution, roughness)
    normalizer_error = abs(levels[-1]["denominator"] - expected_normalizer) / expected_normalizer
    rgb = np.asarray(levels[-1]["rgb"])
    differences = [float(np.max(np.abs(np.asarray(right["rgb"]) - left["rgb"])))
                   for left, right in zip(levels[:-1], levels[1:])]
    # A fixed numerical limit, independent of whether either policy improves.
    passed = max(differences) <= 1e-6 and normalizer_error <= 1e-10
    return {"distribution": distribution, "roughness_f64": roughness,
            "sigma_degrees": math.degrees(sigma), "levels": levels,
            "closed_normalizer": expected_normalizer,
            "normalizer_relative_error": normalizer_error,
            "successive_max_component_changes": differences, "rgb": rgb.tolist(),
            "numerical_control_passes": passed}


def self_check():
    sigma = math.radians(SIGMA_DEGREES)
    controls = [oracle("ggx", roughness, sigma) for roughness in (.05, .2, .5, .7, 1.)]
    controls.append(oracle("lambert", 1., sigma))
    if not all(control["numerical_control_passes"] for control in controls):
        raise AssertionError("Finite analytic integration did not pass its normalizer/convergence checks")
    equality = float(np.max(np.abs(np.asarray(controls[-2]["rgb"]) - controls[-1]["rgb"])))
    if equality > 1e-12:
        raise AssertionError("Normalized roughness-one GGX is not the Lambertian control")
    # Integrating a constant shares the checked denominator; normalization must
    # preserve its actual supplied magnitude, not just the value one.
    constant = np.array([.25, 1., 4.])
    constant_error = 0.
    for control in controls:
        denominator = control["levels"][-1]["denominator"]
        reconstructed = constant * denominator / denominator
        constant_error = max(constant_error, float(np.max(np.abs(reconstructed - constant))))
    if constant_error > 2e-15:
        raise AssertionError("Normalized constant control changed color")
    # Check the continuous field's rotation invariance through explicit vectors.
    theta = np.array([sigma / 4, sigma / 2, sigma, sigma * 2, sigma * 4])
    phi = np.linspace(0., 2 * math.pi, 16, endpoint=False)
    expected = np.exp(-.5 * (theta / sigma) ** 2)
    rotation_error = 0.
    for axis in (np.array([1., 0., 0.]), np.array([1., 0., 1.]), np.ones(3)):
        axis /= np.linalg.norm(axis)
        tangent = np.cross(axis, [0., 1., 0.])
        tangent /= np.linalg.norm(tangent)
        bitangent = np.cross(axis, tangent)
        rays = (np.cos(theta)[:, None, None] * axis
                + np.sin(theta)[:, None, None]
                * (np.cos(phi)[None, :, None] * tangent + np.sin(phi)[None, :, None] * bitangent))
        angles = np.arccos(np.clip(rays @ axis, -1., 1.))
        actual = np.exp(-.5 * (angles / sigma) ** 2)
        rotation_error = max(rotation_error, float(np.max(np.abs(actual - expected[:, None]))))
    if rotation_error > 1e-10:
        raise AssertionError("Axial Gaussian field changed under rotation")
    widths = [1e-5, .01, 1.2, 180., 1e6]
    gains = [integrate("ggx", .2, math.radians(width), 128)["gain"] for width in widths]
    if not all(left <= right for left, right in zip(gains[:-1], gains[1:])):
        raise AssertionError("Gaussian gain is not monotonic in width")
    if gains[0] >= 1e-6 or abs(gains[-1] - 1.) >= 1e-8:
        raise AssertionError("Narrow/wide continuous Gaussian limits failed")
    return {"passes": True, "constant_max_component_error": constant_error,
            "r1_ggx_lambert_max_component_difference": equality,
            "rotation_field_max_gain_error": rotation_error,
            "width_limit_degrees": widths, "width_limit_gains": gains,
            "nominal_controls": controls}


def batch_identity(batch):
    return (batch["distribution"], batch["roughness_f32_bits"], batch["requested_proposals"], batch["file"])


def errors(actual, expected):
    difference = actual - expected
    scale = float(np.sqrt(np.mean(expected * expected)))
    return {"rgb": actual.tolist(), "signed_rgb_error": difference.tolist(),
            "mean_absolute_component_error": float(np.mean(np.abs(difference))),
            "max_absolute_component_error": float(np.max(np.abs(difference))),
            "rgb_rms_error": float(np.sqrt(np.mean(difference * difference))),
            "relative_rgb_rms_error": float(np.sqrt(np.mean(difference * difference))) / max(scale, 1e-30)}


def compare_saved(pilot):
    runs = {name: pilot / "runs/lamp-center" / name for name in ("baseline", "candidate")}
    metadata = {name: json.loads((directory / "metadata.json").read_text()) for name, directory in runs.items()}
    if metadata["baseline"]["directions"] != metadata["candidate"]["directions"]:
        raise ValueError("Saved policies have different query directions")
    if any(data["rotation_degrees"] != 0. for data in metadata.values()):
        raise ValueError("This control requires the unrotated lamp-center case")
    directions = np.asarray(metadata["baseline"]["directions"], dtype=float)
    center_indices = np.flatnonzero(np.all(directions == [1., 0., 0.], axis=1))
    if len(center_indices) == 0:
        raise ValueError("Saved pilot lacks an exact normal at the analytic lamp center")
    signatures = {name: [batch_identity(batch) for batch in data["probe_batches"]] for name, data in metadata.items()}
    if signatures["baseline"] != signatures["candidate"]:
        raise ValueError("Saved policies have different roughness/budget batches")
    if {batch["requested_proposals"] for batch in metadata["baseline"]["probe_batches"]} != {256, 1024}:
        raise ValueError("This control expects the declared 256/1024 proposal matrix")
    hashes = {}
    for name, directory in runs.items():
        for path in sorted(directory.glob("*")):
            if path.is_file():
                hashes[str(path.resolve())] = digest(path)
    for baseline_level, candidate_level in zip(metadata["baseline"]["source_levels"][:1],
                                               metadata["candidate"]["source_levels"][:1]):
        if baseline_level != candidate_level:
            raise ValueError("Saved policies have different base source layout")
        if any(digest(runs["baseline"] / name) != digest(runs["candidate"] / name)
               for name in baseline_level["files"]):
            raise ValueError("Saved policies do not share identical mip0")
    inputs = pilot / "inputs" / str(metadata["baseline"]["size"]) / "lamp-center"
    input_hashes = {str(path.resolve()): digest(path) for path in sorted(inputs.glob("*.exr"))}
    if len(input_hashes) != 6:
        raise ValueError("Expected all six saved analytic Gaussian source faces")
    rows = []
    for batch in metadata["baseline"]["probe_batches"]:
        roughness = struct.unpack("<f", struct.pack("<I", batch["roughness_f32_bits"]))[0]
        reference = oracle(batch["distribution"], roughness, math.radians(SIGMA_DEGREES))
        if not reference["numerical_control_passes"]:
            raise ValueError("An actual f32 roughness control failed its fixed numerical checks")
        expected = np.asarray(reference["rgb"])
        policies = {}
        for name, directory in runs.items():
            colors = np.fromfile(directory / batch["file"], dtype="<f4")
            if colors.size != len(directions) * 3 or not np.all(np.isfinite(colors)):
                raise ValueError(f"Invalid saved RGB f32 query data: {directory / batch['file']}")
            selected = colors.reshape(-1, 3)[center_indices].astype(float)
            if not np.array_equal(selected, np.broadcast_to(selected[0], selected.shape)):
                raise ValueError("Repeated identical center directions returned different colors")
            policies[name] = errors(selected[0], expected)
        baseline_error = policies["baseline"]["rgb_rms_error"]
        candidate_error = policies["candidate"]["rgb_rms_error"]
        rows.append({"distribution": batch["distribution"], "roughness_label": batch["roughness"],
                     "roughness_actual_f32": roughness, "roughness_f32_bits": batch["roughness_f32_bits"],
                     "requested_proposals": batch["requested_proposals"], "raw_file": batch["file"],
                     "oracle": reference, "policies": policies,
                     "candidate_minus_baseline_rms_error": candidate_error - baseline_error,
                     "candidate_to_baseline_rms_error_ratio": candidate_error / max(baseline_error, 1e-30)})
    return {"size": metadata["baseline"]["size"], "center_direction": [1., 0., 0.],
            "duplicate_center_indices": center_indices.tolist(), "shared_mip0_bitwise_equal": True,
            "input_sha256": input_hashes, "saved_output_sha256": hashes, "comparisons": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-packages", action="append", type=Path, default=[])
    parser.add_argument("--pilot", type=Path, default=ROOT / "target/mip-weighting/pilot")
    parser.add_argument("--out", type=Path, default=ROOT / "target/mip-weighting/analytic-lamp")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    for path in reversed(args.python_packages):
        sys.path.insert(0, str(path.resolve()))
    global np
    import numpy as np
    checks = self_check()
    if args.self_check:
        print(json.dumps({key: value for key, value in checks.items() if key != "nominal_controls"}, indent=2))
        return
    out = args.out.resolve()
    if out == (ROOT / "target").resolve() or not out.is_relative_to((ROOT / "target").resolve()):
        raise ValueError("Analytic diagnostic outputs must remain under repository target/")
    pilot = args.pilot.resolve()
    comparison = compare_saved(pilot)
    report = {"schema_version": 1, "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "tool_sha256": digest(__file__), "numpy_version": np.__version__,
              "source": "Continuous L(theta)=0.025+exp(-theta^2/(2*sigma^2))*[600,300,90], sigma=1.2 degrees",
              "target": "Normalized N=V GGX prefilter or normalized Lambertian convolution at the lamp center",
              "formula": "Integral_0^(pi/2) G(theta)*D(sqrt((1+cos(theta))/2))*cos(theta)*sin(theta)dtheta divided by the same integral without G; omit D for Lambertian",
              "normalizer_formula": "GGX a=r^4: [4*a*log(2*a/(1+a))+2*(1-a)]/[pi*(1-a)^2], with r=1 limit 1/(2*pi); Lambert=1/2",
              "method": "Independent float64 segmented Gauss-Legendre 32/64/128; no Hammersley, FIS, mip or production kernel reuse",
              "scope": "Supplemental continuous-source single-normal control. Differences include source projection/reconstruction and finite production sampling. It is neither the primary shared-mip0 oracle nor a complete physical BRDF material renderer. It does not modify the pilot gate or production default.",
              "fixed_limits": {"max_segments": 16, "max_order_per_segment": 128,
                               "max_successive_rgb_component_change": 1e-6, "max_normalizer_relative_error": 1e-10},
              "self_checks": checks, **comparison}
    # Ensure none of the concurrently existing saved artifacts changed while
    # reading this diagnostic. This tool never launches bakes or rewrites them.
    for path, expected in report["input_sha256"].items() | report["saved_output_sha256"].items():
        if digest(path) != expected:
            raise ValueError(f"Saved input/output changed during analytic analysis: {path}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# Continuous axial Gaussian-lamp diagnostic", "", report["scope"], "",
             "The independent one-dimensional integral uses 32/64/128 Gauss-Legendre nodes in each of at most sixteen analytically chosen angular intervals. Its normalizer agrees with the closed form, and normalized roughness-one GGX equals Lambertian.", "",
             "Both policies share bitwise identical mip zero. The reference uses the actual stored f32 roughness and a continuous 1.2-degree Gaussian at normal `(1,0,0)`. Errors therefore include the common source projection/reconstruction and the production proposal budget.", "",
             "| Kernel | Roughness | Proposals | Continuous RGB | Box RMS error | Angular RMS error | Angular/box error |",
             "| --- | ---: | ---: | --- | ---: | ---: | ---: |"]
    for row in report["comparisons"]:
        color = ", ".join(f"{value:.9g}" for value in row["oracle"]["rgb"])
        lines.append(f"| {row['distribution']} | {row['roughness_label']} | {row['requested_proposals']} | {color} | {row['policies']['baseline']['rgb_rms_error']:.9g} | {row['policies']['candidate']['rgb_rms_error']:.9g} | {row['candidate_to_baseline_rms_error_ratio']:.9g} |")
    lines += ["", "This supplemental control does not replace the bounded pilot's convergence rules or authorize a default policy change. Input, tool and saved output identities, signed/component errors and the complete quadrature convergence records are retained in `report.json`.", ""]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Saved continuous analytic lamp diagnostic: {out / 'report.json'}")


if __name__ == "__main__":
    main()

"""Verify and conservatively classify the private source-mip weighting pilot.

This analyzes fixed-direction normalized convolution diagnostics. It does not
declare physical ground truth, change production defaults, or run a bake.
Every uncertainty envelope is empirical and is explicitly not a strict bound.
"""
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
import re
import sys
import tempfile
import time

sys.dont_write_bytecode = True
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
if __name__ == "__main__":
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--python-packages", type=Path, action="append", default=[])
    options, _ = bootstrap.parse_known_args()
    for package_dir in reversed(options.python_packages):
        sys.path.insert(0, str(package_dir.resolve()))

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CASES = ("constant", "directional", "directional-rotated", "pisa", "qwantani",
         "lamp-center", "lamp-edge", "lamp-corner")
HDR_CASES = {"pisa", "qwantani"}
FACES = ("px", "nx", "py", "ny", "pz", "nz")
GROUPS = {"uniform": (0, 64), "axes_edges_corners": (64, 90), "lamp_neighborhoods": (90, 117)}
ROUGHNESSES = (.05, .2, .5, .7, 1.)
KERNELS = tuple(("ggx", i, r) for i, r in enumerate(ROUGHNESSES)) + (("lambert", 0, 1.),)
PROPOSALS = (256, 1024)
TOLERANCE = 1e-4
LUMA = np.array([.2126, .7152, .0722])
GATE = dict(relative_rmse_reduction=.05, uncertainty_multiplier=5,
            required_nonconstant_cases=2, required_hdr_cases=1, required_roughnesses=2,
            required_proposals=list(PROPOSALS))


class IntegrityError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise IntegrityError(message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def valid_sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def checked_file(path, expected):
    path = Path(path).resolve()
    require(valid_sha(expected), f"Missing or invalid SHA256: {path}")
    require(path.is_file() and not path.is_symlink(), f"Missing or unsupported file: {path}")
    require(digest(path) == expected, f"File hash mismatch: {path}")
    return path


def under_target(path):
    path = Path(path).resolve()
    require(path.is_relative_to((ROOT / "target").resolve()) and path != (ROOT / "target").resolve(),
            f"Analysis outputs and experiment artifacts must be under target/: {path}")
    return path


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path):
    def invalid(value):
        raise IntegrityError(f"Non-finite JSON token in {path}: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_pairs, parse_constant=invalid)


def inventory(directory, exclude_generation=False):
    result = {}
    for path in sorted(Path(directory).rglob("*")):
        require(not path.is_symlink(), f"Unexpected symlink in artifact inventory: {path}")
        if path.is_file() and not (exclude_generation and path == Path(directory) / "generation.json"):
            result[path.relative_to(directory).as_posix()] = digest(path)
    return result


def input_identity(path):
    path = Path(path).resolve(strict=True)
    if path.is_file():
        require(not path.is_symlink(), f"Unexpected input symlink: {path}")
        return dict(path=str(path), sha256=digest(path))
    require(path.is_dir(), f"Unsupported input: {path}")
    files = inventory(path)
    require(set(files) == {f"{face}.exr" for face in FACES}, f"Six-face input inventory is not exact: {path}")
    return dict(path=str(path), files=files)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_preparation(path, expected_sha):
    path = checked_file(under_target(path), expected_sha)
    manifest = load_json(path)
    prepare = load_module("mip_analysis_prepare", HERE / "prepare.py")
    identity = manifest.get("identity", {})
    require(manifest.get("schema_version") == 1 and identity.get("schema_version") == 1,
            "Preparation schema must be 1")
    require(identity.get("baseline_commit") == prepare.BASELINE, "Frozen production baseline differs")
    checked_file(HERE / "prepare.py", identity.get("prepare_sha256"))
    require(set(identity.get("helpers_sha256", {})) == set(prepare.HELPERS), "Incomplete helper provenance")
    helpers = {}
    for name in prepare.HELPERS:
        checked_file(HERE / name, identity["helpers_sha256"][name])
        helpers[name] = (HERE / name).read_bytes()
    config = ROOT / ".cargo/config.toml"
    require(identity.get("cargo_config_sha256") == (digest(config) if config.exists() else None), "Cargo config drift")
    require(prepare.verify_cached(manifest, identity), "Preparation is not a verified built pair")
    require(set(manifest.get("versions", {})) == {"baseline", "candidate"}, "Prepared pair is incomplete")
    archive_log = manifest["archive"]["command"]
    checked_file(archive_log["log_path"], archive_log.get("log_sha256"))
    require(archive_log.get("returncode") == 0, "Baseline archive command did not succeed")
    for side in ("baseline", "candidate"):
        version = manifest["versions"][side]
        expected = prepare.expected_snapshot(Path(manifest["archive"]["path"]), helpers, side == "candidate")
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in expected.items()}
        require(version["source_files"] == hashes, f"Unexpected {side} source snapshot scope")
        commands = version.get("commands", [])
        require(len(commands) == 6, f"Incomplete {side} build/check commands")
        require([c["command"][1] if c["command"][0] == "cargo" else c["command"][0] for c in commands]
                == ["fmt", "rustfmt", "build", "build", "test", "clippy"], f"Unexpected {side} check sequence")
        for command in commands:
            require(command.get("returncode") == 0, f"Failed prepared command: {command['command']}")
            if command["command"][0] == "cargo" and command["command"][1] in ("build", "test", "clippy"):
                require(all(flag in command["command"] for flag in ("--release", "--locked", "--offline")), "Build optimization/options differ")
        test = commands[4]
        require(test.get("tests_passed", 0) > 0, f"No passing {side} test suite")
        require(re.search(r"test result: ok\. \d+ passed;", Path(test["log_path"]).read_text(errors="replace")) is not None,
                f"Missing passing test result in {side} log")
    for record in identity.get("inputs", []):
        require(prepare.input_identity(record["path"]) == record, "Prepared input identity drift")
    return manifest


def verify_generation(directory, embedded, expected_identity, expected_command):
    directory = under_target(directory)
    saved = load_json(directory / "generation.json")
    require(saved == embedded, f"Embedded and saved generation records differ: {directory}")
    require(saved.get("identity") == expected_identity, f"Generation producer/input/probe identity differs: {directory}")
    require(valid_sha(expected_identity.get("producer")) and expected_identity.get("schema") == 1,
            f"Invalid generation schema or producer: {directory}")
    require(saved.get("command") == expected_command, f"Generation command differs: {directory}")
    require(saved.get("files") == inventory(directory, exclude_generation=True), f"Generation inventory is not exact: {directory}")
    require("metadata.json" in saved["files"] and "export.log" in saved["files"], f"Incomplete generation: {directory}")
    return load_json(directory / "metadata.json")


def _finite_rgb(rgb):
    value = np.asarray(rgb, dtype=np.float64)
    require(value.shape == (3,) and np.isfinite(value).all(), "Expected finite RGB triple")
    return value


def read_rgb(path, count):
    require(Path(path).stat().st_size == count * 3 * 4, f"Raw float payload length differs: {path}")
    values = np.fromfile(path, dtype="<f4").reshape(count, 3).astype(np.float64)
    require(np.isfinite(values).all(), f"Non-finite raw float payload: {path}")
    return values


def verify_metadata(metadata, directory, size, rotation):
    require(metadata.get("schema_version") == 1 and metadata.get("size") == size
            and metadata.get("rotation_degrees") == rotation and metadata.get("clamping") == "none"
            and metadata.get("storage") == "little-endian interleaved RGB IEEE754 f32", "Raw exporter metadata differs")
    directions = np.asarray(metadata.get("directions"), dtype=np.float64)
    require(directions.shape == (117, 3) and np.isfinite(directions).all()
            and np.max(np.abs(np.linalg.norm(directions, axis=1) - 1)) < 1e-6, "Actual probe directions differ")
    levels, n, level = [], size, 0
    while True:
        names = [f"source_m{level}_{face}.f32" for face in FACES]
        levels.append(dict(level=level, size=n, files=names))
        for name in names:
            read_rgb(directory / name, n * n)
        if n == 1:
            break
        n, level = max(1, n // 2), level + 1
    require(metadata.get("source_levels") == levels, "Source mip layout differs")
    expected = [(distribution, index, roughness, samples) for samples in PROPOSALS for distribution, index, roughness in KERNELS]
    batches = metadata.get("probe_batches", [])
    require(len(batches) == len(expected), "Missing/duplicate raw probe batches")
    for batch, (distribution, index, roughness, samples) in zip(batches, expected):
        bits = int(np.asarray([roughness], dtype=np.float32).view(np.uint32)[0])
        name = f"probes_ggx_s{samples}_r{index}.f32" if distribution == "ggx" else f"probes_lambert_s{samples}.f32"
        require(batch.get("distribution") == distribution and batch.get("requested_proposals") == samples
                and batch.get("kernel_proposals") == samples and batch.get("roughness_f32_bits") == bits
                and batch.get("file") == name, "Kernel proposal/roughness/file identity differs")
        accepted = np.asarray(batch.get("accepted_light_samples"))
        require(accepted.shape == (117,) and np.all(accepted == accepted.astype(np.int64))
                and np.all((accepted > 0) & (accepted <= samples)), "Accepted proposal counts differ")
        require(batch.get("accepted_light_samples_min") == int(accepted.min())
                and batch.get("accepted_light_samples_max") == int(accepted.max()), "Accepted sample range differs")
        read_rgb(directory / name, 117)
    expected_files = {"metadata.json", "export.log"} | {name for entry in levels for name in entry["files"]} | {b["file"] for b in batches}
    require(set(inventory(directory, True)) == expected_files, f"Unexpected raw export file inventory: {directory}")
    return directions


def _rms(values):
    values = np.asarray(values, dtype=np.float64)
    require(values.size > 0 and np.isfinite(values).all(), "RMS input must be nonempty and finite")
    scale = float(np.max(np.abs(values)))
    return 0. if scale == 0 else scale * float(np.sqrt(np.mean((values / scale) ** 2)))


@lru_cache(maxsize=12)
def _exact_kernel_normalizer(roughness, distribution):
    if distribution == "lambert":
        return .5
    reference = load_module("mip_analysis_reference_formula", HERE / "reference.py")
    return reference.ggx_normalizer(roughness)


def reference_evidence(record, normal, roughness, distribution, shared_source, constant=None, mandatory_local=False, source_bounds=None):
    """Return numerical best estimate, empirical spread, and conservative qualification."""
    require(isinstance(record, dict), "Expected a reference record object")
    if record.get("rgb") is None:
        return dict(rgb=None, qualified=False, spread=None, reasons=["No completed reference estimate"])
    rgb = _finite_rgb(record["rgb"])
    if source_bounds is not None:
        lower, upper = map(_finite_rgb, source_bounds)
        require(np.all(lower <= upper), "Invalid shared-source color range")
        # Positive normalized weights preserve the source range. Allow a
        # conservative floating accumulation margin, not a quality-gate floor.
        margin = np.maximum(np.abs(lower), np.abs(upper)) * (4 * 256 * 512 * np.finfo(np.float64).eps)
        require(np.all(rgb >= lower - margin) and np.all(rgb <= upper + margin), "Normalized reference RGB exceeds its shared f32 source range")
    require(record.get("target") == "shared_mip0", "Primary reference target is not shared mip0")
    if record.get("status") == "exact_constant":
        require(constant is not None and np.array_equal(rgb, constant), "Invalid exact-constant claim")
        return dict(rgb=rgb, qualified=True, spread=0., reasons=[])
    require(record.get("schema") == 1 and record.get("distribution") == distribution
            and record.get("roughness") == roughness and record.get("shared_source") == shared_source,
            "Reference source/kernel identity differs")
    require(all(record.get(k) is False for k in ("source_mips", "fis_lod", "production_hammersley")), "Reference used a production approximation")
    require(record.get("strict_error_bound") is False and record.get("relative_tolerance") == TOLERANCE,
            "Reference uncertainty semantics differ")
    expected_normal = normal / np.linalg.norm(normal)
    require(np.max(np.abs(_finite_rgb(record["normal"]) - expected_normal)) <= 1e-12, "Reference normal differs")
    reasons = []
    levels = record.get("levels", [])
    require(isinstance(levels, list) and len(levels) <= 4, "Reference level cap or schema differs")
    if record.get("status") != "converged_diagnostic":
        reasons.append(f"Primary reference status: {record.get('status')}")
    if len(levels) < 3:
        reasons.append("Fewer than three completed quadrature levels")
    spread = 0.
    scale = max(_rms(rgb), 1e-12)  # This floor reproduces the solver's diagnostic scale; it is not a gain threshold.
    for i, level in enumerate(levels):
        require((level.get("radial"), level.get("azimuth")) == ((32, 64), (64, 128), (128, 256), (256, 512))[i], "Unexpected reference level schedule")
        phases = level.get("phases", [])
        require(len(phases) == 2 and [p.get("offset_cells") for p in phases] == [0., .5], "Reference phase identity differs")
        for phase in phases:
            nodes = level["radial"] * level["azimuth"]
            require(phase.get("nodes") == nodes and isinstance(phase.get("support_hits"), int)
                    and 0 <= phase["support_hits"] <= nodes
                    and math.isfinite(phase.get("denominator", math.nan)) and phase["denominator"] > 0,
                    "Invalid completed quadrature node/denominator metadata")
        require(phases[0]["denominator"] == phases[1]["denominator"], "Azimuth phases have different kernel normalizers")
        phase_rgb = [_finite_rgb(p["rgb"]) for p in phases]
        require(np.max(np.abs(np.mean(phase_rgb, axis=0) - _finite_rgb(level["rgb"]))) <= 1e-12 * max(1., _rms(rgb)), "Reference phase average differs")
        require(math.isfinite(level.get("normalizer_relative_error", math.nan)) and level["normalizer_relative_error"] >= 0, "Invalid normalizer diagnostic")
        exact = _exact_kernel_normalizer(roughness, distribution)
        normalizer_error = abs(phases[0]["denominator"] - exact) / exact
        require(abs(normalizer_error - level["normalizer_relative_error"]) <= 1e-12 * max(1., normalizer_error), "Stored normalizer diagnostic differs from its actual denominator")
        if i >= len(levels) - 2:
            phase_spread = float(np.max(np.abs(phase_rgb[0] - phase_rgb[1])))
            spread = max(spread, phase_spread, normalizer_error * scale)
            if phase_spread / scale > TOLERANCE or normalizer_error > TOLERANCE:
                reasons.append("Final phase/normalizer diagnostic exceeds tolerance")
            if i > 0:
                change = max(float(np.max(np.abs(phase_rgb[j] - _finite_rgb(levels[i-1]["phases"][j]["rgb"])))) for j in range(2))
                spread = max(spread, change)
                if change / max(_rms(level["rgb"]), 1e-12) > TOLERANCE:
                    reasons.append("One of the final two level changes exceeds tolerance")
    if levels:
        require(np.array_equal(rgb, np.asarray(levels[-1]["rgb"])), "Reference estimate does not match final level")
    local_required = mandatory_local or record.get("local_crosscheck_required") is True
    if local_required:
        regions = record.get("support_regions", [])
        if not regions or record.get("local_crosscheck_required") is not True:
            reasons.append("Required HDR support is empty or was not declared for local checking")
        for region in regions:
            require(isinstance(region.get("face"), int) and 0 <= region["face"] < 6
                    and all(math.isfinite(region.get(k, math.nan)) for k in ("u0", "u1", "v0", "v1"))
                    and 0 <= region["u0"] < region["u1"] <= 1 and 0 <= region["v0"] < region["v1"] <= 1,
                    "Invalid recorded source-UV support rectangle")
        local = record.get("highlight_crosscheck")
        if not isinstance(local, dict):
            reasons.append("Required HDR support cross-check is missing")
        else:
            require(local.get("target") == "shared_mip0" and local.get("distribution") == distribution
                    and local.get("roughness") == roughness and local.get("shared_source") == shared_source
                    and local.get("normal") == record.get("normal") and local.get("regions") == record.get("support_regions"),
                    "Local/reference target, source, kernel or support identity differs")
            require(local.get("strict_error_bound") is False, "Local diagnostic is incorrectly labelled a bound")
            if local.get("status") != "consistent_local_diagnostic":
                reasons.append(f"Required local support status: {local.get('status')}")
            else:
                require(local.get("schema") == 1 and local.get("relative_tolerance") == TOLERANCE
                        and local.get("missed_highlight") is False and local.get("depth_limited") is False,
                        "Incomplete positive local classification metadata")
                require(isinstance(local.get("nodes"), int) and 0 < local["nodes"] <= local.get("max_nodes", 0) <= 100000
                        and isinstance(local.get("initial_cells"), int) and local["initial_cells"] > 0
                        and isinstance(local.get("leaf_cells"), int) and local["leaf_cells"] >= local["initial_cells"]
                        and 0 <= local.get("max_reached_depth", -1) <= local.get("max_depth", -1) <= 6
                        and math.isfinite(local.get("support_solid_angle", math.nan)) and local["support_solid_angle"] > 0,
                        "Invalid positive local integration budget/coverage metadata")
            if local.get("missed_highlight") is True or local.get("depth_limited") is True:
                reasons.append("Missed highlight or unresolved local depth limit")
            if local.get("local_rgb") is None:
                reasons.append("No completed independent local contribution")
            else:
                value = _finite_rgb(local["local_rgb"])
                primary_local = [_finite_rgb(p["local_rgb"]) for p in levels[-1]["phases"]]
                observed_error = _finite_rgb(local["observed_low_high_error_rgb"])
                require(np.all(observed_error >= 0), "Negative low/high diagnostic error")
                local_spread = max(float(np.max(np.abs(value - p))) for p in primary_local)
                local_spread = max(local_spread, float(np.max(np.abs(primary_local[0] - primary_local[1]))),
                                   float(np.max(observed_error)))
                spread = max(spread, local_spread)
                if any(p["support_hits"] == 0 for p in levels[-1]["phases"]) and np.max(np.abs(value)) > TOLERANCE * scale:
                    reasons.append("Primary quadrature missed a material independently integrated support contribution")
                if local_spread / scale > TOLERANCE:
                    reasons.append("Independent support contribution disagreement exceeds tolerance")
    require(math.isfinite(spread) and spread >= 0, "Non-finite or negative empirical reference spread")
    return dict(rgb=rgb, qualified=not reasons, spread=spread, reasons=sorted(set(reasons)))


def summarize_metric(a, b, references, selected, context):
    available = [i for i in selected if references[i]["rgb"] is not None]
    reasons = sorted({reason for i in selected for reason in references[i]["reasons"]})
    row = dict(context, selected_probes=len(selected), available_probes=len(available),
               qualified=bool(selected) and all(references[i]["qualified"] for i in selected),
               qualification_reasons=reasons, baseline_rmse=None, candidate_rmse=None,
               reference_rms=None, baseline_relative_rmse=None, candidate_relative_rmse=None,
               relative_rmse_reduction=None, rmse_delta=None, empirical_reference_rms=None,
               empirical_delta_envelope=None, delta_over_envelope=None, qualified_gain=False,
               qualified_retreat=False, diagnostic_retreat=False)
    if not available:
        return row
    r = np.asarray([references[i]["rgb"] for i in available])
    base, candidate, scale = _rms(a[available] - r), _rms(b[available] - r), _rms(r)
    spreads = [references[i]["spread"] for i in available]
    uncertainty = _rms(spreads) if all(s is not None for s in spreads) else None
    envelope = 2 * uncertainty if uncertainty is not None else None
    delta = base - candidate
    reduction = delta / base if base > 0 else (0. if candidate == 0 else None)
    stable = envelope is not None and abs(delta) > GATE["uncertainty_multiplier"] * envelope
    row.update(baseline_rmse=base, candidate_rmse=candidate, reference_rms=scale,
               baseline_relative_rmse=base / scale if scale > 0 else (0. if base == 0 else None),
               candidate_relative_rmse=candidate / scale if scale > 0 else (0. if candidate == 0 else None),
               relative_rmse_reduction=reduction, rmse_delta=delta, empirical_reference_rms=uncertainty,
               empirical_delta_envelope=envelope,
               delta_over_envelope=delta / envelope if envelope is not None and envelope > 0 else None,
               qualified_gain=row["qualified"] and stable and reduction is not None and reduction >= .05 and delta > 0,
               qualified_retreat=row["qualified"] and stable and delta < 0,
               diagnostic_retreat=delta < 0)
    require(all(value is None or math.isfinite(value) for key, value in row.items()
                if key in ("baseline_rmse", "candidate_rmse", "reference_rms", "baseline_relative_rmse",
                           "candidate_relative_rmse", "relative_rmse_reduction", "rmse_delta",
                           "empirical_reference_rms", "empirical_delta_envelope", "delta_over_envelope")),
            "Non-finite derived metric")
    return row


def matrix_issues(screen):
    issues = []
    if screen.get("state") != "complete":
        issues.append("Screen state is not complete")
    if screen.get("size") != 256:
        issues.append("The approved initial 256 pilot matrix was not run")
    require(screen.get("schema") == 1 and screen.get("quality_gate") == GATE, "Screen schema or gate was altered")
    require(screen.get("roughnesses") == list(ROUGHNESSES) and screen.get("proposals") == list(PROPOSALS)
            and screen.get("probe_groups") == {k: list(v) for k, v in GROUPS.items()}, "Requested numerical matrix differs")
    names = [c.get("case") for c in screen.get("cases", [])]
    require(len(names) == len(set(names)) and not set(names) - set(CASES), "Duplicate or unknown cases")
    missing = sorted(set(CASES) - set(names))
    if missing:
        issues.append(f"Missing cases: {', '.join(missing)}")
    for case in screen.get("cases", []):
        seen = []
        for batch in case.get("batches", []):
            key = batch.get("distribution"), batch.get("roughness")
            require(key not in seen and key in {(d, r) for d, _, r in KERNELS}, f"Duplicate or unknown batch: {case['case']} {key}")
            seen.append(key)
            metrics = [(m.get("proposals"), m.get("group")) for m in batch.get("metrics", [])]
            require(len(metrics) == len(set(metrics)), "Duplicate metric rows")
            if set(metrics) != {(s, g) for s in PROPOSALS for g in GROUPS}:
                issues.append(f"Missing metric matrix: {case['case']} {key}")
        if set(seen) != {(d, r) for d, _, r in KERNELS}:
            issues.append(f"Missing kernel matrix: {case['case']}")
    return issues


def classify(rows, scope_issues):
    scope_issues = list(scope_issues)
    expected = {(case, distribution, roughness, samples, group, region)
                for case in CASES for distribution, _, roughness in KERNELS for samples in PROPOSALS
                for group in (*GROUPS, "all_probes") for region in ("all", "brightest_5pct_reference")}
    actual = [(r["case"], r["distribution"], r["roughness"], r["proposals"], r["group"], r["region"]) for r in rows]
    require(len(actual) == len(set(actual)), "Duplicate analysis metric rows")
    if set(actual) != expected:
        scope_issues.append("The recomputed analysis matrix is missing required cases/kernels/budgets/groups/regions")
    nonconstant = [r for r in rows if r["case"] != "constant"]
    grouped = {}
    for row in nonconstant:
        key = row["case"], row["distribution"], row["roughness"], row["group"], row["region"]
        grouped.setdefault(key, {})[row["proposals"]] = row
    repeated_gains, stable_retreats = {}, []
    for key, budgets in grouped.items():
        if set(budgets) != set(PROPOSALS):
            continue
        retreat_budgets = [samples for samples, row in budgets.items() if row["qualified_retreat"]]
        if retreat_budgets:
            stable_retreats.append(dict(case=key[0], distribution=key[1], roughness=key[2], group=key[3], region=key[4],
                                       proposals=sorted(retreat_budgets), repeated_at_both_budgets=len(retreat_budgets) == 2))
        if key[1] == "ggx" and key[3] in GROUPS and all(r["qualified_gain"] for r in budgets.values()):
            repeated_gains.setdefault((key[0], key[3], key[4]), []).append(key[2])
    cases = sorted({key[0] for key, roughnesses in repeated_gains.items() if len(set(roughnesses)) >= 2})
    witnesses = [dict(case=key[0], group=key[1], region=key[2], roughnesses=sorted(set(roughnesses)), proposals=list(PROPOSALS))
                 for key, roughnesses in sorted(repeated_gains.items()) if len(set(roughnesses)) >= 2]
    repeat_gate = len(cases) >= 2 and bool(set(cases) & HDR_CASES)
    unknown = [r for r in rows if not r["qualified"]]
    complete = not scope_issues and not unknown
    if not complete:
        category = "evidence_insufficient"
    elif repeat_gate and not stable_retreats:
        category = "worth_followup"
    elif stable_retreats and (repeat_gate or any(r["qualified_gain"] for r in nonconstant)):
        category = "mixed_benefits"
    else:
        category = "no_repeatable_benefit"
    return dict(classification=category, production_default="unchanged cube-UV box", production_change_authorized=False,
                expansion_gate_passed=category == "worth_followup", matrix_and_reference_scope_complete=complete,
                repeated_gain_gate_passed=repeat_gate, repeated_gain_cases=cases, repeated_gain_witnesses=witnesses,
                stable_retreats_blocking_expansion=stable_retreats, unknown_metric_rows=len(unknown),
                scope_issues=scope_issues, diagnostic_retreat_rows=sum(r["diagnostic_retreat"] for r in rows),
                qualified_retreat_rows=sum(r["qualified_retreat"] for r in rows))


def analyze_screen(screen_path, build_manifest=None):
    """Read-only verification and computation; the caller chooses whether to save."""
    started = time.perf_counter()
    screen_path = under_target(screen_path)
    screen_sha = digest(screen_path)
    screen = load_json(screen_path)
    require(screen.get("state") == "complete", "Screen is not complete; analyze only the frozen completed pilot")
    issues = matrix_issues(screen)
    expected_tools = {"scripts/mip-weighting/screen.py", "scripts/mip-weighting/reference.py", "scripts/source-sampling/quality.py"}
    require({key.replace("\\", "/") for key in screen.get("tools", {})} == expected_tools
            and len(screen.get("tools", {})) == len(expected_tools), "Incomplete numerical tool provenance")
    for relative, sha in screen["tools"].items():
        checked_file(ROOT / relative, sha)
    preparation_path = Path(build_manifest) if build_manifest else ROOT / "target/mip-weighting/preparation.json"
    preparation = verify_preparation(preparation_path, screen.get("preparation_sha256"))
    require(screen.get("baseline_commit") == preparation["identity"]["baseline_commit"], "Screen baseline differs")
    require(screen.get("screen_only") is True and screen.get("production_default") == "unchanged cube-UV box", "Production scope differs")
    out = screen_path.parent
    probes = out / "probes.csv"
    probe_sha = digest(probes)
    csv_directions = np.loadtxt(probes, delimiter=",", skiprows=1)
    require(csv_directions.shape == (117, 3) and np.isfinite(csv_directions).all(), "Probe CSV shape differs")
    rows, verified, reference_files, unknown_probes = [], [], {}, []
    size = screen["size"]
    for case in screen["cases"]:
        name, rotation = case["case"], 37. if case["case"] == "directional-rotated" else 0.
        expected_input = (ROOT / "fixtures/inputs/pisa.hdr" if name == "pisa" else
                          ROOT / "target/ibl-comparison/inputs/qwantani_noon_puresky_1k.hdr" if name == "qwantani" else
                          out / "inputs" / str(size) / name)
        actual_input = input_identity(expected_input)
        require(case.get("input") == actual_input and case.get("rotation") == rotation
                and case.get("mip0_bitwise_equal") is True, f"Case input/rotation/parity claim differs: {name}")
        directories, metadata = {}, {}
        for side in ("baseline", "candidate"):
            directory = out / "runs" / name / side
            producer = preparation["versions"][side]
            identity = dict(schema=1, producer=producer["exporter_sha256"], input=actual_input,
                            size=size, rotation=rotation, probes_sha256=probe_sha)
            command = [producer["exporter"], actual_input["path"], str(directory), "--size", str(size),
                       "--rotation", str(rotation), "--probes", str(probes)]
            metadata[side] = verify_generation(directory, case["generations"][side], identity, command)
            verify_metadata(metadata[side], directory, size, rotation)
            directories[side] = directory
        require(metadata["baseline"] == metadata["candidate"], f"Exporter layouts, actual directions, or accepted proposals differ: {name}")
        directions = np.asarray(metadata["baseline"]["directions"], dtype=np.float64)
        expected_dirs = csv_directions / np.linalg.norm(csv_directions, axis=1)[:, None]
        require(np.max(np.abs(expected_dirs - directions)) < 8 * np.finfo(np.float32).eps, "Actual probes differ from CSV directions")
        for face in FACES:
            require(digest(directories["baseline"] / f"source_m0_{face}.f32") == digest(directories["candidate"] / f"source_m0_{face}.f32"), f"Mip0 is not bitwise identical: {name}/{face}")
        faces = np.asarray([read_rgb(directories["baseline"] / f"source_m0_{face}.f32", size * size).reshape(size, size, 3) for face in FACES])
        shared_source = dict(source_size=size,
                             shared_mip0_rgb_f64_sha256=hashlib.sha256(memoryview(np.ascontiguousarray(faces, dtype="<f8")).cast("B")).hexdigest(),
                             hash_representation="six faces in px,nx,py,ny,pz,nz order; contiguous little-endian RGB f64",
                             sampler_source=str((ROOT / "scripts/source-sampling/quality.py").resolve()))
        constant = faces[0, 0, 0] if np.array_equal(faces, np.broadcast_to(faces[0, 0, 0], faces.shape)) else None
        source_bounds = np.min(faces, axis=(0, 1, 2)), np.max(faces, axis=(0, 1, 2))
        require(name != "constant" or constant is not None, "Constant case is not constant")
        sensitive = []
        if name in HDR_CASES:
            base = read_rgb(directories["baseline"] / "probes_ggx_s1024_r2.f32", 117)
            candidate = read_rgb(directories["candidate"] / "probes_ggx_s1024_r2.f32", 117)
            sensitive = sorted(set(np.argsort(base @ LUMA)[-4:].tolist() + np.argsort(np.linalg.norm(candidate - base, axis=1))[-4:].tolist()))
            require(case.get("sensitive_probe_indices") == sensitive, "HDR sensitive-probe selection differs")
        for batch in case.get("batches", []):
            distribution, roughness = batch["distribution"], batch["roughness"]
            index = ROUGHNESSES.index(roughness) if distribution == "ggx" else 0
            actual_r = float(np.float32(roughness))
            require(batch.get("actual_roughness") == actual_r and batch.get("total_probes") == 117, "Reference batch roughness/count differs")
            ref_path = out / "references" / name / f"{distribution}_r{index}.json"
            require(Path(batch["reference_file"]).resolve() == ref_path.resolve(), "Reference path differs")
            checked_file(ref_path, batch.get("reference_sha256"))
            references = load_json(ref_path)
            require(isinstance(references, list) and len(references) == 117, "Reference inventory has missing probes")
            evidence = [reference_evidence(record, directions[i], actual_r, distribution, shared_source,
                                           constant=constant if name == "constant" else None, mandatory_local=i in sensitive,
                                           source_bounds=source_bounds)
                        for i, record in enumerate(references)]
            reference_files[str(ref_path)] = batch["reference_sha256"]
            unknown_probes += [dict(case=name, distribution=distribution, roughness=roughness, probe=i, reasons=e["reasons"])
                               for i, e in enumerate(evidence) if not e["qualified"]]
            for samples in PROPOSALS:
                filename = f"probes_ggx_s{samples}_r{index}.f32" if distribution == "ggx" else f"probes_lambert_s{samples}.f32"
                base = read_rgb(directories["baseline"] / filename, 117)
                candidate = read_rgb(directories["candidate"] / filename, 117)
                for group, (first, last) in (GROUPS | {"all_probes": (0, 117)}).items():
                    selected = list(range(first, last))
                    available = [i for i in selected if evidence[i]["rgb"] is not None]
                    if available:
                        luminance = np.asarray([evidence[i]["rgb"] for i in available]) @ LUMA
                        bright = [i for i, value in zip(available, luminance) if value >= np.quantile(luminance, .95)]
                    else:
                        bright = []
                    bright_mask_complete = len(available) == len(selected) and all(evidence[i]["qualified"] for i in selected)
                    for region, indices in (("all", selected), ("brightest_5pct_reference", bright)):
                        context = dict(case=name, distribution=distribution, roughness=roughness,
                                       actual_roughness=actual_r, proposals=samples, group=group, region=region,
                                       bright_mask_complete=bright_mask_complete, reference_file=str(ref_path))
                        row = summarize_metric(base, candidate, evidence, indices, context)
                        if region != "all" and not bright_mask_complete:
                            row["qualified"] = row["qualified_gain"] = row["qualified_retreat"] = False
                            row["qualification_reasons"].append("Bright ranking includes missing or unqualified reference probes")
                        rows.append(row)
        verified.append(dict(case=name, input=actual_input, source_shared_mip0=shared_source, sensitive_probe_indices=sensitive,
                             generation_manifest_sha256={side: digest(directories[side] / "generation.json") for side in directories}))
    require(digest(screen_path) == screen_sha, "Screen manifest changed during analysis")
    for relative, sha in screen["tools"].items():
        checked_file(ROOT / relative, sha)
    checked_file(preparation_path, screen["preparation_sha256"])
    for path, sha in reference_files.items():
        checked_file(path, sha)
    for case in screen["cases"]:
        require(input_identity(case["input"]["path"]) == case["input"], "Input changed during analysis")
        for side in ("baseline", "candidate"):
            directory = out / "runs" / case["case"] / side
            require(inventory(directory, True) == case["generations"][side]["files"]
                    and load_json(directory / "generation.json") == case["generations"][side], "Generation changed during analysis")
    decision = classify(rows, issues)
    return dict(schema=1, state="analyzed", **decision, source_screen=str(screen_path), source_screen_sha256=screen_sha,
                preparation=str(Path(preparation_path).resolve()), preparation_sha256=screen["preparation_sha256"],
                tools=screen["tools"] | {"scripts/mip-weighting/analyze.py": digest(__file__)}, probes_sha256=probe_sha,
                quality_gate=GATE, verified_cases=verified, reference_files=reference_files, unknown_reference_probes=unknown_probes,
                uncertainty={"strict_error_bound": False,
                             "probe_spread": "maximum final two phase-wise level changes, phase differences, normalizer diagnostic, and required HDR local differences",
                             "aggregate": "RMS of per-probe maximum RGB-component spreads; same fixed reference bright mask",
                             "rmse_delta_envelope": "2 times aggregate reference spread, from RMSE's 1-Lipschitz dependence on reference",
                             "gain": "relative RMSE reduction >=5% and positive RMSE delta >5 times the empirical delta envelope",
                             "retreat": "any qualified negative delta beyond 5 empirical envelopes; both-budget repetition reported separately; no extra 5% threshold",
                             "limitation": "Empirical diagnostics cannot certify global HDR convolution error or physical rendering truth"},
                bright_region="Top 5% reference luminance within each fixed probe group; ties may increase the count",
                all_probes_role="Additional fixed 117-probe diagnostic/retreat scope; excluded from repeated-gain witnesses",
                immutable_source_assumption="Common Cubemap faces/padded were not mutated after construction in the verified screen tool",
                production_change=False, not_run=screen.get("not_run", []), rows=rows,
                analysis_seconds=time.perf_counter() - started)


def write_analysis(report, output):
    output = under_target(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "analysis.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    rows = report.get("rows", [])
    fields = list(rows[0]) if rows else ["case", "distribution", "roughness", "proposals", "group", "region", "qualified"]
    with (output / "metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value) if isinstance(value, (dict, list)) else value for key, value in row.items()})
    retreat_rows = [row for row in rows if row.get("diagnostic_retreat")]
    unknown = report.get("unknown_reference_probes", [])
    text = ["# Source-mip weighting pilot analysis", "", f"Classification: **{report['classification']}**.", "",
            "Production keeps the cube-UV box filter. This is a private screening result, not authorization to change production.", "",
            f"Expansion gate passed: {report.get('expansion_gate_passed', False)}. Complete required scope: {report.get('matrix_and_reference_scope_complete', False)}.",
            f"Repeated gain cases: {', '.join(report.get('repeated_gain_cases', [])) or 'none'}.",
            f"Unknown reference probes: {len(unknown)}. Diagnostic retreat rows: {len(retreat_rows)}.", "",
            "## Evidence and uncertainty", "",
            "Numerical references integrate the shared immutable mip-zero cubemap using normalized N=V GGX or Lambert kernels. They are not a full physical material renderer.",
            "The maximum final two phase-wise changes, azimuth phase spread, normalizer discrepancy and required HDR local discrepancy form a per-probe empirical spread. Its group RMS gives E; the RMSE-difference envelope is 2E. Neither is a strict error bound.",
            "A gain must reduce RMSE by at least 5% and exceed five empirical difference envelopes, at both 256/1024 proposal budgets and two GGX roughnesses in the same case/group/region. At least two nonconstant cases, including HDR, are required. Any stable qualified nonconstant retreat blocks expansion; repetition at both budgets is reported separately.",
            "Missing matrix entries, unresolved primary references, or any required HDR local check prevent a positive conclusion. Additional all-probe rows check retreats but cannot create repeated-gain witnesses.", "",
            "## Verification", "", f"Screen: `{report.get('source_screen', '')}`.",
            f"Screen SHA256: `{report.get('source_screen_sha256', '')}`.",
            ("Tool, frozen source, build/test log, binary, input, probe CSV, exact generation inventory, shared-mip0, and reference hashes were rechecked. Numeric metrics are recomputed from raw RGB floats."
             if report.get("state") == "analyzed" else "Verification stopped at an integrity rejection; no metric or expansion conclusion is accepted."), "",
            "## Scope gaps", ""]
    text += [f"- {issue}" for issue in report.get("scope_issues", [])] or ["- No missing matrix entries."]
    if report.get("integrity_errors"):
        text += [f"- Integrity rejection: {error}" for error in report["integrity_errors"]]
    text += ["", "## Repeated gain witnesses", ""]
    text += [f"- {w['case']}, {w['group']}/{w['region']}, r={w['roughnesses']}, both proposal budgets."
             for w in report.get("repeated_gain_witnesses", [])] or ["- None."]
    text += ["", "## Stable retreats blocking expansion", ""]
    text += [f"- {w['case']} {w['distribution']} r={w['roughness']}, {w['group']}/{w['region']}, proposals={w['proposals']}; repeats at both budgets={w['repeated_at_both_budgets']}."
             for w in report.get("stable_retreats_blocking_expansion", [])] or ["- No qualified repeated retreat."]
    text += ["", "## All observed diagnostic retreats", "",
             "Every row below is retained, including small changes and unqualified references. Full numeric data and qualification reasons are in metrics.csv and analysis.json.", ""]
    for row in retreat_rows:
        qualification = "qualified" if row["qualified"] else "; ".join(row["qualification_reasons"]) or "incomplete bright ranking"
        text.append(f"- {row['case']} {row['distribution']} r={row['roughness']:g}, {row['proposals']} proposals, {row['group']}/{row['region']}: RMSE {row['baseline_rmse']:.8g} -> {row['candidate_rmse']:.8g}; {qualification}; stable={row['qualified_retreat']}.")
    text += ["", "## Unresolved reference scopes", ""]
    counts = {}
    for item in unknown:
        key = item["case"], item["distribution"], item["roughness"]
        counts[key] = counts.get(key, 0) + 1
    text += [f"- {key[0]} {key[1]} r={key[2]}: {count}/117 unresolved probes." for key, count in sorted(counts.items())] or ["- None."]
    text += ["", "## Not run", ""] + [f"- {item}." for item in report.get("not_run", [])]
    (output / "analysis.md").write_text("\n".join(text) + "\n", encoding="utf-8")


def run_self_checks():
    checks = []
    def check(name, condition):
        require(condition, f"Analysis self-check failed: {name}")
        checks.append(dict(name=name, passed=True))
    def rows_for(cases, uncertain=False, retreat=False):
        rows = []
        for name in CASES:
            for distribution, _, roughness in KERNELS:
                for samples in PROPOSALS:
                    for group in (*GROUPS, "all_probes"):
                        for region in ("all", "brightest_5pct_reference"):
                            affected = name in cases and distribution == "ggx" and roughness in (.5, .7) and group == "uniform" and region == "all"
                            rows.append(dict(case=name, distribution=distribution, roughness=roughness, proposals=samples,
                                             group=group, region=region, qualified=not (uncertain and affected),
                                             qualified_gain=affected and not uncertain and not retreat,
                                             qualified_retreat=affected and not uncertain and retreat,
                                             diagnostic_retreat=affected and retreat))
        return rows
    gains = rows_for(["directional", "pisa"])
    check("repeated_qualified_gain_can_pass", classify(gains, [])["classification"] == "worth_followup")
    check("uncertain_cannot_pass", classify(rows_for(["directional", "pisa"], uncertain=True), [])["classification"] == "evidence_insufficient")
    check("missing_matrix_cannot_pass", classify(gains, ["Missing lamp case"])["classification"] == "evidence_insufficient")
    check("hdr_witness_is_required", classify(rows_for(["directional", "lamp-center"]), [])["classification"] == "no_repeatable_benefit")
    check("single_budget_cannot_pass", classify([r for r in gains if r["proposals"] == 256], [])["classification"] == "evidence_insufficient")
    check("missing_case_subset_cannot_pass", classify([r for r in gains if r["case"] != "lamp-corner"], [])["classification"] == "evidence_insufficient")
    mixed = [dict(row, qualified_retreat=True, diagnostic_retreat=True) if row["case"] == "lamp-edge"
             and row["roughness"] == .5 and row["proposals"] == 1024 else row for row in gains]
    check("stable_retreat_blocks_expansion", classify(mixed, [])["classification"] == "mixed_benefits")
    check("rms_large_finite_input_is_stable", math.isfinite(_rms([1e200, 1e200, 1e200])) and _rms([1e200] * 3) == 1e200)
    sample = dict(schema=1, state="complete", size=256, quality_gate=GATE, roughnesses=list(ROUGHNESSES), proposals=list(PROPOSALS),
                  probe_groups={k: list(v) for k, v in GROUPS.items()}, cases=[])
    check("strict_case_matrix_checked", bool(matrix_issues(sample)))
    source = dict(source_size=1, shared_mip0_rgb_f64_sha256="a"*64)
    levels = []
    for radial, azimuth in ((32, 64), (64, 128), (128, 256)):
        nodes = radial * azimuth
        phases = [dict(offset_cells=offset, rgb=[1., 1., 1.], local_rgb=[1., 1., 1.],
                       nodes=nodes, support_hits=nodes, denominator=.5) for offset in (0., .5)]
        levels.append(dict(radial=radial, azimuth=azimuth, phases=phases, rgb=[1., 1., 1.], normalizer_relative_error=0.))
    reference = dict(schema=1, status="converged_diagnostic", target="shared_mip0", distribution="lambert", roughness=1.,
                     shared_source=source, source_mips=False, fis_lod=False, production_hammersley=False,
                     strict_error_bound=False, relative_tolerance=TOLERANCE, normal=[0., 0., 1.], rgb=[1., 1., 1.], levels=levels)
    def evidence(value, mandatory=False):
        return reference_evidence(value, np.array([0., 0., 1.]), 1., "lambert", source, mandatory_local=mandatory)
    check("valid_primary_metadata_qualified", evidence(reference)["qualified"])
    excessive = json.loads(json.dumps(reference))
    excessive["rgb"] = [1e200] * 3
    try:
        reference_evidence(excessive, np.array([0., 0., 1.]), 1., "lambert", source,
                           source_bounds=(np.zeros(3), np.ones(3)))
    except IntegrityError:
        check("reference_outside_actual_source_range_rejected", True)
    else:
        check("reference_outside_actual_source_range_rejected", False)
    unknown_local = json.loads(json.dumps(reference))
    check("missing_mandatory_local_not_qualified", not evidence(unknown_local, True)["qualified"])
    invalid = json.loads(json.dumps(reference))
    invalid["levels"][0]["phases"][0]["denominator"] = 0.
    try:
        evidence(invalid)
    except IntegrityError:
        check("zero_denominator_rejected", True)
    else:
        check("zero_denominator_rejected", False)
    local = dict(schema=1, status="consistent_local_diagnostic", target="shared_mip0", distribution="lambert", roughness=1.,
                 shared_source=source, normal=[0., 0., 1.], strict_error_bound=False, relative_tolerance=TOLERANCE,
                 missed_highlight=False, depth_limited=False, nodes=120, max_nodes=100000, initial_cells=6, leaf_cells=6,
                 max_reached_depth=0, max_depth=6, support_solid_angle=4*math.pi, local_rgb=[1., 1., 1.],
                 observed_low_high_error_rgb=[0., 0., 0.])
    regions = [dict(face=f, u0=0., u1=1., v0=0., v1=1.) for f in range(6)]
    good_local = json.loads(json.dumps(reference))
    good_local.update(local_crosscheck_required=True, support_regions=regions, highlight_crosscheck=dict(local, regions=regions))
    check("valid_required_local_metadata_qualified", evidence(good_local, True)["qualified"])
    empty = json.loads(json.dumps(good_local))
    empty["support_regions"] = empty["highlight_crosscheck"]["regions"] = []
    empty["local_crosscheck_required"] = False
    check("empty_mandatory_support_is_not_qualified", not evidence(empty, True)["qualified"])
    for name, mutate in (("negative_local_error_rejected", lambda x: x["highlight_crosscheck"].update(observed_low_high_error_rgb=[-1., -1., -1.])),
                         ("missing_failure_flag_rejected", lambda x: x["highlight_crosscheck"].pop("missed_highlight")),
                         ("forged_normalizer_error_rejected", lambda x: x["levels"][-1].update(normalizer_relative_error=.5))):
        invalid = json.loads(json.dumps(good_local))
        mutate(invalid)
        try:
            evidence(invalid, True)
        except IntegrityError:
            check(name, True)
        else:
            check(name, False)
    # Exercise real file hashes and exact inventories in a temporary target tree.
    temp_parent = under_target(ROOT / "target/mip-weighting/analysis-self-check")
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_parent) as temporary:
        directory = under_target(temporary)
        for name, value in (("metadata.json", "{}"), ("export.log", "ok"), ("probes_ggx_s256_r0.f32", "raw")):
            (directory / name).write_text(value)
        identity = dict(schema=1, producer="a"*64, input={"fixture": "test"}, size=256, rotation=0., probes_sha256="b"*64)
        command = ["fixture.exe", "source", str(directory)]
        record = dict(identity=identity, command=command, files=inventory(directory, True))
        (directory / "generation.json").write_text(json.dumps(record))
        check("valid_saved_generation", verify_generation(directory, record, identity, command) == {})
        (directory / "extra_mip.f32").write_text("unexpected")
        try:
            verify_generation(directory, record, identity, command)
        except IntegrityError:
            check("extra_unrecorded_output_rejected", True)
        else:
            check("extra_unrecorded_output_rejected", False)
        (directory / "extra_mip.f32").unlink()
        expected = digest(directory / "export.log")
        (directory / "export.log").write_text("modified")
        try:
            checked_file(directory / "export.log", expected)
        except IntegrityError:
            check("modified_real_hash_rejected", True)
        else:
            check("modified_real_hash_rejected", False)
    return dict(schema=1, passed=True, checks=checks, strict_error_bound=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen", type=Path, default=ROOT / "target/mip-weighting/pilot/screen.json")
    parser.add_argument("--build-manifest", type=Path)
    parser.add_argument("--out", type=Path, help="Output directory under target/; default is screen's directory")
    parser.add_argument("--python-packages", type=Path, action="append", default=[])
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        print(json.dumps(run_self_checks(), indent=2))
        return
    output = args.out or args.screen.resolve().parent
    try:
        report = analyze_screen(args.screen, args.build_manifest)
    except (ValueError, TypeError, KeyError, IndexError, ArithmeticError, AttributeError, OSError) as error:
        report = dict(schema=1, state="integrity_rejected", classification="evidence_insufficient",
                      production_default="unchanged cube-UV box", production_change=False,
                      expansion_gate_passed=False, matrix_and_reference_scope_complete=False,
                      source_screen=str(args.screen.resolve()), integrity_errors=[str(error)], rows=[])
        write_analysis(report, output)
        print(f"Integrity rejected; production keeps box: {error}", file=sys.stderr)
        raise SystemExit(2)
    write_analysis(report, output)
    print(json.dumps({key: report[key] for key in ("classification", "expansion_gate_passed", "repeated_gain_cases", "unknown_metric_rows", "diagnostic_retreat_rows")}, indent=2))


if __name__ == "__main__":
    main()

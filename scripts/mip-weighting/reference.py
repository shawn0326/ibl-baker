"""Bounded, independent f64 convolution diagnostics for the mip-weighting pilot.

The target is a normalized N=V GGX convolution, or normalized Lambert
convolution. It is not a full physical renderer. Integration samples the
continuous analytic field or the explicitly labelled shared mip-zero field;
there are no source mips, FIS LODs, or production Hammersley sequences here.

Convergence and local cross-check errors are diagnostics, never rigorous error
bounds. A deadline, unresolved local support, or disagreement produces
``uncertain``. Callers must not turn uncertain evidence into a positive result.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import heapq
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
# The CLI accepts the same isolated-package option as the phase-two tools.
if __name__ == "__main__":
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--python-packages", type=Path, action="append", default=[])
    options, _ = bootstrap.parse_known_args()
    for package_dir in reversed(options.python_packages):
        sys.path.insert(0, str(package_dir.resolve()))

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
LEVELS = ((32, 64), (64, 128), (128, 256), (256, 512))
RELATIVE_TOLERANCE = 1e-4
FACES = ("px", "nx", "py", "ny", "pz", "nz")


class _Limit(RuntimeError):
    pass


class _Failure(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _quality():
    """Reuse only the previously checked common cube reconstruction."""
    path = ROOT / "scripts/source-sampling/quality.py"
    spec = importlib.util.spec_from_file_location("mip_weighting_common_cube", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.np = np
    return module


def shared_mip0_sampler(faces):
    """Return phase-two's f64 Cubemap; pass ``cube.sample`` to the integrator."""
    return _quality().Cubemap(_faces(faces))


def _faces(faces):
    values = np.asarray(faces, dtype=np.float64)
    if (values.ndim != 4 or values.shape[0] != 6 or values.shape[-1] != 3
            or values.shape[1] != values.shape[2] or values.shape[1] < 1
            or not np.isfinite(values).all()):
        raise ValueError("Expected finite six-face square RGB mip-zero pixels")
    return values


def _normal(normal):
    n = np.asarray(normal, dtype=np.float64)
    if n.shape != (3,) or not np.isfinite(n).all():
        raise ValueError("Expected a finite three-component normal")
    length = float(np.linalg.norm(n))
    if length < 1e-20:
        raise ValueError("Normal must have nonzero length")
    return n / length


def _parameters(roughness, distribution):
    if distribution not in ("ggx", "lambert"):
        raise ValueError("Distribution must be 'ggx' or 'lambert'")
    r = float(roughness)
    if not math.isfinite(r) or not 0 <= r <= 1 or (distribution == "ggx" and r == 0):
        raise ValueError("GGX requires 0 < roughness <= 1; Lambert accepts 0 <= roughness <= 1")
    if distribution == "ggx" and r ** 4 == 0:
        raise ValueError("Roughness is too small to represent an f64 GGX kernel")
    return r


def _basis(n):
    axis = np.array([0., 0., 1.]) if abs(n[2]) < .9 else np.array([0., 1., 0.])
    tangent = np.cross(axis, n)
    tangent /= np.linalg.norm(tangent)
    return tangent, np.cross(n, tangent)


@lru_cache(maxsize=12)
def _legendre(order):
    nodes, weights = np.polynomial.legendre.leggauss(order)
    nodes.flags.writeable = False
    weights.flags.writeable = False
    return nodes, weights


def half_cdf_mu(u, roughness):
    """GGX half-vector CDF to N.L, with alpha=r^2 and N=V.

    Only u in [0, 1/(1+alpha^2)] reflects into the visible hemisphere.
    """
    r = _parameters(roughness, "ggx")
    q = r ** 4
    u = np.asarray(u, dtype=np.float64)
    return ((1 - u) - q * u) / ((1 - u) + q * u)


def ggx_normalizer(roughness):
    """Exact f64 1D integral Z=integral D(H)*NoL/4 dOmega over NoL>0."""
    r = _parameters(roughness, "ggx")
    q = r ** 4
    a, b = (1 + q) * .5, (q - 1) * .5
    x = b / a
    if abs(x) < 1e-3:
        # log(1+x)-x/(1+x), divided by x^2, evaluated without cancellation.
        series = sum(((-1.) ** k) * (k - 1) / k * x ** (k - 2) for k in range(2, 12))
        return q * .5 * series / (a * a)
    return (2 * q * math.log(2 * q / (1 + q)) + (1 - q)) / ((1 - q) ** 2)


def normalized_kernel(mu, roughness, distribution="ggx"):
    """Density with respect to solid angle for the selected normalized target.

    GGX: D(H)*NoL/(4Z), H=normalize(N+L). Lambert: NoL/pi.
    This is a convolution kernel, not a complete Cook-Torrance BRDF.
    """
    r = _parameters(roughness, distribution)
    mu = np.asarray(mu, dtype=np.float64)
    positive = np.clip(mu, 0., 1.)
    if distribution == "lambert":
        return positive / math.pi
    q = r ** 4
    denominator = (1 - positive) * .5 + q * (1 + positive) * .5
    d = q / (math.pi * denominator ** 2)
    return d * positive / (4 * ggx_normalizer(r))


def _rms(rgb):
    return float(np.sqrt(np.mean(np.asarray(rgb, dtype=np.float64) ** 2)))


def _relative_difference(a, b, scale):
    return float(np.max(np.abs(np.asarray(a) - np.asarray(b)))) / max(float(scale), 1e-12)


def _check_deadline(deadline):
    if time.perf_counter() >= deadline:
        raise _Limit("Reference wall-clock deadline reached")


def _sample(sample_fn, rays):
    try:
        rgb = np.asarray(sample_fn(rays), dtype=np.float64)
    except Exception as error:
        raise _Failure(f"Sampler failed: {type(error).__name__}: {error}") from error
    if rgb.shape != rays.shape or not np.isfinite(rgb).all():
        raise _Failure("Sampler did not return finite RGB for every direction")
    return rgb


def _shared_source(sample_fn, expected_faces=None):
    """Tie a shared-mip0 claim to the actual common Cubemap.sample object."""
    owner = getattr(sample_fn, "__self__", None)
    code = getattr(getattr(sample_fn, "__func__", None), "__code__", None)
    path = ROOT / "scripts/source-sampling/quality.py"
    if (owner is None or code is None or getattr(sample_fn, "__name__", None) != "sample"
            or Path(code.co_filename).resolve() != path.resolve()):
        raise ValueError("The shared_mip0 target requires the common quality.Cubemap.sample bound method")
    faces = _faces(owner.faces)
    if expected_faces is not None and not np.array_equal(faces, _faces(expected_faces)):
        raise ValueError("Support pixels and the sampled shared mip-zero pixels differ")
    contiguous = np.ascontiguousarray(faces, dtype="<f8")
    digest = hashlib.sha256(memoryview(contiguous).cast("B")).hexdigest()
    return dict(source_size=faces.shape[1], shared_mip0_rgb_f64_sha256=digest,
                hash_representation="six faces in px,nx,py,ny,pz,nz order; contiguous little-endian RGB f64",
                sampler_source=str(path.resolve()))


def _regions(regions):
    result = []
    for region in regions or []:
        f = int(region["face"])
        values = [float(region[k]) for k in ("u0", "u1", "v0", "v1")]
        u0, u1, v0, v1 = values
        if (f != region["face"] or not 0 <= f < 6
                or not all(math.isfinite(x) for x in values)
                or not 0 <= u0 < u1 <= 1 or not 0 <= v0 < v1 <= 1):
            raise ValueError("Expected cube-UV rectangles within one face")
        result.append(dict(face=f, u0=u0, u1=u1, v0=v0, v1=v1))
        if len(result) > 128:
            raise ValueError("A local check supports at most 128 finite rectangles")
    return result


def _region_mask(rays, regions):
    f, u, v = _quality().direction_to_face_uv(rays)
    mask = np.zeros(len(rays), dtype=bool)
    for region in regions:
        mask |= ((f == region["face"]) & (u >= region["u0"]) & (u < region["u1"])
                 & (v >= region["v0"]) & (v < region["v1"]))
    return mask


def select_highlight_support(cubemap_faces, max_seeds=8):
    """Select finite local support around bright/high-gradient source texels.

    Each texel's bilinear support receives a one-pixel halo. Face-boundary
    neighbors receive conservative matching rectangles. These regions are a
    local diagnostic subset, never a claim to cover all HDR structure.
    """
    faces = _faces(cubemap_faces)
    n = faces.shape[1]
    if not 1 <= int(max_seeds) <= 8:
        raise ValueError("Use between one and eight support seeds")
    brightness = np.max(np.abs(faces), axis=-1)
    gradient = np.zeros_like(brightness)
    gradient[:, :, 1:] = np.maximum(gradient[:, :, 1:], np.max(np.abs(np.diff(faces, axis=2)), axis=-1))
    gradient[:, :, :-1] = np.maximum(gradient[:, :, :-1], np.max(np.abs(np.diff(faces, axis=2)), axis=-1))
    gradient[:, 1:, :] = np.maximum(gradient[:, 1:, :], np.max(np.abs(np.diff(faces, axis=1)), axis=-1))
    gradient[:, :-1, :] = np.maximum(gradient[:, :-1, :], np.max(np.abs(np.diff(faces, axis=1)), axis=-1))
    seeds = []
    quota = (int(max_seeds) + 1) // 2
    for kind, metric, count in (("brightness", brightness, quota), ("gradient", gradient, int(max_seeds) - quota)):
        working = metric.copy()
        for _ in range(count):
            index = int(np.argmax(working))
            score = float(working.flat[index])
            if score <= 0:
                break
            f, y, x = np.unravel_index(index, working.shape)
            if not any(s["face"] == f and abs(s["x"] - x) <= 3 and abs(s["y"] - y) <= 3 for s in seeds):
                seeds.append(dict(face=int(f), x=int(x), y=int(y), kind=kind, score=score))
            working[f, max(0, y - 4):min(n, y + 5), max(0, x - 4):min(n, x + 5)] = 0
    regions = []
    def add(f, x, y):
        region = dict(face=int(f), u0=max(0., (x - 1.5) / n), u1=min(1., (x + 2.5) / n),
                      v0=max(0., (y - 1.5) / n), v1=min(1., (y + 2.5) / n))
        if region not in regions:
            regions.append(region)
    for seed in seeds:
        f, x, y = seed["face"], seed["x"], seed["y"]
        add(f, x, y)
        # A halo crossing an edge/corner must also inspect the incident faces.
        for dx in (-2., 0., 2.):
            for dy in (-2., 0., 2.):
                u, v = (x + .5 + dx) / n, (y + .5 + dy) / n
                if 0 <= u <= 1 and 0 <= v <= 1:
                    continue
                ray = _quality().face_direction(f, np.array(2 * u - 1), np.array(2 * v - 1))
                nf, nu, nv = _quality().direction_to_face_uv(ray)
                add(int(nf), min(n - 1, int(nu * n)), min(n - 1, int(nv * n)))
    return dict(regions=_regions(regions), seeds=seeds, source_size=n,
                selection="up to eight bright/high-gradient texel supports with one-pixel halo",
                coverage_claim="local geometric union only; other HDR structure may remain unresolved")


def _quadrature_level(sample_fn, n, roughness, distribution, radial, azimuth, regions, deadline):
    x, w = _legendre(radial)
    if distribution == "ggx":
        limit = 1 / (1 + roughness ** 4)
        u, weights = (x + 1) * (.5 * limit), w * (.5 * limit)
        mu = np.clip(half_cdf_mu(u, roughness), 0., 1.)
    else:
        mu, weights = (x + 1) * .5, w * .5
    tangent, bitangent = _basis(n)
    denominator = float(np.sum(weights * mu))
    records = []
    for phase in (0., .5):
        phi = (np.arange(azimuth) + phase) * (2 * math.pi / azimuth)
        ring = np.cos(phi)[:, None] * tangent + np.sin(phi)[:, None] * bitangent
        total, local = np.zeros(3), np.zeros(3)
        hits = 0
        # At most 8192 rays per block, independent of the reference level.
        rows = max(1, 8192 // azimuth)
        for start in range(0, radial, rows):
            _check_deadline(deadline)
            m = mu[start:start + rows]
            rays = (m[:, None, None] * n + np.sqrt(np.maximum(0., 1 - m * m))[:, None, None] * ring)
            rays = rays.reshape(-1, 3)
            rgb = _sample(sample_fn, rays)
            _check_deadline(deadline)
            weighted = (weights[start:start + rows] * m / azimuth).repeat(azimuth)
            total += np.sum(rgb * weighted[:, None], axis=0, dtype=np.float64)
            if regions:
                selected = _region_mask(rays, regions)
                local += np.sum(rgb[selected] * weighted[selected, None], axis=0, dtype=np.float64)
                hits += int(np.count_nonzero(selected))
        records.append(dict(offset_cells=phase, rgb=(total / denominator).tolist(),
                            local_rgb=(local / denominator).tolist(), support_hits=hits,
                            nodes=radial * azimuth, denominator=denominator))
    rgb = np.mean([p["rgb"] for p in records], axis=0)
    scale = max(_rms(rgb), 1e-12)
    exact = ggx_normalizer(roughness) if distribution == "ggx" else .5
    return dict(radial=radial, azimuth=azimuth, phases=records, rgb=rgb.tolist(),
                local_rgb=np.mean([p["local_rgb"] for p in records], axis=0).tolist(),
                phase_relative_spread=_relative_difference(records[0]["rgb"], records[1]["rgb"], scale),
                normalizer_relative_error=abs(denominator - exact) / exact)


def evaluate_reference(sample_fn, normal, roughness, distribution="ggx", *, source_faces=None,
                       support_regions=None, deadline=None, label="shared_mip0", seconds=60.,
                       relative_tolerance=RELATIVE_TOLERANCE, levels=LEVELS):
    """Return a bounded JSON-ready independent convolution diagnostic.

    ``deadline`` is an absolute ``time.perf_counter()`` deadline shared by the
    pilot. ``seconds`` caps this reference item, including its subsequent local
    cross-check. ``label`` must distinguish continuous analytic and shared mip0
    targets. The callable accepts [count,3] unit directions and returns RGB.
    """
    started = time.perf_counter()
    n, r = _normal(normal), _parameters(roughness, distribution)
    if label not in ("continuous_analytic", "shared_mip0"):
        raise ValueError("Label must be 'continuous_analytic' or 'shared_mip0'")
    if not math.isfinite(seconds) or not 0 < seconds <= 60 or not 0 < relative_tolerance <= 1e-2:
        raise ValueError("Expected an item budget in (0,60] seconds and a positive relative tolerance")
    if deadline is not None and math.isnan(float(deadline)):
        raise ValueError("Deadline must not be NaN")
    item_deadline = min(float(deadline) if deadline is not None else math.inf, started + seconds)
    source_metadata = _shared_source(sample_fn, source_faces) if label == "shared_mip0" else None
    if label == "continuous_analytic" and source_faces is not None:
        raise ValueError("Source support pixels belong to shared_mip0, not the continuous analytic target")
    selection = (select_highlight_support(source_faces) if source_faces is not None
                 and support_regions is None and time.perf_counter() < item_deadline else None)
    regions = _regions(selection["regions"] if selection else support_regions)
    records, consecutive, reason = [], 0, "Quadrature level cap reached without two successive diagnostic changes"
    status = "uncertain"
    last_dimensions = (0, 0)
    for index, (radial, azimuth) in enumerate(levels):
        if (not 1 <= radial <= 256 or not 1 <= azimuth <= 512
                or int(radial) != radial or int(azimuth) != azimuth or index >= 4
                or radial <= last_dimensions[0] or azimuth <= last_dimensions[1]):
            raise ValueError("Reference levels must increase and remain within the finite 256 by 512 node cap")
        last_dimensions = radial, azimuth
        try:
            record = _quadrature_level(sample_fn, n, r, distribution, radial, azimuth, regions, item_deadline)
        except (_Limit, _Failure) as error:
            status, reason = "uncertain", str(error)
            break
        if records:
            scale = max(_rms(record["rgb"]), 1e-12)
            changes = [_relative_difference(p["rgb"], q["rgb"], scale)
                       for p, q in zip(record["phases"], records[-1]["phases"])]
            record["previous_relative_change"] = max(changes)
            local_changes = [_relative_difference(p["local_rgb"], q["local_rgb"], scale)
                             for p, q in zip(record["phases"], records[-1]["phases"])]
            record["previous_local_relative_change"] = max(local_changes)
            passed = (max(changes) <= relative_tolerance
                      and record["phase_relative_spread"] <= relative_tolerance
                      and record["normalizer_relative_error"] <= relative_tolerance)
            consecutive = consecutive + 1 if passed else 0
        else:
            record["previous_relative_change"] = None
            record["previous_local_relative_change"] = None
        record["local_phase_relative_spread"] = _relative_difference(
            record["phases"][0]["local_rgb"], record["phases"][1]["local_rgb"], max(_rms(record["rgb"]), 1e-12))
        records.append(record)
        if consecutive >= 2:
            status, reason = "converged_diagnostic", "Two successive changes and azimuth phase spread met the diagnostic tolerance"
            # A hard region mask has its own slower convergence. Spend the last
            # allowed level on that local contribution when it remains unstable.
            if not regions or (record["local_phase_relative_spread"] <= relative_tolerance
                               and record["previous_local_relative_change"] <= relative_tolerance):
                break
        else:
            status = "uncertain"
            reason = "Latest levels did not establish two successive diagnostic changes within tolerance"
    return dict(schema=1, status=status, reason=reason, target=label, distribution=distribution,
                roughness=r, alpha=r * r if distribution == "ggx" else None, normal=n.tolist(),
                rgb=records[-1]["rgb"] if records else None, levels=records,
                relative_tolerance=relative_tolerance, strict_error_bound=False,
                error_metric="max RGB component change divided by final RGB RMS (floor 1e-12)",
                source_mips=False, fis_lod=False, production_hammersley=False,
                shared_source=source_metadata,
                support_regions=regions, support_selection=selection,
                local_crosscheck_required=bool(regions), seconds=time.perf_counter() - started,
                item_deadline_monotonic=item_deadline,
                limitation="Level and phase agreement can miss narrow HDR highlights; local checks only cover their recorded support union")


def rectangle_solid_angle(u0, u1, v0, v1):
    """Exact cube-UV rectangle solid angle, independent of the quadrature."""
    s0, s1, t0, t1 = 2 * u0 - 1, 2 * u1 - 1, 2 * v0 - 1, 2 * v1 - 1
    def primitive(s, t):
        return math.atan2(s * t, math.sqrt(1 + s * s + t * t))
    return primitive(s1, t1) - primitive(s0, t1) - primitive(s1, t0) + primitive(s0, t0)


def _union_cells(regions, size, max_cells=None, deadline=math.inf):
    """Disjoint union, also partitioned at source bilinear knots."""
    cells = []
    for f in range(6):
        face_regions = [r for r in regions if r["face"] == f]
        if not face_regions:
            continue
        u_values = {r[k] for r in face_regions for k in ("u0", "u1")}
        v_values = {r[k] for r in face_regions for k in ("v0", "v1")}
        # Every sampled source function uses pixel centers as bilinear knots.
        for k in range(size):
            value = (k + .5) / size
            if any(r["u0"] < value < r["u1"] for r in face_regions):
                u_values.add(value)
            if any(r["v0"] < value < r["v1"] for r in face_regions):
                v_values.add(value)
        us, vs = sorted(u_values), sorted(v_values)
        for u0, u1 in zip(us, us[1:]):
            _check_deadline(deadline)
            for v0, v1 in zip(vs, vs[1:]):
                u, v = (u0 + u1) * .5, (v0 + v1) * .5
                if any(r["u0"] <= u < r["u1"] and r["v0"] <= v < r["v1"] for r in face_regions):
                    cells.append((f, u0, u1, v0, v1, 0))
                    if max_cells is not None and len(cells) > max_cells:
                        raise _Limit("Initial disjoint source-UV partition exceeds node cap")
    return cells


def _local_pair(sample_fn, n, roughness, distribution, cell, budget):
    f, u0, u1, v0, v1, _ = cell
    results = []
    for order in (2, 4):
        count = order * order
        _check_deadline(budget["deadline"])
        if budget["nodes"] + count > budget["max_nodes"]:
            raise _Limit("Local source-UV node cap reached")
        x, w = _legendre(order)
        u, v = u0 + (x + 1) * ((u1 - u0) * .5), v0 + (x + 1) * ((v1 - v0) * .5)
        uu, vv = np.meshgrid(u, v)
        ww = np.outer(w, w) * ((u1 - u0) * (v1 - v0) * .25)
        s, t = 2 * uu - 1, 2 * vv - 1
        rays = _quality().face_direction(f, s, t).reshape(-1, 3)
        budget["nodes"] += count
        rgb = _sample(sample_fn, rays)
        mu = np.sum(rays * n, axis=-1)
        jacobian = 4 / (1 + s * s + t * t) ** 1.5
        weight = ww.ravel() * jacobian.ravel() * normalized_kernel(mu, roughness, distribution)
        results.append(np.sum(rgb * weight[:, None], axis=0, dtype=np.float64))
        if not np.isfinite(results[-1]).all():
            raise _Failure("Non-finite local source-UV integral")
        _check_deadline(budget["deadline"])
    return results[1], np.abs(results[1] - results[0])


def _split(cell):
    f, u0, u1, v0, v1, depth = cell
    um, vm = (u0 + u1) * .5, (v0 + v1) * .5
    return [(f, a, b, c, d, depth + 1) for a, b in ((u0, um), (um, u1))
            for c, d in ((v0, vm), (vm, v1))]


def _kernel_underresolved(cell, normal_uv, roughness, distribution):
    # A smooth-looking low/high pair can jointly miss a sharp GGX kernel.
    # Force geometric refinement near its peak instead of relying on agreement.
    if distribution != "ggx":
        return False
    f, u0, u1, v0, v1, _ = cell
    nf, nu, nv = normal_uv
    alpha = roughness * roughness
    distance = math.hypot(max(u0 - nu, 0., nu - u1), max(v0 - nv, 0., nv - v1))
    return f == nf and distance <= 2 * alpha and 2 * math.hypot(u1 - u0, v1 - v0) > alpha


def crosscheck_highlight_support(cubemap_faces, sample_fn, normal, roughness, main_record, *,
                                distribution="ggx", deadline=None, max_depth=6,
                                max_nodes=100000, seconds=60.):
    """Independently integrate only the recorded cube-UV support union.

    Low/high-order adaptive product Gauss rules use the exact cube Jacobian.
    Rectangles are disjoint and split at source bilinear knots. The main CDF
    quadrature contribution over the identical region is compared in linear RGB.
    Neither consistency nor the local error estimate certifies the full HDR
    convolution. This function never compares the original latlong projection.
    """
    started = time.perf_counter()
    faces, n = _faces(cubemap_faces), _normal(normal)
    r = _parameters(roughness, distribution)
    if (not 0 <= max_depth <= 6 or not 1 <= max_nodes <= 100000
            or not math.isfinite(seconds) or not 0 < seconds <= 60):
        raise ValueError("Local limits are depth <=6, nodes <=100000, and seconds <=60")
    if main_record.get("target") != "shared_mip0":
        raise ValueError("Source-UV HDR cross-check requires the shared_mip0 target")
    source_metadata = _shared_source(sample_fn, faces)
    if source_metadata != main_record.get("shared_source"):
        raise ValueError("The local and primary integrals do not use the same recorded shared mip-zero source")
    if (main_record.get("distribution") != distribution or main_record.get("roughness") != r
            or np.max(np.abs(np.asarray(main_record.get("normal")) - n)) > 1e-12):
        raise ValueError("Local and primary integrals must have the same normal and kernel")
    regions = _regions(main_record.get("support_regions"))
    if deadline is not None and math.isnan(float(deadline)):
        raise ValueError("Deadline must not be NaN")
    end = min(float(deadline) if deadline is not None else math.inf, started + seconds,
              main_record.get("item_deadline_monotonic", math.inf))
    budget = dict(deadline=end, nodes=0, max_nodes=max_nodes)
    result = dict(schema=1, status="uncertain", target="shared_mip0", distribution=distribution,
                  roughness=r, normal=n.tolist(), local_rgb=None, nodes=0, max_nodes=max_nodes,
                  max_depth=max_depth, strict_error_bound=False, regions=regions,
                  coverage_claim="Only the recorded source-UV geometric union; no global convolution error bound",
                  shared_source=source_metadata,
                  method="independent adaptive 2x2/4x4 Gauss rules in source cube-UV with solid-angle Jacobian")
    if not regions or not main_record.get("levels") or main_record.get("rgb") is None:
        result.update(reason="No completed primary integral or no recorded local support", seconds=time.perf_counter() - started)
        return result
    try:
        cells = _union_cells(regions, faces.shape[1], max_cells=max_nodes // 20, deadline=end)
    except _Limit as error:
        result.update(reason=str(error), initial_cells=None, seconds=time.perf_counter() - started)
        return result
    total_area = sum(rectangle_solid_angle(*cell[1:5]) for cell in cells)
    tolerance = float(main_record["relative_tolerance"])
    scale = max(_rms(main_record["rgb"]), 1e-12)
    absolute_tolerance = tolerance * scale
    nf, nu, nv = _quality().direction_to_face_uv(n)
    normal_uv = int(nf), float(nu), float(nv)
    estimates, heap, serial = {}, [], 0
    max_reached_depth, incomplete, depth_limited = 0, False, False
    reason = "Local adaptive diagnostic met tolerance"
    def push(cell, rgb, error):
        nonlocal serial, max_reached_depth, depth_limited
        area = rectangle_solid_angle(*cell[1:5])
        epsilon = absolute_tolerance * area / max(total_area, 1e-30)
        forced = _kernel_underresolved(cell, normal_uv, r, distribution)
        needs = float(np.max(error)) > epsilon or forced
        serial += 1
        estimates[serial] = (cell, rgb, error)
        max_reached_depth = max(max_reached_depth, cell[5])
        if needs and cell[5] >= max_depth:
            depth_limited = True
        elif needs:
            priority = max(float(np.max(error)) / max(epsilon, 1e-30), 2. if forced else 0.)
            heapq.heappush(heap, (-priority, serial))
    try:
        for cell in cells:
            rgb, error = _local_pair(sample_fn, n, r, distribution, cell, budget)
            push(cell, rgb, error)
        while heap:
            _check_deadline(end)
            _, identifier = heapq.heappop(heap)
            cell, _, _ = estimates[identifier]
            children = []
            for child in _split(cell):
                rgb, error = _local_pair(sample_fn, n, r, distribution, child, budget)
                children.append((child, rgb, error))
            # Replace a parent only after all four child estimates exist.
            del estimates[identifier]
            for child, rgb, error in children:
                push(child, rgb, error)
    except (_Limit, _Failure) as error:
        incomplete = True
        reason = str(error)
    complete_initial = len(estimates) >= len(cells)
    result.update(nodes=budget["nodes"], initial_cells=len(cells), leaf_cells=len(estimates),
                  max_reached_depth=max_reached_depth, depth_limited=depth_limited,
                  support_solid_angle=total_area, seconds=time.perf_counter() - started)
    if not complete_initial:
        result["reason"] = reason
        return result
    local = sum((entry[1] for entry in estimates.values()), np.zeros(3))
    observed_error = sum((entry[2] for entry in estimates.values()), np.zeros(3))
    phases = main_record["levels"][-1]["phases"]
    differences = [_relative_difference(local, p["local_rgb"], scale) for p in phases]
    phase_spread = _relative_difference(phases[0]["local_rgb"], phases[1]["local_rgb"], scale)
    observed_relative_error = float(np.max(observed_error)) / scale
    missing = any(p["support_hits"] == 0 for p in phases) and float(np.max(np.abs(local))) > absolute_tolerance
    passed = (not incomplete and not depth_limited and not missing
              and max(differences) <= tolerance and phase_spread <= tolerance
              and observed_relative_error <= tolerance)
    if missing:
        reason = "Primary quadrature missed support with a material independently integrated local contribution"
    elif depth_limited:
        reason = "Local source-UV depth cap left an unresolved contribution or GGX peak"
    elif not incomplete and not passed:
        reason = "Primary CDF and independent local source-UV contributions disagree at the diagnostic tolerance"
    result.update(status="consistent_local_diagnostic" if passed else "uncertain", reason=reason,
                  local_rgb=local.tolist(), primary_local_rgb=[p["local_rgb"] for p in phases],
                  relative_difference_per_phase=differences, primary_local_phase_spread=phase_spread,
                  observed_low_high_error_rgb=observed_error.tolist(), observed_relative_error=observed_relative_error,
                  missed_highlight=missing, relative_tolerance=tolerance,
                  error_metric="max local RGB component difference divided by full-reference RGB RMS")
    return result


def run_self_checks():
    """Small deterministic checks; no bake, production sampler sequence, or HDR download."""
    started, checks = time.perf_counter(), []
    def check(name, condition, detail=None):
        if not condition:
            raise AssertionError(f"Reference self-check failed: {name}: {detail}")
        checks.append(dict(name=name, passed=True, detail=detail))
    normals = [np.array([0., 0., 1.]), _normal([1., 2., -3.])]
    constant = np.array([.25, 2., 17.])
    for distribution in ("ggx", "lambert"):
        roughnesses = (.05, .2, .5, .7, 1.) if distribution == "ggx" else (1.,)
        for r in roughnesses:
            for normal in normals:
                result = evaluate_reference(lambda rays: np.broadcast_to(constant, rays.shape), normal, r,
                                            distribution, label="continuous_analytic")
                error = float(np.max(np.abs(np.asarray(result["rgb"]) - constant)))
                check(f"constant_{distribution}_{r}_{normal[2]:.3f}", error < 1e-11, error)
    for normal in normals:
        for distribution in ("ggx", "lambert"):
            result = evaluate_reference(lambda rays: .5 + .5 * rays, normal, 1., distribution,
                                        label="continuous_analytic")
            error = float(np.max(np.abs(np.asarray(result["rgb"]) - (.5 + normal / 3))))
            check(f"directional_r1_{distribution}_{normal[2]:.3f}", result["status"] == "converged_diagnostic" and error < 1e-12, error)
    # The CDF Jacobian is checked against the independently expressed spherical D(H)/4 density.
    for r in (.05, .2, .5, .7, .99999, 1.):
        q = r ** 4
        u = np.array([.07, .31, .79]) / (1 + q)
        mu = half_cdf_mu(u, r)
        du_dmu = 2 * q / (((1 + q) + (q - 1) * mu) ** 2)
        spherical = normalized_kernel(mu, r) * (2 * math.pi) / mu
        error = float(np.max(np.abs(spherical - du_dmu / ggx_normalizer(r)) / spherical))
        check(f"ggx_cdf_kernel_equivalence_{r}", error < 2e-10, error)
        check(f"ggx_hemisphere_endpoint_{r}", abs(float(half_cdf_mu(1 / (1 + q), r))) < 1e-9)
    # r>=.2 can also be integrated reliably in the independent uniform-mu coordinate.
    nodes, weights = _legendre(256)
    mu = (nodes + 1) * .5
    for distribution, r in (("lambert", 1.), ("ggx", .2), ("ggx", .5), ("ggx", .7), ("ggx", 1.)):
        integral = float(np.sum(normalized_kernel(mu, r, distribution) * weights * math.pi))
        check(f"solid_angle_kernel_normalization_{distribution}_{r}", abs(integral - 1) < 1e-9, integral)
    check("cube_solid_angle", abs(6 * rectangle_solid_angle(0., 1., 0., 1.) - 4 * math.pi) < 1e-14)
    for size in (1, 3, 8):
        cube = shared_mip0_sampler(np.broadcast_to(constant, (6, size, size, 3)))
        result = evaluate_reference(cube.sample, normals[1], .7, label="shared_mip0")
        check(f"shared_mip0_constant_{size}", np.max(np.abs(np.asarray(result["rgb"]) - constant)) < 1e-11)
    expired = evaluate_reference(lambda rays: np.ones_like(rays), normals[0], 1.,
                                 deadline=time.perf_counter() - 1, label="continuous_analytic")
    check("expired_global_budget_is_uncertain", expired["status"] == "uncertain" and expired["rgb"] is None)
    bad = evaluate_reference(lambda rays: np.full_like(rays, np.nan), normals[0], 1., label="continuous_analytic")
    check("nonfinite_sampler_is_uncertain", bad["status"] == "uncertain")
    def failing_sampler(_):
        raise RuntimeError("Deliberate sampler failure")
    failed = evaluate_reference(failing_sampler, normals[0], 1., label="continuous_analytic")
    check("sampler_exception_is_uncertain", failed["status"] == "uncertain" and failed["rgb"] is None)
    try:
        evaluate_reference(lambda rays: rays, normals[0], 1., label="shared_mip0")
    except ValueError:
        check("unverified_shared_mip0_claim_is_rejected", True)
    else:
        check("unverified_shared_mip0_claim_is_rejected", False)
    faces = np.ones((6, 8, 8, 3))
    cube = shared_mip0_sampler(faces)
    regions = [dict(face=4, u0=.25, u1=.75, v0=.25, v1=.75)]
    primary = evaluate_reference(cube.sample, normals[0], 1., source_faces=faces, support_regions=regions)
    local = crosscheck_highlight_support(faces, cube.sample, normals[0], 1., primary)
    # Hard geometric masks slow the CDF local convergence; an unresolved local
    # contribution must stay uncertain even though the whole constant converged.
    check("source_uv_local_integral_available", local["local_rgb"] is not None and local["observed_relative_error"] < 1e-4)
    if max(local["relative_difference_per_phase"]) > 1e-4:
        check("local_disagreement_is_uncertain", local["status"] == "uncertain")
    capped = crosscheck_highlight_support(faces, cube.sample, normals[0], 1., primary, max_nodes=1)
    check("local_node_cap_is_uncertain", capped["status"] == "uncertain" and capped["local_rgb"] is None)
    expired_local = crosscheck_highlight_support(faces, cube.sample, normals[0], 1., primary,
                                                deadline=time.perf_counter() - 1)
    check("local_deadline_is_uncertain", expired_local["status"] == "uncertain" and expired_local["local_rgb"] is None)
    try:
        crosscheck_highlight_support(faces * 2, cube.sample, normals[0], 1., primary)
    except ValueError:
        check("mismatched_local_source_is_rejected", True)
    else:
        check("mismatched_local_source_is_rejected", False)
    # Overlapping regions must integrate their union once.
    a = [dict(face=4, u0=.2, u1=.6, v0=.2, v1=.6), dict(face=4, u0=.4, u1=.8, v0=.4, v1=.8)]
    union = _union_cells(a, 8)
    area = sum(rectangle_solid_angle(*cell[1:5]) for cell in union)
    expected = rectangle_solid_angle(.2, .6, .2, .6) + rectangle_solid_angle(.4, .8, .4, .8) - rectangle_solid_angle(.4, .6, .4, .6)
    check("overlap_is_integrated_once", abs(area - expected) < 1e-13, area)
    # A deliberately fabricated zero-hit primary record tests conservative classification.
    missed = dict(primary)
    missed["levels"] = [dict(primary["levels"][-1])]
    missed["levels"][0]["phases"] = [dict(p, local_rgb=[0., 0., 0.], support_hits=0) for p in primary["levels"][-1]["phases"]]
    diagnosis = crosscheck_highlight_support(faces, cube.sample, normals[0], 1., missed)
    check("missed_local_highlight_is_uncertain", diagnosis["status"] == "uncertain" and diagnosis["missed_highlight"])
    # This is also exercised with a real piecewise-bilinear single bright texel,
    # using intentionally inadequate low orders to provoke jointly missed rays.
    narrow = np.zeros((6, 32, 32, 3))
    narrow[4, 7, 22] = 100.
    narrow_cube = shared_mip0_sampler(narrow)
    undersampled = evaluate_reference(narrow_cube.sample, normals[0], 1., source_faces=narrow,
                                     levels=((1, 1), (2, 2), (3, 4)))
    local_narrow = crosscheck_highlight_support(narrow, narrow_cube.sample, normals[0], 1., undersampled)
    check("real_narrow_texel_is_detected", local_narrow["status"] == "uncertain"
          and local_narrow.get("missed_highlight", False), local_narrow.get("reason"))
    return dict(schema=1, passed=True, checks=checks, seconds=time.perf_counter() - started,
                strict_error_bound=False, limitation="Checks validate formulas and failure classification, not global HDR quadrature error")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-packages", type=Path, action="append", default=[])
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not args.self_check:
        parser.error("This module is imported by the pilot; use --self-check for its standalone check")
    report = run_self_checks()
    data = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(data, encoding="utf-8")
    print(data, end="")


if __name__ == "__main__":
    main()

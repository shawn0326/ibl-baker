"""Paired release CLI benchmarks with Windows Job Object peak commit accounting."""
from __future__ import annotations

import argparse
import ctypes as ct
from ctypes import wintypes as wt
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def source_identity(path):
    path = Path(path).resolve()
    if path.is_file():
        return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size}
    if not path.is_dir():
        raise FileNotFoundError(path)
    files = {str(p.relative_to(path)): {"sha256": digest(p), "bytes": p.stat().st_size}
             for p in sorted(path.rglob("*")) if p.is_file()}
    if not files:
        raise ValueError(f"Input directory is empty: {path}")
    return {"path": str(path), "files": files,
            "sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}


def source_snapshot(path):
    path = Path(path).resolve()
    if not path.is_dir():
        raise FileNotFoundError(path)
    files = [path / name for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml")]
    files += sorted((path / "crates").glob("*/Cargo.toml"))
    files += sorted((path / "crates").glob("*/build.rs"))
    files += sorted((path / "crates").glob("*/src/**/*.rs"))
    files += sorted((path / ".cargo").glob("*"))
    hashes = {str(p.relative_to(path)): digest(p) for p in files if p.is_file()}
    return {"path": str(path), "files_sha256": hashes,
            "sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
            "scope": "Current source/build configuration snapshot; binary hash and actual build record must establish build identity"}


def machine_metadata():
    def version(command):
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        return {"command": command, "returncode": result.returncode,
                "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    processor = platform.processor()
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            processor = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    build_environment = {key: value for key, value in os.environ.items()
                         if key in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTUP_TOOLCHAIN", "CARGO_BUILD_TARGET")
                         or key.startswith("CARGO_PROFILE_RELEASE_")
                         or key.startswith("CARGO_TARGET_") and key.endswith(("_RUSTFLAGS", "_LINKER"))}
    return {"os": platform.uname()._asdict(), "processor": processor,
            "logical_cpu_count": os.cpu_count(), "python": sys.version,
            "rustc_inventory": version(["rustc", "-vV"]), "cargo_inventory": version(["cargo", "-V"]),
            "build_environment_inventory": build_environment,
            "toolchain_scope": "Inventory at benchmark time, not proof of the toolchain that produced prebuilt binaries"}


def summarize_runs(measured, rounds):
    medians = {name: {key: statistics.median(row[key] for row in values)
                      for key in ("seconds", "peak_commit_bytes")}
               for name, values in measured.items()}
    ratios = {key: medians["candidate"][key] / medians["baseline"][key]
              for key in ("seconds", "peak_commit_bytes")}
    paired = [c["seconds"] / b["seconds"] for b, c in zip(measured["baseline"], measured["candidate"])]
    # Resample paired rounds to preserve shared thermal/system drift. This is a
    # noise diagnostic rather than a claim of independent statistical samples.
    rng = random.Random(0x1B1)
    bootstrap = {key: [] for key in ratios}
    for _ in range(2000):
        indices = [rng.randrange(rounds) for _ in range(rounds)]
        for key in ratios:
            b = statistics.median(measured["baseline"][i][key] for i in indices)
            c = statistics.median(measured["candidate"][i][key] for i in indices)
            bootstrap[key].append(c / b)
    intervals = {key: [sorted(values)[49], sorted(values)[1949]] for key, values in bootstrap.items()}
    thresholds = {"seconds": 1.05, "peak_commit_bytes": 1.10}
    noisy = any(intervals[key][0] <= threshold < intervals[key][1] for key, threshold in thresholds.items())
    point_pass = all(ratios[key] <= threshold for key, threshold in thresholds.items())
    status = "needs_15_rounds" if noisy and rounds < 15 else "uncertain" if noisy else "pass" if point_pass else "fail"
    return {"medians": medians, "ratios": ratios,
            "paired_time_ratio_range": [min(paired), max(paired)],
            "paired_median_ratio_bootstrap_95pct": intervals,
            "noise_diagnostic": "2000 deterministic paired bootstrap resamples, seed 0x1B1; correlated host noise can remain",
            "point_estimate_passes": point_pass, "acceptance_status": status, "passes": status == "pass"}


class StartupInfo(ct.Structure):
    _fields_ = [("cb", wt.DWORD), ("reserved", wt.LPWSTR), ("desktop", wt.LPWSTR),
                ("title", wt.LPWSTR), ("x", wt.DWORD), ("y", wt.DWORD),
                ("xsize", wt.DWORD), ("ysize", wt.DWORD), ("xchars", wt.DWORD),
                ("ychars", wt.DWORD), ("fill", wt.DWORD), ("flags", wt.DWORD),
                ("show", wt.WORD), ("reserved_size", wt.WORD),
                ("reserved_bytes", ct.POINTER(ct.c_byte)), ("stdin", wt.HANDLE),
                ("stdout", wt.HANDLE), ("stderr", wt.HANDLE)]


class ProcessInfo(ct.Structure):
    _fields_ = [("process", wt.HANDLE), ("thread", wt.HANDLE),
                ("pid", wt.DWORD), ("tid", wt.DWORD)]


class BasicLimits(ct.Structure):
    _fields_ = [("process_time", ct.c_int64), ("job_time", ct.c_int64),
                ("flags", wt.DWORD), ("min_working_set", ct.c_size_t),
                ("max_working_set", ct.c_size_t), ("active_processes", wt.DWORD),
                ("affinity", ct.c_size_t), ("priority", wt.DWORD),
                ("scheduling", wt.DWORD)]


class IoCounters(ct.Structure):
    _fields_ = [(name, ct.c_uint64) for name in
                ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")]


class ExtendedLimits(ct.Structure):
    _fields_ = [("basic", BasicLimits), ("io", IoCounters),
                ("process_limit", ct.c_size_t), ("job_limit", ct.c_size_t),
                ("peak_process", ct.c_size_t), ("peak_job", ct.c_size_t)]


def run_process(command, log, cwd, threads):
    """Assign a suspended process before it runs; query retained peak after exit."""
    if os.name != "nt":
        raise RuntimeError("This benchmark requires Windows Job Object memory accounting")
    import msvcrt
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ct.c_void_p, wt.LPCWSTR]
    kernel.CreateJobObjectW.restype = wt.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    kernel.AssignProcessToJobObject.restype = wt.BOOL
    kernel.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ct.c_void_p, ct.c_void_p,
                                     wt.BOOL, wt.DWORD, ct.c_void_p, wt.LPCWSTR,
                                     ct.POINTER(StartupInfo), ct.POINTER(ProcessInfo)]
    kernel.CreateProcessW.restype = wt.BOOL
    kernel.ResumeThread.argtypes = [wt.HANDLE]
    kernel.ResumeThread.restype = wt.DWORD
    kernel.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    kernel.WaitForSingleObject.restype = wt.DWORD
    kernel.GetExitCodeProcess.argtypes = [wt.HANDLE, ct.POINTER(wt.DWORD)]
    kernel.GetExitCodeProcess.restype = wt.BOOL
    kernel.QueryInformationJobObject.argtypes = [wt.HANDLE, ct.c_int, ct.c_void_p,
                                                wt.DWORD, ct.c_void_p]
    kernel.QueryInformationJobObject.restype = wt.BOOL
    kernel.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ct.WinError(ct.get_last_error())
    process = ProcessInfo()
    finished = False
    try:
        with log.open("wb") as output, open(os.devnull, "rb") as input_file:
            handles = [msvcrt.get_osfhandle(f.fileno()) for f in (input_file, output)]
            for handle in handles:
                os.set_handle_inheritable(handle, True)
            startup = StartupInfo(cb=ct.sizeof(StartupInfo), flags=0x100,
                                  stdin=handles[0], stdout=handles[1], stderr=handles[1])
            env = dict(os.environ, RAYON_NUM_THREADS=str(threads))
            environment = ct.create_unicode_buffer("\0".join(f"{k}={v}" for k, v in
                                                    sorted(env.items(), key=lambda item: item[0].upper())) + "\0\0")
            command_line = ct.create_unicode_buffer(subprocess.list2cmdline(list(map(str, command))))
            started_utc = utc_now()
            started = time.perf_counter()
            if not kernel.CreateProcessW(str(Path(command[0]).resolve()), command_line, None, None, True,
                                         0x4 | 0x400 | 0x08000000, environment,
                                         str(cwd), ct.byref(startup), ct.byref(process)):
                raise ct.WinError(ct.get_last_error())
            if not kernel.AssignProcessToJobObject(job, process.process):
                raise ct.WinError(ct.get_last_error())
            if kernel.ResumeThread(process.thread) == 0xFFFFFFFF:
                raise ct.WinError(ct.get_last_error())
            if kernel.WaitForSingleObject(process.process, 0xFFFFFFFF) != 0:
                raise ct.WinError(ct.get_last_error())
            elapsed = time.perf_counter() - started
            finished = True
            status = wt.DWORD()
            if not kernel.GetExitCodeProcess(process.process, ct.byref(status)):
                raise ct.WinError(ct.get_last_error())
            limits = ExtendedLimits()
            if not kernel.QueryInformationJobObject(job, 9, ct.byref(limits),
                                                     ct.sizeof(limits), None):
                raise ct.WinError(ct.get_last_error())
            if status.value:
                raise RuntimeError(f"Process exited with {status.value}; see {log}")
            if not limits.peak_process:
                raise RuntimeError("Operating system returned zero peak committed memory")
            return {"seconds": elapsed, "peak_commit_bytes": limits.peak_process,
                    "peak_job_commit_bytes": limits.peak_job,
                    "started_at_utc": started_utc,
                    "pid": process.pid, "exit_code": status.value,
                    "command": list(map(str, command)), "cwd": str(cwd), "log": str(log)}
    finally:
        if process.process and not finished:
            kernel.TerminateProcess(process.process, 1)
        for handle in (process.thread, process.process, job):
            if handle:
                kernel.CloseHandle(handle)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--pisa", type=Path, required=True)
    parser.add_argument("--qwantani", type=Path, required=True)
    parser.add_argument("--cube", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("target/source-sampling-performance"))
    parser.add_argument("--rounds", type=int, choices=(7, 15), default=7)
    parser.add_argument("--case", action="append", help="Run only these case IDs")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--baseline-source", type=Path, default=ROOT / "target/source-sampling-baseline")
    parser.add_argument("--candidate-source", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.threads < 1 or args.warmups < 0:
        raise ValueError("Expected positive thread count and nonnegative warmups")
    args.output = args.output.resolve()
    if not args.output.is_relative_to((ROOT / "target").resolve()):
        raise ValueError("Benchmark outputs must stay under repository target/")
    args.output.mkdir(parents=True, exist_ok=True)
    executables = {"baseline": args.baseline.resolve(), "candidate": args.candidate.resolve()}
    cases = []
    for name, source in [("pisa", args.pisa), ("qwantani", args.qwantani), ("rotated-cube", args.cube)]:
        for size in (256, 512):
            cases.append((f"{name}-specular-{size}", source, "specular", size, name == "rotated-cube", True))
    for name, source in [("qwantani", args.qwantani), ("rotated-cube", args.cube)]:
        cases.append((f"{name}-irradiance-512", source, "irradiance", 512, name == "rotated-cube", True))
    cases.append(("rotated-cube-specular-255", args.cube, "specular", 255, True, False))
    unknown = set(args.case or ()) - {case[0] for case in cases}
    if unknown:
        raise ValueError(f"Unknown case IDs: {sorted(unknown)}")
    inputs = {name: source_identity(path) for name, path in
              (("pisa", args.pisa), ("qwantani", args.qwantani), ("cube", args.cube))}
    records = []
    result_path = args.output / "benchmark.json"
    summary = {"schema_version": 2, "started_at_utc": utc_now(),
               "state": "running", "machine": machine_metadata(), "threads": args.threads,
               "requested_rounds": args.rounds, "warmups": args.warmups,
               "working_directory": str(ROOT), "output_directory": str(args.output),
               "disk_cache_policy": "Two warmups per version; same local output disk; overwrite same per-version files",
               "measurement_scope": "CreateProcessW suspended + Job assignment + resume through process exit; includes launch, bake, encoding, file writes and logs",
               "protocol": {"required_threads": 4, "required_warmups": 2,
                            "matches": args.threads == 4 and args.warmups == 2},
               "memory_metric": "Windows Job Object PeakProcessMemoryUsed (committed bytes)",
               "inputs": inputs,
               "source_snapshots": {"baseline": source_snapshot(args.baseline_source),
                                    "candidate": source_snapshot(args.candidate_source)},
               "executables": {k: {"path": str(v), "sha256": digest(v)} for k, v in executables.items()},
               "tool_sha256": digest(__file__), "cases": records}
    # A fifteen-round rerun of selected cases preserves the other completed
    # cases only when their complete input/producer/measurement identity matches.
    if args.case and result_path.exists():
        previous = json.loads(result_path.read_text())
        keys = ("schema_version", "threads", "warmups", "executables", "inputs", "source_snapshots", "tool_sha256")
        if not all(previous.get(key) == summary[key] for key in keys):
            raise ValueError("Cannot merge subset rerun with different provenance; use a fresh --output directory")
        records.extend(record for record in previous["cases"] if record["id"] not in args.case)
        summary["previous_started_at_utc"] = previous["started_at_utc"]
    result_path.write_text(json.dumps(summary, indent=2) + "\n")
    for case_id, source, target, size, rotate, gated in cases:
        if args.case and case_id not in args.case:
            continue
        directory = args.output / case_id
        directory.mkdir(exist_ok=True)
        measured = {"baseline": [], "candidate": []}
        for round_index in range(-args.warmups, args.rounds):
            order = ("baseline", "candidate") if round_index % 2 == 0 else ("candidate", "baseline")
            for name in order:
                destination = directory / name
                destination.mkdir(exist_ok=True)
                command = [executables[name], "bake", source.resolve(), "--out-dir", destination,
                           "--size", str(size), "--target", target, "--output-format", "both",
                           "--quality", "high", "--samples", "1024"]
                if rotate:
                    command += ["--rotation", "37"]
                sample = run_process(command, directory / f"{name}-{round_index}.log", ROOT, args.threads)
                sample.update(round=round_index, order_in_pair=order.index(name), completed_at_utc=utc_now())
                if round_index >= 0:
                    measured[name].append(sample)
                print(f"{case_id} {name} round={round_index}: {sample['seconds']:.3f}s, "
                      f"{sample['peak_commit_bytes']/1048576:.2f} MiB", flush=True)
        record = {"id": case_id, "source": str(source.resolve()), "target": target,
                  "size": size, "rotation_degrees": 37 if rotate else 0, "gated": gated,
                  "rounds": args.rounds, "runs": measured, **summarize_runs(measured, args.rounds)}
        if not summary["protocol"]["matches"]:
            record.update(acceptance_status="nonstandard_protocol", passes=False)
        records.append(record)
        result_path.write_text(json.dumps(summary, indent=2) + "\n")
        print(f"{case_id}: time={record['ratios']['seconds']:.4f}, memory={record['ratios']['peak_commit_bytes']:.4f}, "
              f"status={record['acceptance_status']}", flush=True)
    for name, binary in executables.items():
        if digest(binary) != summary["executables"][name]["sha256"]:
            raise RuntimeError(f"Executable changed during benchmark: {binary}")
    for name, path in (("pisa", args.pisa), ("qwantani", args.qwantani), ("cube", args.cube)):
        if source_identity(path) != inputs[name]:
            raise RuntimeError(f"Input changed during benchmark: {path}")
    for name, path in (("baseline", args.baseline_source), ("candidate", args.candidate_source)):
        if source_snapshot(path) != summary["source_snapshots"][name]:
            raise RuntimeError(f"Source snapshot changed during benchmark: {path}")
    matrix_complete = {case[0] for case in cases if case[-1]} <= {record["id"] for record in records}
    summary.update(state="complete", completed_at_utc=utc_now(), full_gated_matrix_complete=matrix_complete,
                   all_gated_cases_pass=matrix_complete and all(record["passes"] for record in records if record["gated"]),
                   completed_case_ids=[record["id"] for record in records])
    result_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Results: {result_path}")


if __name__ == "__main__":
    main()

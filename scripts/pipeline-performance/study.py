"""Private phase profiling and byte-identical bake performance acceptance."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/"target/pipeline-performance"
BASELINE="125ea90"


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
def run(command,log,env=None,cwd=ROOT):
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open("w",encoding="utf-8") as f:subprocess.run(list(map(str,command)),cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
def replace(text,old,new):
    if text.count(old)!=1:raise ValueError(f"Expected one injection point: {old[:100]!r}; found {text.count(old)}")
    return text.replace(old,new)
def guard(text,function,label):
    if text.count(function)!=1:raise ValueError(f"Ambiguous function: {function}")
    start=text.index("{",text.index(function))+1
    return text[:start]+f'\n    let _phase = ibl_profile_private::scope("{label}");'+text[start:]


def snapshot(name,revision=None):
    destination=OUT/name
    names=subprocess.check_output(["git","ls-tree","-r","--name-only",BASELINE,"--","crates","Cargo.toml","Cargo.lock","rust-toolchain.toml"],cwd=ROOT,text=True).splitlines()
    hashes={}
    for path in names:
        target=destination/path;target.parent.mkdir(parents=True,exist_ok=True)
        data=subprocess.check_output(["git","show",f"{revision}:{path}"],cwd=ROOT) if revision else (ROOT/path).read_bytes()
        target.write_bytes(data);hashes[path]=digest(target)
    config=destination/".cargo/config.toml";config.parent.mkdir(exist_ok=True)
    config.write_text('[source.crates-io]\nreplace-with="pnpm-crates-io"\n[source.pnpm-crates-io]\ndirectory='+json.dumps(str(ROOT/".pnpm/crates/crates-io"))+'\n',encoding="utf-8")
    return destination,hashes


def instrument(root):
    workspace=root/"Cargo.toml";text=workspace.read_text(encoding="utf-8-sig")
    workspace.write_text(replace(text,'members = [','members = [\n    "crates/ibl_profile_private",'),encoding="utf-8")
    helper=root/"crates/ibl_profile_private";helper.mkdir(exist_ok=True)
    (helper/"Cargo.toml").write_text('[package]\nname="ibl_profile_private"\nversion="0.0.0"\nedition="2021"\n[lib]\npath="profile.rs"\n',encoding="utf-8")
    shutil.copyfile(Path(__file__).with_name("profile.rs"),helper/"profile.rs")
    for crate in ("ibl_core","ibl_cli","ktx2_writer"):
        path=root/f"crates/{crate}/Cargo.toml"
        path.write_text(replace(path.read_text(),"[dependencies]",'[dependencies]\nibl_profile_private = { path = "../ibl_profile_private" }'),encoding="utf-8")
    lib=root/"crates/ibl_core/src/lib.rs";text=lib.read_text(encoding="utf-8-sig")
    for call in ("load_environment_from_file(input)?","load_environment_from_cubemap_paths(input)?","load_environment_from_file(input_path)?"):
        text=text.replace(call,'{ let _phase = ibl_profile_private::scope("load"); '+call+' }')
    text=guard(text,"pub fn write_asset<","write_ibla")
    text=guard(text,"pub fn to_asset_with_report(","encode_ibla")
    text=guard(text,"fn asset_from_entries(","package_ibla")
    lib.write_text(text,encoding="utf-8")
    pipeline=root/"crates/ibl_core/src/bake_pipeline.rs";text=pipeline.read_text(encoding="utf-8-sig")
    text=replace(text,"        let base_directions = build_direction_cache(base_size);\n        let base_cubemap = render_cubemap_faces(source, rotation, &base_directions, base_size);",'''        let (base_directions, base_cubemap) = {
            let _phase = ibl_profile_private::scope("projection");
            let directions = build_direction_cache(base_size);
            let cube = render_cubemap_faces(source, rotation, &directions, base_size);
            (directions, cube)
        };''')
    base_argument="&base_cubemap" if "build_cubemap_mip_chain(&base_cubemap);" in text else "base_cubemap"
    text=replace(text,f"        let cubemap_mips = build_cubemap_mip_chain({base_argument});",'''        let cubemap_mips = {
            let _phase = ibl_profile_private::scope("source_mips");
            build_cubemap_mip_chain(ARGUMENT)
        };'''.replace("ARGUMENT",base_argument))
    text=replace(text,"        let cubemap_borders = cubemap_mips.iter().map(CubemapBorders::new).collect();",'''        let cubemap_borders = {
            let _phase = ibl_profile_private::scope("source_borders");
            cubemap_mips.iter().map(CubemapBorders::new).collect()
        };''')
    argument="&mut context" if "build_specular_mip_chain(&mut context, options, mip_count)" in text else "context"
    call=f"    build_specular_mip_chain({argument}, options, mip_count)"
    text=replace(text,call,'    let _phase = ibl_profile_private::scope("filter_specular");\n'+call)
    text=replace(text,"    render_filtered_faces(\n        &mut context,\n        options.irradiance_size,",'    let _phase = ibl_profile_private::scope("filter_irradiance");\n    render_filtered_faces(\n        &mut context,\n        options.irradiance_size,')
    for name,label in [("pub(crate) fn encode_mip_chain_to_ktx2(","encode_ktx2"),("pub(crate) fn encode_cubemap_mips(","png"),("fn build_brdf_lut(","filter_lut")]:text=guard(text,name,label)
    text=replace(text,"    let bytes = encode_png_image(&image, EncodingKind::Linear)?;",'    let bytes = { let _phase = ibl_profile_private::scope("encode_lut"); encode_png_image(&image, EncodingKind::Linear)? };')
    text=replace(text,"    let levels: Vec<CubemapLevel> = mip_chain",'    let _packing = ibl_profile_private::scope("ktx2_rgb_pack");\n    let levels: Vec<CubemapLevel> = mip_chain')
    text=replace(text,"    let meta = WriterMetadata {",'    drop(_packing);\n    let meta = WriterMetadata {')
    pipeline.write_text(text,encoding="utf-8")
    writer=root/"crates/ktx2_writer/src/lib.rs";text=writer.read_text(encoding="utf-8-sig")
    text=replace(text,"    for face in &level.face_pixels {",'    let _bc6h = ibl_profile_private::scope("bc6h");\n    for face in &level.face_pixels {')
    text=replace(text,"    let uncompressed_len = uncompressed.len() as u64;",'    drop(_bc6h);\n    let _zstd = ibl_profile_private::scope("zstd");\n    let uncompressed_len = uncompressed.len() as u64;')
    writer.write_text(text,encoding="utf-8")
    cli=root/"crates/ibl_cli/src/main.rs";text=cli.read_text(encoding="utf-8-sig")
    text=replace(text,"fn main() {",'fn main() {\n    ibl_profile_private::start_sampling();\n    let _profile = ibl_profile_private::scope("process");')
    text=replace(text,"    process::exit(exit_code);",'    drop(_profile);\n    ibl_profile_private::stop_sampling();\n    process::exit(exit_code);')
    for call,label in [('fs::write(&output, ktx2_bytes).map_err(IblError::from)?;',"write_ktx2"),('fs::write(&output, bytes).map_err(IblError::from)?;',"write_lut")]:
        text=replace(text,call,'{ let _phase = ibl_profile_private::scope("'+label+'"); '+call+' }')
    cli.write_text(text,encoding="utf-8")


def prepare(profile,candidate=False):
    name="profile-candidate" if candidate else "profile-baseline" if profile else "baseline-source"
    root,hashes=snapshot(name,None if candidate else BASELINE)
    if profile:instrument(root)
    target=OUT/("profile-candidate-build" if candidate else "profile-build" if profile else "baseline-build")
    env=dict(os.environ,CARGO_TARGET_DIR=str(target))
    command=["cargo","build","--offline","--release","--manifest-path",root/"Cargo.toml","-p","ibl_cli"]
    if not profile:command.append("--locked")
    run(command,OUT/f"{name}-build.log",env,root)
    binary=target/"release/ibl-baker.exe"
    actual_sources={str(p.relative_to(root)):digest(p) for p in sorted((root/"crates").rglob("*")) if p.is_file() and p.suffix in (".rs",".toml")}
    save(OUT/f"{name}.json",dict(baseline=BASELINE,sources=hashes,binary=str(binary),binary_sha256=digest(binary),actual_sources=actual_sources,
        instrumented=profile,profiler=digest(root/"crates/ibl_profile_private/profile.rs") if profile else None,tool=digest(__file__),build_command=list(map(str,command))))
    print(name,digest(binary),flush=True)


SOURCES={"pisa":ROOT/"fixtures/inputs/pisa.hdr", "spruit":ROOT/"fixtures/inputs/spruit_sunrise_2k.jpg", "bridge":ROOT/"fixtures/inputs/Bridge2"}

def command(binary,source,output,size,fmt="both"):
    return [binary,"bake",source,"--out-dir",output,"--size",str(size),"--output-format",fmt]

def outputs(root):
    return {p.name:dict(bytes=p.stat().st_size,sha256=digest(p)) for p in sorted(root.iterdir()) if p.suffix in (".ibla",".ktx2",".png")}

def phases(log):
    result=[]
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.startswith("IBL_PHASE\t"):continue
        _,index,parent,name,seconds,heap_start,heap_peak,heap_end,commit_start,commit_peak,commit_end,samples=line.split("\t")
        result.append(dict(id=int(index),parent=int(parent),name=name,seconds=float(seconds),heap_start=int(heap_start),heap_peak=int(heap_peak),heap_end=int(heap_end),
            commit_start=int(commit_start),commit_peak=int(commit_peak),commit_end=int(commit_end),commit_samples=int(samples)))
    if len([r for r in result if r["name"]=="process"])!=1:raise ValueError("Missing root phase")
    return result

def profile(sizes,rounds,candidate=False):
    baseline=OUT/"baseline-build/release/ibl-baker.exe"
    binary=OUT/("profile-candidate-build" if candidate else "profile-build")/"release/ibl-baker.exe"
    variant="candidate" if candidate else "baseline"
    env=dict(os.environ,RAYON_NUM_THREADS="4");rows=[]
    for size in sizes:
        for case,source in SOURCES.items():
            root=OUT/f"phases-{variant}"/f"{case}-{size}"
            run(command(baseline,source,root/"control",size),root/"control.log",env)
            controls=outputs(root/"control")
            measured=[]
            for iteration in range(-1,rounds):
                log=root/f"{iteration}.log"
                run(command(binary,source,root/"profile",size),log,env)
                if outputs(root/"profile")!=controls:raise AssertionError("Instrumentation changed output bytes")
                if iteration>=0:measured.append(phases(log))
            labels=sorted({r["name"] for trial in measured for r in trial});summary={}
            for label in labels:
                trials=[[r for r in trial if r["name"]==label] for trial in measured]
                summary[label]=dict(calls=len(trials[0]),seconds=statistics.median(sum(r["seconds"] for r in trial) for trial in trials),
                    heap_peak=statistics.median(max(r["heap_peak"] for r in trial) for trial in trials),
                    sampled_commit_peak=statistics.median(max(r["commit_peak"] for r in trial) for trial in trials))
            rows.append(dict(case=case,size=size,runs=measured,summary=summary,outputs=controls))
            save(OUT/f"phases-{variant}.json",dict(rows=rows,binaries={"baseline":digest(baseline),"profile":digest(binary)},threads=4,warmups=1,rounds=rounds,
                memory="Absolute requested-live Rust heap high-water marks and sampled native private commit; not additive phase allocations. Native malloc and transient realloc copies are excluded from heap.",
                timing="Instrumented diagnostics; assess production gains with separate uninstrumented paired runs"))
            print(case,size,{k:(v["calls"],round(v["seconds"],4),round(v["heap_peak"]/2**20,2)) for k,v in summary.items()},flush=True)


def benchmark(sizes,rounds):
    process=module("paired_process",ROOT/"scripts/source-sampling/benchmark.py")
    binaries=dict(baseline=OUT/"baseline-build/release/ibl-baker.exe",candidate=ROOT/"target/release/ibl-baker.exe")
    identities={k:digest(v) for k,v in binaries.items()};rows=[]
    machine=process.machine_metadata()
    sources={case:{str(p.relative_to(ROOT)):digest(p) for p in (sorted(source.glob("*.jpg")) if source.is_dir() else [source])} for case,source in SOURCES.items()}
    candidate_source=process.source_snapshot(ROOT)
    for size in sizes:
        for case,source in SOURCES.items():
            for fmt in ("ibla","ktx2","both"):
                root=OUT/"benchmark"/f"{case}-{size}-{fmt}";root.mkdir(parents=True,exist_ok=True)
                measured={name:[] for name in binaries}
                for iteration in range(-2,rounds):
                    order=list(binaries) if iteration%2==0 else list(binaries)[::-1]
                    for name in order:
                        record=process.run_process(command(binaries[name],source,root/name,size,fmt),root/f"{iteration}-{name}.log",ROOT,4)
                        if iteration>=0:measured[name].append(record)
                    if outputs(root/"baseline")!=outputs(root/"candidate"):raise AssertionError("Production output bytes changed")
                summary=process.summarize_runs(measured,rounds)
                rows.append(dict(case=case,size=size,format=fmt,runs=measured,summary=summary,outputs=outputs(root/"candidate")))
                save(OUT/"benchmark.json",dict(baseline=BASELINE,binaries=identities,rows=rows,machine=machine,source_inputs=sources,candidate_source=candidate_source,
                    threads=4,warmups=2,rounds=rounds,quality="medium",samples=1024,targets="all",scope="Uninstrumented production CLI; byte-identical IBLA/KTX2/LUT required after every paired run"))
                print(case,size,fmt,"ratios",summary["ratios"],summary["acceptance_status"],flush=True)
    if identities!={k:digest(v) for k,v in binaries.items()}:raise AssertionError("Measured binary changed during timing")


def compatibility():
    parsers=module("actual_parsers",ROOT/"scripts/quality-optimization/acceptance.py")
    bins=dict(baseline=OUT/"baseline-build/release/ibl-baker.exe",candidate=ROOT/"target/release/ibl-baker.exe")
    rows=[];env=dict(os.environ,RAYON_NUM_THREADS="4")
    cases=[("pisa",size,[]) for size in (1,3,31,255)]
    cases += [("bridge",31,["--irradiance-size","64","--rotation","27.5"]),
        ("pisa",255,["--specular-min-size","16","--samples","7","--quality","high"]),
        ("pisa",31,["--target","irradiance"]),("pisa",31,["--target","lut"])]
    for index,(case,size,extra) in enumerate(cases):
        root=OUT/"compatibility"/str(index)
        for name,binary in bins.items():run(command(binary,SOURCES[case],root/name,size)+extra,root/f"{name}.log",env)
        before,after=outputs(root/"baseline"),outputs(root/"candidate")
        if before!=after:raise AssertionError("Contract matrix changed bytes")
        parsed=parsers.parsers(root/"candidate") if "--target" not in extra else None
        rows.append(dict(case=case,size=size,options=extra,outputs=after,parsers=parsed))
    save(OUT/"compatibility.json",dict(rows=rows,binaries={k:digest(v) for k,v in bins.items()}))
    print("Tiny, NPOT, truncated, rotated, large-irradiance and selected-target byte parity passed",flush=True)


def confirm_noisy():
    initial=json.loads((OUT/"benchmark.json").read_text())
    process=module("confirmation_process",ROOT/"scripts/source-sampling/benchmark.py")
    binaries=dict(baseline=OUT/"baseline-build/release/ibl-baker.exe",candidate=ROOT/"target/release/ibl-baker.exe")
    if initial["binaries"]!={k:digest(v) for k,v in binaries.items()}:raise AssertionError("Confirmation binary identity changed")
    rows=[]
    for row in initial["rows"]:
        if row["summary"]["acceptance_status"]!="needs_15_rounds":continue
        case,size,fmt=row["case"],row["size"],row["format"]
        root=OUT/"confirmation"/f"{case}-{size}-{fmt}";root.mkdir(parents=True,exist_ok=True)
        measured={name:[] for name in binaries}
        for iteration in range(-2,15):
            for name in (list(binaries) if iteration%2==0 else list(binaries)[::-1]):
                value=process.run_process(command(binaries[name],SOURCES[case],root/name,size,fmt),root/f"{iteration}-{name}.log",ROOT,4)
                if iteration>=0:measured[name].append(value)
            if outputs(root/"baseline")!=row["outputs"] or outputs(root/"candidate")!=row["outputs"]:raise AssertionError("Confirmation output bytes changed")
        summary=process.summarize_runs(measured,15)
        rows.append(dict(case=case,size=size,format=fmt,runs=measured,summary=summary))
        print("confirmed",case,size,fmt,summary["ratios"],summary["acceptance_status"],flush=True)
    save(OUT/"confirmation.json",dict(initial_sha256=digest(OUT/"benchmark.json"),binaries=initial["binaries"],rows=rows,rounds=15,warmups=2,threads=4))
    if initial["binaries"]!={k:digest(v) for k,v in binaries.items()}:raise AssertionError("Binary changed during confirmation")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["prepare-baseline","prepare-profile","prepare-profile-candidate","profile","profile-candidate","benchmark","benchmark-confirm","compatibility"])
    parser.add_argument("--sizes",default="512")
    parser.add_argument("--rounds",type=int,choices=[3,7,15])
    args=parser.parse_args()
    rounds=args.rounds or (7 if args.command=="benchmark" else 3)
    if args.command=="benchmark":benchmark(list(map(int,args.sizes.split(","))),rounds)
    elif args.command=="benchmark-confirm":confirm_noisy()
    elif args.command=="compatibility":compatibility()
    elif args.command.startswith("profile"):profile(list(map(int,args.sizes.split(","))),rounds,args.command=="profile-candidate")
    else:prepare(args.command!="prepare-baseline",args.command=="prepare-profile-candidate")

if __name__=="__main__":main()

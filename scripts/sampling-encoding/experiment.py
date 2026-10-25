"""Full-chain 2x2 sampling/footprint study and isolated BC6H re-encoding."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/"target/sampling-encoding"
BASELINE="4398483"
sys.path.insert(0,str(ROOT/"scripts/quality-optimization"))
import study as previous

save=previous.save
digest=previous.digest
module=previous.module
run=previous.run
FACES=previous.FACES
POLICIES={"quadratic":(0,0),"linear":(1,1),"sample-only":(1,0),"footprint-only":(0,1)}
POLICIES.update({"linear-footprint-25":(1,.25),"linear-footprint-50":(1,.5),"linear-footprint-75":(1,.75)})
CODECS={"basic-black":(0,0),"basic-edge":(0,1),"slow-black":(1,0),"slow-edge":(1,1),"very-slow-edge":(2,1),"hybrid-edge":(3,1),
    "refine8-edge":(4,1),"refine32-edge":(5,1),"basic-refine8-edge":(6,1),"fast-edge":(7,1)}


def prepare():
    snapshot=OUT/"snapshot"; hashes={}
    names=subprocess.check_output(["git","ls-tree","-r","--name-only",BASELINE,"--","crates","Cargo.toml","Cargo.lock","rust-toolchain.toml"],cwd=ROOT,text=True).splitlines()
    for name in names:
        destination=snapshot/name;destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(subprocess.check_output(["git","show",f"{BASELINE}:{name}"],cwd=ROOT))
        hashes[name]=digest(destination)
    pipeline=snapshot/"crates/ibl_core/src/bake_pipeline.rs"
    text=pipeline.read_text(encoding="utf-8")
    start=text.index("fn effective_specular_sample_count(")
    end=text.index("fn effective_irradiance_sample_count(",start)
    original=text[start:end]
    quadratic=original.replace("fn effective_specular_sample_count(","fn baseline_specular_sample_count(")
    linear=original.replace("fn effective_specular_sample_count(","fn linear_specular_sample_count(").replace("roughness.clamp(0.0, 1.0).powi(2)","roughness.clamp(0.0, 1.0)")
    text=text[:start]+quadratic+linear+text[end:]
    hook="compute_cubemap_lod(sample.pdf, sample_count, base_width, cubemap_mips)"
    if text.count(hook)!=2: raise ValueError("Unexpected GGX/Lambert LOD call sites")
    # Only the second occurrence belongs to GGX. Lambert remains unchanged.
    first=text.index(hook);second=text.index(hook,first+len(hook))
    text=text[:second]+"compute_cubemap_lod(sample.pdf, experiment_footprint_samples(roughness, base_width), base_width, cubemap_mips)"+text[second+len(hook):]
    text+='''
fn experiment_curves() -> [f32; 2] {
    static CURVES: std::sync::OnceLock<[f32; 2]> = std::sync::OnceLock::new();
    *CURVES.get_or_init(|| [std::env::var("IBL_SAMPLE_LINEAR").unwrap().parse().unwrap(),
        std::env::var("IBL_FOOTPRINT_LINEAR").unwrap().parse().unwrap()])
}
pub(crate) fn effective_specular_sample_count(options: &BakeOptions, r: f32, size: u32, base: u32) -> u32 {
    if experiment_curves()[0] >= 1.0 { linear_specular_sample_count(options,r,size,base) }
    else { baseline_specular_sample_count(options,r,size,base) }
}
pub(crate) fn experiment_footprint_samples(r: f32, base: u32) -> u32 {
    // Private experiment invariant: complete natural chain, medium / 1024.
    let mip=(r*(31-base.max(1).leading_zeros()) as f32).round() as u32;
    let size=(base>>mip).max(1);
    let options=BakeOptions { quality:BakeQuality::Medium,sample_count:1024,..Default::default() };
    let low=baseline_specular_sample_count(&options,r,size,base);
    let high=linear_specular_sample_count(&options,r,size,base);
    (low as f32+(high-low) as f32*experiment_curves()[1]).round() as u32
}
'''
    pipeline.write_text(text,encoding="utf-8")
    encoder=snapshot/"crates/ktx2_writer/src/compress.rs";text=encoder.read_text(encoding="utf-8")
    text=text.replace("for y in 0..face_usize {","for y in 0..padded_usize {").replace("for x in 0..face_usize {","for x in 0..padded_usize {")
    text=text.replace("let src = (y * face_usize + x) * 3;",'''if (x >= face_usize || y >= face_usize) && std::env::var("IBL_CODEC_EDGE").unwrap() != "1" { continue; }
            let src = (y.min(face_usize-1) * face_usize + x.min(face_usize-1)) * 3;''')
    text=text.replace("let settings = bc6h::basic_settings();",'''let settings=match std::env::var("IBL_CODEC").unwrap().as_str() {
        "0"=>bc6h::basic_settings(),"1"=>bc6h::slow_settings(),"2"=>bc6h::very_slow_settings(),
        "3"=>if face_size<=64 { bc6h::very_slow_settings() } else { bc6h::basic_settings() },
        "4"=>bc6h::EncodeSettings { refine_iterations_1p:8,refine_iterations_2p:8,..bc6h::slow_settings() },
        "5"=>bc6h::EncodeSettings { refine_iterations_1p:32,refine_iterations_2p:32,..bc6h::slow_settings() },
        "6"=>bc6h::EncodeSettings { refine_iterations_1p:8,refine_iterations_2p:8,..bc6h::basic_settings() },
        "7"=>bc6h::fast_settings(),
        _=>panic!("invalid experimental codec") };''')
    encoder.write_text(text,encoding="utf-8")
    for crate,source in [("ibl_core","export.rs"),("ktx2_writer","reencode.rs")]:
        target=snapshot/f"crates/{crate}/examples";target.mkdir(exist_ok=True)
        shutil.copyfile(Path(__file__).with_name(source),target/source)
    config=snapshot/".cargo/config.toml";config.parent.mkdir(exist_ok=True)
    config.write_text('[source.crates-io]\nreplace-with="pnpm-crates-io"\n[source.pnpm-crates-io]\ndirectory='+json.dumps(str(ROOT/".pnpm/crates/crates-io"))+'\n',encoding="utf-8")
    env=dict(os.environ,CARGO_TARGET_DIR=str(OUT/"build"))
    run(["cargo","build","--locked","--offline","--release","--manifest-path",snapshot/"Cargo.toml","-p","ibl_core","--example","export","-p","ktx2_writer","--example","reencode"],OUT/"prepare.log",env,snapshot)
    save(OUT/"preparation.json",dict(baseline=BASELINE,sources=hashes,experiment_pipeline=digest(pipeline),experiment_encoder=digest(encoder),
        executables={name:digest(OUT/f"build/release/examples/{name}.exe") for name in ("export","reencode")},tool=digest(__file__)))


def prepare_timing():
    # A static coupled-linear candidate has no per-sample experiment hooks.
    snapshot=OUT/"timing-snapshot";hashes={}
    names=subprocess.check_output(["git","ls-tree","-r","--name-only",BASELINE,"--","crates","Cargo.toml","Cargo.lock","rust-toolchain.toml"],cwd=ROOT,text=True).splitlines()
    for name in names:
        path=snapshot/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(subprocess.check_output(["git","show",f"{BASELINE}:{name}"],cwd=ROOT));hashes[name]=digest(path)
    pipeline=snapshot/"crates/ibl_core/src/bake_pipeline.rs";text=pipeline.read_text()
    old="roughness.clamp(0.0, 1.0).powi(2)"
    if text.count(old)!=1:raise ValueError("Unexpected budget injection point")
    pipeline.write_text(text.replace(old,"roughness.clamp(0.0, 1.0)"),encoding="utf-8")
    encoder=snapshot/"crates/ktx2_writer/src/compress.rs"
    shutil.copyfile(ROOT/"crates/ktx2_writer/src/compress.rs",encoder)
    config=snapshot/".cargo/config.toml";config.parent.mkdir(exist_ok=True)
    config.write_text('[source.crates-io]\nreplace-with="pnpm-crates-io"\n[source.pnpm-crates-io]\ndirectory='+json.dumps(str(ROOT/".pnpm/crates/crates-io"))+'\n',encoding="utf-8")
    env=dict(os.environ,CARGO_TARGET_DIR=str(OUT/"timing-build"))
    run(["cargo","build","--locked","--offline","--release","--manifest-path",snapshot/"Cargo.toml","-p","ibl_cli","--bins"],OUT/"prepare-timing.log",env,snapshot)
    save(OUT/"timing-preparation.json",dict(baseline=BASELINE,sources=hashes,pipeline=digest(pipeline),encoder=digest(encoder),
        binary=digest(OUT/"timing-build/release/ibl-baker.exe"),method="Static linear actual budget, coupled original FIS, current production encoder; no experiment hooks"))


def raw(case,size,policy,paths):
    directory=OUT/"raw"/str(size)/case/policy
    binary=OUT/"build/release/examples/export.exe"
    source=paths[case];files=sorted(source.glob("*.exr")) if source.is_dir() else [source]
    identity=dict(source={str(p):digest(p) for p in files},binary=digest(binary),size=size,policy=policy)
    cache=directory/"generation.json"
    if cache.exists():
        cached=json.loads(cache.read_text())
        if cached["identity"]==identity and cached.get("outputs") and all(
            (directory/name).is_file() and digest(directory/name)==sha for name,sha in cached["outputs"].items()):return directory
    sample,footprint=POLICIES[policy]
    env=dict(os.environ,RAYON_NUM_THREADS="4",IBL_SAMPLE_LINEAR=str(sample),IBL_FOOTPRINT_LINEAR=str(footprint))
    run([binary,source,directory,size],directory/"run.log",env)
    save(cache,dict(identity=identity,outputs={p.name:digest(p) for p in directory.iterdir() if p.suffix in (".f32",".ibla") or p.name=="metadata.json"}))
    return directory


def encode(source,size,codec):
    relative=source.relative_to(OUT/"raw")
    directory=OUT/"encoded"/relative/codec;directory.mkdir(parents=True,exist_ok=True)
    binary=OUT/"build/release/examples/reencode.exe"
    identity=dict(raw=digest(source/"generation.json"),binary=digest(binary),codec=codec)
    cache=directory/"generation.json"
    if cache.exists():
        cached=json.loads(cache.read_text());payload=directory/"specular.ktx2"
        if cached["identity"]==identity and payload.is_file() and cached["sha256"]==digest(payload):return directory
    mode,edge=CODECS[codec];env=dict(os.environ,IBL_CODEC=str(mode),IBL_CODEC_EDGE=str(edge))
    run([binary,source,directory/"specular.ktx2",size],directory/"run.log",env)
    save(cache,dict(identity=identity,sha256=digest(directory/"specular.ktx2"),bytes=(directory/"specular.ktx2").stat().st_size,
        seconds=float((directory/"run.log").read_text().strip())))
    return directory


def initialize(packages):
    for p in reversed(packages):sys.path.insert(0,str(p.resolve()))
    import numpy as np
    import OpenEXR
    previous.np=np;previous.OpenEXR=OpenEXR;previous.quality=module("full_chain_quality",ROOT/"scripts/source-sampling/quality.py");previous.quality.np=np
    return previous.inputs()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["prepare","prepare-timing","generate"])
    parser.add_argument("--python-packages",type=Path,action="append",default=[])
    parser.add_argument("--sizes",default="128")
    parser.add_argument("--cases",default="hemisphere-0,hemisphere-1,hemisphere-2")
    parser.add_argument("--policies",default=",".join(POLICIES))
    parser.add_argument("--codecs",default=",".join(CODECS))
    args=parser.parse_args()
    if args.command=="prepare":prepare();return
    if args.command=="prepare-timing":prepare_timing();return
    paths,_,_=initialize(args.python_packages)
    for size in map(int,args.sizes.split(",")):
        for case in args.cases.split(","):
            for policy in args.policies.split(","):
                source=raw(case,size,policy,paths)
                for codec in filter(None,args.codecs.split(",")):
                    encode(source,size,codec)
                print(size,case,policy,flush=True)

if __name__=="__main__":main()

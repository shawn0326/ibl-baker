//! Private raw-float encoder. No public decoder or runtime API is added.
include!("../src/lib.rs");
use std::path::PathBuf;

fn main() -> Result<(),Box<dyn std::error::Error>> {
    let args: Vec<_>=std::env::args().skip(1).collect();
    if args.len()!=3 { return Err("expected RAW_DIRECTORY OUTPUT_KTX2 BASE_SIZE".into()); }
    let input=PathBuf::from(&args[0]);
    let mut n: u32=args[2].parse()?;
    let mut levels=Vec::new();
    for mip in 0.. {
        let mut faces=Vec::new();
        for face in ["px","nx","py","ny","pz","nz"] {
            let bytes=std::fs::read(input.join(format!("m{mip}_{face}.f32")))?;
            if bytes.len()!=n as usize*n as usize*12 { return Err("unexpected raw-float face length".into()); }
            faces.push(bytes.chunks_exact(4).map(|b|f32::from_le_bytes(b.try_into().unwrap())).collect());
        }
        levels.push(CubemapLevel { face_pixels:faces.try_into().unwrap(),face_size:n });
        if n==1 { break; }
        n/=2;
    }
    let start=std::time::Instant::now();
    let bytes=write_bc6h_cubemap_ktx2(&levels,&WriterMetadata { writer:"ibl-baker v0.2.3" })?;
    let seconds=start.elapsed().as_secs_f64();
    std::fs::write(&args[1],bytes)?;
    println!("{seconds:.9}");
    Ok(())
}

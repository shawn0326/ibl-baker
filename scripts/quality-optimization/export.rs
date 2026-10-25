//! Private quality exporter, installed only in a task-owned source snapshot.
include!("../src/lib.rs");
use std::io::Write;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 5 { return Err("expected INPUT OUTPUT SIZE MIN_SIZE SAMPLES".into()); }
    let input = PathBuf::from(&args[0]);
    let out = PathBuf::from(&args[1]);
    let options = BakeOptions { cube_size: args[2].parse()?, specular_min_size: Some(args[3].parse()?),
        sample_count: args[4].parse()?, quality: BakeQuality::Medium, ..Default::default() };
    let (source, format) = if input.is_dir() {
        load_environment_from_cubemap_paths(&CubemapInputPaths {
            face_paths: std::array::from_fn(|f| input.join(format!("{}.exr", Face::all()[f].as_str()))) })?
    } else { load_environment_from_file(&input)? };
    fs::create_dir_all(&out)?;
    let start = std::time::Instant::now();
    let baked = bake_environment_to_cubemap(format, &source, options.clone())?;
    let bake_seconds = start.elapsed().as_secs_f64();
    let mut levels = Vec::new();
    for (mip, faces) in baked.levels.iter().enumerate() {
        let r = mip as f32 / (baked.levels.len() - 1).max(1) as f32;
        let size = faces[0].width;
        let samples = if mip == 0 { 0 } else { bake_pipeline::effective_specular_sample_count(&options, r, size, options.cube_size) };
        levels.push(format!("{{\"mip\":{mip},\"size\":{size},\"roughness\":{r},\"samples\":{samples}}}"));
        for (face, image) in Face::all().iter().zip(faces) {
            let mut f = std::io::BufWriter::new(fs::File::create(out.join(format!("m{mip}_{}.f32", face.as_str())))?);
            for pixel in &image.pixels { for v in pixel.to_array() { f.write_all(&v.to_le_bytes())?; } }
        }
    }
    let (asset, _) = baked.to_asset_with_report()?;
    write_asset(out.join("specular.ibla"), &asset)?;
    fs::write(out.join("specular.ktx2"), baked.to_ktx2_with_report()?.0)?;
    fs::write(out.join("metadata.json"), format!("{{\"levels\":[{}],\"bake_seconds\":{bake_seconds},\"samples\":{},\"quality\":\"medium\"}}", levels.join(","), options.sample_count))?;
    Ok(())
}

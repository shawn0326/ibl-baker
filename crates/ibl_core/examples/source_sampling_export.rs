//! Private raw-float acceptance helper. No public API or shipped format changes.
//! Build this same source against both the frozen baseline and the candidate.
include!("../src/lib.rs");

use std::io::{BufWriter, Write};
use std::time::Instant;

type ExportResult<T> = Result<T, Box<dyn std::error::Error>>;

fn main() {
    if let Err(error) = export() {
        eprintln!("Source sampling export failed: {error}");
        std::process::exit(1);
    }
}

fn export() -> ExportResult<()> {
    let mut args = std::env::args().skip(1);
    let Some(input) = args.next() else {
        return Err("expected INPUT OUTPUT [--size N] [--samples N] [--rotation DEGREES]".into());
    };
    if input == "--help" {
        println!("Private raw-float export: INPUT OUTPUT [--size N] [--irradiance-size N] [--samples N] [--rotation DEGREES]\nINPUT is a panorama, or a directory containing px.exr, nx.exr, py.exr, ny.exr, pz.exr, nz.exr. Outputs are little-endian interleaved RGB f32 plus metadata and the production BRDF PNG.");
        return Ok(());
    }
    let input = PathBuf::from(input);
    let output = PathBuf::from(args.next().ok_or("missing output directory")?);
    let mut options = BakeOptions {
        cube_size: 256,
        quality: BakeQuality::High,
        ..BakeOptions::default()
    };
    while let Some(name) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {name}"))?;
        match name.as_str() {
            "--size" => options.cube_size = value.parse()?,
            "--irradiance-size" => options.irradiance_size = value.parse()?,
            "--samples" => options.sample_count = value.parse()?,
            "--rotation" => options.rotation_degrees = value.parse()?,
            _ => return Err(format!("unknown option: {name}").into()),
        }
    }
    if options.cube_size == 0 || options.irradiance_size == 0 || options.sample_count == 0 {
        return Err("sizes and sample count must be positive".into());
    }
    if !options.rotation_degrees.is_finite() {
        return Err("rotation must be finite".into());
    }
    fs::create_dir_all(&output)?;
    let started = Instant::now();
    let (source, _) = if input.is_dir() {
        source_image::load_environment_from_cubemap_paths(&CubemapInputPaths {
            face_paths: std::array::from_fn(|i| {
                input.join(format!("{}.exr", Face::all()[i].as_str()))
            }),
        })?
    } else {
        source_image::load_environment_from_file(&input)?
    };
    let load_ms = started.elapsed().as_secs_f64() * 1000.0;
    let started = Instant::now();
    let mip_count = estimate_mip_count(options.cube_size);
    let specular = build_specular_raw(&source, &options, mip_count);
    let specular_ms = started.elapsed().as_secs_f64() * 1000.0;
    let started = Instant::now();
    let irradiance = build_irradiance_raw(&source, &options);
    let irradiance_ms = started.elapsed().as_secs_f64() * 1000.0;
    let started = Instant::now();
    let (entries, _) = build_brdf_lut_chunk_entries(BRDF_LUT_SIZE, &options)?;
    fs::write(output.join("brdf-lut.png"), &entries[0].chunk.bytes)?;
    let brdf_ms = started.elapsed().as_secs_f64() * 1000.0;
    let mut levels = Vec::new();
    for (mip, faces) in specular.iter().enumerate() {
        for (face, image) in Face::all().iter().zip(faces) {
            write_rgb_f32(&output.join(format!("m{mip}_{}.f32", face.as_str())), image)?;
        }
        let roughness = mip as f32 / mip_count.saturating_sub(1).max(1) as f32;
        levels.push(format!(
            "{{\"mip\":{mip},\"size\":{},\"roughness\":{roughness}}}",
            faces[0].width
        ));
    }
    for (face, image) in Face::all().iter().zip(&irradiance) {
        write_rgb_f32(
            &output.join(format!("irradiance_{}.f32", face.as_str())),
            image,
        )?;
    }
    let metadata = format!(
        "{{\n  \"schema_version\":1,\n  \"generator\":\"production raw-float export\",\n  \"storage\":\"little-endian interleaved RGB IEEE754 f32\",\n  \"clamping\":\"none\",\n  \"size\":{},\n  \"irradiance_size\":{},\n  \"sample_count\":{},\n  \"quality\":\"high\",\n  \"rotation_degrees\":{},\n  \"direction_transform\":\"identity\",\n  \"roughness_mapping\":\"linear\",\n  \"levels\":[{}],\n  \"timings_ms\":{{\"source_load\":{load_ms},\"specular_bake\":{specular_ms},\"irradiance_bake\":{irradiance_ms},\"brdf_lut\":{brdf_ms}}}\n}}\n",
        options.cube_size, options.irradiance_size, options.sample_count,
        options.rotation_degrees, levels.join(",")
    );
    fs::write(output.join("metadata.json"), metadata)?;
    println!(
        "Exported {mip_count} unencoded specular levels and irradiance to {}",
        output.display()
    );
    Ok(())
}

fn write_rgb_f32(path: &Path, image: &source_image::SourceImage) -> ExportResult<()> {
    let mut writer = BufWriter::new(fs::File::create(path)?);
    for pixel in &image.pixels {
        if !pixel.is_finite() {
            return Err(format!("non-finite pixels in {}", path.display()).into());
        }
        for component in [pixel.x, pixel.y, pixel.z] {
            writer.write_all(&component.to_le_bytes())?;
        }
    }
    writer.flush()?;
    Ok(())
}

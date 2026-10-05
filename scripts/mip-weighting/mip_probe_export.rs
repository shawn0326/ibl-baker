//! Private source-mip and fixed-direction experiment exporter.
//! Prepared snapshots copy this file into crates/ibl_core/examples.
include!("../src/lib.rs");

use std::io::{BufWriter, Write};

type ProbeResult<T> = Result<T, Box<dyn std::error::Error>>;

fn main() {
    if let Err(error) = export_probes() {
        eprintln!("Mip probe export failed: {error}");
        std::process::exit(1);
    }
}

fn export_probes() -> ProbeResult<()> {
    let mut args = std::env::args().skip(1);
    let Some(input) = args.next() else {
        return Err("expected INPUT OUTPUT --probes CSV [--size N] [--rotation DEGREES]".into());
    };
    if input == "--help" {
        println!("Private mip probe export: INPUT OUTPUT --probes CSV [--size N] [--rotation DEGREES]\nCSV has one x,y,z direction per row; a single x,y,z header is optional.\nThe exact proposal budgets are 256 and 1024, independent of CLI adaptive budgets.\nINPUT is a panorama, or a directory containing px.exr, nx.exr, py.exr, ny.exr, pz.exr, nz.exr.");
        return Ok(());
    }
    let input = PathBuf::from(input);
    let output = PathBuf::from(args.next().ok_or("missing output directory")?);
    let mut size = 256_u32;
    let mut rotation = 0.0_f32;
    let mut probes_path = None;
    while let Some(option) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {option}"))?;
        match option.as_str() {
            "--size" => size = value.parse()?,
            "--rotation" => rotation = value.parse()?,
            "--probes" => probes_path = Some(PathBuf::from(value)),
            _ => return Err(format!("unknown option {option}").into()),
        }
    }
    if size == 0 || !rotation.is_finite() {
        return Err("size must be positive and rotation finite".into());
    }
    let directions = read_probe_csv(&probes_path.ok_or("--probes is required")?)?;
    let (source, _) = if input.is_dir() {
        source_image::load_environment_from_cubemap_paths(&CubemapInputPaths {
            face_paths: std::array::from_fn(|index| {
                input.join(format!("{}.exr", Face::all()[index].as_str()))
            }),
        })?
    } else {
        source_image::load_environment_from_file(&input)?
    };
    let measured = bake_pipeline::measure_fixed_mip_probes(&source, size, rotation, &directions);
    fs::create_dir_all(&output)?;
    let mut level_json = Vec::new();
    for (level, faces) in measured.source_mips.iter().enumerate() {
        let mut files = Vec::new();
        for (face, image) in Face::all().iter().zip(faces) {
            let file = format!("source_m{level}_{}.f32", face.as_str());
            write_probe_colors(&output.join(&file), &image.pixels)?;
            files.push(format!("\"{file}\""));
        }
        level_json.push(format!(
            "{{\"level\":{level},\"size\":{},\"files\":[{}]}}",
            faces[0].width,
            files.join(",")
        ));
    }
    let mut batch_json = Vec::new();
    for (index, batch) in measured.batches.iter().enumerate() {
        let roughness_index = index % 6;
        let file = if batch.distribution == "lambert" {
            format!("probes_lambert_s{}.f32", batch.requested_proposals)
        } else {
            format!(
                "probes_ggx_s{}_r{roughness_index}.f32",
                batch.requested_proposals
            )
        };
        write_probe_colors(&output.join(&file), &batch.colors)?;
        let accepted = batch
            .accepted_light_samples
            .iter()
            .map(u32::to_string)
            .collect::<Vec<_>>()
            .join(",");
        let accepted_min = batch
            .accepted_light_samples
            .iter()
            .min()
            .copied()
            .unwrap_or(0);
        let accepted_max = batch
            .accepted_light_samples
            .iter()
            .max()
            .copied()
            .unwrap_or(0);
        batch_json.push(format!("{{\"distribution\":\"{}\",\"roughness\":{},\"roughness_f32_bits\":{},\"requested_proposals\":{},\"kernel_proposals\":{},\"accepted_light_samples_min\":{accepted_min},\"accepted_light_samples_max\":{accepted_max},\"accepted_light_samples\":[{accepted}],\"file\":\"{file}\"}}",
            batch.distribution, batch.roughness, batch.roughness.to_bits(), batch.requested_proposals, batch.kernel_proposals));
    }
    let direction_json = directions
        .iter()
        .map(|direction| format!("[{},{},{}]", direction.x, direction.y, direction.z))
        .collect::<Vec<_>>()
        .join(",");
    let metadata = format!("{{\n  \"schema_version\":1,\n  \"storage\":\"little-endian interleaved RGB IEEE754 f32\",\n  \"clamping\":\"none\",\n  \"size\":{size},\n  \"rotation_degrees\":{rotation},\n  \"directions\":[{direction_json}],\n  \"source_levels\":[{}],\n  \"probe_batches\":[{}]\n}}\n", level_json.join(","), batch_json.join(","));
    fs::write(output.join("metadata.json"), metadata)?;
    println!(
        "Exported {} source levels and {} fixed probe batches to {}",
        measured.source_mips.len(),
        measured.batches.len(),
        output.display()
    );
    Ok(())
}

fn read_probe_csv(path: &Path) -> ProbeResult<Vec<glam::Vec3>> {
    let text = fs::read_to_string(path)?;
    let mut directions = Vec::new();
    for (line_index, line) in text.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if directions.is_empty() && line.eq_ignore_ascii_case("x,y,z") {
            continue;
        }
        let values = line
            .split(',')
            .map(str::trim)
            .map(str::parse::<f32>)
            .collect::<Result<Vec<_>, _>>()?;
        if values.len() != 3 {
            return Err(
                format!("line {} must have exactly three components", line_index + 1).into(),
            );
        }
        let direction = glam::Vec3::new(values[0], values[1], values[2]);
        if !direction.is_finite()
            || !direction.length_squared().is_finite()
            || direction.length_squared() < 1.0e-20
        {
            return Err(format!("line {} has an invalid direction", line_index + 1).into());
        }
        directions.push(direction.normalize());
    }
    if directions.is_empty() {
        return Err("probe CSV must contain at least one direction".into());
    }
    Ok(directions)
}

fn write_probe_colors(path: &Path, pixels: &[glam::Vec3]) -> ProbeResult<()> {
    let mut writer = BufWriter::new(fs::File::create(path)?);
    for color in pixels {
        if !color.is_finite() {
            return Err(format!("non-finite colors in {}", path.display()).into());
        }
        for component in [color.x, color.y, color.z] {
            writer.write_all(&component.to_le_bytes())?;
        }
    }
    writer.flush()?;
    Ok(())
}

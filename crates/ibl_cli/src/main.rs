use std::collections::BTreeMap;
use std::env;
use std::fmt::{self, Display, Formatter};
use std::fs;
use std::io::{Cursor, Read};
use std::path::{Path, PathBuf};
use std::process;

use ibl_core::{
    bake_cubemap_to_asset, bake_to_asset, inspect_asset, read_asset, validate_asset, write_asset,
    AssetKind, BakeOptions, BakeQuality, CubemapInputPaths, EncodingKind, IblError, SourceFormat,
};

fn main() {
    let exit_code = match run(env::args().collect()) {
        Ok(output) => {
            if !output.is_empty() {
                println!("{output}");
            }
            0
        }
        Err(error) => {
            eprintln!("Error: {error}");
            1
        }
    };

    process::exit(exit_code);
}

fn run(args: Vec<String>) -> Result<String, CliError> {
    if args.len() <= 1 {
        return Ok(help_text());
    }

    match args[1].as_str() {
        "help" | "--help" | "-h" => Ok(help_text()),
        "bake" => handle_bake(&args[2..]),
        "validate" => handle_validate(&args[2..]),
        other => Err(CliError::Usage(format!("unknown command: {other}"))),
    }
}

fn handle_bake(args: &[String]) -> Result<String, CliError> {
    if args.is_empty() {
        return Err(CliError::Usage(
            "bake requires an input image path".to_string(),
        ));
    }

    let input = PathBuf::from(&args[0]);
    let mut options = BakeOptions::default();
    let mut requested_size = RequestedSize::Auto;
    let mut requested_encoding = RequestedEncoding::Auto;
    let mut output_dir: Option<PathBuf> = None;
    let mut target_selection = TargetSelection::default();
    let mut requested_faces: Option<String> = None;

    let mut index = 1;
    while index < args.len() {
        let flag = &args[index];
        let value = args
            .get(index + 1)
            .ok_or_else(|| CliError::Usage(format!("missing value for {flag}")))?;

        match flag.as_str() {
            "--target" => target_selection.include(parse_bake_target(value)?),
            "--size" => requested_size = parse_size(value)?,
            "--irradiance-size" => options.irradiance_size = parse_u32(value, "--irradiance-size")?,
            "--encoding" => requested_encoding = parse_encoding(value)?,
            "--out-dir" => output_dir = Some(PathBuf::from(value)),
            "--rotation" => options.rotation_degrees = parse_f32(value, "--rotation")?,
            "--samples" => options.sample_count = parse_u32(value, "--samples")?,
            "--quality" => options.quality = parse_quality(value)?,
            "--faces" => requested_faces = Some(value.to_string()),
            _ => return Err(CliError::Usage(format!("unknown bake option: {flag}"))),
        }

        index += 2;
    }

    let output_dir =
        output_dir.ok_or_else(|| CliError::Usage("bake requires --out-dir <path>".to_string()))?;
    fs::create_dir_all(&output_dir).map_err(IblError::from)?;

    let input = resolve_bake_input(input, requested_faces.as_deref())?;
    options.cube_size = resolve_requested_size(&input, requested_size)?;
    options.output_encoding = resolve_requested_encoding(&input, requested_encoding);

    let mut outputs = Vec::new();
    for target in target_selection.resolved_targets() {
        match target {
            BakeTarget::Specular => {
                let mut target_options = options.clone();
                target_options.asset_kind = AssetKind::SpecularCubemap;
                let asset = bake_input_to_asset(&input, target_options)?;
                let output = output_dir.join("specular.ibla");
                write_asset(&output, &asset)?;
                outputs.push(output);
            }
            BakeTarget::Irradiance => {
                let mut target_options = options.clone();
                target_options.asset_kind = AssetKind::IrradianceCubemap;
                let asset = bake_input_to_asset(&input, target_options)?;
                let output = output_dir.join("irradiance.ibla");
                write_asset(&output, &asset)?;
                outputs.push(output);
            }
            BakeTarget::Lut => {
                let mut target_options = options.clone();
                target_options.asset_kind = AssetKind::BrdfLut;
                let asset = bake_input_to_asset(&input, target_options)?;
                let output = output_dir.join("brdf-lut.png");
                let bytes = asset
                    .chunks
                    .first()
                    .ok_or_else(|| {
                        CliError::Core(IblError::InvalidFormat(
                            "brdf-lut bake did not produce an image chunk".to_string(),
                        ))
                    })?
                    .bytes
                    .clone();
                fs::write(&output, bytes).map_err(IblError::from)?;
                outputs.push(output);
            }
        }
    }

    let mut lines = vec![format!(
        "Baked {} output(s) from {} into {}",
        outputs.len(),
        display_path(input.path()),
        display_path(&output_dir)
    )];
    lines.extend(
        outputs
            .iter()
            .map(|path| format!("Wrote {}", display_path(path))),
    );
    Ok(lines.join("\n"))
}

fn handle_validate(args: &[String]) -> Result<String, CliError> {
    let asset_path = expect_single_path(args, "validate")?;
    let asset = read_asset(&asset_path)?;
    let info = inspect_asset(&asset);
    let report = validate_asset(&asset);

    let mut lines = vec![
        format!("Version: {}", info.version),
        format!("Face Count: {}", info.face_count),
        format!("Chunks: {}", info.chunk_count),
        format!("Width: {}", info.width),
        format!("Height: {}", info.height),
        format!("Mip Count: {}", info.mip_count),
        format!("Encoding: {}", info.encoding),
        format!(
            "Validation: {}",
            if report.is_valid { "passed" } else { "failed" }
        ),
    ];

    for issue in report.issues {
        lines.push(format!("{:?}: {}", issue.severity, issue.message));
    }
    Ok(lines.join("\n"))
}

fn expect_single_path(args: &[String], command: &str) -> Result<PathBuf, CliError> {
    if args.len() != 1 {
        return Err(CliError::Usage(format!(
            "{command} requires exactly one asset path"
        )));
    }
    Ok(PathBuf::from(&args[0]))
}

fn parse_bake_target(value: &str) -> Result<BakeTarget, CliError> {
    match value {
        "specular" => Ok(BakeTarget::Specular),
        "irradiance" => Ok(BakeTarget::Irradiance),
        "lut" => Ok(BakeTarget::Lut),
        other => Err(CliError::Usage(format!(
            "unsupported target: {other}; expected specular, irradiance, or lut"
        ))),
    }
}

fn parse_size(value: &str) -> Result<RequestedSize, CliError> {
    if value == "auto" {
        return Ok(RequestedSize::Auto);
    }

    Ok(RequestedSize::Exact(parse_u32(value, "--size")?))
}

fn parse_encoding(value: &str) -> Result<RequestedEncoding, CliError> {
    if value == "auto" {
        return Ok(RequestedEncoding::Auto);
    }

    value
        .parse::<EncodingKind>()
        .map(RequestedEncoding::Explicit)
        .map_err(|_| {
            CliError::Usage(format!(
                "unsupported encoding: {value}; expected auto, rgbd-srgb, srgb, or linear"
            ))
        })
}

fn parse_quality(value: &str) -> Result<BakeQuality, CliError> {
    match value {
        "low" => Ok(BakeQuality::Low),
        "medium" => Ok(BakeQuality::Medium),
        "high" => Ok(BakeQuality::High),
        other => Err(CliError::Usage(format!(
            "unsupported quality: {other}; expected low, medium, or high"
        ))),
    }
}

fn parse_u32(value: &str, flag: &str) -> Result<u32, CliError> {
    value
        .parse::<u32>()
        .map_err(|_| CliError::Usage(format!("invalid value for {flag}: {value}")))
}

fn parse_f32(value: &str, flag: &str) -> Result<f32, CliError> {
    value
        .parse::<f32>()
        .map_err(|_| CliError::Usage(format!("invalid value for {flag}: {value}")))
}

fn display_path(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

fn resolve_requested_size(input: &BakeInput, requested: RequestedSize) -> Result<u32, CliError> {
    match requested {
        RequestedSize::Exact(size) => Ok(size),
        RequestedSize::Auto => Ok(resolve_auto_size(input).unwrap_or(DEFAULT_SPECULAR_SIZE)),
    }
}

fn resolve_auto_size(input: &BakeInput) -> Option<u32> {
    match input {
        BakeInput::File { path } => {
            let (width, height) = read_image_dimensions(path).ok()??;
            Some(choose_auto_specular_size(width, height))
        }
        BakeInput::Cubemap { face_size, .. } => Some(choose_supported_specular_size(*face_size)),
    }
}

fn resolve_requested_encoding(input: &BakeInput, requested: RequestedEncoding) -> EncodingKind {
    match requested {
        RequestedEncoding::Explicit(encoding) => encoding,
        RequestedEncoding::Auto => match input.source_format() {
            SourceFormat::Hdr | SourceFormat::Exr => EncodingKind::RgbdSrgb,
            SourceFormat::Png | SourceFormat::Jpg | SourceFormat::Jpeg | SourceFormat::Unknown => {
                EncodingKind::Srgb
            }
        },
    }
}

fn choose_auto_specular_size(width: u32, height: u32) -> u32 {
    let estimated_face_size = estimate_equirect_face_size(width, height);
    choose_supported_specular_size(estimated_face_size)
}

fn estimate_equirect_face_size(width: u32, height: u32) -> u32 {
    let width_based = (width / 4).max(1);
    let height_based = (height / 2).max(1);
    width_based.min(height_based)
}

fn choose_supported_specular_size(face_size: u32) -> u32 {
    const AUTO_SIZE_BUCKETS: [u32; 6] = [128, 256, 512, 1024, 2048, 4096];

    AUTO_SIZE_BUCKETS
        .iter()
        .rev()
        .copied()
        .find(|size| *size <= face_size)
        .unwrap_or(AUTO_SIZE_BUCKETS[0])
}

fn bake_input_to_asset(input: &BakeInput, options: BakeOptions) -> Result<ibl_core::IblAsset, CliError> {
    match input {
        BakeInput::File { path } => bake_to_asset(path, options).map_err(CliError::from),
        BakeInput::Cubemap { faces, .. } => bake_cubemap_to_asset(faces, options).map_err(CliError::from),
    }
}

fn resolve_bake_input(input: PathBuf, requested_faces: Option<&str>) -> Result<BakeInput, CliError> {
    if input.is_file() {
        if requested_faces.is_some() {
            return Err(CliError::Usage(
                "--faces can only be used when the bake input path is a directory".to_string(),
            ));
        }
        return Ok(BakeInput::File { path: input });
    }

    if input.is_dir() {
        let faces = match requested_faces {
            Some(value) => resolve_explicit_faces(&input, value)?,
            None => auto_detect_cubemap_faces(&input)?,
        };
        let (source_format, face_size) = inspect_cubemap_faces(&faces)?;
        return Ok(BakeInput::Cubemap {
            root: input,
            faces,
            source_format,
            face_size,
        });
    }

    Err(CliError::Usage(format!(
        "input path does not exist: {}",
        display_path(&input)
    )))
}

fn resolve_explicit_faces(root: &Path, value: &str) -> Result<CubemapInputPaths, CliError> {
    let names = value
        .split(',')
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
        .collect::<Vec<_>>();
    if names.len() != 6 {
        return Err(CliError::Usage(
            "--faces expects exactly 6 file names in px,nx,py,ny,pz,nz order".to_string(),
        ));
    }

    let paths = names
        .into_iter()
        .map(|name| resolve_face_name(root, name))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(CubemapInputPaths::from_face_order(
        paths
            .try_into()
            .unwrap_or_else(|_| unreachable!("explicit cubemap faces should contain six paths")),
    ))
}

fn auto_detect_cubemap_faces(root: &Path) -> Result<CubemapInputPaths, CliError> {
    const PRESETS: [(&str, [&str; 6]); 2] = [
        ("px/nx/py/ny/pz/nz", ["px", "nx", "py", "ny", "pz", "nz"]),
        (
            "posx/negx/posy/negy/posz/negz",
            ["posx", "negx", "posy", "negy", "posz", "negz"],
        ),
    ];

    let mut files_by_stem: BTreeMap<String, Vec<PathBuf>> = BTreeMap::new();
    for entry in fs::read_dir(root).map_err(IblError::from)? {
        let entry = entry.map_err(IblError::from)?;
        let path = entry.path();
        if !path.is_file() {
            continue;
        }

        let source_format = SourceFormat::from_input_path(&path);
        if source_format == SourceFormat::Unknown {
            continue;
        }

        let stem = path
            .file_stem()
            .and_then(|value| value.to_str())
            .ok_or_else(|| {
                CliError::Usage(format!(
                    "cubemap face file name must be valid UTF-8: {}",
                    display_path(&path)
                ))
            })?
            .to_ascii_lowercase();
        files_by_stem.entry(stem).or_default().push(path);
    }

    let mut matches = Vec::new();
    for (label, preset) in PRESETS {
        let mut resolved = Vec::with_capacity(6);
        let mut missing = false;
        for expected in preset {
            match files_by_stem.get(expected) {
                Some(paths) if paths.len() == 1 => resolved.push(paths[0].clone()),
                Some(_) | None => {
                    missing = true;
                    break;
                }
            }
        }

        if !missing {
            matches.push((label, resolved));
        }
    }

    match matches.len() {
        1 => {
            let (_, resolved) = matches.remove(0);
            Ok(CubemapInputPaths::from_face_order(
                resolved
                    .try_into()
                    .unwrap_or_else(|_| unreachable!("auto-detected cubemap should contain six paths")),
            ))
        }
        0 => Err(CliError::Usage(format!(
            "could not auto-detect cubemap faces in {}; supported names are px/nx/py/ny/pz/nz or posx/negx/posy/negy/posz/negz; use --faces <px,nx,py,ny,pz,nz>",
            display_path(root)
        ))),
        _ => Err(CliError::Usage(format!(
            "multiple cubemap naming presets matched in {}; use --faces <px,nx,py,ny,pz,nz> to disambiguate",
            display_path(root)
        ))),
    }
}

fn resolve_face_name(root: &Path, name: &str) -> Result<PathBuf, CliError> {
    let candidate = Path::new(name);
    if candidate.is_absolute() || candidate.components().count() != 1 {
        return Err(CliError::Usage(
            "--faces entries must be file names within the input directory".to_string(),
        ));
    }

    Ok(root.join(candidate))
}

fn inspect_cubemap_faces(faces: &CubemapInputPaths) -> Result<(SourceFormat, u32), CliError> {
    let mut resolved_format = None;
    let mut face_size = None;

    for path in faces.as_array() {
        let source_format = normalize_source_format(SourceFormat::from_input_path(path));
        if source_format == SourceFormat::Unknown {
            return Err(CliError::Usage(format!(
                "unsupported cubemap face format: {}",
                display_path(path)
            )));
        }

        match resolved_format {
            Some(expected) if expected != source_format => {
                return Err(CliError::Usage(
                    "cubemap faces must use the same source format family".to_string(),
                ));
            }
            None => resolved_format = Some(source_format),
            _ => {}
        }

        let (width, height) = read_image_dimensions(path)?.ok_or_else(|| {
            CliError::Usage(format!(
                "could not read dimensions from cubemap face: {}",
                display_path(path)
            ))
        })?;
        if width != height {
            return Err(CliError::Usage(format!(
                "cubemap faces must be square: {} is {}x{}",
                display_path(path),
                width,
                height
            )));
        }

        match face_size {
            Some(expected) if expected != width => {
                return Err(CliError::Usage(
                    "cubemap faces must share the same dimensions".to_string(),
                ));
            }
            None => face_size = Some(width),
            _ => {}
        }
    }

    Ok((
        resolved_format.unwrap_or(SourceFormat::Unknown),
        face_size.unwrap_or(0),
    ))
}

fn normalize_source_format(source_format: SourceFormat) -> SourceFormat {
    match source_format {
        SourceFormat::Jpeg => SourceFormat::Jpg,
        other => other,
    }
}

fn read_image_dimensions(path: &Path) -> Result<Option<(u32, u32)>, CliError> {
    let source_format = SourceFormat::from_input_path(path);
    let bytes = fs::read(path).map_err(IblError::from)?;

    let dimensions = match source_format {
        SourceFormat::Hdr => parse_hdr_dimensions(&bytes),
        SourceFormat::Exr => parse_exr_dimensions(&bytes),
        SourceFormat::Png => parse_png_dimensions(&bytes),
        SourceFormat::Jpg | SourceFormat::Jpeg => parse_jpeg_dimensions(&bytes),
        SourceFormat::Unknown => parse_png_dimensions(&bytes)
            .or_else(|| parse_jpeg_dimensions(&bytes))
            .or_else(|| parse_hdr_dimensions(&bytes))
            .or_else(|| parse_exr_dimensions(&bytes)),
    };

    Ok(dimensions)
}

fn parse_png_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    if bytes.len() < 24 || &bytes[..8] != b"\x89PNG\r\n\x1a\n" {
        return None;
    }

    let width = u32::from_be_bytes(bytes[16..20].try_into().ok()?);
    let height = u32::from_be_bytes(bytes[20..24].try_into().ok()?);
    Some((width, height))
}

fn parse_jpeg_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    if bytes.len() < 4 || bytes[0] != 0xFF || bytes[1] != 0xD8 {
        return None;
    }

    let mut cursor = Cursor::new(bytes);
    let mut soi = [0u8; 2];
    cursor.read_exact(&mut soi).ok()?;

    loop {
        let mut byte = [0u8; 1];
        cursor.read_exact(&mut byte).ok()?;
        while byte[0] != 0xFF {
            cursor.read_exact(&mut byte).ok()?;
        }

        cursor.read_exact(&mut byte).ok()?;
        while byte[0] == 0xFF {
            cursor.read_exact(&mut byte).ok()?;
        }

        let marker = byte[0];
        if marker == 0xD9 || marker == 0xDA {
            return None;
        }

        if (0xD0..=0xD7).contains(&marker) || marker == 0x01 {
            continue;
        }

        let mut length_bytes = [0u8; 2];
        cursor.read_exact(&mut length_bytes).ok()?;
        let segment_length = u16::from_be_bytes(length_bytes);
        if segment_length < 2 {
            return None;
        }

        if matches!(
            marker,
            0xC0 | 0xC1
                | 0xC2
                | 0xC3
                | 0xC5
                | 0xC6
                | 0xC7
                | 0xC9
                | 0xCA
                | 0xCB
                | 0xCD
                | 0xCE
                | 0xCF
        ) {
            let mut frame_header = vec![0u8; usize::from(segment_length - 2)];
            cursor.read_exact(&mut frame_header).ok()?;
            if frame_header.len() < 5 {
                return None;
            }
            let height = u16::from_be_bytes([frame_header[1], frame_header[2]]) as u32;
            let width = u16::from_be_bytes([frame_header[3], frame_header[4]]) as u32;
            return Some((width, height));
        }

        let next_position = cursor.position() + u64::from(segment_length - 2);
        if next_position > bytes.len() as u64 {
            return None;
        }
        cursor.set_position(next_position);
    }
}

fn parse_hdr_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    let text = String::from_utf8_lossy(bytes);
    for line in text.lines() {
        let tokens: Vec<&str> = line.split_whitespace().collect();
        if tokens.len() != 4 {
            continue;
        }

        let first_axis = tokens[0];
        let first_value = tokens[1].parse::<u32>().ok()?;
        let second_axis = tokens[2];
        let second_value = tokens[3].parse::<u32>().ok()?;

        if first_axis.ends_with('Y') && second_axis.ends_with('X') {
            return Some((second_value, first_value));
        }

        if first_axis.ends_with('X') && second_axis.ends_with('Y') {
            return Some((first_value, second_value));
        }
    }

    None
}

fn parse_exr_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    if bytes.len() < 8 || &bytes[..4] != [0x76, 0x2f, 0x31, 0x01] {
        return None;
    }

    let mut offset = 8usize;
    let mut data_window = None;

    while offset < bytes.len() {
        let name_end = bytes[offset..].iter().position(|byte| *byte == 0)?;
        if name_end == 0 {
            break;
        }
        let name = std::str::from_utf8(&bytes[offset..offset + name_end]).ok()?;
        offset += name_end + 1;

        let type_end = bytes[offset..].iter().position(|byte| *byte == 0)?;
        let attr_type = std::str::from_utf8(&bytes[offset..offset + type_end]).ok()?;
        offset += type_end + 1;

        if offset + 4 > bytes.len() {
            return None;
        }
        let size = u32::from_le_bytes(bytes[offset..offset + 4].try_into().ok()?);
        offset += 4;
        let value_end = offset.checked_add(size as usize)?;
        if value_end > bytes.len() {
            return None;
        }

        if name == "dataWindow" && attr_type == "box2i" && size == 16 {
            let min_x = i32::from_le_bytes(bytes[offset..offset + 4].try_into().ok()?);
            let min_y = i32::from_le_bytes(bytes[offset + 4..offset + 8].try_into().ok()?);
            let max_x = i32::from_le_bytes(bytes[offset + 8..offset + 12].try_into().ok()?);
            let max_y = i32::from_le_bytes(bytes[offset + 12..offset + 16].try_into().ok()?);
            let width = u32::try_from(max_x - min_x + 1).ok()?;
            let height = u32::try_from(max_y - min_y + 1).ok()?;
            data_window = Some((width, height));
        }

        offset = value_end;
    }

    data_window
}

fn help_text() -> String {
    [
        "ibl-baker",
        "",
        "Commands",
        "  ibl-baker bake input-path --out-dir ./out",
        "  ibl-baker bake input-path --out-dir ./out --target specular",
        "  ibl-baker bake input-dir --out-dir ./out --faces px.png,nx.png,py.png,ny.png,pz.png,nz.png",
        "  ibl-baker validate ./out/specular.ibla",
        "",
        "bake options",
        "  --out-dir",
        "  --target <specular|irradiance|lut>",
        "  --size <auto|n>",
        "  --irradiance-size <n>",
        "  --encoding <auto|rgbd-srgb|srgb|linear>",
        "  --faces <px,nx,py,ny,pz,nz>",
        "  --rotation <deg>",
        "  --samples <n>",
        "  --quality <low|medium|high>",
        "",
        "bake defaults",
        "  --size auto -> 128 | 256 | 512 | 1024 | 2048 | 4096",
        "  file input derives an equivalent cubemap face size from input dimensions before bucketing",
        "  directory input uses the cubemap face size before bucketing",
        "  --irradiance-size -> 32",
        "  directory auto-detect names -> px/nx/py/ny/pz/nz or posx/negx/posy/negy/posz/negz",
        "  --faces order -> px, nx, py, ny, pz, nz",
        "  --encoding auto -> rgbd-srgb for .hdr/.exr, srgb for .png/.jpg/.jpeg/unknown",
        "  output files -> specular.ibla, irradiance.ibla, brdf-lut.png",
        "",
        "validate output",
        "  version, face count, chunk count, width, height, mip count, encoding, validation status",
    ]
    .join("\n")
}

const DEFAULT_SPECULAR_SIZE: u32 = 512;

#[derive(Debug, Clone, PartialEq, Eq)]
enum BakeInput {
    File { path: PathBuf },
    Cubemap {
        root: PathBuf,
        faces: CubemapInputPaths,
        source_format: SourceFormat,
        face_size: u32,
    },
}

impl BakeInput {
    fn path(&self) -> &Path {
        match self {
            Self::File { path } => path,
            Self::Cubemap { root, .. } => root,
        }
    }

    fn source_format(&self) -> SourceFormat {
        match self {
            Self::File { path } => SourceFormat::from_input_path(path),
            Self::Cubemap { source_format, .. } => *source_format,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RequestedSize {
    Auto,
    Exact(u32),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RequestedEncoding {
    Auto,
    Explicit(EncodingKind),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum BakeTarget {
    Specular,
    Irradiance,
    Lut,
}

#[derive(Debug, Clone, Copy, Default)]
struct TargetSelection {
    specular: bool,
    irradiance: bool,
    lut: bool,
}

impl TargetSelection {
    fn include(&mut self, target: BakeTarget) {
        match target {
            BakeTarget::Specular => self.specular = true,
            BakeTarget::Irradiance => self.irradiance = true,
            BakeTarget::Lut => self.lut = true,
        }
    }

    fn resolved_targets(&self) -> Vec<BakeTarget> {
        let selection = if self.specular || self.irradiance || self.lut {
            *self
        } else {
            Self {
                specular: true,
                irradiance: true,
                lut: true,
            }
        };

        let mut targets = Vec::new();
        if selection.specular {
            targets.push(BakeTarget::Specular);
        }
        if selection.irradiance {
            targets.push(BakeTarget::Irradiance);
        }
        if selection.lut {
            targets.push(BakeTarget::Lut);
        }
        targets
    }
}

#[derive(Debug)]
enum CliError {
    Usage(String),
    Core(IblError),
}

impl Display for CliError {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::Usage(message) => write!(f, "{message}"),
            Self::Core(error) => write!(f, "{error}"),
        }
    }
}

impl std::error::Error for CliError {}

impl From<IblError> for CliError {
    fn from(value: IblError) -> Self {
        Self::Core(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ibl_core::read_asset;
    use image::codecs::hdr::HdrEncoder;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn unique_temp_path(label: &str) -> PathBuf {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time before UNIX_EPOCH")
            .as_nanos();
        std::env::temp_dir().join(format!(
            "ibl-baker-cli-{label}-{timestamp}-{}",
            std::process::id()
        ))
    }

    fn write_test_png(path: &Path, width: u32, height: u32) {
        let image = image::RgbImage::from_fn(width, height, |x, y| {
            let r = ((x as f32 / width.max(1) as f32) * 255.0).round() as u8;
            let g = ((y as f32 / height.max(1) as f32) * 255.0).round() as u8;
            image::Rgb([r, g, 128])
        });
        image.save(path).expect("png fixture should be written");
    }

    fn write_test_hdr(path: &Path, width: u32, height: u32) {
        let file = fs::File::create(path).expect("hdr fixture should be created");
        let encoder = HdrEncoder::new(file);
        let mut pixels = Vec::new();
        for y in 0..height {
            for x in 0..width {
                let fx = if width > 1 {
                    x as f32 / (width - 1) as f32
                } else {
                    0.0
                };
                let fy = if height > 1 {
                    y as f32 / (height - 1) as f32
                } else {
                    0.0
                };
                pixels.push(image::Rgb([0.5 + fx, 0.25 + fy, 0.1 + 0.25 * fx]));
            }
        }
        encoder
            .encode(&pixels, width as usize, height as usize)
            .expect("hdr fixture should encode");
    }

    fn write_solid_png(path: &Path, size: u32, color: [u8; 3]) {
        let image = image::RgbImage::from_pixel(size, size, image::Rgb(color));
        image.save(path).expect("solid png fixture should be written");
    }

    fn write_cubemap_dir(root: &Path, names: [&str; 6], size: u32) {
        fs::create_dir_all(root).expect("cubemap dir should be created");
        let colors = [
            [255, 0, 0],
            [0, 255, 0],
            [0, 0, 255],
            [255, 255, 0],
            [255, 0, 255],
            [0, 255, 255],
        ];

        for (name, color) in names.into_iter().zip(colors) {
            write_solid_png(&root.join(name), size, color);
        }
    }

    #[test]
    fn bake_without_targets_emits_all_default_outputs() {
        let input = unique_temp_path("input");
        let output_dir = unique_temp_path("out-dir");

        write_test_hdr(&input, 8, 4);

        let bake_output = run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input.to_string_lossy().to_string(),
            "--out-dir".to_string(),
            output_dir.to_string_lossy().to_string(),
        ])
        .expect("bake should succeed");
        assert!(bake_output.contains("Baked 3 output(s)"));
        assert!(output_dir.join("specular.ibla").is_file());
        assert!(output_dir.join("irradiance.ibla").is_file());
        assert!(output_dir.join("brdf-lut.png").is_file());

        fs::remove_file(&input).ok();
        fs::remove_dir_all(&output_dir).ok();
    }

    #[test]
    fn bake_with_specular_target_only_emits_specular_asset() {
        let input = unique_temp_path("specular-input");
        let output_dir = unique_temp_path("specular-out");

        write_test_hdr(&input, 8, 4);

        run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input.to_string_lossy().to_string(),
            "--out-dir".to_string(),
            output_dir.to_string_lossy().to_string(),
            "--target".to_string(),
            "specular".to_string(),
        ])
        .expect("bake should succeed");

        assert!(output_dir.join("specular.ibla").is_file());
        assert!(!output_dir.join("irradiance.ibla").exists());
        assert!(!output_dir.join("brdf-lut.png").exists());

        fs::remove_file(&input).ok();
        fs::remove_dir_all(&output_dir).ok();
    }

    #[test]
    fn bake_with_irradiance_and_lut_targets_emits_requested_outputs() {
        let input = unique_temp_path("irradiance-lut-input");
        let output_dir = unique_temp_path("irradiance-lut-out");

        write_test_hdr(&input, 8, 4);

        run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input.to_string_lossy().to_string(),
            "--out-dir".to_string(),
            output_dir.to_string_lossy().to_string(),
            "--target".to_string(),
            "irradiance".to_string(),
            "--target".to_string(),
            "lut".to_string(),
        ])
        .expect("bake should succeed");

        assert!(!output_dir.join("specular.ibla").exists());
        assert!(output_dir.join("irradiance.ibla").is_file());
        assert!(output_dir.join("brdf-lut.png").is_file());

        fs::remove_file(&input).ok();
        fs::remove_dir_all(&output_dir).ok();
    }

    #[test]
    fn validate_reports_summary_for_specular_assets() {
        let input = unique_temp_path("validate-specular-input");
        let output_dir = unique_temp_path("validate-specular-out");
        let asset_path = output_dir.join("specular.ibla");

        write_test_hdr(&input, 8, 4);

        run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input.to_string_lossy().to_string(),
            "--out-dir".to_string(),
            output_dir.to_string_lossy().to_string(),
            "--target".to_string(),
            "specular".to_string(),
        ])
        .expect("bake should succeed");

        let validate_output = run(vec![
            "ibl-baker".to_string(),
            "validate".to_string(),
            asset_path.to_string_lossy().to_string(),
        ])
        .expect("validate should succeed");

        assert!(validate_output.contains("Face Count: 6"));
        assert!(validate_output.contains("Validation: passed"));

        fs::remove_file(&input).ok();
        fs::remove_dir_all(&output_dir).ok();
    }

    #[test]
    fn bake_defaults_to_auto_encoding_and_resolves_hdr_inputs_to_rgbd_srgb() {
        let input = unique_temp_path("auto-encoding-hdr").with_extension("hdr");
        let output_dir = unique_temp_path("auto-encoding-hdr-out");
        let asset_path = output_dir.join("specular.ibla");

        write_test_hdr(&input, 8, 4);

        run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input.to_string_lossy().to_string(),
            "--out-dir".to_string(),
            output_dir.to_string_lossy().to_string(),
            "--target".to_string(),
            "specular".to_string(),
        ])
        .expect("bake should succeed");

        let asset = read_asset(&asset_path).expect("asset should read");
        assert_eq!(asset.manifest.encoding, "rgbd-srgb");

        fs::remove_file(&input).ok();
        fs::remove_dir_all(&output_dir).ok();
    }

    #[test]
    fn bake_defaults_to_auto_encoding_and_resolves_png_inputs_to_srgb() {
        let input = unique_temp_path("auto-encoding-png").with_extension("png");
        let output_dir = unique_temp_path("auto-encoding-png-out");
        let asset_path = output_dir.join("specular.ibla");

        write_test_png(&input, 1500, 900);

        run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input.to_string_lossy().to_string(),
            "--out-dir".to_string(),
            output_dir.to_string_lossy().to_string(),
            "--target".to_string(),
            "specular".to_string(),
        ])
        .expect("bake should succeed");

        let asset = read_asset(&asset_path).expect("asset should read");
        assert_eq!(asset.manifest.encoding, "srgb");
        assert_eq!(asset.manifest.width, 256);

        fs::remove_file(&input).ok();
        fs::remove_dir_all(&output_dir).ok();
    }

    #[test]
    fn bake_accepts_explicit_linear_encoding() {
        let input = unique_temp_path("explicit-linear").with_extension("png");
        let output_dir = unique_temp_path("explicit-linear-out");
        let asset_path = output_dir.join("specular.ibla");

        write_test_png(&input, 512, 512);

        run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input.to_string_lossy().to_string(),
            "--out-dir".to_string(),
            output_dir.to_string_lossy().to_string(),
            "--target".to_string(),
            "specular".to_string(),
            "--encoding".to_string(),
            "linear".to_string(),
        ])
        .expect("bake should succeed");

        let asset = read_asset(&asset_path).expect("asset should read");
        assert_eq!(asset.manifest.encoding, "linear");

        fs::remove_file(&input).ok();
        fs::remove_dir_all(&output_dir).ok();
    }

    #[test]
    fn bake_accepts_auto_detected_px_cubemap_directory() {
        let input_dir = unique_temp_path("cubemap-px");
        let output_dir = unique_temp_path("cubemap-px-out");
        let asset_path = output_dir.join("specular.ibla");

        write_cubemap_dir(
            &input_dir,
            ["px.png", "nx.png", "py.png", "ny.png", "pz.png", "nz.png"],
            16,
        );

        run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input_dir.to_string_lossy().to_string(),
            "--out-dir".to_string(),
            output_dir.to_string_lossy().to_string(),
            "--target".to_string(),
            "specular".to_string(),
            "--size".to_string(),
            "16".to_string(),
        ])
        .expect("cubemap directory bake should succeed");

        let asset = read_asset(&asset_path).expect("asset should read");
        assert_eq!(asset.manifest.build.source_format, "png");

        fs::remove_dir_all(&input_dir).ok();
        fs::remove_dir_all(&output_dir).ok();
    }

    #[test]
    fn bake_accepts_auto_detected_posx_cubemap_directory() {
        let input_dir = unique_temp_path("cubemap-posx");
        let output_dir = unique_temp_path("cubemap-posx-out");

        write_cubemap_dir(
            &input_dir,
            [
                "posx.png",
                "negx.png",
                "posy.png",
                "negy.png",
                "posz.png",
                "negz.png",
            ],
            8,
        );

        run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input_dir.to_string_lossy().to_string(),
            "--out-dir".to_string(),
            output_dir.to_string_lossy().to_string(),
            "--target".to_string(),
            "irradiance".to_string(),
            "--irradiance-size".to_string(),
            "8".to_string(),
        ])
        .expect("posx cubemap directory bake should succeed");

        assert!(output_dir.join("irradiance.ibla").is_file());

        fs::remove_dir_all(&input_dir).ok();
        fs::remove_dir_all(&output_dir).ok();
    }

    #[test]
    fn bake_accepts_faces_override_for_directory_input() {
        let input_dir = unique_temp_path("cubemap-faces");
        let output_dir = unique_temp_path("cubemap-faces-out");
        let asset_path = output_dir.join("specular.ibla");

        write_cubemap_dir(
            &input_dir,
            ["a.png", "b.png", "c.png", "d.png", "e.png", "f.png"],
            8,
        );

        run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input_dir.to_string_lossy().to_string(),
            "--out-dir".to_string(),
            output_dir.to_string_lossy().to_string(),
            "--target".to_string(),
            "specular".to_string(),
            "--size".to_string(),
            "8".to_string(),
            "--faces".to_string(),
            "a.png,b.png,c.png,d.png,e.png,f.png".to_string(),
        ])
        .expect("directory bake with --faces should succeed");

        assert!(asset_path.is_file());

        fs::remove_dir_all(&input_dir).ok();
        fs::remove_dir_all(&output_dir).ok();
    }

    #[test]
    fn bake_rejects_cubemap_directory_with_missing_faces() {
        let input_dir = unique_temp_path("cubemap-missing");
        fs::create_dir_all(&input_dir).expect("cubemap dir should be created");
        for name in ["px.png", "nx.png", "py.png", "ny.png", "pz.png"] {
            write_solid_png(&input_dir.join(name), 8, [255, 0, 0]);
        }

        let error = run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input_dir.to_string_lossy().to_string(),
            "--out-dir".to_string(),
            unique_temp_path("cubemap-missing-out")
                .to_string_lossy()
                .to_string(),
        ])
        .expect_err("missing cubemap faces should fail");

        assert!(error.to_string().contains("could not auto-detect cubemap faces"));

        fs::remove_dir_all(&input_dir).ok();
    }

    #[test]
    fn bake_rejects_mixed_format_cubemap_faces() {
        let input_dir = unique_temp_path("cubemap-mixed");
        fs::create_dir_all(&input_dir).expect("cubemap dir should be created");
        let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        fs::copy(
            repo_root.join("fixtures/inputs/pisa/px.png"),
            input_dir.join("px.png"),
        )
        .expect("px fixture should copy");
        fs::copy(
            repo_root.join("fixtures/inputs/Bridge2/negx.jpg"),
            input_dir.join("nx.jpg"),
        )
        .expect("nx fixture should copy");
        fs::copy(
            repo_root.join("fixtures/inputs/Bridge2/posy.jpg"),
            input_dir.join("py.jpg"),
        )
        .expect("py fixture should copy");
        fs::copy(
            repo_root.join("fixtures/inputs/Bridge2/negy.jpg"),
            input_dir.join("ny.jpg"),
        )
        .expect("ny fixture should copy");
        fs::copy(
            repo_root.join("fixtures/inputs/Bridge2/posz.jpg"),
            input_dir.join("pz.jpg"),
        )
        .expect("pz fixture should copy");
        fs::copy(
            repo_root.join("fixtures/inputs/Bridge2/negz.jpg"),
            input_dir.join("nz.jpg"),
        )
        .expect("nz fixture should copy");

        let error = run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input_dir.to_string_lossy().to_string(),
            "--out-dir".to_string(),
            unique_temp_path("cubemap-mixed-out")
                .to_string_lossy()
                .to_string(),
        ])
        .expect_err("mixed-format cubemap should fail");

        assert!(error
            .to_string()
            .contains("cubemap faces must use the same source format family"));

        fs::remove_dir_all(&input_dir).ok();
    }

    #[test]
    fn bake_faces_override_order_changes_output() {
        let input_dir = unique_temp_path("cubemap-order");
        let output_dir_a = unique_temp_path("cubemap-order-a");
        let output_dir_b = unique_temp_path("cubemap-order-b");

        write_cubemap_dir(
            &input_dir,
            ["a.png", "b.png", "c.png", "d.png", "e.png", "f.png"],
            8,
        );

        for (output_dir, faces) in [
            (&output_dir_a, "a.png,b.png,c.png,d.png,e.png,f.png"),
            (&output_dir_b, "b.png,a.png,c.png,d.png,e.png,f.png"),
        ] {
            run(vec![
                "ibl-baker".to_string(),
                "bake".to_string(),
                input_dir.to_string_lossy().to_string(),
                "--out-dir".to_string(),
                output_dir.to_string_lossy().to_string(),
                "--target".to_string(),
                "specular".to_string(),
                "--size".to_string(),
                "8".to_string(),
                "--faces".to_string(),
                faces.to_string(),
            ])
            .expect("directory bake with --faces should succeed");
        }

        let first = fs::read(output_dir_a.join("specular.ibla")).expect("first asset should exist");
        let second =
            fs::read(output_dir_b.join("specular.ibla")).expect("second asset should exist");
        assert_ne!(first, second);

        fs::remove_dir_all(&input_dir).ok();
        fs::remove_dir_all(&output_dir_a).ok();
        fs::remove_dir_all(&output_dir_b).ok();
    }

    #[test]
    fn validate_reports_summary_for_irradiance_assets() {
        let input = unique_temp_path("validate-irradiance-input");
        let output_dir = unique_temp_path("validate-irradiance-out");
        let asset_path = output_dir.join("irradiance.ibla");

        write_test_hdr(&input, 8, 4);

        run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input.to_string_lossy().to_string(),
            "--out-dir".to_string(),
            output_dir.to_string_lossy().to_string(),
            "--target".to_string(),
            "irradiance".to_string(),
        ])
        .expect("bake should succeed");

        let validate_output = run(vec![
            "ibl-baker".to_string(),
            "validate".to_string(),
            asset_path.to_string_lossy().to_string(),
        ])
        .expect("validate should succeed");

        assert!(validate_output.contains("Face Count: 6"));
        assert!(validate_output.contains("Validation: passed"));

        fs::remove_file(&input).ok();
        fs::remove_dir_all(&output_dir).ok();
    }

    #[test]
    fn removed_commands_return_usage_errors() {
        let inspect_error = run(vec!["ibl-baker".to_string(), "inspect".to_string()])
            .expect_err("inspect should be removed");
        assert!(inspect_error.to_string().contains("unknown command"));

        let extract_error = run(vec!["ibl-baker".to_string(), "extract".to_string()])
            .expect_err("extract should be removed");
        assert!(extract_error.to_string().contains("unknown command"));
    }

    #[test]
    fn help_text_reflects_public_command_surface() {
        let help = help_text();
        assert!(help.contains("ibl-baker bake input-path --out-dir ./out"));
        assert!(help.contains("ibl-baker validate ./out/specular.ibla"));
        assert!(help.contains("--target <specular|irradiance|lut>"));
        assert!(help.contains("--size <auto|n>"));
        assert!(help.contains("--encoding <auto|rgbd-srgb|srgb|linear>"));
        assert!(help.contains("--faces <px,nx,py,ny,pz,nz>"));
        assert!(help.contains("directory auto-detect names"));
        assert!(help.contains("output files -> specular.ibla, irradiance.ibla, brdf-lut.png"));
        assert!(help.contains("validation status"));
        assert!(!help.contains("inspect"));
        assert!(!help.contains("extract"));
    }

    #[test]
    fn bake_requires_out_dir_usage_error() {
        let input = unique_temp_path("missing-out-dir").with_extension("hdr");
        write_test_hdr(&input, 4, 2);

        let error = run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input.to_string_lossy().to_string(),
        ])
        .expect_err("bake without out-dir should fail");

        assert_eq!(error.to_string(), "bake requires --out-dir <path>");

        fs::remove_file(&input).ok();
    }

    #[test]
    fn validate_requires_exactly_one_asset_path() {
        let error = run(vec!["ibl-baker".to_string(), "validate".to_string()])
            .expect_err("validate without path should fail");

        assert_eq!(
            error.to_string(),
            "validate requires exactly one asset path"
        );
    }

    #[test]
    fn bake_rejects_unknown_options_with_usage_error() {
        let input = unique_temp_path("unknown-option").with_extension("hdr");
        write_test_hdr(&input, 4, 2);

        let error = run(vec![
            "ibl-baker".to_string(),
            "bake".to_string(),
            input.to_string_lossy().to_string(),
            "--out-dir".to_string(),
            unique_temp_path("unknown-option-out")
                .to_string_lossy()
                .to_string(),
            "--bogus".to_string(),
            "value".to_string(),
        ])
        .expect_err("unknown option should fail");

        assert_eq!(error.to_string(), "unknown bake option: --bogus");

        fs::remove_file(&input).ok();
    }

    #[test]
    fn auto_size_uses_equirect_equivalent_face_size_before_bucketing() {
        assert_eq!(choose_auto_specular_size(128, 64), 128);
        assert_eq!(choose_auto_specular_size(1024, 512), 256);
        assert_eq!(choose_auto_specular_size(1500, 750), 256);
        assert_eq!(choose_auto_specular_size(2048, 1024), 512);
        assert_eq!(choose_auto_specular_size(4096, 2048), 1024);
        assert_eq!(choose_auto_specular_size(8192, 4096), 2048);
        assert_eq!(choose_auto_specular_size(2048, 1536), 512);
    }
}

use std::env;
use std::fmt::{self, Display, Formatter};
use std::fs;
use std::io::{Cursor, Read};
use std::path::{Path, PathBuf};
use std::process;

use ibl_core::{
    bake_to_asset, inspect_asset, read_asset, validate_asset, write_asset, AssetKind, BakeOptions,
    BakeQuality, EncodingKind, IblError, SourceFormat,
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
            _ => return Err(CliError::Usage(format!("unknown bake option: {flag}"))),
        }

        index += 2;
    }

    let output_dir =
        output_dir.ok_or_else(|| CliError::Usage("bake requires --out-dir <path>".to_string()))?;
    fs::create_dir_all(&output_dir).map_err(IblError::from)?;

    options.cube_size = resolve_requested_size(&input, requested_size)?;
    options.output_encoding = resolve_requested_encoding(&input, requested_encoding);

    let mut outputs = Vec::new();
    for target in target_selection.resolved_targets() {
        match target {
            BakeTarget::Specular => {
                let mut target_options = options.clone();
                target_options.asset_kind = AssetKind::SpecularCubemap;
                let asset = bake_to_asset(&input, target_options)?;
                let output = output_dir.join("specular.ibla");
                write_asset(&output, &asset)?;
                outputs.push(output);
            }
            BakeTarget::Irradiance => {
                let mut target_options = options.clone();
                target_options.asset_kind = AssetKind::IrradianceCubemap;
                let asset = bake_to_asset(&input, target_options)?;
                let output = output_dir.join("irradiance.ibla");
                write_asset(&output, &asset)?;
                outputs.push(output);
            }
            BakeTarget::Lut => {
                let mut target_options = options.clone();
                target_options.asset_kind = AssetKind::BrdfLut;
                let asset = bake_to_asset(&input, target_options)?;
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
        display_path(&input),
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

fn resolve_requested_size(input: &Path, requested: RequestedSize) -> Result<u32, CliError> {
    match requested {
        RequestedSize::Exact(size) => Ok(size),
        RequestedSize::Auto => Ok(resolve_auto_size(input).unwrap_or(DEFAULT_SPECULAR_SIZE)),
    }
}

fn resolve_auto_size(input: &Path) -> Option<u32> {
    let (width, height) = read_image_dimensions(input).ok()??;
    Some(choose_auto_specular_size(width.max(height)))
}

fn resolve_requested_encoding(input: &Path, requested: RequestedEncoding) -> EncodingKind {
    match requested {
        RequestedEncoding::Explicit(encoding) => encoding,
        RequestedEncoding::Auto => match SourceFormat::from_input_path(input) {
            SourceFormat::Hdr | SourceFormat::Exr => EncodingKind::RgbdSrgb,
            SourceFormat::Png | SourceFormat::Jpg | SourceFormat::Jpeg | SourceFormat::Unknown => {
                EncodingKind::Srgb
            }
        },
    }
}

fn choose_auto_specular_size(long_edge: u32) -> u32 {
    const AUTO_SIZE_BUCKETS: [u32; 5] = [256, 512, 1024, 2048, 4096];

    AUTO_SIZE_BUCKETS
        .iter()
        .rev()
        .copied()
        .find(|size| *size <= long_edge)
        .unwrap_or(AUTO_SIZE_BUCKETS[0])
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
            0xC0 | 0xC1 | 0xC2 | 0xC3 | 0xC5 | 0xC6 | 0xC7 | 0xC9 | 0xCA | 0xCB | 0xCD | 0xCE | 0xCF
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
        "Commands:",
        "  ibl-baker bake <input-image> --out-dir <dir> [--target <specular|irradiance|lut>] [--size <auto|n>] [--irradiance-size <n>] [--encoding <auto|rgbd-srgb|srgb|linear>] [--rotation <deg>] [--samples <n>] [--quality <level>]",
        "  ibl-baker validate <asset.ibla>",
    ]
    .join("\n")
}

const DEFAULT_SPECULAR_SIZE: u32 = 512;

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

    fn write_png_header(path: &Path, width: u32, height: u32) {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"\x89PNG\r\n\x1a\n");
        bytes.extend_from_slice(&13u32.to_be_bytes());
        bytes.extend_from_slice(b"IHDR");
        bytes.extend_from_slice(&width.to_be_bytes());
        bytes.extend_from_slice(&height.to_be_bytes());
        bytes.extend_from_slice(&[8, 6, 0, 0, 0]);
        fs::write(path, bytes).expect("png header should be written");
    }

    #[test]
    fn bake_without_targets_emits_all_default_outputs() {
        let input = unique_temp_path("input");
        let output_dir = unique_temp_path("out-dir");

        fs::write(&input, b"placeholder hdr").expect("input should be created");

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

        fs::write(&input, b"placeholder hdr").expect("input should be created");

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

        fs::write(&input, b"placeholder hdr").expect("input should be created");

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

        fs::write(&input, b"placeholder hdr").expect("input should be created");

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

        fs::write(&input, b"placeholder hdr").expect("input should be created");

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

        write_png_header(&input, 1500, 900);

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
        assert_eq!(asset.manifest.width, 1024);

        fs::remove_file(&input).ok();
        fs::remove_dir_all(&output_dir).ok();
    }

    #[test]
    fn bake_accepts_explicit_linear_encoding() {
        let input = unique_temp_path("explicit-linear").with_extension("png");
        let output_dir = unique_temp_path("explicit-linear-out");
        let asset_path = output_dir.join("specular.ibla");

        write_png_header(&input, 512, 512);

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
    fn validate_reports_summary_for_irradiance_assets() {
        let input = unique_temp_path("validate-irradiance-input");
        let output_dir = unique_temp_path("validate-irradiance-out");
        let asset_path = output_dir.join("irradiance.ibla");

        fs::write(&input, b"placeholder hdr").expect("input should be created");

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
        assert!(help.contains("bake <input-image> --out-dir <dir>"));
        assert!(help.contains("--size <auto|n>"));
        assert!(help.contains("--encoding <auto|rgbd-srgb|srgb|linear>"));
        assert!(help.contains("validate <asset.ibla>"));
        assert!(!help.contains("inspect"));
        assert!(!help.contains("extract"));
    }

    #[test]
    fn auto_size_chooses_nearest_supported_bucket_not_exceeding_source_size() {
        assert_eq!(choose_auto_specular_size(128), 256);
        assert_eq!(choose_auto_specular_size(256), 256);
        assert_eq!(choose_auto_specular_size(300), 256);
        assert_eq!(choose_auto_specular_size(1024), 1024);
        assert_eq!(choose_auto_specular_size(1500), 1024);
        assert_eq!(choose_auto_specular_size(4096), 4096);
        assert_eq!(choose_auto_specular_size(8192), 4096);
    }
}

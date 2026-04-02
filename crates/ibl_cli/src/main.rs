use std::env;
use std::fmt::{self, Display, Formatter};
use std::fs;
use std::path::{Path, PathBuf};
use std::process;

use ibl_core::{
    bake_to_asset, inspect_asset, read_asset, validate_asset, write_asset, AssetKind, BakeOptions,
    BakeQuality, EncodingKind, IblError,
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
            "bake requires an input HDR path".to_string(),
        ));
    }

    let input = PathBuf::from(&args[0]);
    let mut options = BakeOptions::default();
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
            "--size" => options.cube_size = parse_u32(value, "--size")?,
            "--irradiance-size" => options.irradiance_size = parse_u32(value, "--irradiance-size")?,
            "--encoding" => options.output_encoding = parse_encoding(value)?,
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

fn parse_encoding(value: &str) -> Result<EncodingKind, CliError> {
    match value {
        "rgbd" => Ok(EncodingKind::Rgbd),
        other => Err(CliError::Usage(format!(
            "unsupported encoding: {other}; only rgbd is available in phase one"
        ))),
    }
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

fn help_text() -> String {
    [
        "ibl-baker",
        "",
        "Commands:",
        "  ibl-baker bake <input.hdr> --out-dir <dir> [--target <specular|irradiance|lut>] [--size <n>] [--irradiance-size <n>] [--encoding rgbd] [--rotation <deg>] [--samples <n>] [--quality <level>]",
        "  ibl-baker validate <asset.ibla>",
    ]
    .join("\n")
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
        assert!(help.contains("bake <input.hdr> --out-dir <dir>"));
        assert!(help.contains("validate <asset.ibla>"));
        assert!(!help.contains("inspect"));
        assert!(!help.contains("extract"));
    }
}

use std::collections::{BTreeMap, BTreeSet};
use std::fmt::{self, Display, Formatter};
use std::fs;
use std::path::{Path, PathBuf};
use std::str::FromStr;
#[cfg(test)]
use std::time::{SystemTime, UNIX_EPOCH};

mod bake_pipeline;
mod source_image;

#[cfg(test)]
use bake_pipeline::cubemap_direction;
use bake_pipeline::{
    build_brdf_lut_chunk_entries, build_irradiance_chunk_entries, build_irradiance_raw,
    build_specular_chunk_entries, build_specular_raw, encode_mip_chain_to_ktx2,
};
#[cfg(test)]
use source_image::{
    encode_png_image, encode_rgbd_srgb, load_source_image, write_test_exr, write_test_hdr,
    write_test_png,
};
use source_image::{load_environment_from_cubemap_paths, load_environment_from_file};

pub const FORMAT_MAGIC: [u8; 4] = *b"IBLA";
pub const FORMAT_VERSION: u16 = 1;
pub const HEADER_BYTE_LENGTH: usize = 16;
pub const BRDF_LUT_SIZE: u32 = 256;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Face {
    PositiveX,
    NegativeX,
    PositiveY,
    NegativeY,
    PositiveZ,
    NegativeZ,
}

impl Face {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::PositiveX => "px",
            Self::NegativeX => "nx",
            Self::PositiveY => "py",
            Self::NegativeY => "ny",
            Self::PositiveZ => "pz",
            Self::NegativeZ => "nz",
        }
    }

    pub fn code(&self) -> u8 {
        match self {
            Self::PositiveX => 1,
            Self::NegativeX => 2,
            Self::PositiveY => 3,
            Self::NegativeY => 4,
            Self::PositiveZ => 5,
            Self::NegativeZ => 6,
        }
    }

    pub fn from_code(value: u8) -> Result<Self, IblError> {
        match value {
            1 => Ok(Self::PositiveX),
            2 => Ok(Self::NegativeX),
            3 => Ok(Self::PositiveY),
            4 => Ok(Self::NegativeY),
            5 => Ok(Self::PositiveZ),
            6 => Ok(Self::NegativeZ),
            _ => Err(IblError::InvalidFormat(format!(
                "invalid face code: {value}"
            ))),
        }
    }

    pub fn all() -> &'static [Face; 6] {
        static FACES: [Face; 6] = [
            Face::PositiveX,
            Face::NegativeX,
            Face::PositiveY,
            Face::NegativeY,
            Face::PositiveZ,
            Face::NegativeZ,
        ];
        &FACES
    }

    pub(crate) fn index(self) -> usize {
        match self {
            Self::PositiveX => 0,
            Self::NegativeX => 1,
            Self::PositiveY => 2,
            Self::NegativeY => 3,
            Self::PositiveZ => 4,
            Self::NegativeZ => 5,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AssetKind {
    SpecularCubemap,
    IrradianceCubemap,
    BrdfLut,
}

impl AssetKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::SpecularCubemap => "specular-cubemap",
            Self::IrradianceCubemap => "irradiance-cubemap",
            Self::BrdfLut => "brdf-lut",
        }
    }

    pub fn cli_name(&self) -> &'static str {
        match self {
            Self::SpecularCubemap => "specular",
            Self::IrradianceCubemap => "irradiance",
            Self::BrdfLut => "brdf-lut",
        }
    }

    pub fn is_cubemap(&self) -> bool {
        matches!(self, Self::SpecularCubemap | Self::IrradianceCubemap)
    }
}

impl FromStr for AssetKind {
    type Err = IblError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "specular-cubemap" | "specular" => Ok(Self::SpecularCubemap),
            "irradiance-cubemap" | "irradiance" => Ok(Self::IrradianceCubemap),
            "brdf-lut" => Ok(Self::BrdfLut),
            _ => Err(IblError::InvalidFormat(format!(
                "invalid asset type: {value}"
            ))),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EncodingKind {
    RgbdSrgb,
    Srgb,
    Linear,
}

impl EncodingKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::RgbdSrgb => "rgbd-srgb",
            Self::Srgb => "srgb",
            Self::Linear => "linear",
        }
    }
}

impl FromStr for EncodingKind {
    type Err = IblError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "rgbd-srgb" => Ok(Self::RgbdSrgb),
            "srgb" => Ok(Self::Srgb),
            "linear" => Ok(Self::Linear),
            _ => Err(IblError::InvalidFormat(format!(
                "invalid encoding: {value}"
            ))),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SourceFormat {
    Hdr,
    Exr,
    Png,
    Jpg,
    Jpeg,
    Unknown,
}

impl SourceFormat {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Hdr => "hdr",
            Self::Exr => "exr",
            Self::Png => "png",
            Self::Jpg => "jpg",
            Self::Jpeg => "jpeg",
            Self::Unknown => "unknown",
        }
    }

    pub fn from_input_path(path: &Path) -> Self {
        match path
            .extension()
            .and_then(|extension| extension.to_str())
            .map(|extension| extension.to_ascii_lowercase())
            .as_deref()
        {
            Some("hdr") => Self::Hdr,
            Some("exr") => Self::Exr,
            Some("png") => Self::Png,
            Some("jpg") => Self::Jpg,
            Some("jpeg") => Self::Jpeg,
            _ => Self::Unknown,
        }
    }
}

impl FromStr for SourceFormat {
    type Err = IblError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "hdr" => Ok(Self::Hdr),
            "exr" => Ok(Self::Exr),
            "png" => Ok(Self::Png),
            "jpg" => Ok(Self::Jpg),
            "jpeg" => Ok(Self::Jpeg),
            "unknown" => Ok(Self::Unknown),
            _ => Err(IblError::InvalidFormat(format!(
                "invalid source format: {value}"
            ))),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BakeQuality {
    Low,
    Medium,
    High,
}

impl BakeQuality {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Low => "low",
            Self::Medium => "medium",
            Self::High => "high",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct BakeOptions {
    pub asset_kind: AssetKind,
    pub cube_size: u32,
    pub irradiance_size: u32,
    pub output_encoding: EncodingKind,
    pub rotation_degrees: f32,
    pub sample_count: u32,
    pub quality: BakeQuality,
}

impl Default for BakeOptions {
    fn default() -> Self {
        Self {
            asset_kind: AssetKind::SpecularCubemap,
            cube_size: 512,
            irradiance_size: 32,
            output_encoding: EncodingKind::RgbdSrgb,
            rotation_degrees: 0.0,
            sample_count: 1024,
            quality: BakeQuality::Medium,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CubemapInputPaths {
    pub face_paths: [PathBuf; 6],
}

impl CubemapInputPaths {
    pub fn from_face_order(face_paths: [PathBuf; 6]) -> Self {
        Self { face_paths }
    }

    pub fn as_array(&self) -> &[PathBuf; 6] {
        &self.face_paths
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IblHeader {
    pub magic: [u8; 4],
    pub version: u16,
    pub flags: u16,
    pub manifest_byte_length: u32,
    pub chunk_table_byte_length: u32,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BuildInfo {
    pub rotation_degrees: f32,
    pub sample_count: u32,
    pub quality: String,
    pub source_format: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Manifest {
    pub generator: String,
    pub generator_version: String,
    pub encoding: String,
    pub container: String,
    pub width: u32,
    pub height: u32,
    pub mip_count: u32,
    pub face_count: u32,
    pub build: BuildInfo,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChunkRecord {
    pub mip_level: u32,
    pub face: Option<Face>,
    pub byte_offset: u64,
    pub byte_length: u64,
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChunkData {
    pub mip_level: u32,
    pub face: Option<Face>,
    pub bytes: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct IblAsset {
    pub header: IblHeader,
    pub manifest: Manifest,
    pub chunk_table: Vec<ChunkRecord>,
    pub chunks: Vec<ChunkData>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InspectInfo {
    pub version: u16,
    pub chunk_count: usize,
    pub width: u32,
    pub height: u32,
    pub mip_count: u32,
    pub face_count: u32,
    pub encoding: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidationIssue {
    pub severity: ValidationSeverity,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ValidationSeverity {
    Error,
    Warning,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidationReport {
    pub is_valid: bool,
    pub issues: Vec<ValidationIssue>,
}

#[derive(Debug)]
pub enum IblError {
    Io(std::io::Error),
    InvalidInput(String),
    InvalidFormat(String),
    ImageDecode(String),
    UnsupportedExrLayout(String),
    UnsupportedExrChannelModel(String),
    PngEncode(String),
}

impl Display for IblError {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(f, "I/O error: {error}"),
            Self::InvalidInput(message) => write!(f, "Invalid input: {message}"),
            Self::InvalidFormat(message) => write!(f, "Invalid format: {message}"),
            Self::ImageDecode(message) => write!(f, "Image decode error: {message}"),
            Self::UnsupportedExrLayout(message) => {
                write!(f, "Unsupported EXR layout: {message}")
            }
            Self::UnsupportedExrChannelModel(message) => {
                write!(f, "Unsupported EXR channel model: {message}")
            }
            Self::PngEncode(message) => write!(f, "PNG encode error: {message}"),
        }
    }
}

impl std::error::Error for IblError {}

impl From<std::io::Error> for IblError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<image::ImageError> for IblError {
    fn from(value: image::ImageError) -> Self {
        Self::ImageDecode(value.to_string())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct ChunkIdentity {
    mip_level: u32,
    face: Option<Face>,
}

#[derive(Debug, Clone)]
struct ChunkEntry {
    record: ChunkRecord,
    chunk: ChunkData,
}

pub fn bake_to_asset<P: AsRef<Path>>(input: P, options: BakeOptions) -> Result<IblAsset, IblError> {
    let input_path = input.as_ref();
    if !input_path.exists() {
        return Err(IblError::InvalidInput(format!(
            "input file does not exist: {}",
            input_path.display()
        )));
    }

    let (source, source_format) = load_environment_from_file(input_path)?;
    bake_environment_to_asset(source_format, &source, options)
}

pub fn bake_cubemap_to_asset(
    input: &CubemapInputPaths,
    options: BakeOptions,
) -> Result<IblAsset, IblError> {
    let (source, source_format) = load_environment_from_cubemap_paths(input)?;
    bake_environment_to_asset(source_format, &source, options)
}

/// Bake an equirectangular (latlong) or single-file HDR/EXR/LDR source to KTX2 bytes
/// (BC6H + zstd cubemap). Only valid for `SpecularCubemap` and `IrradianceCubemap` asset kinds.
pub fn bake_to_ktx2<P: AsRef<Path>>(input: P, options: BakeOptions) -> Result<Vec<u8>, IblError> {
    let input_path = input.as_ref();
    if !input_path.exists() {
        return Err(IblError::InvalidInput(format!(
            "input file does not exist: {}",
            input_path.display()
        )));
    }
    let (source, _source_format) = load_environment_from_file(input_path)?;
    bake_environment_to_ktx2(&source, options)
}

/// Bake 6-face cubemap inputs to KTX2 bytes (BC6H + zstd). Only valid for `SpecularCubemap`
/// and `IrradianceCubemap` asset kinds.
pub fn bake_cubemap_to_ktx2(
    input: &CubemapInputPaths,
    options: BakeOptions,
) -> Result<Vec<u8>, IblError> {
    let (source, _source_format) = load_environment_from_cubemap_paths(input)?;
    bake_environment_to_ktx2(&source, options)
}

fn bake_environment_to_ktx2(
    source: &source_image::EnvironmentSource,
    options: BakeOptions,
) -> Result<Vec<u8>, IblError> {
    if options.cube_size == 0 || options.irradiance_size == 0 {
        return Err(IblError::InvalidInput(
            "image sizes must be greater than zero".to_string(),
        ));
    }
    match options.asset_kind {
        AssetKind::SpecularCubemap => {
            let mip_count = estimate_mip_count(options.cube_size);
            let mip_chain = build_specular_raw(source, &options, mip_count);
            encode_mip_chain_to_ktx2(&mip_chain)
        }
        AssetKind::IrradianceCubemap => {
            let faces = build_irradiance_raw(source, &options);
            encode_mip_chain_to_ktx2(&[faces])
        }
        AssetKind::BrdfLut => Err(IblError::InvalidInput(
            "BRDF LUT does not support KTX2 output; use bake_to_asset() for PNG".to_string(),
        )),
    }
}

fn bake_environment_to_asset(
    source_format: SourceFormat,
    source: &source_image::EnvironmentSource,
    options: BakeOptions,
) -> Result<IblAsset, IblError> {
    if options.cube_size == 0 || options.irradiance_size == 0 {
        return Err(IblError::InvalidInput(
            "image sizes must be greater than zero".to_string(),
        ));
    }

    let manifest = build_manifest(source_format, &options);
    let mut asset = IblAsset {
        header: IblHeader {
            magic: FORMAT_MAGIC,
            version: FORMAT_VERSION,
            flags: 0,
            manifest_byte_length: 0,
            chunk_table_byte_length: 0,
        },
        manifest,
        chunk_table: Vec::new(),
        chunks: Vec::new(),
    };

    let entries = match options.asset_kind {
        AssetKind::SpecularCubemap => {
            build_specular_chunk_entries(source, &options, asset.manifest.mip_count)?
        }
        AssetKind::IrradianceCubemap => build_irradiance_chunk_entries(source, &options)?,
        AssetKind::BrdfLut => build_brdf_lut_chunk_entries(BRDF_LUT_SIZE, &options)?,
    };
    asset.chunk_table = entries.iter().map(|entry| entry.record.clone()).collect();
    asset.chunks = entries.iter().map(|entry| entry.chunk.clone()).collect();

    normalize_asset(&asset)
}

pub fn write_asset<P: AsRef<Path>>(path: P, asset: &IblAsset) -> Result<(), IblError> {
    let bytes = encode_asset_bytes(asset)?;
    fs::write(path, bytes)?;
    Ok(())
}

pub fn read_asset<P: AsRef<Path>>(path: P) -> Result<IblAsset, IblError> {
    let bytes = fs::read(path)?;
    if bytes.len() < HEADER_BYTE_LENGTH {
        return Err(IblError::InvalidFormat(
            "file is too small to contain a valid header".to_string(),
        ));
    }

    let header = parse_header(&bytes[..HEADER_BYTE_LENGTH])?;
    let manifest_start = HEADER_BYTE_LENGTH;
    let manifest_end = manifest_start + header.manifest_byte_length as usize;
    let chunk_table_end = manifest_end + header.chunk_table_byte_length as usize;

    if bytes.len() < chunk_table_end {
        return Err(IblError::InvalidFormat(
            "header lengths exceed file size".to_string(),
        ));
    }

    let manifest_text = std::str::from_utf8(&bytes[manifest_start..manifest_end])
        .map_err(|_| IblError::InvalidFormat("manifest is not valid UTF-8".to_string()))?;
    let manifest = parse_manifest(manifest_text)?;
    let chunk_table = parse_chunk_table(&manifest, &bytes[manifest_end..chunk_table_end])?;
    let chunks = build_chunks_from_records(&chunk_table, &bytes[chunk_table_end..])?;

    Ok(IblAsset {
        header,
        manifest,
        chunk_table,
        chunks,
    })
}

pub fn inspect_asset(asset: &IblAsset) -> InspectInfo {
    InspectInfo {
        version: asset.header.version,
        chunk_count: asset.chunk_table.len(),
        width: asset.manifest.width,
        height: asset.manifest.height,
        mip_count: asset.manifest.mip_count,
        face_count: asset.manifest.face_count,
        encoding: asset.manifest.encoding.clone(),
    }
}

pub fn validate_asset(asset: &IblAsset) -> ValidationReport {
    let mut issues = Vec::new();

    if asset.header.magic != FORMAT_MAGIC {
        issues.push(error_issue("header magic must be IBLA"));
    }

    if asset.header.version != FORMAT_VERSION {
        issues.push(ValidationIssue {
            severity: ValidationSeverity::Warning,
            message: format!(
                "asset version {} differs from current version {}",
                asset.header.version, FORMAT_VERSION
            ),
        });
    }

    if EncodingKind::from_str(&asset.manifest.encoding).is_err() {
        issues.push(error_issue(
            "manifest encoding must be rgbd-srgb, srgb, or linear",
        ));
    }

    if asset.manifest.container != "png" {
        issues.push(error_issue("manifest container must be png"));
    }

    if asset.manifest.width == 0 || asset.manifest.height == 0 {
        issues.push(error_issue(
            "manifest width and height must be greater than zero",
        ));
    }

    if asset.manifest.mip_count == 0 {
        issues.push(error_issue("manifest mipCount must be greater than zero"));
    }

    if asset.manifest.face_count != 1 && asset.manifest.face_count != 6 {
        issues.push(error_issue("manifest faceCount must be 1 or 6"));
    }

    if SourceFormat::from_str(&asset.manifest.build.source_format).is_err() {
        issues.push(error_issue(
            "manifest build.sourceFormat must be hdr, exr, png, jpg, jpeg, or unknown",
        ));
    }

    let mut record_keys = BTreeSet::new();
    for record in &asset.chunk_table {
        let key = identity_from_record(record);
        if !record_keys.insert(key.clone()) {
            issues.push(error_issue(&format!(
                "duplicate chunk record for {}",
                describe_identity(&key)
            )));
        }

        if record.width == 0 || record.height == 0 {
            issues.push(error_issue(
                "chunk width and height must be greater than zero",
            ));
        }
    }

    let mut chunk_map = BTreeMap::new();
    for chunk in &asset.chunks {
        let key = identity_from_chunk(chunk);
        if chunk_map.insert(key.clone(), chunk).is_some() {
            issues.push(error_issue(&format!(
                "duplicate chunk payload for {}",
                describe_identity(&key)
            )));
        }
    }

    let total_binary_bytes = asset
        .chunks
        .iter()
        .map(|chunk| chunk.bytes.len() as u64)
        .sum::<u64>();
    let mut ranges = Vec::new();

    for record in &asset.chunk_table {
        let key = identity_from_record(record);
        match chunk_map.get(&key) {
            Some(chunk) => {
                if record.byte_length != chunk.bytes.len() as u64 {
                    issues.push(error_issue(&format!(
                        "byte length mismatch for {}",
                        describe_identity(&key)
                    )));
                }
            }
            None => issues.push(error_issue(&format!(
                "missing binary payload for {}",
                describe_identity(&key)
            ))),
        }

        let end = match record.byte_offset.checked_add(record.byte_length) {
            Some(value) => value,
            None => {
                issues.push(error_issue(&format!(
                    "byte range overflow for {}",
                    describe_identity(&key)
                )));
                continue;
            }
        };

        if end > total_binary_bytes {
            issues.push(error_issue(&format!(
                "byte range exceeds binary section for {}",
                describe_identity(&key)
            )));
        }

        ranges.push((record.byte_offset, end, key));
    }

    ranges.sort_by_key(|(start, _, _)| *start);
    for window in ranges.windows(2) {
        let (_, first_end, first_key) = &window[0];
        let (second_start, _, second_key) = &window[1];
        if *second_start < *first_end {
            issues.push(error_issue(&format!(
                "chunk payload ranges overlap between {} and {}",
                describe_identity(first_key),
                describe_identity(second_key)
            )));
        }
    }

    if let Some((_, last_end, _)) = ranges.last() {
        if *last_end != total_binary_bytes {
            issues.push(error_issue(
                "chunk table does not cover the entire binary section",
            ));
        }
    } else if total_binary_bytes != 0 {
        issues.push(error_issue(
            "chunk table does not cover the entire binary section",
        ));
    }

    validate_asset_shape(asset, &mut issues);

    ValidationReport {
        is_valid: !issues
            .iter()
            .any(|issue| issue.severity == ValidationSeverity::Error),
        issues,
    }
}

pub fn extract_asset<P: AsRef<Path>>(asset: &IblAsset, dir: P) -> Result<Vec<PathBuf>, IblError> {
    let normalized = normalize_asset(asset)?;
    let output_dir = dir.as_ref();
    fs::create_dir_all(output_dir)?;

    let manifest_path = output_dir.join("manifest.json");
    let chunk_table_path = output_dir.join("chunk-table.txt");
    let summary_path = output_dir.join("summary.txt");
    let chunks_dir = output_dir.join("images");

    fs::create_dir_all(&chunks_dir)?;
    fs::write(&manifest_path, serialize_manifest(&normalized.manifest))?;
    fs::write(
        &chunk_table_path,
        render_chunk_table_text(&normalized.chunk_table),
    )?;
    fs::write(&summary_path, render_summary_text(&normalized))?;

    let mut outputs = vec![
        manifest_path.clone(),
        chunk_table_path.clone(),
        summary_path.clone(),
        chunks_dir.clone(),
    ];

    for chunk in &normalized.chunks {
        let file_name = format_chunk_file_name(&normalized.manifest, chunk);
        let path = chunks_dir.join(file_name);
        fs::write(&path, &chunk.bytes)?;
        outputs.push(path);
    }

    Ok(outputs)
}

fn error_issue(message: &str) -> ValidationIssue {
    ValidationIssue {
        severity: ValidationSeverity::Error,
        message: message.to_string(),
    }
}

fn build_manifest(source_format: SourceFormat, options: &BakeOptions) -> Manifest {
    let (width, height, mip_count, face_count) = match options.asset_kind {
        AssetKind::SpecularCubemap => (
            options.cube_size,
            options.cube_size,
            estimate_mip_count(options.cube_size),
            6,
        ),
        AssetKind::IrradianceCubemap => (options.irradiance_size, options.irradiance_size, 1, 6),
        AssetKind::BrdfLut => (BRDF_LUT_SIZE, BRDF_LUT_SIZE, 1, 1),
    };

    Manifest {
        generator: "ibl-baker".to_string(),
        generator_version: env!("CARGO_PKG_VERSION").to_string(),
        encoding: options.output_encoding.as_str().to_string(),
        container: "png".to_string(),
        width,
        height,
        mip_count,
        face_count,
        build: BuildInfo {
            rotation_degrees: options.rotation_degrees,
            sample_count: options.sample_count,
            quality: options.quality.as_str().to_string(),
            source_format: source_format.as_str().to_string(),
        },
    }
}

fn validate_asset_shape(asset: &IblAsset, issues: &mut Vec<ValidationIssue>) {
    match asset.manifest.face_count {
        6 => {
            let expected_count = asset.manifest.mip_count as usize * Face::all().len();
            if asset.chunk_table.len() != expected_count {
                issues.push(error_issue(
                    "cubemap chunk count does not match mipCount and faceCount",
                ));
            }

            let mut expected_records = BTreeSet::new();
            for mip_level in 0..asset.manifest.mip_count {
                for face in Face::all() {
                    expected_records.insert(ChunkIdentity {
                        mip_level,
                        face: Some(*face),
                    });
                }
            }

            validate_expected_records(asset, issues, &expected_records, true);
        }
        1 => {
            if asset.chunk_table.len() != asset.manifest.mip_count as usize {
                issues.push(error_issue(
                    "single-face chunk count does not match mipCount",
                ));
            }

            let expected_records = (0..asset.manifest.mip_count)
                .map(|mip_level| ChunkIdentity {
                    mip_level,
                    face: None,
                })
                .collect::<BTreeSet<_>>();

            validate_expected_records(asset, issues, &expected_records, false);
        }
        _ => {}
    }
}

fn validate_expected_records(
    asset: &IblAsset,
    issues: &mut Vec<ValidationIssue>,
    expected_records: &BTreeSet<ChunkIdentity>,
    expect_faces: bool,
) {
    let actual_records = asset
        .chunk_table
        .iter()
        .map(identity_from_record)
        .collect::<BTreeSet<_>>();

    for record in &asset.chunk_table {
        match (expect_faces, record.face) {
            (true, None) => issues.push(error_issue("cubemap chunks must include a face")),
            (false, Some(_)) => {
                issues.push(error_issue("single-face chunks must not include a face"))
            }
            _ => {}
        }
    }

    for identity in expected_records.difference(&actual_records) {
        issues.push(error_issue(&format!(
            "missing chunk record for {}",
            describe_identity(identity)
        )));
    }

    for identity in actual_records.difference(expected_records) {
        issues.push(error_issue(&format!(
            "unexpected chunk record for {}",
            describe_identity(identity)
        )));
    }
}

fn dimension_at_mip(base: u32, mip_level: u32) -> u32 {
    let shift = mip_level.min(31);
    let dimension = base >> shift;
    dimension.max(1)
}

fn normalize_asset(asset: &IblAsset) -> Result<IblAsset, IblError> {
    let mut entries = pair_entries(asset)?;
    sort_entries(&mut entries);

    let mut offset = 0_u64;
    for entry in &mut entries {
        entry.record.byte_offset = offset;
        entry.record.byte_length = entry.chunk.bytes.len() as u64;
        offset += entry.record.byte_length;
    }

    let mut normalized = IblAsset {
        header: IblHeader {
            magic: FORMAT_MAGIC,
            version: FORMAT_VERSION,
            flags: asset.header.flags,
            manifest_byte_length: 0,
            chunk_table_byte_length: 0,
        },
        manifest: asset.manifest.clone(),
        chunk_table: entries.iter().map(|entry| entry.record.clone()).collect(),
        chunks: entries.iter().map(|entry| entry.chunk.clone()).collect(),
    };

    refresh_header_lengths(&mut normalized)?;
    Ok(normalized)
}

fn pair_entries(asset: &IblAsset) -> Result<Vec<ChunkEntry>, IblError> {
    let mut chunk_map = BTreeMap::new();
    for chunk in &asset.chunks {
        let identity = identity_from_chunk(chunk);
        if chunk_map.insert(identity.clone(), chunk.clone()).is_some() {
            return Err(IblError::InvalidFormat(format!(
                "duplicate chunk payload for {}",
                describe_identity(&identity)
            )));
        }
    }

    let mut entries = Vec::new();
    for record in &asset.chunk_table {
        let identity = identity_from_record(record);
        let chunk = chunk_map.remove(&identity).ok_or_else(|| {
            IblError::InvalidFormat(format!(
                "missing chunk payload for {}",
                describe_identity(&identity)
            ))
        })?;

        entries.push(ChunkEntry {
            record: record.clone(),
            chunk,
        });
    }

    if let Some(identity) = chunk_map.keys().next() {
        return Err(IblError::InvalidFormat(format!(
            "orphan chunk payload for {}",
            describe_identity(identity)
        )));
    }

    Ok(entries)
}

fn sort_entries(entries: &mut [ChunkEntry]) {
    entries.sort_by(|left, right| {
        left.record
            .mip_level
            .cmp(&right.record.mip_level)
            .then(face_sort_key(left.record.face).cmp(&face_sort_key(right.record.face)))
    });
}

fn face_sort_key(face: Option<Face>) -> u8 {
    face.map(|value| value.code()).unwrap_or(u8::MAX)
}

fn identity_from_record(record: &ChunkRecord) -> ChunkIdentity {
    ChunkIdentity {
        mip_level: record.mip_level,
        face: record.face,
    }
}

fn identity_from_chunk(chunk: &ChunkData) -> ChunkIdentity {
    ChunkIdentity {
        mip_level: chunk.mip_level,
        face: chunk.face,
    }
}

fn describe_identity(identity: &ChunkIdentity) -> String {
    match identity.face {
        Some(face) => format!("mip {} face {}", identity.mip_level, face.as_str()),
        None => format!("mip {}", identity.mip_level),
    }
}

fn encode_asset_bytes(asset: &IblAsset) -> Result<Vec<u8>, IblError> {
    let normalized = normalize_asset(asset)?;
    let manifest_json = serialize_manifest(&normalized.manifest);
    let chunk_table_bytes = serialize_chunk_table(&normalized.chunk_table)?;
    let chunk_bytes_len = normalized
        .chunks
        .iter()
        .map(|chunk| chunk.bytes.len())
        .sum::<usize>();

    let mut bytes = Vec::with_capacity(
        HEADER_BYTE_LENGTH + manifest_json.len() + chunk_table_bytes.len() + chunk_bytes_len,
    );
    bytes.extend_from_slice(&encode_header(&normalized.header));
    bytes.extend_from_slice(manifest_json.as_bytes());
    bytes.extend_from_slice(&chunk_table_bytes);

    for chunk in &normalized.chunks {
        bytes.extend_from_slice(&chunk.bytes);
    }

    Ok(bytes)
}

fn encode_header(header: &IblHeader) -> [u8; HEADER_BYTE_LENGTH] {
    let mut bytes = [0_u8; HEADER_BYTE_LENGTH];
    bytes[0..4].copy_from_slice(&header.magic);
    bytes[4..6].copy_from_slice(&header.version.to_le_bytes());
    bytes[6..8].copy_from_slice(&header.flags.to_le_bytes());
    bytes[8..12].copy_from_slice(&header.manifest_byte_length.to_le_bytes());
    bytes[12..16].copy_from_slice(&header.chunk_table_byte_length.to_le_bytes());
    bytes
}

fn parse_header(bytes: &[u8]) -> Result<IblHeader, IblError> {
    if bytes.len() != HEADER_BYTE_LENGTH {
        return Err(IblError::InvalidFormat(format!(
            "invalid header length: {}",
            bytes.len()
        )));
    }

    let magic = [bytes[0], bytes[1], bytes[2], bytes[3]];
    if magic != FORMAT_MAGIC {
        return Err(IblError::InvalidFormat(
            "unexpected file magic, expected IBLA".to_string(),
        ));
    }

    let version = u16::from_le_bytes([bytes[4], bytes[5]]);
    let flags = u16::from_le_bytes([bytes[6], bytes[7]]);
    let manifest_byte_length = u32::from_le_bytes([bytes[8], bytes[9], bytes[10], bytes[11]]);
    let chunk_table_byte_length = u32::from_le_bytes([bytes[12], bytes[13], bytes[14], bytes[15]]);

    Ok(IblHeader {
        magic,
        version,
        flags,
        manifest_byte_length,
        chunk_table_byte_length,
    })
}

fn refresh_header_lengths(asset: &mut IblAsset) -> Result<(), IblError> {
    let manifest_byte_length = serialize_manifest(&asset.manifest).len();
    let chunk_table_byte_length = serialize_chunk_table(&asset.chunk_table)?.len();

    asset.header.manifest_byte_length = u32::try_from(manifest_byte_length)
        .map_err(|_| IblError::InvalidFormat("manifest exceeds u32 length".to_string()))?;
    asset.header.chunk_table_byte_length = u32::try_from(chunk_table_byte_length)
        .map_err(|_| IblError::InvalidFormat("chunk table exceeds u32 length".to_string()))?;
    Ok(())
}

fn serialize_manifest(manifest: &Manifest) -> String {
    format!(
        "{{\n  \"generator\": \"{}\",\n  \"generatorVersion\": \"{}\",\n  \"encoding\": \"{}\",\n  \"container\": \"{}\",\n  \"width\": {},\n  \"height\": {},\n  \"mipCount\": {},\n  \"faceCount\": {},\n  \"build\": {{\n    \"rotation\": {},\n    \"samples\": {},\n    \"quality\": \"{}\",\n    \"sourceFormat\": \"{}\"\n  }}\n}}\n",
        manifest.generator,
        manifest.generator_version,
        manifest.encoding,
        manifest.container,
        manifest.width,
        manifest.height,
        manifest.mip_count,
        manifest.face_count,
        format_f32(manifest.build.rotation_degrees),
        manifest.build.sample_count,
        manifest.build.quality,
        manifest.build.source_format
    )
}

fn parse_manifest(text: &str) -> Result<Manifest, IblError> {
    let generator = extract_json_string(text, "\"generator\":")?;
    let generator_version = extract_json_string(text, "\"generatorVersion\":")?;
    let encoding = extract_json_string(text, "\"encoding\":")?;
    let container = extract_json_string(text, "\"container\":")?;
    let width = extract_json_u32(text, "\"width\":")?;
    let height = extract_json_u32(text, "\"height\":")?;
    let mip_count = extract_json_u32(text, "\"mipCount\":")?;
    let face_count = extract_json_u32(text, "\"faceCount\":")?;
    let build_body = extract_object_body(text, "\"build\":")?;

    Ok(Manifest {
        generator,
        generator_version,
        encoding,
        container,
        width,
        height,
        mip_count,
        face_count,
        build: BuildInfo {
            rotation_degrees: extract_json_f32(build_body, "\"rotation\":")?,
            sample_count: extract_json_u32(build_body, "\"samples\":")?,
            quality: extract_json_string(build_body, "\"quality\":")?,
            source_format: extract_json_string(build_body, "\"sourceFormat\":")?,
        },
    })
}

fn serialize_chunk_table(records: &[ChunkRecord]) -> Result<Vec<u8>, IblError> {
    let mut bytes = Vec::with_capacity(records.len() * std::mem::size_of::<u64>());
    for record in records {
        push_u64(&mut bytes, record.byte_length);
    }

    Ok(bytes)
}

fn parse_chunk_table(manifest: &Manifest, bytes: &[u8]) -> Result<Vec<ChunkRecord>, IblError> {
    let mut cursor = Cursor::new(bytes);
    let expected_count = expected_chunk_count(manifest)?;
    let expected_byte_length = expected_count
        .checked_mul(std::mem::size_of::<u64>())
        .ok_or_else(|| IblError::InvalidFormat("chunk table length overflow".to_string()))?;
    if bytes.len() != expected_byte_length {
        return Err(IblError::InvalidFormat(format!(
            "chunk table length {} does not match expected {}",
            bytes.len(),
            expected_byte_length
        )));
    }

    let mut records = Vec::with_capacity(expected_count);
    let mut byte_offset = 0_u64;
    for index in 0..expected_count {
        let byte_length = cursor.read_u64()?;
        let (mip_level, face, width, height) = derive_chunk_metadata(manifest, index)?;

        records.push(ChunkRecord {
            mip_level,
            byte_offset,
            byte_length,
            width,
            height,
            face,
        });
        byte_offset = byte_offset
            .checked_add(byte_length)
            .ok_or_else(|| IblError::InvalidFormat("chunk byte offset overflow".to_string()))?;
    }

    if !cursor.is_at_end() {
        return Err(IblError::InvalidFormat(
            "chunk table contains trailing bytes".to_string(),
        ));
    }

    Ok(records)
}

fn build_chunks_from_records(
    records: &[ChunkRecord],
    binary_section: &[u8],
) -> Result<Vec<ChunkData>, IblError> {
    let mut chunks = Vec::with_capacity(records.len());
    for record in records {
        let start = usize::try_from(record.byte_offset).map_err(|_| {
            IblError::InvalidFormat("chunk offset exceeds platform usize".to_string())
        })?;
        let byte_length = usize::try_from(record.byte_length).map_err(|_| {
            IblError::InvalidFormat("chunk length exceeds platform usize".to_string())
        })?;
        let end = start
            .checked_add(byte_length)
            .ok_or_else(|| IblError::InvalidFormat("chunk payload range overflow".to_string()))?;

        if end > binary_section.len() {
            return Err(IblError::InvalidFormat(format!(
                "chunk payload exceeds binary section for {}",
                describe_identity(&identity_from_record(record))
            )));
        }

        chunks.push(ChunkData {
            mip_level: record.mip_level,
            face: record.face,
            bytes: binary_section[start..end].to_vec(),
        });
    }

    let covered_binary_bytes = records.iter().try_fold(0usize, |max_end, record| {
        let start = usize::try_from(record.byte_offset).map_err(|_| {
            IblError::InvalidFormat("chunk offset exceeds platform usize".to_string())
        })?;
        let byte_length = usize::try_from(record.byte_length).map_err(|_| {
            IblError::InvalidFormat("chunk length exceeds platform usize".to_string())
        })?;
        let end = start
            .checked_add(byte_length)
            .ok_or_else(|| IblError::InvalidFormat("chunk payload range overflow".to_string()))?;
        Ok::<usize, IblError>(max_end.max(end))
    })?;

    if covered_binary_bytes != binary_section.len() {
        return Err(IblError::InvalidFormat(
            "chunk table does not cover the entire binary section".to_string(),
        ));
    }

    Ok(chunks)
}

fn expected_chunk_count(manifest: &Manifest) -> Result<usize, IblError> {
    let mip_count = usize::try_from(manifest.mip_count)
        .map_err(|_| IblError::InvalidFormat("mipCount exceeds platform usize".to_string()))?;
    let face_count = usize::try_from(manifest.face_count)
        .map_err(|_| IblError::InvalidFormat("faceCount exceeds platform usize".to_string()))?;
    mip_count
        .checked_mul(face_count)
        .ok_or_else(|| IblError::InvalidFormat("chunk count overflow".to_string()))
}

fn derive_chunk_metadata(
    manifest: &Manifest,
    index: usize,
) -> Result<(u32, Option<Face>, u32, u32), IblError> {
    match manifest.face_count {
        1 => {
            let mip_level = u32::try_from(index)
                .map_err(|_| IblError::InvalidFormat("mip index exceeds u32".to_string()))?;
            Ok((
                mip_level,
                None,
                dimension_at_mip(manifest.width, mip_level),
                dimension_at_mip(manifest.height, mip_level),
            ))
        }
        6 => {
            let face_count = Face::all().len();
            let mip_level = u32::try_from(index / face_count)
                .map_err(|_| IblError::InvalidFormat("mip index exceeds u32".to_string()))?;
            let face = Face::all()
                .get(index % face_count)
                .copied()
                .ok_or_else(|| IblError::InvalidFormat("invalid cubemap face index".to_string()))?;
            let size = dimension_at_mip(manifest.width, mip_level);
            Ok((mip_level, Some(face), size, size))
        }
        other => Err(IblError::InvalidFormat(format!(
            "unsupported faceCount in chunk metadata: {other}"
        ))),
    }
}

fn render_chunk_table_text(records: &[ChunkRecord]) -> String {
    let mut lines = vec!["mip|face|offset|length|width|height".to_string()];
    for record in records {
        lines.push(format!(
            "{}|{}|{}|{}|{}|{}",
            record.mip_level,
            record.face.map(|face| face.as_str()).unwrap_or("-"),
            record.byte_offset,
            record.byte_length,
            record.width,
            record.height
        ));
    }
    format!("{}\n", lines.join("\n"))
}

fn render_summary_text(asset: &IblAsset) -> String {
    let lines = vec![
        format!("version={}", asset.header.version),
        format!("chunks={}", asset.chunk_table.len()),
        format!("width={}", asset.manifest.width),
        format!("height={}", asset.manifest.height),
        format!("mipCount={}", asset.manifest.mip_count),
        format!("faceCount={}", asset.manifest.face_count),
        format!("encoding={}", asset.manifest.encoding),
    ];

    format!("{}\n", lines.join("\n"))
}

fn format_chunk_file_name(manifest: &Manifest, chunk: &ChunkData) -> String {
    let asset_name = match manifest.face_count {
        6 => "cubemap",
        1 => "image",
        other => panic!("unsupported face count in extracted file name: {other}"),
    };
    match chunk.face {
        Some(face) => format!(
            "{asset_name}_mip{:02}_{}.png",
            chunk.mip_level,
            face.as_str()
        ),
        None => format!("{asset_name}_mip{:02}.png", chunk.mip_level),
    }
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_le_bytes());
}

fn format_f32(value: f32) -> String {
    if value.fract() == 0.0 {
        format!("{value:.1}")
    } else {
        value.to_string()
    }
}

fn extract_json_string(text: &str, key: &str) -> Result<String, IblError> {
    let start = text
        .find(key)
        .ok_or_else(|| IblError::InvalidFormat(format!("missing {key}")))?;
    let slice = &text[start + key.len()..];
    let opening_quote = slice
        .find('"')
        .ok_or_else(|| IblError::InvalidFormat(format!("missing opening quote for {key}")))?;
    let rest = &slice[opening_quote + 1..];
    let closing_quote = rest
        .find('"')
        .ok_or_else(|| IblError::InvalidFormat(format!("missing closing quote for {key}")))?;
    Ok(rest[..closing_quote].to_string())
}

fn extract_json_u32(text: &str, key: &str) -> Result<u32, IblError> {
    let start = text
        .find(key)
        .ok_or_else(|| IblError::InvalidFormat(format!("missing {key}")))?;
    let slice = &text[start + key.len()..];
    let digits = slice
        .chars()
        .skip_while(|character| character.is_whitespace())
        .take_while(|character| character.is_ascii_digit())
        .collect::<String>();

    digits
        .parse::<u32>()
        .map_err(|_| IblError::InvalidFormat(format!("invalid numeric value for {key}: {digits}")))
}

fn extract_json_f32(text: &str, key: &str) -> Result<f32, IblError> {
    let start = text
        .find(key)
        .ok_or_else(|| IblError::InvalidFormat(format!("missing {key}")))?;
    let slice = &text[start + key.len()..];
    let digits = slice
        .chars()
        .skip_while(|character| character.is_whitespace())
        .take_while(|character| {
            character.is_ascii_digit() || *character == '.' || *character == '-'
        })
        .collect::<String>();

    digits
        .parse::<f32>()
        .map_err(|_| IblError::InvalidFormat(format!("invalid float value for {key}: {digits}")))
}

fn extract_object_body<'a>(text: &'a str, key: &str) -> Result<&'a str, IblError> {
    extract_delimited_body(text, key, '{', '}')
}

fn extract_delimited_body<'a>(
    text: &'a str,
    key: &str,
    open: char,
    close: char,
) -> Result<&'a str, IblError> {
    let key_start = text
        .find(key)
        .ok_or_else(|| IblError::InvalidFormat(format!("missing {key}")))?;
    let slice = &text[key_start + key.len()..];
    let open_index = slice
        .find(open)
        .ok_or_else(|| IblError::InvalidFormat(format!("missing opening delimiter for {key}")))?;

    let mut depth = 0_i32;
    let mut end_index = None;
    for (index, character) in slice[open_index..].char_indices() {
        if character == open {
            depth += 1;
        } else if character == close {
            depth -= 1;
            if depth == 0 {
                end_index = Some(open_index + index);
                break;
            }
        }
    }

    let end_index = end_index.ok_or_else(|| {
        IblError::InvalidFormat(format!("unterminated delimited block for {key}"))
    })?;
    Ok(&slice[open_index + 1..end_index])
}

struct Cursor<'a> {
    bytes: &'a [u8],
    position: usize,
}

impl<'a> Cursor<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, position: 0 }
    }

    fn read_u64(&mut self) -> Result<u64, IblError> {
        Ok(u64::from_le_bytes(self.read_exact::<8>()?))
    }

    fn read_exact<const N: usize>(&mut self) -> Result<[u8; N], IblError> {
        let slice = self.read_bytes(N)?;
        let mut array = [0_u8; N];
        array.copy_from_slice(slice);
        Ok(array)
    }

    fn read_bytes(&mut self, length: usize) -> Result<&'a [u8], IblError> {
        let end = self.position.checked_add(length).ok_or_else(|| {
            IblError::InvalidFormat("cursor overflow while reading chunk table".to_string())
        })?;
        if end > self.bytes.len() {
            return Err(IblError::InvalidFormat(
                "unexpected end of chunk table".to_string(),
            ));
        }

        let slice = &self.bytes[self.position..end];
        self.position = end;
        Ok(slice)
    }

    fn is_at_end(&self) -> bool {
        self.position == self.bytes.len()
    }
}

fn estimate_mip_count(width: u32) -> u32 {
    let mut size = width.max(1);
    let mut mip_count = 1;
    while size > 1 {
        size /= 2;
        mip_count += 1;
    }
    mip_count
}

#[cfg(test)]
fn unique_temp_path(label: &str) -> PathBuf {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time before UNIX_EPOCH")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "ibl-baker-{label}-{timestamp}-{}",
        std::process::id()
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use approx::assert_relative_eq;

    fn write_solid_png(path: &Path, color: glam::Vec3) {
        let bytes = encode_png_image(&single_color_image(4, 4, color), EncodingKind::Srgb)
            .expect("png should encode");
        fs::write(path, bytes).expect("png should be written");
    }

    #[test]
    fn header_round_trip_is_stable() {
        let header = IblHeader {
            magic: FORMAT_MAGIC,
            version: FORMAT_VERSION,
            flags: 7,
            manifest_byte_length: 128,
            chunk_table_byte_length: 256,
        };

        let encoded = encode_header(&header);
        let decoded = parse_header(&encoded).expect("header should decode");
        assert_eq!(decoded, header);
    }

    #[test]
    fn hdr_input_decodes_into_linear_source_image() {
        let path = unique_temp_path("decode-hdr").with_extension("hdr");
        write_test_hdr(&path, 4, 2);

        let source = load_source_image(&path).expect("hdr should decode");
        assert_eq!(source_image_dimensions(&source), (4, 2));
        assert!(source_image_pixel(&source, 3, 1).x > source_image_pixel(&source, 0, 0).x);

        fs::remove_file(&path).ok();
    }

    #[test]
    fn png_input_decodes_as_linearized_srgb() {
        let path = unique_temp_path("decode-png").with_extension("png");
        write_test_png(&path, 2, 2);

        let source = load_source_image(&path).expect("png should decode");
        assert_eq!(source_image_dimensions(&source), (2, 2));
        assert!(source_image_pixel(&source, 1, 0).x > source_image_pixel(&source, 0, 0).x);

        fs::remove_file(&path).ok();
    }

    #[test]
    fn exr_input_decodes_into_linear_source_image() {
        let path = unique_temp_path("decode-exr").with_extension("exr");
        write_test_exr(&path, 4, 2);

        let source = load_source_image(&path).expect("exr should decode");
        assert_eq!(source_image_dimensions(&source), (4, 2));
        assert!(source_image_pixel(&source, 3, 1).z > source_image_pixel(&source, 0, 0).z);

        fs::remove_file(&path).ok();
    }

    #[test]
    fn cubemap_input_bakes_and_records_png_source_format() {
        let input_dir = unique_temp_path("cubemap-input");
        fs::create_dir_all(&input_dir).expect("cubemap dir should be created");

        for (name, color) in [
            ("px.png", glam::Vec3::new(1.0, 0.0, 0.0)),
            ("nx.png", glam::Vec3::new(0.0, 1.0, 0.0)),
            ("py.png", glam::Vec3::new(0.0, 0.0, 1.0)),
            ("ny.png", glam::Vec3::new(1.0, 1.0, 0.0)),
            ("pz.png", glam::Vec3::new(1.0, 0.0, 1.0)),
            ("nz.png", glam::Vec3::new(0.0, 1.0, 1.0)),
        ] {
            write_solid_png(&input_dir.join(name), color);
        }

        let asset = bake_cubemap_to_asset(
            &CubemapInputPaths::from_face_order([
                input_dir.join("px.png"),
                input_dir.join("nx.png"),
                input_dir.join("py.png"),
                input_dir.join("ny.png"),
                input_dir.join("pz.png"),
                input_dir.join("nz.png"),
            ]),
            BakeOptions {
                cube_size: 8,
                ..BakeOptions::default()
            },
        )
        .expect("cubemap asset should bake");

        assert_eq!(asset.manifest.build.source_format, "png");
        fs::remove_dir_all(&input_dir).ok();
    }

    #[test]
    fn cubemap_input_rejects_non_square_faces() {
        let input_dir = unique_temp_path("cubemap-nonsquare");
        fs::create_dir_all(&input_dir).expect("cubemap dir should be created");

        write_test_png(&input_dir.join("px.png"), 8, 4);
        for name in ["nx.png", "py.png", "ny.png", "pz.png", "nz.png"] {
            write_test_png(&input_dir.join(name), 4, 4);
        }

        let error = bake_cubemap_to_asset(
            &CubemapInputPaths::from_face_order([
                input_dir.join("px.png"),
                input_dir.join("nx.png"),
                input_dir.join("py.png"),
                input_dir.join("ny.png"),
                input_dir.join("pz.png"),
                input_dir.join("nz.png"),
            ]),
            BakeOptions::default(),
        )
        .expect_err("non-square cubemap should fail");

        assert!(error.to_string().contains("must be square"));
        fs::remove_dir_all(&input_dir).ok();
    }

    #[test]
    fn asset_round_trip_preserves_manifest_and_chunk_records() {
        let input = unique_temp_path("asset-roundtrip-input").with_extension("hdr");
        write_test_hdr(&input, 8, 4);

        let asset = bake_to_asset(
            &input,
            BakeOptions {
                cube_size: 8,
                ..BakeOptions::default()
            },
        )
        .expect("asset should bake");
        let encoded = encode_asset_bytes(&asset).expect("asset should encode");
        let asset_path = unique_temp_path("asset-roundtrip-file");
        fs::write(&asset_path, encoded).expect("encoded asset should be written");

        let decoded = read_asset(&asset_path).expect("asset should decode");
        assert_eq!(decoded.manifest, asset.manifest);
        assert_eq!(decoded.chunk_table, asset.chunk_table);

        fs::remove_file(&input).ok();
        fs::remove_file(&asset_path).ok();
    }

    #[test]
    fn chunk_table_binary_round_trip_is_lossless() {
        let manifest = Manifest {
            generator: "ibl-baker".to_string(),
            generator_version: "0.2.1".to_string(),
            encoding: "rgbd-srgb".to_string(),
            container: "png".to_string(),
            width: BRDF_LUT_SIZE,
            height: BRDF_LUT_SIZE,
            mip_count: 2,
            face_count: 1,
            build: BuildInfo {
                rotation_degrees: 0.0,
                sample_count: 1024,
                quality: "medium".to_string(),
                source_format: "hdr".to_string(),
            },
        };
        let records = vec![
            ChunkRecord {
                mip_level: 0,
                face: None,
                byte_offset: 0,
                byte_length: 70,
                width: BRDF_LUT_SIZE,
                height: BRDF_LUT_SIZE,
            },
            ChunkRecord {
                mip_level: 1,
                face: None,
                byte_offset: 70,
                byte_length: 35,
                width: BRDF_LUT_SIZE / 2,
                height: BRDF_LUT_SIZE / 2,
            },
        ];

        let encoded = serialize_chunk_table(&records).expect("chunk table should encode");
        let decoded = parse_chunk_table(&manifest, &encoded).expect("chunk table should decode");
        assert_eq!(decoded, records);
    }

    #[test]
    fn bake_outputs_expected_cubemap_chunk_count() {
        let input = unique_temp_path("specular-count-input").with_extension("hdr");
        write_test_hdr(&input, 16, 8);

        let asset = bake_to_asset(
            &input,
            BakeOptions {
                cube_size: 8,
                ..BakeOptions::default()
            },
        )
        .expect("asset should bake");
        assert_eq!(asset.manifest.face_count, 6);
        assert_eq!(
            asset.chunk_table.len(),
            asset.manifest.mip_count as usize * Face::all().len()
        );
        assert_eq!(png_dimensions(&asset.chunks[0].bytes), (8, 8));

        fs::remove_file(&input).ok();
    }

    #[test]
    fn brdf_lut_asset_uses_a_single_two_dimensional_image() {
        let input = unique_temp_path("brdf-lut-input").with_extension("hdr");
        write_test_hdr(&input, 4, 2);

        let options = BakeOptions {
            asset_kind: AssetKind::BrdfLut,
            ..BakeOptions::default()
        };
        let asset = bake_to_asset(&input, options).expect("asset should bake");

        assert_eq!(asset.manifest.face_count, 1);
        assert_eq!(asset.chunk_table.len(), 1);
        assert_eq!(asset.chunk_table[0].face, None);
        assert_eq!(
            png_dimensions(&asset.chunks[0].bytes),
            (BRDF_LUT_SIZE, BRDF_LUT_SIZE)
        );

        fs::remove_file(&input).ok();
    }

    #[test]
    fn validate_detects_duplicate_keys_and_offset_errors() {
        let bytes = encode_png_image(
            &single_color_image(1, 1, glam::Vec3::new(0.25, 0.5, 0.75)),
            EncodingKind::Srgb,
        )
        .expect("png should encode");

        let asset = IblAsset {
            header: IblHeader {
                magic: FORMAT_MAGIC,
                version: FORMAT_VERSION,
                flags: 0,
                manifest_byte_length: 0,
                chunk_table_byte_length: 0,
            },
            manifest: Manifest {
                generator: "ibl-baker".to_string(),
                generator_version: "0.2.1".to_string(),
                encoding: "rgbd-srgb".to_string(),
                container: "png".to_string(),
                width: 512,
                height: 512,
                mip_count: 1,
                face_count: 6,
                build: BuildInfo {
                    rotation_degrees: 0.0,
                    sample_count: 1024,
                    quality: "medium".to_string(),
                    source_format: "hdr".to_string(),
                },
            },
            chunk_table: vec![
                ChunkRecord {
                    mip_level: 0,
                    face: Some(Face::PositiveX),
                    byte_offset: 0,
                    byte_length: 70,
                    width: 512,
                    height: 512,
                },
                ChunkRecord {
                    mip_level: 0,
                    face: Some(Face::PositiveX),
                    byte_offset: 20,
                    byte_length: 70,
                    width: 512,
                    height: 512,
                },
            ],
            chunks: vec![
                ChunkData {
                    mip_level: 0,
                    face: Some(Face::PositiveX),
                    bytes: bytes.clone(),
                },
                ChunkData {
                    mip_level: 0,
                    face: Some(Face::PositiveX),
                    bytes,
                },
            ],
        };

        let report = validate_asset(&asset);
        assert!(!report.is_valid);
        assert!(report
            .issues
            .iter()
            .any(|issue| issue.message.contains("duplicate")));
        assert!(report
            .issues
            .iter()
            .any(|issue| issue.message.contains("overlap") || issue.message.contains("range")));
    }

    #[test]
    fn read_asset_rejects_trailing_bytes_after_declared_chunks() {
        let input = unique_temp_path("trailing-bytes-input").with_extension("hdr");
        let asset_path = unique_temp_path("trailing-bytes-asset").with_extension("ibla");
        write_test_hdr(&input, 8, 4);

        let asset = bake_to_asset(
            &input,
            BakeOptions {
                cube_size: 8,
                ..BakeOptions::default()
            },
        )
        .expect("asset should bake");
        let mut encoded = encode_asset_bytes(&asset).expect("asset should encode");
        encoded.extend_from_slice(&[9, 9, 9]);
        fs::write(&asset_path, encoded).expect("asset should be written");

        let error = read_asset(&asset_path).expect_err("trailing bytes should be rejected");
        assert!(error
            .to_string()
            .contains("chunk table does not cover the entire binary section"));

        fs::remove_file(&input).ok();
        fs::remove_file(&asset_path).ok();
    }

    #[test]
    fn encoding_output_is_deterministic() {
        let input = unique_temp_path("deterministic-input").with_extension("hdr");
        write_test_hdr(&input, 8, 4);

        let asset = bake_to_asset(
            &input,
            BakeOptions {
                cube_size: 8,
                ..BakeOptions::default()
            },
        )
        .expect("asset should bake");
        let first = encode_asset_bytes(&asset).expect("first encoding should work");
        let second = encode_asset_bytes(&asset).expect("second encoding should work");
        assert_eq!(first, second);

        fs::remove_file(&input).ok();
    }

    #[test]
    fn validate_accepts_all_supported_manifest_encodings() {
        let bytes = encode_png_image(
            &single_color_image(4, 4, glam::Vec3::new(0.25, 0.5, 0.75)),
            EncodingKind::Srgb,
        )
        .expect("png should encode");

        for encoding in ["rgbd-srgb", "srgb", "linear"] {
            let asset = IblAsset {
                header: IblHeader {
                    magic: FORMAT_MAGIC,
                    version: FORMAT_VERSION,
                    flags: 0,
                    manifest_byte_length: 0,
                    chunk_table_byte_length: 0,
                },
                manifest: Manifest {
                    generator: "ibl-baker".to_string(),
                    generator_version: "0.2.1".to_string(),
                    encoding: encoding.to_string(),
                    container: "png".to_string(),
                    width: 4,
                    height: 4,
                    mip_count: 1,
                    face_count: 1,
                    build: BuildInfo {
                        rotation_degrees: 0.0,
                        sample_count: 16,
                        quality: "medium".to_string(),
                        source_format: "png".to_string(),
                    },
                },
                chunk_table: vec![ChunkRecord {
                    mip_level: 0,
                    face: None,
                    byte_offset: 0,
                    byte_length: bytes.len() as u64,
                    width: 4,
                    height: 4,
                }],
                chunks: vec![ChunkData {
                    mip_level: 0,
                    face: None,
                    bytes: bytes.clone(),
                }],
            };

            let report = validate_asset(&asset);
            assert!(
                report.is_valid,
                "encoding {encoding} should be accepted, got issues: {:?}",
                report.issues
            );
        }
    }

    #[test]
    fn bake_records_source_format_from_input_extension() {
        let input = unique_temp_path("source-format-input").with_extension("EXR");
        write_test_exr(&input, 4, 2);

        let asset = bake_to_asset(
            &input,
            BakeOptions {
                cube_size: 8,
                ..BakeOptions::default()
            },
        )
        .expect("asset should bake");
        assert_eq!(asset.manifest.build.source_format, "exr");

        fs::remove_file(&input).ok();
    }

    #[test]
    fn cubemap_direction_is_normalized_and_oriented() {
        let direction = cubemap_direction(Face::PositiveZ, glam::Vec2::ZERO);
        assert_relative_eq!(direction.length(), 1.0, epsilon = 1.0e-6);
        assert!(direction.z > 0.9);
    }

    #[test]
    fn rgbd_encoding_preserves_hdr_energy_order() {
        let (_, dark_d) = encode_rgbd_srgb(glam::Vec3::splat(0.5));
        let (bright_rgb, bright_d) = encode_rgbd_srgb(glam::Vec3::splat(8.0));
        assert!(bright_d < dark_d);
        assert!(bright_rgb.x > 0.9);
    }

    fn png_dimensions(bytes: &[u8]) -> (u32, u32) {
        (
            u32::from_be_bytes(bytes[16..20].try_into().expect("png width bytes")),
            u32::from_be_bytes(bytes[20..24].try_into().expect("png height bytes")),
        )
    }

    fn single_color_image(width: u32, height: u32, color: glam::Vec3) -> source_image::SourceImage {
        let mut image = source_image::SourceImage::new(width, height);
        for y in 0..height {
            for x in 0..width {
                image.set(x, y, color);
            }
        }
        image
    }

    fn source_image_dimensions(image: &source_image::SourceImage) -> (u32, u32) {
        (image.width, image.height)
    }

    fn source_image_pixel(image: &source_image::SourceImage, x: u32, y: u32) -> glam::Vec3 {
        image.get(x, y)
    }
}

mod compress;
mod dfd;
mod kv;

use std::fmt;

// ── Public types ─────────────────────────────────────────────────────────────

/// Error type returned by KTX2 write operations.
#[derive(Debug)]
pub enum Ktx2Error {
    InvalidInput(String),
    CompressFailed(String),
    ZstdFailed(String),
}

impl fmt::Display for Ktx2Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidInput(m) => write!(f, "invalid input: {m}"),
            Self::CompressFailed(m) => write!(f, "BC6H compression failed: {m}"),
            Self::ZstdFailed(m) => write!(f, "zstd compression failed: {m}"),
        }
    }
}

impl std::error::Error for Ktx2Error {}

/// One mip level of a cubemap: 6 faces of linear f32 RGB pixels.
///
/// Face order (index 0..5): +X, -X, +Y, -Y, +Z, -Z (KTX2 and ibl_core canonical order).
///
/// Each face slice has length `face_size * face_size * 3` (R, G, B interleaved, row-major).
/// Pixel values must be linear (not sRGB). Values may exceed 1.0 for HDR content.
pub struct CubemapLevel {
    /// Linear RGB f32 pixels for each of the 6 faces.
    pub face_pixels: [Vec<f32>; 6],
    /// Width == height == face_size. Must be ≥ 1.
    pub face_size: u32,
}

/// Caller-provided generator string written to `KTXwriter` metadata.
/// Recommended format: `"ibl-baker ktx2_writer v0.2.1"`.
pub struct WriterMetadata<'a> {
    pub writer: &'a str,
}

// ── Public API ────────────────────────────────────────────────────────────────

/// Write a BC6H-compressed, zstd-supercompressed KTX2 cubemap.
///
/// `levels` must be ordered **largest first** (level 0 = base mip, level N-1 = smallest mip).
/// All six faces inside each level must have the `face_size` declared for that level, and
/// `face_size` must halve (floor) from one level to the next.
///
/// Uses `VK_FORMAT_BC6H_UFLOAT_BLOCK` (unsigned half-float HDR). Suitable for specular
/// and irradiance cubemaps baked from HDR or LDR source images — BC6H cleanly represents
/// the linear [0, 65504] range.
///
/// A `KTXorientation` (`"rd"`) and `KTXwriter` entry are always included in key/value data.
pub fn write_bc6h_cubemap_ktx2(
    levels: &[CubemapLevel],
    meta: &WriterMetadata<'_>,
) -> Result<Vec<u8>, Ktx2Error> {
    validate_levels(levels)?;

    let level_count = levels.len() as u32;
    let base_size = levels[0].face_size;

    // Step 1: BC6H-compress then zstd each mip level.
    // Returns (zstd_bytes, uncompressed_byte_length) per level.
    let compressed: Vec<(Vec<u8>, u64)> = levels
        .iter()
        .map(compress_level)
        .collect::<Result<_, _>>()?;

    // Step 2: compute file layout.
    let dfd_bytes: &[u8] = &dfd::BC6H_UFLOAT_DFD;
    let kv_bytes = kv::build_kv_data(meta.writer);

    // Fixed sizes:
    //   header            = 48 bytes  (identifier 12 + 9 × u32 36)
    //   index             = 32 bytes  (4 × u32 + 2 × u64)
    //   level index       = level_count × 24 bytes  (3 × u64 per entry)
    let level_index_start: u64 = 80; // header(48) + index(32)
    let dfd_start: u64 = level_index_start + level_count as u64 * 24;
    let kv_start: u64 = dfd_start + dfd_bytes.len() as u64;
    let image_data_start: u64 = kv_start + kv_bytes.len() as u64;

    // With zstd supercompression, required_alignment = 1 (no mipPadding).
    // Data is written smallest mip first (level[N-1] ... level[0]).
    let mut level_byte_offsets = vec![0u64; level_count as usize];
    let mut cursor = image_data_start;
    for p in (0..level_count as usize).rev() {
        level_byte_offsets[p] = cursor;
        cursor += compressed[p].0.len() as u64;
    }

    // Step 3: serialize.
    let mut out: Vec<u8> = Vec::with_capacity(cursor as usize);

    // — Header (48 bytes) —
    out.extend_from_slice(&KTX2_IDENTIFIER);
    push_u32(&mut out, VK_FORMAT_BC6H_UFLOAT_BLOCK);
    push_u32(&mut out, 1); // typeSize: 1 for block-compressed formats
    push_u32(&mut out, base_size); // pixelWidth
    push_u32(&mut out, base_size); // pixelHeight
    push_u32(&mut out, 0); // pixelDepth = 0 (2D cubemap)
    push_u32(&mut out, 0); // layerCount = 0 (non-array)
    push_u32(&mut out, 6); // faceCount = 6 (cubemap)
    push_u32(&mut out, level_count);
    push_u32(&mut out, SUPERCOMPRESSION_ZSTD);

    // — Index (32 bytes) —
    push_u32(&mut out, dfd_start as u32); // dfdByteOffset
    push_u32(&mut out, dfd_bytes.len() as u32); // dfdByteLength
    push_u32(&mut out, kv_start as u32); // kvdByteOffset
    push_u32(&mut out, kv_bytes.len() as u32); // kvdByteLength
    push_u64(&mut out, 0); // sgdByteOffset = 0 (zstd has no global data)
    push_u64(&mut out, 0); // sgdByteLength = 0

    // — Level Index (level_count × 24 bytes) —
    // Entry 0 = level 0 (largest/base), entry N-1 = level N-1 (smallest).
    for p in 0..level_count as usize {
        let (zstd_data, uncompressed_len) = &compressed[p];
        push_u64(&mut out, level_byte_offsets[p]); // byteOffset
        push_u64(&mut out, zstd_data.len() as u64); // byteLength (compressed)
        push_u64(&mut out, *uncompressed_len); // uncompressedByteLength
    }

    // — DFD —
    out.extend_from_slice(dfd_bytes);

    // — Key/Value data —
    out.extend_from_slice(&kv_bytes);

    // — Mip level data (smallest mip first) —
    for p in (0..level_count as usize).rev() {
        out.extend_from_slice(&compressed[p].0);
    }

    debug_assert_eq!(out.len() as u64, cursor);
    Ok(out)
}

// ── Internal helpers ──────────────────────────────────────────────────────────

const KTX2_IDENTIFIER: [u8; 12] = [
    0xAB, 0x4B, 0x54, 0x58, 0x20, 0x32, 0x30, 0xBB, 0x0D, 0x0A, 0x1A, 0x0A,
];
const VK_FORMAT_BC6H_UFLOAT_BLOCK: u32 = 131;
const SUPERCOMPRESSION_ZSTD: u32 = 2;

fn validate_levels(levels: &[CubemapLevel]) -> Result<(), Ktx2Error> {
    if levels.is_empty() {
        return Err(Ktx2Error::InvalidInput("levels must not be empty".into()));
    }
    for (i, level) in levels.iter().enumerate() {
        if level.face_size == 0 {
            return Err(Ktx2Error::InvalidInput(format!(
                "level {i}: face_size must be >= 1"
            )));
        }
        let expected = (level.face_size as usize).saturating_mul(level.face_size as usize) * 3;
        for (f, face) in level.face_pixels.iter().enumerate() {
            if face.len() != expected {
                return Err(Ktx2Error::InvalidInput(format!(
                    "level {i} face {f}: expected {expected} floats \
                     ({face_size}×{face_size}×3), got {}",
                    face.len(),
                    face_size = level.face_size,
                )));
            }
        }
    }
    Ok(())
}

/// BC6H-compress all 6 faces of one mip level, then zstd the concatenated block data.
fn compress_level(level: &CubemapLevel) -> Result<(Vec<u8>, u64), Ktx2Error> {
    let mut uncompressed: Vec<u8> =
        Vec::with_capacity(6 * compress::bc6h_level_bytes(level.face_size));

    for face in &level.face_pixels {
        let blocks = compress::compress_face_bc6h(face, level.face_size)?;
        uncompressed.extend_from_slice(&blocks);
    }

    let uncompressed_len = uncompressed.len() as u64;

    let zstd_data = zstd::encode_all(&uncompressed[..], 3)
        .map_err(|e| Ktx2Error::ZstdFailed(e.to_string()))?;

    Ok((zstd_data, uncompressed_len))
}

#[inline]
fn push_u32(out: &mut Vec<u8>, v: u32) {
    out.extend_from_slice(&v.to_le_bytes());
}

#[inline]
fn push_u64(out: &mut Vec<u8>, v: u64) {
    out.extend_from_slice(&v.to_le_bytes());
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn make_solid_level(face_size: u32, r: f32, g: f32, b: f32) -> CubemapLevel {
        let n = (face_size as usize) * (face_size as usize) * 3;
        let face: Vec<f32> = (0..n)
            .map(|i| match i % 3 {
                0 => r,
                1 => g,
                _ => b,
            })
            .collect();
        CubemapLevel {
            face_pixels: std::array::from_fn(|_| face.clone()),
            face_size,
        }
    }

    #[test]
    fn write_single_level_cubemap_produces_valid_header() {
        let levels = vec![make_solid_level(4, 1.0, 0.5, 0.0)];
        let meta = WriterMetadata {
            writer: "ibl-baker ktx2_writer test",
        };
        let bytes = write_bc6h_cubemap_ktx2(&levels, &meta).expect("write should succeed");

        // KTX2 identifier
        assert_eq!(&bytes[..12], &KTX2_IDENTIFIER);

        // vkFormat = 131 (BC6H_UFLOAT_BLOCK)
        let vk_format = u32::from_le_bytes(bytes[12..16].try_into().unwrap());
        assert_eq!(vk_format, 131);

        // typeSize = 1
        let type_size = u32::from_le_bytes(bytes[16..20].try_into().unwrap());
        assert_eq!(type_size, 1);

        // faceCount = 6
        let face_count = u32::from_le_bytes(bytes[36..40].try_into().unwrap());
        assert_eq!(face_count, 6);

        // levelCount = 1
        let level_count = u32::from_le_bytes(bytes[40..44].try_into().unwrap());
        assert_eq!(level_count, 1);

        // supercompressionScheme = 2 (zstd)
        let scheme = u32::from_le_bytes(bytes[44..48].try_into().unwrap());
        assert_eq!(scheme, 2);
    }

    #[test]
    fn write_multi_level_cubemap_level_count_matches() {
        let levels = vec![
            make_solid_level(8, 2.0, 1.0, 0.5),
            make_solid_level(4, 1.0, 0.5, 0.25),
            make_solid_level(2, 0.5, 0.25, 0.1),
            make_solid_level(1, 0.1, 0.05, 0.0),
        ];
        let meta = WriterMetadata {
            writer: "ibl-baker ktx2_writer test",
        };
        let bytes = write_bc6h_cubemap_ktx2(&levels, &meta).expect("write should succeed");

        let level_count = u32::from_le_bytes(bytes[40..44].try_into().unwrap());
        assert_eq!(level_count, 4);

        // pixelWidth == base face size
        let pixel_width = u32::from_le_bytes(bytes[20..24].try_into().unwrap());
        assert_eq!(pixel_width, 8);
    }

    #[test]
    fn validate_rejects_empty_levels() {
        let meta = WriterMetadata { writer: "test" };
        let result = write_bc6h_cubemap_ktx2(&[], &meta);
        assert!(result.is_err());
    }

    #[test]
    fn validate_rejects_wrong_pixel_count() {
        let mut level = make_solid_level(4, 1.0, 0.0, 0.0);
        level.face_pixels[2].pop(); // break one face
        let meta = WriterMetadata { writer: "test" };
        let result = write_bc6h_cubemap_ktx2(&[level], &meta);
        assert!(result.is_err());
    }

    #[test]
    fn level_index_byte_offsets_are_consistent() {
        // Two levels: verify the level 0 byteOffset points past the level 1 data
        // (since smallest = level 1 is stored first in file).
        let levels = vec![
            make_solid_level(8, 1.0, 1.0, 1.0),
            make_solid_level(4, 0.5, 0.5, 0.5),
        ];
        let meta = WriterMetadata { writer: "test" };
        let bytes = write_bc6h_cubemap_ktx2(&levels, &meta).unwrap();

        // Level index starts at byte 80.
        let l0_offset = u64::from_le_bytes(bytes[80..88].try_into().unwrap());
        let l0_compressed_len = u64::from_le_bytes(bytes[88..96].try_into().unwrap());
        let l1_offset = u64::from_le_bytes(bytes[104..112].try_into().unwrap());
        let l1_compressed_len = u64::from_le_bytes(bytes[112..120].try_into().unwrap());

        // Smallest (l1) is stored first, so l1_offset < l0_offset.
        assert!(l1_offset < l0_offset);
        // level 0 data immediately follows level 1 data.
        assert_eq!(l1_offset + l1_compressed_len, l0_offset);
        // The file ends right after level 0 data.
        assert_eq!((l0_offset + l0_compressed_len) as usize, bytes.len());
    }
}

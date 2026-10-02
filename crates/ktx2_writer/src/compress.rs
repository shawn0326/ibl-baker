use half::f16;
use intel_tex_2::{bc6h, RgbaSurface};

use crate::{Ktx2Error, BC6H_UFLOAT_MAX};

const BLOCK_SIZE: usize = 16; // bytes per BC6H 4×4 block
const BLOCK_DIM: u32 = 4; // texels per block edge

/// Expected byte count of the BC6H output for a face of `face_size × face_size` texels.
pub(crate) fn bc6h_level_bytes(face_size: u32) -> usize {
    let blocks = blocks_per_dim(face_size);
    blocks * blocks * BLOCK_SIZE
}

/// Compress a single cubemap face to BC6H block data.
///
/// `pixels` is linear f32 RGB, length = `face_size * face_size * 3`, row-major.
/// Returns raw BC6H block bytes covering the original `face_size × face_size` area.
pub(crate) fn compress_face_bc6h(pixels: &[f32], face_size: u32) -> Result<Vec<u8>, Ktx2Error> {
    // ISPC BC6H encoder requires width and height to be multiples of 4.
    // Pad to the nearest block boundary; extra texels are filled with black (0.0).
    let padded = round_up_to_block(face_size);
    let padded_usize = padded as usize;
    let face_usize = face_size as usize;

    // Build an f16 RGBA image (8 bytes/pixel); alpha is unused but required by the surface type.
    let stride_bytes = padded_usize.saturating_mul(8);
    let mut data: Vec<u8> = vec![0u8; padded_usize.saturating_mul(padded_usize) * 8];

    for y in 0..face_usize {
        for x in 0..face_usize {
            let src = (y * face_usize + x) * 3;
            let dst = (y * padded_usize + x) * 8;

            let r = rgb_to_f16(pixels[src])?;
            let g = rgb_to_f16(pixels[src + 1])?;
            let b = rgb_to_f16(pixels[src + 2])?;
            let a = f16::from_f32(1.0);

            data[dst..dst + 2].copy_from_slice(&r.to_le_bytes());
            data[dst + 2..dst + 4].copy_from_slice(&g.to_le_bytes());
            data[dst + 4..dst + 6].copy_from_slice(&b.to_le_bytes());
            data[dst + 6..dst + 8].copy_from_slice(&a.to_le_bytes());
        }
        // Padded columns remain zeroed (black).
    }

    let surface = RgbaSurface {
        data: &data,
        width: padded,
        height: padded,
        stride: stride_bytes as u32,
    };

    let settings = bc6h::basic_settings();
    let result = bc6h::compress_blocks(&settings, &surface);

    // If the original face was smaller than the padded surface, strip the extra block columns
    // and rows so the caller only gets blocks covering the original texel region.
    if padded == face_size {
        Ok(result)
    } else {
        let orig_bx = blocks_per_dim(face_size);
        let orig_by = orig_bx; // square face
        let pad_bx = (padded / BLOCK_DIM) as usize;

        let mut trimmed = Vec::with_capacity(orig_bx * orig_by * BLOCK_SIZE);
        for row in 0..orig_by {
            let s = row * pad_bx * BLOCK_SIZE;
            trimmed.extend_from_slice(&result[s..s + orig_bx * BLOCK_SIZE]);
        }
        Ok(trimmed)
    }
}

/// Reject invalid components and clamp finite RGB before half-float conversion.
fn rgb_to_f16(value: f32) -> Result<f16, Ktx2Error> {
    if !value.is_finite() {
        return Err(Ktx2Error::InvalidInput(format!(
            "RGB components must be finite, got {value}"
        )));
    }
    Ok(f16::from_f32(value.clamp(0.0, BC6H_UFLOAT_MAX)))
}

/// Number of BC6H blocks (per dimension) needed to cover `size` texels.
#[inline]
fn blocks_per_dim(size: u32) -> usize {
    size.div_ceil(BLOCK_DIM) as usize
}

/// Round `size` up to the nearest multiple of `BLOCK_DIM` (4).
#[inline]
fn round_up_to_block(size: u32) -> u32 {
    (size + BLOCK_DIM - 1) & !(BLOCK_DIM - 1)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rgb_to_f16_clamps_finite_out_of_range_components() {
        let below_max = f32::from_bits(BC6H_UFLOAT_MAX.to_bits() - 1);
        let above_max = f32::from_bits(BC6H_UFLOAT_MAX.to_bits() + 1);
        for value in [
            -f32::MAX,
            -1.0,
            -f32::MIN_POSITIVE,
            0.0,
            below_max,
            BC6H_UFLOAT_MAX,
            above_max,
            f32::MAX,
        ] {
            let actual = rgb_to_f16(value).unwrap();
            assert_eq!(actual, f16::from_f32(value.clamp(0.0, 65504.0)));
            assert!(actual.is_finite(), "value={value}");
            assert!(actual.to_f32() >= 0.0, "value={value}");
        }
        assert_eq!(rgb_to_f16(-1.0).unwrap(), f16::ZERO);
        assert_eq!(rgb_to_f16(f32::MAX).unwrap(), f16::MAX);
    }

    #[test]
    fn rgb_to_f16_preserves_in_range_half_float_bytes() {
        for value in [
            0.0,
            -0.0,
            f32::MIN_POSITIVE,
            0.1,
            1.0,
            255.0,
            4096.0,
            f32::from_bits(BC6H_UFLOAT_MAX.to_bits() - 1),
            BC6H_UFLOAT_MAX,
        ] {
            assert_eq!(
                rgb_to_f16(value).unwrap().to_le_bytes(),
                f16::from_f32(value).to_le_bytes(),
                "value={value}"
            );
        }
    }

    #[test]
    fn compress_rejects_non_finite_rgb_before_encoding() {
        for value in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY] {
            for channel in 0..3 {
                let mut pixels = [0.0; 3];
                pixels[channel] = value;
                assert!(matches!(
                    compress_face_bc6h(&pixels, 1),
                    Err(Ktx2Error::InvalidInput(_))
                ));
            }
        }
    }

    #[test]
    fn bc6h_output_size_exact_block() {
        // 8x8 face -> 2x2 blocks x 16 bytes = 64 bytes
        let pixels = vec![1.0f32; 8 * 8 * 3];
        let result = compress_face_bc6h(&pixels, 8).unwrap();
        assert_eq!(result.len(), 64);
    }

    #[test]
    fn bc6h_output_size_non_block_aligned() {
        // 5x5 face -> ceil(5/4)=2 blocks per dim -> 2x2 x 16 = 64 bytes
        let pixels = vec![0.5f32; 5 * 5 * 3];
        let result = compress_face_bc6h(&pixels, 5).unwrap();
        assert_eq!(result.len(), 64);
    }

    #[test]
    fn bc6h_output_size_1x1() {
        // 1x1 face -> 1x1 block -> 16 bytes
        let pixels = vec![0.0f32, 1.0, 0.5];
        let result = compress_face_bc6h(&pixels, 1).unwrap();
        assert_eq!(result.len(), 16);
    }

    #[test]
    fn bc6h_level_bytes_matches_compress_output() {
        for size in [1u32, 2, 3, 4, 7, 8, 16] {
            let pixels = vec![0.8f32; (size * size * 3) as usize];
            let expected = bc6h_level_bytes(size);
            let actual = compress_face_bc6h(&pixels, size).unwrap().len();
            assert_eq!(actual, expected, "size={size}");
        }
    }
}

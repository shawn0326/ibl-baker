use std::f32::consts::{PI, TAU};

use glam::{Vec2, Vec3};

use crate::source_image::{blur_image, encode_png_image, sample_latlong, SourceImage};
use crate::{
    BakeOptions, BakeQuality, ChunkData, ChunkEntry, ChunkRecord, EncodingKind, Face, IblError,
};

const DEFAULT_SPECULAR_SAMPLES_LOW: u32 = 256;
const DEFAULT_SPECULAR_SAMPLES_MEDIUM: u32 = 512;
const DEFAULT_SPECULAR_SAMPLES_HIGH: u32 = 1024;
const DEFAULT_BRDF_SAMPLES_LOW: u32 = 32;
const DEFAULT_BRDF_SAMPLES_MEDIUM: u32 = 64;
const DEFAULT_BRDF_SAMPLES_HIGH: u32 = 128;

#[derive(Debug, Clone, Copy, PartialEq)]
struct BrdfLutSample {
    scale: f32,
    bias: f32,
}

pub(crate) fn build_specular_chunk_entries(
    source: &SourceImage,
    options: &BakeOptions,
    mip_count: u32,
) -> Result<Vec<ChunkEntry>, IblError> {
    let base_faces = render_cubemap_faces(source, options.cube_size, options.rotation_degrees);
    let source_mips = build_source_mip_chain(source);
    let mip_chain = build_specular_mip_chain(&source_mips, &base_faces, options, mip_count);
    encode_cubemap_mips(&mip_chain, options.output_encoding)
}

pub(crate) fn build_irradiance_chunk_entries(
    source: &SourceImage,
    options: &BakeOptions,
) -> Result<Vec<ChunkEntry>, IblError> {
    let mut faces = render_cubemap_faces(source, options.irradiance_size, options.rotation_degrees);
    let passes = match options.quality {
        BakeQuality::Low => 2,
        BakeQuality::Medium => 4,
        BakeQuality::High => 6,
    };
    for face in &mut faces {
        *face = blur_image(face, 1, passes);
    }

    encode_cubemap_mips(&[faces], options.output_encoding)
}

pub(crate) fn build_brdf_lut_chunk_entries(
    size: u32,
    options: &BakeOptions,
) -> Result<Vec<ChunkEntry>, IblError> {
    let image = build_brdf_lut(size, options);
    let bytes = encode_png_image(&image, EncodingKind::Linear)?;

    Ok(vec![ChunkEntry {
        record: ChunkRecord {
            mip_level: 0,
            face: None,
            byte_offset: 0,
            byte_length: bytes.len() as u64,
            width: image.width,
            height: image.height,
        },
        chunk: ChunkData {
            mip_level: 0,
            face: None,
            bytes,
        },
    }])
}

pub(crate) fn cubemap_direction(face: Face, uv: Vec2) -> Vec3 {
    match face {
        Face::PositiveX => Vec3::new(1.0, -uv.y, -uv.x),
        Face::NegativeX => Vec3::new(-1.0, -uv.y, uv.x),
        Face::PositiveY => Vec3::new(uv.x, 1.0, uv.y),
        Face::NegativeY => Vec3::new(uv.x, -1.0, -uv.y),
        Face::PositiveZ => Vec3::new(uv.x, -uv.y, 1.0),
        Face::NegativeZ => Vec3::new(-uv.x, -uv.y, -1.0),
    }
    .normalize_or_zero()
}

fn render_cubemap_faces(
    source: &SourceImage,
    size: u32,
    rotation_degrees: f32,
) -> Vec<SourceImage> {
    Face::all()
        .iter()
        .copied()
        .map(|face| render_cubemap_face(source, face, size, rotation_degrees))
        .collect()
}

fn render_cubemap_face(
    source: &SourceImage,
    face: Face,
    size: u32,
    rotation_degrees: f32,
) -> SourceImage {
    let mut image = SourceImage::new(size, size);

    for y in 0..size {
        for x in 0..size {
            let uv = Vec2::new(
                (2.0 * ((x as f32 + 0.5) / size as f32)) - 1.0,
                (2.0 * ((y as f32 + 0.5) / size as f32)) - 1.0,
            );
            let direction = cubemap_direction(face, uv);
            image.set(x, y, sample_latlong(source, direction, rotation_degrees));
        }
    }

    image
}

fn build_specular_mip_chain(
    source_mips: &[SourceImage],
    base_faces: &[SourceImage],
    options: &BakeOptions,
    mip_count: u32,
) -> Vec<Vec<SourceImage>> {
    let mut chain = Vec::with_capacity(mip_count as usize);
    chain.push(base_faces.to_vec());
    let base_face_size = base_faces[0].width.max(1);

    for mip_level in 1..mip_count {
        let roughness = mip_level as f32 / (mip_count.saturating_sub(1).max(1) as f32);
        let face_size = (base_face_size >> mip_level).max(1);
        let sample_count =
            effective_specular_sample_count(options, roughness, face_size, base_face_size);
        let faces = render_prefiltered_cubemap_faces(
            source_mips,
            face_size,
            options.rotation_degrees,
            roughness,
            sample_count,
        );

        chain.push(faces);
    }

    chain
}

fn render_prefiltered_cubemap_faces(
    source_mips: &[SourceImage],
    size: u32,
    rotation_degrees: f32,
    roughness: f32,
    sample_count: u32,
) -> Vec<SourceImage> {
    Face::all()
        .iter()
        .copied()
        .map(|face| {
            let mut image = SourceImage::new(size, size);
            for y in 0..size {
                for x in 0..size {
                    let uv = Vec2::new(
                        (2.0 * ((x as f32 + 0.5) / size as f32)) - 1.0,
                        (2.0 * ((y as f32 + 0.5) / size as f32)) - 1.0,
                    );
                    let reflection = cubemap_direction(face, uv);
                    image.set(
                        x,
                        y,
                        prefilter_environment(
                            source_mips,
                            reflection,
                            rotation_degrees,
                            roughness,
                            sample_count,
                        ),
                    );
                }
            }
            image
        })
        .collect()
}

fn build_source_mip_chain(source: &SourceImage) -> Vec<SourceImage> {
    let mut levels = vec![source.clone()];
    loop {
        let prev = levels.last().unwrap();
        if prev.width <= 1 && prev.height <= 1 {
            break;
        }
        levels.push(downsample_half(prev));
    }
    levels
}

fn downsample_half(image: &SourceImage) -> SourceImage {
    let new_width = (image.width / 2).max(1);
    let new_height = (image.height / 2).max(1);
    let mut result = SourceImage::new(new_width, new_height);
    for y in 0..new_height {
        for x in 0..new_width {
            let sx = x * 2;
            let sy = y * 2;
            let sx1 = (sx + 1).min(image.width - 1);
            let sy1 = (sy + 1).min(image.height - 1);
            let avg = (image.get(sx, sy)
                + image.get(sx1, sy)
                + image.get(sx, sy1)
                + image.get(sx1, sy1))
                * 0.25;
            result.set(x, y, avg);
        }
    }
    result
}

fn sample_source_lod(
    source_mips: &[SourceImage],
    direction: Vec3,
    rotation_degrees: f32,
    lod: f32,
) -> Vec3 {
    let max_level = (source_mips.len() - 1) as f32;
    let lod = lod.clamp(0.0, max_level);
    let level_low = lod.floor() as usize;
    let level_high = (level_low + 1).min(source_mips.len() - 1);
    let fract = lod - lod.floor();

    let sample_low = sample_latlong(&source_mips[level_low], direction, rotation_degrees);
    if level_low == level_high || fract < 1e-4 {
        return sample_low;
    }
    let sample_high = sample_latlong(&source_mips[level_high], direction, rotation_degrees);
    sample_low.lerp(sample_high, fract)
}

fn ggx_distribution(ndoth: f32, roughness: f32) -> f32 {
    let alpha = roughness * roughness;
    let alpha2 = alpha * alpha;
    let denom = ndoth * ndoth * (alpha2 - 1.0) + 1.0;
    alpha2 / (PI * denom * denom)
}

fn prefilter_environment(
    source_mips: &[SourceImage],
    reflection: Vec3,
    rotation_degrees: f32,
    roughness: f32,
    sample_count: u32,
) -> Vec3 {
    if roughness <= 1.0e-4 || sample_count <= 1 {
        return sample_source_lod(source_mips, reflection, rotation_degrees, 0.0);
    }

    let normal = reflection.normalize_or_zero();
    let view = normal;
    let mut accumulated = Vec3::ZERO;
    let mut total_weight = 0.0;

    let source_texel_count = source_mips[0].width as f32 * source_mips[0].height as f32;
    let omega_p = 4.0 * PI / source_texel_count;
    let max_lod = (source_mips.len() - 1) as f32;

    for sample_index in 0..sample_count {
        let xi = hammersley(sample_index, sample_count);
        let half_vector = importance_sample_ggx(xi, roughness.max(1.0e-4), normal);
        let light = (2.0 * view.dot(half_vector) * half_vector - view).normalize_or_zero();
        let ndotl = normal.dot(light).max(0.0);

        if ndotl > 0.0 {
            let ndoth = normal.dot(half_vector).max(0.0);
            let vdoth = view.dot(half_vector).max(0.0);

            let d = ggx_distribution(ndoth, roughness);
            let pdf = (d * ndoth / (4.0 * vdoth.max(1e-4))).max(1e-7);
            let omega_s = 1.0 / (sample_count as f32 * pdf);
            let lod = (0.5 * (omega_s / omega_p).log2() + 1.0).clamp(0.0, max_lod);

            accumulated += sample_source_lod(source_mips, light, rotation_degrees, lod) * ndotl;
            total_weight += ndotl;
        }
    }

    if total_weight > 0.0 {
        accumulated / total_weight
    } else {
        sample_source_lod(source_mips, normal, rotation_degrees, 0.0)
    }
}

fn effective_specular_sample_count(
    options: &BakeOptions,
    roughness: f32,
    face_size: u32,
    base_face_size: u32,
) -> u32 {
    let quality_cap = match options.quality {
        BakeQuality::Low => DEFAULT_SPECULAR_SAMPLES_LOW,
        BakeQuality::Medium => DEFAULT_SPECULAR_SAMPLES_MEDIUM,
        BakeQuality::High => DEFAULT_SPECULAR_SAMPLES_HIGH,
    };

    let capped_max = options.sample_count.max(1).min(quality_cap);
    let size_ratio = (base_face_size.max(1) as f32 / face_size.max(1) as f32).max(1.0);
    let size_boost = size_ratio.sqrt().round().max(1.0) as u32;
    let boosted_max = capped_max
        .saturating_mul(size_boost)
        .min(options.sample_count.max(1));
    let min_budget = (capped_max / 4).max(8);
    let roughness_weight = roughness.clamp(0.0, 1.0).powi(2);
    let scaled = min_budget as f32 + (boosted_max - min_budget) as f32 * roughness_weight;
    scaled.round().max(1.0) as u32
}

fn encode_cubemap_mips(
    mip_chain: &[Vec<SourceImage>],
    encoding: EncodingKind,
) -> Result<Vec<ChunkEntry>, IblError> {
    let mut entries = Vec::new();
    for (mip_level, faces) in mip_chain.iter().enumerate() {
        for face in Face::all() {
            let image = &faces[face.index()];
            let bytes = encode_png_image(image, encoding)?;
            entries.push(ChunkEntry {
                record: ChunkRecord {
                    mip_level: mip_level as u32,
                    face: Some(*face),
                    byte_offset: 0,
                    byte_length: bytes.len() as u64,
                    width: image.width,
                    height: image.height,
                },
                chunk: ChunkData {
                    mip_level: mip_level as u32,
                    face: Some(*face),
                    bytes,
                },
            });
        }
    }
    Ok(entries)
}

fn build_brdf_lut(size: u32, options: &BakeOptions) -> SourceImage {
    let mut image = SourceImage::new(size, size);
    let sample_count = effective_brdf_sample_count(options);

    for y in 0..size {
        let roughness = ((y as f32) + 0.5) / size as f32;
        for x in 0..size {
            let ndotv = (((x as f32) + 0.5) / size as f32).clamp(0.0, 1.0);
            let sample = integrate_brdf(ndotv, roughness, sample_count);
            image.set(x, y, Vec3::new(sample.scale, sample.bias, 0.0));
        }
    }

    image
}

fn effective_brdf_sample_count(options: &BakeOptions) -> u32 {
    let cap = match options.quality {
        BakeQuality::Low => DEFAULT_BRDF_SAMPLES_LOW,
        BakeQuality::Medium => DEFAULT_BRDF_SAMPLES_MEDIUM,
        BakeQuality::High => DEFAULT_BRDF_SAMPLES_HIGH,
    };
    options.sample_count.max(1).min(cap)
}

fn integrate_brdf(ndotv: f32, roughness: f32, sample_count: u32) -> BrdfLutSample {
    let v = Vec3::new(
        (1.0 - ndotv * ndotv).max(0.0).sqrt(),
        0.0,
        ndotv.max(1.0e-4),
    );
    let n = Vec3::Z;
    let mut scale = 0.0;
    let mut bias = 0.0;

    for sample_index in 0..sample_count {
        let xi = hammersley(sample_index, sample_count);
        let h = importance_sample_ggx(xi, roughness.max(1.0e-4), n);
        let l = (2.0 * v.dot(h) * h - v).normalize_or_zero();

        let ndotl = l.z.max(0.0);
        let ndoth = h.z.max(0.0);
        let vdoth = v.dot(h).max(0.0);
        if ndotl > 0.0 && ndoth > 0.0 {
            let geometry = geometry_smith(ndotv.max(1.0e-4), ndotl, roughness);
            let visibility = (geometry * vdoth) / (ndoth * ndotv.max(1.0e-4));
            let fresnel = (1.0 - vdoth).powi(5);
            scale += (1.0 - fresnel) * visibility;
            bias += fresnel * visibility;
        }
    }

    BrdfLutSample {
        scale: scale / sample_count as f32,
        bias: bias / sample_count as f32,
    }
}

fn importance_sample_ggx(xi: Vec2, roughness: f32, normal: Vec3) -> Vec3 {
    let alpha = roughness * roughness;
    let phi = TAU * xi.x;
    let cos_theta = ((1.0 - xi.y) / (1.0 + (alpha * alpha - 1.0) * xi.y)).sqrt();
    let sin_theta = (1.0 - cos_theta * cos_theta).max(0.0).sqrt();

    let h_tangent = Vec3::new(phi.cos() * sin_theta, phi.sin() * sin_theta, cos_theta);
    tangent_to_world(normal, h_tangent).normalize_or_zero()
}

fn tangent_to_world(normal: Vec3, tangent_space: Vec3) -> Vec3 {
    let up = if normal.z.abs() < 0.999 {
        Vec3::Z
    } else {
        Vec3::X
    };
    let tangent = up.cross(normal).normalize_or_zero();
    let bitangent = normal.cross(tangent);
    tangent * tangent_space.x + bitangent * tangent_space.y + normal * tangent_space.z
}

fn geometry_smith(ndotv: f32, ndotl: f32, roughness: f32) -> f32 {
    geometry_schlick_ggx(ndotv, roughness) * geometry_schlick_ggx(ndotl, roughness)
}

fn geometry_schlick_ggx(ndotv: f32, roughness: f32) -> f32 {
    let k = (roughness * roughness) / 2.0;
    ndotv / (ndotv * (1.0 - k) + k)
}

fn hammersley(index: u32, sample_count: u32) -> Vec2 {
    Vec2::new(
        index as f32 / sample_count as f32,
        radical_inverse_vdc(index),
    )
}

fn radical_inverse_vdc(mut bits: u32) -> f32 {
    bits = bits.rotate_right(16);
    bits = ((bits & 0x5555_5555) << 1) | ((bits & 0xAAAA_AAAA) >> 1);
    bits = ((bits & 0x3333_3333) << 2) | ((bits & 0xCCCC_CCCC) >> 2);
    bits = ((bits & 0x0F0F_0F0F) << 4) | ((bits & 0xF0F0_F0F0) >> 4);
    bits = ((bits & 0x00FF_00FF) << 8) | ((bits & 0xFF00_FF00) >> 8);
    bits as f32 * 2.328_306_4e-10
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hotspot_latlong(width: u32, height: u32) -> SourceImage {
        let mut image = SourceImage::new(width, height);
        for y in 0..height {
            for x in 0..width {
                let u = x as f32 / width.max(1) as f32;
                let v = y as f32 / height.max(1) as f32;
                let hotspot = if (u - 0.5).abs() < 0.06 && (v - 0.5).abs() < 0.12 {
                    12.0
                } else {
                    0.1
                };
                image.set(x, y, Vec3::splat(hotspot));
            }
        }
        image
    }

    fn decode_png_rgba(bytes: &[u8]) -> image::RgbaImage {
        image::load_from_memory(bytes)
            .expect("png should decode")
            .into_rgba8()
    }

    #[test]
    fn specular_prefilter_uses_more_samples_for_rougher_mips() {
        let options = BakeOptions {
            sample_count: 256,
            quality: BakeQuality::High,
            ..BakeOptions::default()
        };

        let smooth = effective_specular_sample_count(&options, 0.1, 128, 128);
        let rough = effective_specular_sample_count(&options, 1.0, 128, 128);

        assert!(rough > smooth);
        assert!(rough <= 256);
    }

    #[test]
    fn specular_prefilter_boosts_samples_for_smaller_high_roughness_mips() {
        let options = BakeOptions {
            sample_count: 1024,
            quality: BakeQuality::Medium,
            ..BakeOptions::default()
        };

        let large_face = effective_specular_sample_count(&options, 1.0, 256, 256);
        let tiny_face = effective_specular_sample_count(&options, 1.0, 4, 256);

        assert!(tiny_face > large_face);
        assert_eq!(large_face, 512);
        assert_eq!(tiny_face, 1024);
    }

    #[test]
    fn specular_prefilter_produces_distinct_mip_payloads() {
        let source = hotspot_latlong(64, 32);
        let options = BakeOptions {
            cube_size: 8,
            sample_count: 128,
            quality: BakeQuality::Medium,
            ..BakeOptions::default()
        };

        let entries =
            build_specular_chunk_entries(&source, &options, 4).expect("specular should bake");
        let mip0 = entries
            .iter()
            .find(|entry| entry.record.mip_level == 0 && entry.record.face == Some(Face::PositiveZ))
            .expect("mip 0 face should exist");
        let mip3 = entries
            .iter()
            .find(|entry| entry.record.mip_level == 3 && entry.record.face == Some(Face::PositiveZ))
            .expect("mip 3 face should exist");

        let mip0_image = decode_png_rgba(&mip0.chunk.bytes);
        let mip3_image = decode_png_rgba(&mip3.chunk.bytes);

        assert_eq!(mip0_image.width(), 8);
        assert_eq!(mip3_image.width(), 1);
        assert_ne!(mip0.chunk.bytes, mip3.chunk.bytes);
    }
}

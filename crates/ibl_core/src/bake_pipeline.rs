use std::array;
use std::collections::BTreeMap;
use std::f32::consts::{PI, TAU};

use glam::{Vec2, Vec3};
use rayon::prelude::*;

use crate::source_image::{encode_png_image, sample_environment, EnvironmentSource, Rotation, SourceImage};
use crate::{
    BakeOptions, BakeQuality, ChunkData, ChunkEntry, ChunkRecord, EncodingKind, Face, IblError,
};

const DEFAULT_SPECULAR_SAMPLES_LOW: u32 = 256;
const DEFAULT_SPECULAR_SAMPLES_MEDIUM: u32 = 512;
const DEFAULT_SPECULAR_SAMPLES_HIGH: u32 = 1024;
const DEFAULT_IRRADIANCE_SAMPLES_LOW: u32 = 128;
const DEFAULT_IRRADIANCE_SAMPLES_MEDIUM: u32 = 256;
const DEFAULT_IRRADIANCE_SAMPLES_HIGH: u32 = 512;
const DEFAULT_BRDF_SAMPLES_LOW: u32 = 32;
const DEFAULT_BRDF_SAMPLES_MEDIUM: u32 = 64;
const DEFAULT_BRDF_SAMPLES_HIGH: u32 = 128;
const MIN_ROUGHNESS: f32 = 1.0e-4;
const MIN_PDF: f32 = 1.0e-7;

type CubemapFaces = [SourceImage; 6];
type DirectionCache = [Vec<Vec3>; 6];

#[derive(Debug, Clone, Copy, PartialEq)]
enum Distribution {
    Lambertian,
    Ggx,
}

#[derive(Debug, Clone, Copy, PartialEq)]
struct BrdfLutSample {
    scale: f32,
    bias: f32,
}

#[derive(Debug, Clone, Copy, PartialEq)]
struct KernelSample {
    local_direction: Vec3,
    pdf: f32,
}

#[derive(Default)]
struct SampleKernelCache {
    ggx: BTreeMap<(u32, u32), Vec<KernelSample>>,
    lambertian: BTreeMap<u32, Vec<KernelSample>>,
}

impl SampleKernelCache {
    fn ensure(&mut self, distribution: Distribution, roughness: f32, sample_count: u32) {
        match distribution {
            Distribution::Ggx => {
                let key = (roughness.to_bits(), sample_count);
                self.ggx
                    .entry(key)
                    .or_insert_with(|| build_ggx_kernel(roughness, sample_count));
            }
            Distribution::Lambertian => {
                self.lambertian
                    .entry(sample_count)
                    .or_insert_with(|| build_lambertian_kernel(sample_count));
            }
        }
    }

    fn kernel(
        &self,
        distribution: Distribution,
        roughness: f32,
        sample_count: u32,
    ) -> &[KernelSample] {
        match distribution {
            Distribution::Ggx => self
                .ggx
                .get(&(roughness.to_bits(), sample_count))
                .expect("GGX kernel should be cached"),
            Distribution::Lambertian => self
                .lambertian
                .get(&sample_count)
                .expect("Lambertian kernel should be cached"),
        }
    }
}

struct BakeContext<'a> {
    base_cubemap: CubemapFaces,
    cubemap_mips: Vec<CubemapFaces>,
    direction_caches: BTreeMap<u32, DirectionCache>,
    kernel_cache: SampleKernelCache,
    _source: &'a EnvironmentSource,
}

impl<'a> BakeContext<'a> {
    fn new(source: &'a EnvironmentSource, base_size: u32, rotation_degrees: f32) -> Self {
        let rotation = Rotation::from_degrees(rotation_degrees);
        let base_directions = build_direction_cache(base_size);
        let base_cubemap = render_cubemap_faces(source, rotation, &base_directions, base_size);
        let cubemap_mips = build_cubemap_mip_chain(&base_cubemap);

        let mut direction_caches = BTreeMap::new();
        direction_caches.insert(base_size, base_directions);

        Self {
            base_cubemap,
            cubemap_mips,
            direction_caches,
            kernel_cache: SampleKernelCache::default(),
            _source: source,
        }
    }

    fn ensure_direction_cache(&mut self, size: u32) {
        self.direction_caches
            .entry(size)
            .or_insert_with(|| build_direction_cache(size));
    }

    fn ensure_kernel(&mut self, distribution: Distribution, roughness: f32, sample_count: u32) {
        self.kernel_cache
            .ensure(distribution, roughness, sample_count.max(1));
    }
}

pub(crate) fn build_specular_chunk_entries(
    source: &EnvironmentSource,
    options: &BakeOptions,
    mip_count: u32,
) -> Result<Vec<ChunkEntry>, IblError> {
    let mip_chain = build_specular_raw(source, options, mip_count);
    encode_cubemap_mips(&mip_chain, options.output_encoding)
}

pub(crate) fn build_irradiance_chunk_entries(
    source: &EnvironmentSource,
    options: &BakeOptions,
) -> Result<Vec<ChunkEntry>, IblError> {
    let faces = build_irradiance_raw(source, options);
    encode_cubemap_mips(&[faces], options.output_encoding)
}

pub(crate) fn build_specular_raw(
    source: &EnvironmentSource,
    options: &BakeOptions,
    mip_count: u32,
) -> Vec<CubemapFaces> {
    let mut context = BakeContext::new(source, options.cube_size, options.rotation_degrees);
    build_specular_mip_chain(&mut context, options, mip_count)
}

pub(crate) fn build_irradiance_raw(
    source: &EnvironmentSource,
    options: &BakeOptions,
) -> CubemapFaces {
    let mut context = BakeContext::new(source, options.irradiance_size, options.rotation_degrees);
    render_filtered_faces(
        &mut context,
        options.irradiance_size,
        Distribution::Lambertian,
        1.0,
        effective_irradiance_sample_count(options),
    )
}

pub(crate) fn encode_mip_chain_to_ktx2(
    mip_chain: &[CubemapFaces],
) -> Result<Vec<u8>, IblError> {
    use ktx2_writer::{CubemapLevel, WriterMetadata, write_bc6h_cubemap_ktx2};

    let levels: Vec<CubemapLevel> = mip_chain
        .iter()
        .map(|faces| {
            let face_size = faces[0].width;
            let face_pixels = std::array::from_fn(|i| {
                faces[i]
                    .pixels
                    .iter()
                    .flat_map(|v| [v.x, v.y, v.z])
                    .collect()
            });
            CubemapLevel {
                face_pixels,
                face_size,
            }
        })
        .collect();

    let meta = WriterMetadata {
        writer: concat!("ibl-baker v", env!("CARGO_PKG_VERSION")),
    };

    write_bc6h_cubemap_ktx2(&levels, &meta).map_err(|e| IblError::InvalidInput(e.to_string()))
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

fn build_specular_mip_chain(
    context: &mut BakeContext<'_>,
    options: &BakeOptions,
    mip_count: u32,
) -> Vec<CubemapFaces> {
    let mut chain = Vec::with_capacity(mip_count as usize);
    chain.push(context.base_cubemap.clone());
    let base_face_size = context.base_cubemap[0].width.max(1);

    for mip_level in 1..mip_count {
        let roughness = mip_level as f32 / (mip_count.saturating_sub(1).max(1) as f32);
        let face_size = (base_face_size >> mip_level).max(1);
        let sample_count =
            effective_specular_sample_count(options, roughness, face_size, base_face_size);
        let faces = render_filtered_faces(
            context,
            face_size,
            Distribution::Ggx,
            roughness,
            sample_count,
        );
        chain.push(faces);
    }

    chain
}

fn build_cubemap_mip_chain(base_faces: &CubemapFaces) -> Vec<CubemapFaces> {
    let mut levels = vec![base_faces.clone()];
    loop {
        let prev = levels.last().expect("base cubemap mip should exist");
        if prev[0].width <= 1 && prev[0].height <= 1 {
            break;
        }
        levels.push(array::from_fn(|index| downsample_half(&prev[index])));
    }
    levels
}

fn build_direction_cache(size: u32) -> DirectionCache {
    array::from_fn(|face_index| {
        let face = Face::all()[face_index];
        let mut directions = Vec::with_capacity((size as usize) * (size as usize));
        for y in 0..size {
            for x in 0..size {
                let uv = Vec2::new(
                    (2.0 * ((x as f32 + 0.5) / size as f32)) - 1.0,
                    (2.0 * ((y as f32 + 0.5) / size as f32)) - 1.0,
                );
                directions.push(cubemap_direction(face, uv));
            }
        }
        directions
    })
}

fn render_cubemap_faces(
    source: &EnvironmentSource,
    rotation: Rotation,
    direction_cache: &DirectionCache,
    size: u32,
) -> CubemapFaces {
    let faces = Face::all()
        .par_iter()
        .copied()
        .map(|face| render_cubemap_face(source, rotation, &direction_cache[face.index()], size))
        .collect::<Vec<_>>();
    vec_into_cubemap_faces(faces)
}

fn render_cubemap_face(
    source: &EnvironmentSource,
    rotation: Rotation,
    directions: &[Vec3],
    size: u32,
) -> SourceImage {
    let pixels = directions
        .iter()
        .map(|direction| sample_environment(source, *direction, rotation))
        .collect();
    SourceImage::from_pixels(size, size, pixels)
}

fn render_filtered_faces(
    context: &mut BakeContext<'_>,
    size: u32,
    distribution: Distribution,
    roughness: f32,
    sample_count: u32,
) -> CubemapFaces {
    context.ensure_direction_cache(size);
    context.ensure_kernel(distribution, roughness, sample_count);

    let directions = context
        .direction_caches
        .get(&size)
        .expect("direction cache should exist");
    let kernel = context
        .kernel_cache
        .kernel(distribution, roughness, sample_count.max(1));
    let base_width = context.base_cubemap[0].width.max(1);

    let faces = Face::all()
        .par_iter()
        .copied()
        .map(|face| {
            render_filtered_face(
                &context.cubemap_mips,
                &directions[face.index()],
                size,
                kernel,
                distribution,
                roughness,
                base_width,
            )
        })
        .collect::<Vec<_>>();

    vec_into_cubemap_faces(faces)
}

fn render_filtered_face(
    cubemap_mips: &[CubemapFaces],
    directions: &[Vec3],
    size: u32,
    kernel: &[KernelSample],
    distribution: Distribution,
    roughness: f32,
    base_width: u32,
) -> SourceImage {
    let pixels = directions
        .iter()
        .map(|direction| {
            filter_direction(
                cubemap_mips,
                *direction,
                kernel,
                distribution,
                roughness,
                base_width,
            )
        })
        .collect();
    SourceImage::from_pixels(size, size, pixels)
}

fn filter_direction(
    cubemap_mips: &[CubemapFaces],
    direction: Vec3,
    kernel: &[KernelSample],
    distribution: Distribution,
    roughness: f32,
    base_width: u32,
) -> Vec3 {
    let normal = direction.normalize_or_zero();
    if matches!(distribution, Distribution::Ggx)
        && (roughness <= MIN_ROUGHNESS || kernel.len() <= 1)
    {
        return sample_cubemap_lod(cubemap_mips, normal, 0.0);
    }

    let tbn = generate_tbn(normal);
    let sample_count = kernel.len() as u32;

    match distribution {
        Distribution::Lambertian => {
            let mut accumulated = Vec3::ZERO;
            for sample in kernel {
                let light = (tbn * sample.local_direction).normalize_or_zero();
                let lod = compute_cubemap_lod(sample.pdf, sample_count, base_width, cubemap_mips);
                accumulated += sample_cubemap_lod(cubemap_mips, light, lod);
            }

            if kernel.is_empty() {
                sample_cubemap_lod(cubemap_mips, normal, 0.0)
            } else {
                accumulated / kernel.len() as f32
            }
        }
        Distribution::Ggx => {
            let view = normal;
            let mut accumulated = Vec3::ZERO;
            let mut total_weight = 0.0;

            for sample in kernel {
                let half_vector = (tbn * sample.local_direction).normalize_or_zero();
                let light = (2.0 * view.dot(half_vector) * half_vector - view).normalize_or_zero();
                let ndotl = normal.dot(light).max(0.0);

                if ndotl > 0.0 {
                    let lod =
                        compute_cubemap_lod(sample.pdf, sample_count, base_width, cubemap_mips);
                    accumulated += sample_cubemap_lod(cubemap_mips, light, lod) * ndotl;
                    total_weight += ndotl;
                }
            }

            if total_weight > 0.0 {
                accumulated / total_weight
            } else {
                sample_cubemap_lod(cubemap_mips, normal, 0.0)
            }
        }
    }
}

fn compute_cubemap_lod(
    pdf: f32,
    sample_count: u32,
    base_width: u32,
    cubemap_mips: &[CubemapFaces],
) -> f32 {
    let max_lod = (cubemap_mips.len().saturating_sub(1)) as f32;
    if sample_count <= 1 {
        return 0.0;
    }

    let texel_ratio =
        (6.0 * (base_width.max(1) as f32).powi(2)) / ((sample_count as f32) * pdf.max(MIN_PDF));
    (0.5 * texel_ratio.max(1.0).log2()).clamp(0.0, max_lod)
}

fn sample_cubemap_lod(cubemap_mips: &[CubemapFaces], direction: Vec3, lod: f32) -> Vec3 {
    let max_level = (cubemap_mips.len() - 1) as f32;
    let lod = lod.clamp(0.0, max_level);
    let level_low = lod.floor() as usize;
    let level_high = (level_low + 1).min(cubemap_mips.len() - 1);
    let fract = lod - lod.floor();

    let sample_low = sample_cubemap(&cubemap_mips[level_low], direction);
    if level_low == level_high || fract < 1.0e-4 {
        return sample_low;
    }

    let sample_high = sample_cubemap(&cubemap_mips[level_high], direction);
    sample_low.lerp(sample_high, fract)
}

fn sample_cubemap(faces: &CubemapFaces, direction: Vec3) -> Vec3 {
    let (face, uv) = direction_to_face_uv(direction.normalize_or_zero());
    faces[face.index()].sample_bilinear(uv, false)
}

fn direction_to_face_uv(direction: Vec3) -> (Face, Vec2) {
    let abs = direction.abs();
    let (face, u, v, major_axis) = if abs.x >= abs.y && abs.x >= abs.z {
        if direction.x >= 0.0 {
            (Face::PositiveX, -direction.z, -direction.y, abs.x)
        } else {
            (Face::NegativeX, direction.z, -direction.y, abs.x)
        }
    } else if abs.y >= abs.x && abs.y >= abs.z {
        if direction.y >= 0.0 {
            (Face::PositiveY, direction.x, direction.z, abs.y)
        } else {
            (Face::NegativeY, direction.x, -direction.z, abs.y)
        }
    } else if direction.z >= 0.0 {
        (Face::PositiveZ, direction.x, -direction.y, abs.z)
    } else {
        (Face::NegativeZ, -direction.x, -direction.y, abs.z)
    };

    let major_axis = major_axis.max(1.0e-8);
    let uv = Vec2::new(0.5 * (u / major_axis + 1.0), 0.5 * (v / major_axis + 1.0));
    (face, uv)
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
            let avg =
                (image.get(sx, sy) + image.get(sx1, sy) + image.get(sx, sy1) + image.get(sx1, sy1))
                    * 0.25;
            result.set(x, y, avg);
        }
    }
    result
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

fn effective_irradiance_sample_count(options: &BakeOptions) -> u32 {
    let cap = match options.quality {
        BakeQuality::Low => DEFAULT_IRRADIANCE_SAMPLES_LOW,
        BakeQuality::Medium => DEFAULT_IRRADIANCE_SAMPLES_MEDIUM,
        BakeQuality::High => DEFAULT_IRRADIANCE_SAMPLES_HIGH,
    };
    options.sample_count.max(1).min(cap)
}

fn encode_cubemap_mips(
    mip_chain: &[CubemapFaces],
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
    let sample_count = effective_brdf_sample_count(options);
    let mut kernel_cache = SampleKernelCache::default();
    for y in 0..size {
        let roughness = ((y as f32) + 0.5) / size as f32;
        kernel_cache.ensure(Distribution::Ggx, roughness, sample_count);
    }

    let rows = (0..size)
        .into_par_iter()
        .map(|y| {
            let roughness = ((y as f32) + 0.5) / size as f32;
            let kernel = kernel_cache.kernel(Distribution::Ggx, roughness, sample_count);
            (0..size)
                .map(|x| {
                    let ndotv = (((x as f32) + 0.5) / size as f32).clamp(0.0, 1.0);
                    let sample = integrate_brdf(ndotv, roughness, kernel);
                    Vec3::new(sample.scale, sample.bias, 0.0)
                })
                .collect::<Vec<_>>()
        })
        .collect::<Vec<_>>();

    let pixels = rows.into_iter().flatten().collect();
    SourceImage::from_pixels(size, size, pixels)
}

fn effective_brdf_sample_count(options: &BakeOptions) -> u32 {
    let cap = match options.quality {
        BakeQuality::Low => DEFAULT_BRDF_SAMPLES_LOW,
        BakeQuality::Medium => DEFAULT_BRDF_SAMPLES_MEDIUM,
        BakeQuality::High => DEFAULT_BRDF_SAMPLES_HIGH,
    };
    options.sample_count.max(1).min(cap)
}

fn integrate_brdf(ndotv: f32, roughness: f32, kernel: &[KernelSample]) -> BrdfLutSample {
    let view = Vec3::new(
        (1.0 - ndotv * ndotv).max(0.0).sqrt(),
        0.0,
        ndotv.max(MIN_ROUGHNESS),
    );
    let mut scale = 0.0;
    let mut bias = 0.0;

    for sample in kernel {
        let half_vector = sample.local_direction;
        let light = (2.0 * view.dot(half_vector) * half_vector - view).normalize_or_zero();
        let ndotl = light.z.max(0.0);
        let ndoth = half_vector.z.max(0.0);
        let vdoth = view.dot(half_vector).max(0.0);

        if ndotl > 0.0 {
            let visibility = v_smith_ggx_correlated(ndotv.max(MIN_ROUGHNESS), ndotl, roughness);
            let visibility_pdf = visibility * vdoth * ndotl / ndoth.max(MIN_ROUGHNESS);
            let fresnel = (1.0 - vdoth).powi(5);
            scale += (1.0 - fresnel) * visibility_pdf;
            bias += fresnel * visibility_pdf;
        }
    }

    let normalization = if kernel.is_empty() {
        1.0
    } else {
        4.0 / kernel.len() as f32
    };
    BrdfLutSample {
        scale: scale * normalization,
        bias: bias * normalization,
    }
}

fn build_ggx_kernel(roughness: f32, sample_count: u32) -> Vec<KernelSample> {
    (0..sample_count)
        .map(|sample_index| {
            let xi = hammersley(sample_index, sample_count);
            let alpha = roughness.max(MIN_ROUGHNESS) * roughness.max(MIN_ROUGHNESS);
            let cos_theta = ((1.0 - xi.y) / (1.0 + (alpha * alpha - 1.0) * xi.y))
                .sqrt()
                .clamp(0.0, 1.0);
            let sin_theta = (1.0 - cos_theta * cos_theta).max(0.0).sqrt();
            let phi = TAU * xi.x;
            let local_direction =
                Vec3::new(phi.cos() * sin_theta, phi.sin() * sin_theta, cos_theta)
                    .normalize_or_zero();
            let pdf = (d_ggx(cos_theta, alpha) / 4.0).max(MIN_PDF);

            KernelSample {
                local_direction,
                pdf,
            }
        })
        .collect()
}

fn build_lambertian_kernel(sample_count: u32) -> Vec<KernelSample> {
    (0..sample_count)
        .map(|sample_index| {
            let xi = hammersley(sample_index, sample_count);
            let cos_theta = (1.0 - xi.y).sqrt().clamp(0.0, 1.0);
            let sin_theta = xi.y.sqrt();
            let phi = TAU * xi.x;
            let local_direction =
                Vec3::new(phi.cos() * sin_theta, phi.sin() * sin_theta, cos_theta)
                    .normalize_or_zero();

            KernelSample {
                local_direction,
                pdf: (cos_theta / PI).max(MIN_PDF),
            }
        })
        .collect()
}

fn d_ggx(ndoth: f32, alpha: f32) -> f32 {
    let a = ndoth * alpha;
    let k = alpha / (1.0 - ndoth * ndoth + a * a);
    k * k * (1.0 / PI)
}

fn generate_tbn(normal: Vec3) -> glam::Mat3 {
    let mut bitangent = Vec3::Y;
    let ndot_up = normal.dot(Vec3::Y);
    if 1.0 - ndot_up.abs() <= 1.0e-7 {
        bitangent = if ndot_up > 0.0 { Vec3::Z } else { -Vec3::Z };
    }

    let tangent = bitangent.cross(normal).normalize_or_zero();
    let bitangent = normal.cross(tangent);
    glam::Mat3::from_cols(tangent, bitangent, normal)
}

fn v_smith_ggx_correlated(ndotv: f32, ndotl: f32, roughness: f32) -> f32 {
    let a2 = roughness.powi(4);
    let ggx_v = ndotl * (ndotv * ndotv * (1.0 - a2) + a2).sqrt();
    let ggx_l = ndotv * (ndotl * ndotl * (1.0 - a2) + a2).sqrt();
    0.5 / (ggx_v + ggx_l).max(1.0e-7)
}

fn hammersley(index: u32, sample_count: u32) -> Vec2 {
    Vec2::new(
        index as f32 / sample_count.max(1) as f32,
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

fn vec_into_cubemap_faces(faces: Vec<SourceImage>) -> CubemapFaces {
    faces
        .try_into()
        .unwrap_or_else(|_| unreachable!("cubemap face count should stay at six"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::source_image::EnvironmentSource;

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

        let entries = build_specular_chunk_entries(
            &EnvironmentSource::Latlong(source),
            &options,
            4,
        )
        .expect("specular should bake");
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

    #[test]
    fn irradiance_prefilter_preserves_environment_energy() {
        let source = hotspot_latlong(64, 32);
        let options = BakeOptions {
            irradiance_size: 8,
            sample_count: 128,
            quality: BakeQuality::Medium,
            ..BakeOptions::default()
        };

        let entries = build_irradiance_chunk_entries(&EnvironmentSource::Latlong(source), &options)
            .expect("irradiance should bake");
        let face = entries
            .iter()
            .find(|entry| entry.record.face == Some(Face::PositiveZ))
            .expect("positive z face should exist");
        let image = decode_png_rgba(&face.chunk.bytes);

        let center = image.get_pixel(4, 4).0;
        assert!(center[0] > 0);
        assert!(center[0] < 255);
    }

    #[test]
    fn cubemap_lod_matches_reference_formula() {
        let base_width = 512;
        let sample_count = 1024;
        let pdf = 0.125;
        let expected =
            0.5 * ((6.0 * (base_width as f32).powi(2)) / (sample_count as f32 * pdf)).log2();
        let cubemap_mips = vec![
            array::from_fn(|_| SourceImage::new(512, 512)),
            array::from_fn(|_| SourceImage::new(256, 256)),
            array::from_fn(|_| SourceImage::new(128, 128)),
            array::from_fn(|_| SourceImage::new(64, 64)),
            array::from_fn(|_| SourceImage::new(32, 32)),
        ];
        let lod = compute_cubemap_lod(pdf, sample_count, base_width, &cubemap_mips);
        let expected = expected.clamp(0.0, (cubemap_mips.len() - 1) as f32);

        assert!((lod - expected).abs() < 1.0e-5);
    }

    #[test]
    fn brdf_lut_uses_correlated_smith_visibility() {
        let kernel = build_ggx_kernel(0.5, 64);
        let sample = integrate_brdf(0.5, 0.5, &kernel);

        assert!(sample.scale.is_finite());
        assert!(sample.bias.is_finite());
        assert!(sample.scale > 0.0);
        assert!(sample.bias >= 0.0);
    }
}

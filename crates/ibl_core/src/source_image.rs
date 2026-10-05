use std::f32::consts::{PI, TAU};
use std::path::Path;

use exr::prelude::read_all_rgba_layers_from_file;
#[cfg(test)]
use exr::prelude::write_rgba_file;
use glam::{Vec2, Vec3};
#[cfg(test)]
use image::codecs::hdr::HdrEncoder;
#[cfg(test)]
use image::Rgb;
use image::{ImageFormat, ImageReader};
use png::{BitDepth, ColorType};

use crate::cubemap::{direction_to_face_uv, CubemapBorders};
use crate::{CubemapInputPaths, EncodingKind, Face, IblError, SourceFormat};

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct SourceImage {
    pub(crate) width: u32,
    pub(crate) height: u32,
    pub(crate) pixels: Vec<Vec3>,
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) enum EnvironmentSource {
    Latlong(SourceImage),
    Cubemap([SourceImage; 6]),
}

pub(crate) struct EnvironmentSampler<'a> {
    source: &'a EnvironmentSource,
    borders: Option<CubemapBorders>,
}

impl<'a> EnvironmentSampler<'a> {
    pub(crate) fn new(source: &'a EnvironmentSource) -> Self {
        let borders = match source {
            EnvironmentSource::Latlong(_) => None,
            EnvironmentSource::Cubemap(faces) => Some(CubemapBorders::new(faces)),
        };
        Self { source, borders }
    }

    pub(crate) fn sample(&self, direction: Vec3, rotation: Rotation) -> Vec3 {
        let rotated = rotate_direction_y(direction.normalize_or_zero(), rotation);
        match self.source {
            EnvironmentSource::Latlong(image) => sample_latlong(image, rotated),
            EnvironmentSource::Cubemap(faces) => {
                let (face, uv) = direction_to_face_uv(rotated);
                self.borders
                    .as_ref()
                    .expect("cubemap input borders should exist")
                    .sample_bilinear(faces, face, uv)
            }
        }
    }
}

impl SourceImage {
    pub(crate) fn new(width: u32, height: u32) -> Self {
        Self {
            width,
            height,
            pixels: vec![Vec3::ZERO; (width as usize) * (height as usize)],
        }
    }

    pub(crate) fn from_pixels(width: u32, height: u32, pixels: Vec<Vec3>) -> Self {
        debug_assert_eq!(pixels.len(), (width as usize) * (height as usize));
        Self {
            width,
            height,
            pixels,
        }
    }

    pub(crate) fn get(&self, x: u32, y: u32) -> Vec3 {
        self.pixels[(y as usize) * (self.width as usize) + (x as usize)]
    }

    pub(crate) fn set(&mut self, x: u32, y: u32, color: Vec3) {
        self.pixels[(y as usize) * (self.width as usize) + (x as usize)] = color;
    }

    fn validate_finite_rgb(&self) -> Result<(), IblError> {
        if self.pixels.iter().any(|color| !color.is_finite()) {
            return Err(IblError::InvalidInput(
                "RGB values must be finite".to_string(),
            ));
        }
        Ok(())
    }

    pub(crate) fn sample_bilinear(&self, uv: Vec2, wrap_x: bool) -> Vec3 {
        let width = self.width.max(1) as f32;
        let height = self.height.max(1) as f32;

        let u = if wrap_x {
            uv.x.rem_euclid(1.0)
        } else {
            uv.x.clamp(0.0, 1.0)
        };
        let v = uv.y.clamp(0.0, 1.0);

        let x = (u * width - 0.5).clamp(-0.5, width - 0.5);
        let y = (v * height - 0.5).clamp(-0.5, height - 0.5);

        let x0 = x.floor() as i32;
        let y0 = y.floor() as i32;
        let tx = x - x.floor();
        let ty = y - y.floor();

        let x1 = x0 + 1;
        let y1 = y0 + 1;

        let sample = |sx: i32, sy: i32| -> Vec3 {
            let wrapped_x = if wrap_x {
                sx.rem_euclid(self.width as i32) as u32
            } else {
                sx.clamp(0, self.width.saturating_sub(1) as i32) as u32
            };
            let clamped_y = sy.clamp(0, self.height.saturating_sub(1) as i32) as u32;
            self.get(wrapped_x, clamped_y)
        };

        let top = sample(x0, y0).lerp(sample(x1, y0), tx);
        let bottom = sample(x0, y1).lerp(sample(x1, y1), tx);
        top.lerp(bottom, ty)
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub(crate) struct Rotation {
    cos_theta: f32,
    sin_theta: f32,
}

impl Rotation {
    pub(crate) fn from_degrees(rotation_degrees: f32) -> Self {
        let radians = rotation_degrees.to_radians();
        Self {
            cos_theta: radians.cos(),
            sin_theta: radians.sin(),
        }
    }
}

pub(crate) fn load_source_image(path: &Path) -> Result<SourceImage, IblError> {
    let image = match SourceFormat::from_input_path(path) {
        SourceFormat::Exr => load_exr_source_image(path),
        source_format => load_image_source_image(path, source_format),
    }?;
    image.validate_finite_rgb()?;
    Ok(image)
}

pub(crate) fn load_environment_from_file(
    path: &Path,
) -> Result<(EnvironmentSource, SourceFormat), IblError> {
    let source_format = SourceFormat::from_input_path(path);
    let image = load_source_image(path)?;
    Ok((EnvironmentSource::Latlong(image), source_format))
}

pub(crate) fn load_environment_from_cubemap_paths(
    input: &CubemapInputPaths,
) -> Result<(EnvironmentSource, SourceFormat), IblError> {
    let mut resolved_format = None;
    let mut resolved_size = None;
    let mut faces = Vec::with_capacity(Face::all().len());

    for path in input.as_array() {
        if !path.is_file() {
            return Err(IblError::InvalidInput(format!(
                "cubemap face does not exist: {}",
                path.display()
            )));
        }

        let source_format = normalize_source_format(SourceFormat::from_input_path(path));
        if source_format == SourceFormat::Unknown {
            return Err(IblError::InvalidInput(format!(
                "unsupported cubemap face format: {}",
                path.display()
            )));
        }

        match resolved_format {
            Some(expected) if expected != source_format => {
                return Err(IblError::InvalidInput(
                    "cubemap faces must use the same source format family".to_string(),
                ));
            }
            None => resolved_format = Some(source_format),
            _ => {}
        }

        let image = load_source_image(path)?;
        if image.width != image.height {
            return Err(IblError::InvalidInput(format!(
                "cubemap faces must be square: {} is {}x{}",
                path.display(),
                image.width,
                image.height
            )));
        }

        match resolved_size {
            Some(expected) if expected != image.width => {
                return Err(IblError::InvalidInput(
                    "cubemap faces must share the same dimensions".to_string(),
                ));
            }
            None => resolved_size = Some(image.width),
            _ => {}
        }

        faces.push(image);
    }

    let faces: [SourceImage; 6] = faces
        .try_into()
        .unwrap_or_else(|_| unreachable!("cubemap inputs should resolve exactly six faces"));
    Ok((
        EnvironmentSource::Cubemap(faces),
        resolved_format.unwrap_or(SourceFormat::Unknown),
    ))
}

pub(crate) fn encode_png_image(
    image: &SourceImage,
    encoding: EncodingKind,
) -> Result<Vec<u8>, IblError> {
    image.validate_finite_rgb()?;
    let mut bytes = Vec::new();
    let mut encoder = png::Encoder::new(&mut bytes, image.width, image.height);
    encoder.set_color(ColorType::Rgba);
    encoder.set_depth(BitDepth::Eight);

    let mut writer = encoder
        .write_header()
        .map_err(|error| IblError::PngEncode(error.to_string()))?;

    let data = encode_pixels_to_rgba8(image, encoding);
    writer
        .write_image_data(&data)
        .map_err(|error| IblError::PngEncode(error.to_string()))?;
    drop(writer);

    Ok(bytes)
}

pub(crate) fn srgb_to_linear(value: f32) -> f32 {
    if value <= 0.04045 {
        value / 12.92
    } else {
        ((value + 0.055) / 1.055).powf(2.4)
    }
}

pub(crate) fn linear_to_srgb(value: f32) -> f32 {
    if value <= 0.0031308 {
        value * 12.92
    } else {
        1.055 * value.powf(1.0 / 2.4) - 0.055
    }
}

pub(crate) fn encode_rgbd_srgb(color: Vec3) -> (Vec3, f32) {
    let color = color.max(Vec3::ZERO);
    let max_rgb = color.max_element();
    if max_rgb <= 0.0 {
        return (Vec3::ZERO, 1.0);
    }

    let mut d = (255.0 / max_rgb).max(1.0);
    d = (d.floor() / 255.0).clamp(0.0, 1.0);
    let rgbd_linear = (color * d).clamp(Vec3::ZERO, Vec3::ONE);
    (
        Vec3::new(
            linear_to_srgb(rgbd_linear.x),
            linear_to_srgb(rgbd_linear.y),
            linear_to_srgb(rgbd_linear.z),
        ),
        d,
    )
}

fn load_image_source_image(
    path: &Path,
    source_format: SourceFormat,
) -> Result<SourceImage, IblError> {
    let mut reader = ImageReader::open(path).map_err(IblError::from)?;
    if let Some(format) = image_format_for_source(source_format) {
        reader.set_format(format);
    } else {
        reader = reader.with_guessed_format().map_err(IblError::from)?;
    }

    let guessed_format = reader.format();
    let decoded = reader.decode().map_err(IblError::from)?;
    let rgb = decoded.into_rgb32f();
    let (width, height) = rgb.dimensions();

    let treat_as_ldr = match source_format {
        SourceFormat::Hdr => false,
        SourceFormat::Png | SourceFormat::Jpg | SourceFormat::Jpeg => true,
        SourceFormat::Unknown => !matches!(guessed_format, Some(ImageFormat::Hdr)),
        SourceFormat::Exr => false,
    };

    let mut image = SourceImage::new(width, height);
    for y in 0..height {
        for x in 0..width {
            let pixel = rgb.get_pixel(x, y).0;
            let color = Vec3::new(pixel[0], pixel[1], pixel[2]);
            image.set(
                x,
                y,
                if treat_as_ldr {
                    Vec3::new(
                        srgb_to_linear(color.x),
                        srgb_to_linear(color.y),
                        srgb_to_linear(color.z),
                    )
                } else {
                    color
                },
            );
        }
    }

    Ok(image)
}

fn load_exr_source_image(path: &Path) -> Result<SourceImage, IblError> {
    let mut image = read_all_rgba_layers_from_file::<f32, f32, f32, f32, _, _, _>(
        path,
        |resolution, _channels| {
            SourceImage::new(resolution.width() as u32, resolution.height() as u32)
        },
        |storage, position, (r, g, b, _a)| {
            storage.set(position.x() as u32, position.y() as u32, Vec3::new(r, g, b));
        },
    )
    .map_err(|error| IblError::UnsupportedExrChannelModel(error.to_string()))?;

    if image.layer_data.len() != 1 {
        return Err(IblError::UnsupportedExrLayout(
            "multi-layer EXR files are not supported in v1".to_string(),
        ));
    }

    Ok(image.layer_data.remove(0).channel_data.pixels)
}

fn image_format_for_source(source_format: SourceFormat) -> Option<ImageFormat> {
    match source_format {
        SourceFormat::Hdr => Some(ImageFormat::Hdr),
        SourceFormat::Png => Some(ImageFormat::Png),
        SourceFormat::Jpg | SourceFormat::Jpeg => Some(ImageFormat::Jpeg),
        SourceFormat::Exr | SourceFormat::Unknown => None,
    }
}

fn normalize_source_format(source_format: SourceFormat) -> SourceFormat {
    match source_format {
        SourceFormat::Jpeg => SourceFormat::Jpg,
        other => other,
    }
}

fn rotate_direction_y(direction: Vec3, rotation: Rotation) -> Vec3 {
    Vec3::new(
        direction.x * rotation.cos_theta - direction.z * rotation.sin_theta,
        direction.y,
        direction.x * rotation.sin_theta + direction.z * rotation.cos_theta,
    )
}

fn sample_latlong(source: &SourceImage, direction: Vec3) -> Vec3 {
    let u = 0.5 + direction.z.atan2(direction.x) / TAU;
    let v = direction.y.clamp(-1.0, 1.0).acos() / PI;
    source.sample_bilinear(Vec2::new(u, v), true)
}

fn encode_pixels_to_rgba8(image: &SourceImage, encoding: EncodingKind) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(image.pixels.len() * 4);

    for color in &image.pixels {
        let (rgb, alpha) = match encoding {
            EncodingKind::RgbdSrgb => encode_rgbd_srgb(*color),
            EncodingKind::Srgb => (
                Vec3::new(
                    linear_to_srgb(color.x.clamp(0.0, 1.0)),
                    linear_to_srgb(color.y.clamp(0.0, 1.0)),
                    linear_to_srgb(color.z.clamp(0.0, 1.0)),
                ),
                1.0,
            ),
            EncodingKind::Linear => (color.clamp(Vec3::ZERO, Vec3::ONE), 1.0),
        };

        bytes.push(float_to_u8(rgb.x));
        bytes.push(float_to_u8(rgb.y));
        bytes.push(float_to_u8(rgb.z));
        bytes.push(float_to_u8(alpha));
    }

    bytes
}

fn float_to_u8(value: f32) -> u8 {
    (value.clamp(0.0, 1.0) * 255.0).round() as u8
}

#[cfg(test)]
pub(crate) fn write_test_png(path: &Path, width: u32, height: u32) {
    let bytes = encode_png_image(&gradient_source_image(width, height), EncodingKind::Srgb)
        .expect("png fixture should encode");
    std::fs::write(path, bytes).expect("png fixture should be written");
}

#[cfg(test)]
pub(crate) fn write_test_hdr(path: &Path, width: u32, height: u32) {
    let file = std::fs::File::create(path).expect("hdr fixture should be created");
    let encoder = HdrEncoder::new(file);
    let pixels = gradient_hdr_pixels(width, height);
    encoder
        .encode(&pixels, width as usize, height as usize)
        .expect("hdr fixture should encode");
}

#[cfg(test)]
pub(crate) fn write_test_exr(path: &Path, width: usize, height: usize) {
    write_rgba_file(path, width, height, |x, y| {
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
        (fx, fy, 0.25 + 0.5 * fx, 1.0)
    })
    .expect("exr fixture should encode");
}

#[cfg(test)]
fn gradient_source_image(width: u32, height: u32) -> SourceImage {
    let mut image = SourceImage::new(width, height);
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
            image.set(x, y, Vec3::new(fx, fy, 0.25 + 0.5 * fx));
        }
    }
    image
}

#[cfg(test)]
fn gradient_hdr_pixels(width: u32, height: u32) -> Vec<Rgb<f32>> {
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
            pixels.push(Rgb([0.5 + 2.0 * fx, 0.25 + fy, 0.1 + 0.5 * fy]));
        }
    }
    pixels
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rotated_cubemap_sampling_matches_an_independent_direction_field() {
        let size = 64;
        let bases = [
            (Vec3::X, Vec3::NEG_Z, Vec3::NEG_Y),
            (Vec3::NEG_X, Vec3::Z, Vec3::NEG_Y),
            (Vec3::Y, Vec3::X, Vec3::Z),
            (Vec3::NEG_Y, Vec3::X, Vec3::NEG_Z),
            (Vec3::Z, Vec3::X, Vec3::NEG_Y),
            (Vec3::NEG_Z, Vec3::NEG_X, Vec3::NEG_Y),
        ];
        let source = EnvironmentSource::Cubemap(std::array::from_fn(|index| {
            let (normal, right, down) = bases[index];
            let mut image = SourceImage::new(size, size);
            for y in 0..size {
                for x in 0..size {
                    let u = 2.0 * (x as f32 + 0.5) / size as f32 - 1.0;
                    let v = 2.0 * (y as f32 + 0.5) / size as f32 - 1.0;
                    let direction = (normal + right * u + down * v).normalize();
                    image.set(x, y, (direction + Vec3::ONE) * 0.5);
                }
            }
            image
        }));
        let sampler = EnvironmentSampler::new(&source);

        for degrees in [0.0_f32, 37.0, 90.0, -90.0, 180.0, 360.0] {
            // Evaluate rotation independently in f64, including the sign convention.
            let angle = (degrees as f64).to_radians();
            let (sin, cos) = angle.sin_cos();
            for (normal, right, down) in bases {
                // Endpoints include all twelve edges and eight three-face corners.
                for u in [-1.0, -0.71, 0.0, 0.43, 1.0] {
                    for v in [-1.0, -0.63, 0.0, 0.79, 1.0] {
                        let direction = (normal + right * u + down * v).normalize();
                        let expected_direction = Vec3::new(
                            (direction.x as f64 * cos - direction.z as f64 * sin) as f32,
                            direction.y,
                            (direction.x as f64 * sin + direction.z as f64 * cos) as f32,
                        );
                        let expected = (expected_direction + Vec3::ONE) * 0.5;
                        // A copied neighbor row reconstructs seam tangents with a
                        // first-order texel error; face interiors are second order.
                        let actual = sampler.sample(direction, Rotation::from_degrees(degrees));
                        assert!(
                            (actual - expected).abs().max_element()
                                <= 0.25 / size as f32 + 2.0 / (size * size) as f32,
                            "rotation {degrees}, direction {direction}, actual {actual}, expected {expected}"
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn quarter_turn_cubemap_rotation_preserves_exact_pixel_center_colors() {
        let size = 64;
        let bases = [
            (Vec3::X, Vec3::NEG_Z, Vec3::NEG_Y),
            (Vec3::NEG_X, Vec3::Z, Vec3::NEG_Y),
            (Vec3::Y, Vec3::X, Vec3::Z),
            (Vec3::NEG_Y, Vec3::X, Vec3::NEG_Z),
            (Vec3::Z, Vec3::X, Vec3::NEG_Y),
            (Vec3::NEG_Z, Vec3::NEG_X, Vec3::NEG_Y),
        ];
        let source = EnvironmentSource::Cubemap(std::array::from_fn(|index| {
            let (normal, right, down) = bases[index];
            let mut image = SourceImage::new(size, size);
            for y in 0..size {
                for x in 0..size {
                    let u = 2.0 * (x as f32 + 0.5) / size as f32 - 1.0;
                    let v = 2.0 * (y as f32 + 0.5) / size as f32 - 1.0;
                    let direction = (normal + right * u + down * v).normalize();
                    image.set(x, y, (direction + Vec3::ONE) * 0.5);
                }
            }
            image
        }));
        let sampler = EnvironmentSampler::new(&source);
        // Quarter-turn rotations map pixel centers onto exact centers of another
        // face, so they do not incur seam reconstruction approximation.
        for degrees in [90.0_f32, -90.0, 180.0] {
            let angle = (degrees as f64).to_radians();
            let (sin, cos) = angle.sin_cos();
            for (normal, right, down) in bases {
                for x in [0, 1, 31, 62, 63] {
                    for y in [0, 1, 31, 62, 63] {
                        let u = 2.0 * (x as f32 + 0.5) / size as f32 - 1.0;
                        let v = 2.0 * (y as f32 + 0.5) / size as f32 - 1.0;
                        let direction = (normal + right * u + down * v).normalize();
                        let expected_direction = Vec3::new(
                            (direction.x as f64 * cos - direction.z as f64 * sin) as f32,
                            direction.y,
                            (direction.x as f64 * sin + direction.z as f64 * cos) as f32,
                        );
                        let expected = (expected_direction + Vec3::ONE) * 0.5;
                        let actual = sampler.sample(direction, Rotation::from_degrees(degrees));
                        assert!((actual - expected).abs().max_element() <= 2.0e-6);
                    }
                }
            }
        }
    }

    #[test]
    fn cubemap_environment_sampling_hits_expected_face() {
        let cubemap = EnvironmentSource::Cubemap(std::array::from_fn(|index| {
            let mut image = SourceImage::new(2, 2);
            for y in 0..2 {
                for x in 0..2 {
                    image.set(x, y, Vec3::splat(index as f32));
                }
            }
            image
        }));

        let color = EnvironmentSampler::new(&cubemap)
            .sample(Vec3::new(0.0, 0.0, 1.0), Rotation::from_degrees(0.0));

        assert_eq!(color, Vec3::splat(Face::PositiveZ.index() as f32));
    }
}

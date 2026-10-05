// Included only in generated experiment snapshots, inside bake_pipeline.
// The production source mip policy remains unchanged.

#[derive(Debug, Clone)]
struct SolidAngleTap {
    source_index: usize,
    weight: f64,
}

struct SolidAngleDownsampleWeights {
    target_size: u32,
    pixels: Vec<Vec<SolidAngleTap>>,
}

fn spherical_rectangle_area(u0: f64, u1: f64, v0: f64, v1: f64) -> f64 {
    let primitive = |u: f64, v: f64| (u * v).atan2((1.0 + u * u + v * v).sqrt());
    primitive(u1, v1) - primitive(u0, v1) - primitive(u1, v0) + primitive(u0, v0)
}

fn solid_angle_cell_bounds(index: u32, size: u32) -> (f64, f64) {
    let size = size as f64;
    (
        2.0 * index as f64 / size - 1.0,
        2.0 * (index + 1) as f64 / size - 1.0,
    )
}

impl SolidAngleDownsampleWeights {
    fn new(source_size: u32) -> Self {
        assert!(source_size > 0);
        let target_size = (source_size / 2).max(1);
        let ratio = source_size as f64 / target_size as f64;
        let mut pixels = Vec::with_capacity(target_size as usize * target_size as usize);
        for y in 0..target_size {
            let (v0, v1) = solid_angle_cell_bounds(y, target_size);
            let first_y = (y as f64 * ratio).floor() as u32;
            let last_y = (((y + 1) as f64 * ratio).ceil() as u32).min(source_size);
            for x in 0..target_size {
                let (u0, u1) = solid_angle_cell_bounds(x, target_size);
                let target_area = spherical_rectangle_area(u0, u1, v0, v1);
                let first_x = (x as f64 * ratio).floor() as u32;
                let last_x = (((x + 1) as f64 * ratio).ceil() as u32).min(source_size);
                let mut taps =
                    Vec::with_capacity(((last_x - first_x) * (last_y - first_y)) as usize);
                for sy in first_y..last_y {
                    let (sv0, sv1) = solid_angle_cell_bounds(sy, source_size);
                    for sx in first_x..last_x {
                        let (su0, su1) = solid_angle_cell_bounds(sx, source_size);
                        let left = u0.max(su0);
                        let right = u1.min(su1);
                        let top = v0.max(sv0);
                        let bottom = v1.min(sv1);
                        if right <= left || bottom <= top {
                            continue;
                        }
                        let area = spherical_rectangle_area(left, right, top, bottom);
                        assert!(area > 0.0 && area.is_finite());
                        taps.push(SolidAngleTap {
                            source_index: sy as usize * source_size as usize + sx as usize,
                            weight: area / target_area,
                        });
                    }
                }
                pixels.push(taps);
            }
        }
        Self {
            target_size,
            pixels,
        }
    }

    fn downsample(&self, image: &SourceImage) -> SourceImage {
        let pixels = self
            .pixels
            .iter()
            .map(|taps| {
                let mut sum = [0.0_f64; 3];
                for tap in taps {
                    let color = image.pixels[tap.source_index];
                    sum[0] += color.x as f64 * tap.weight;
                    sum[1] += color.y as f64 * tap.weight;
                    sum[2] += color.z as f64 * tap.weight;
                }
                Vec3::new(sum[0] as f32, sum[1] as f32, sum[2] as f32)
            })
            .collect();
        SourceImage::from_pixels(self.target_size, self.target_size, pixels)
    }
}

#[allow(dead_code)]
fn build_solid_angle_cubemap_mip_chain(base_faces: &CubemapFaces) -> Vec<CubemapFaces> {
    let mut levels = vec![base_faces.clone()];
    loop {
        let previous = levels.last().expect("base source level exists");
        let size = previous[0].width;
        assert!(previous
            .iter()
            .all(|image| image.width == size && image.height == size));
        if size <= 1 {
            break;
        }
        let weights = SolidAngleDownsampleWeights::new(size);
        levels.push(std::array::from_fn(|face| {
            weights.downsample(&previous[face])
        }));
    }
    levels
}

#[cfg(test)]
mod mip_weighting_tests {
    use super::*;

    const SIZES: [u32; 11] = [1, 2, 3, 4, 5, 6, 7, 16, 32, 255, 256];

    // Independent Gauss-Legendre integration of the cube-UV Jacobian.
    // This deliberately does not use the candidate rectangle primitive.
    fn numerical_rectangle_area(u0: f64, u1: f64, v0: f64, v1: f64) -> f64 {
        const NODES: [f64; 8] = [
            -0.9602898564975363,
            -0.7966664774136267,
            -0.525_532_409_916_329,
            -0.1834346424956498,
            0.1834346424956498,
            0.525_532_409_916_329,
            0.7966664774136267,
            0.9602898564975363,
        ];
        const WEIGHTS: [f64; 8] = [
            0.1012285362903763,
            0.2223810344533745,
            0.3137066458778873,
            0.362_683_783_378_362,
            0.362_683_783_378_362,
            0.3137066458778873,
            0.2223810344533745,
            0.1012285362903763,
        ];
        let mut total = 0.0;
        // Subdivision keeps the numerical reference accurate for a complete face.
        for by in 0..4 {
            for bx in 0..4 {
                let lo_u = u0 + (u1 - u0) * bx as f64 / 4.0;
                let hi_u = u0 + (u1 - u0) * (bx + 1) as f64 / 4.0;
                let lo_v = v0 + (v1 - v0) * by as f64 / 4.0;
                let hi_v = v0 + (v1 - v0) * (by + 1) as f64 / 4.0;
                for (iy, ny) in NODES.iter().enumerate() {
                    let v = (lo_v + hi_v) * 0.5 + ny * (hi_v - lo_v) * 0.5;
                    for (ix, nx) in NODES.iter().enumerate() {
                        let u = (lo_u + hi_u) * 0.5 + nx * (hi_u - lo_u) * 0.5;
                        total += WEIGHTS[ix]
                            * WEIGHTS[iy]
                            * (1.0 + u * u + v * v).powf(-1.5)
                            * (hi_u - lo_u)
                            * (hi_v - lo_v)
                            * 0.25;
                    }
                }
            }
        }
        total
    }

    fn image(size: u32, color: impl Fn(u32, u32) -> Vec3) -> SourceImage {
        SourceImage::from_pixels(
            size,
            size,
            (0..size)
                .flat_map(|y| {
                    let color = &color;
                    (0..size).map(move |x| color(x, y))
                })
                .collect(),
        )
    }

    fn weighted_sum(image: &SourceImage) -> [f64; 3] {
        let size = image.width;
        let mut sum = [0.0; 3];
        for y in 0..size {
            let (v0, v1) = solid_angle_cell_bounds(y, size);
            for x in 0..size {
                let (u0, u1) = solid_angle_cell_bounds(x, size);
                let area = spherical_rectangle_area(u0, u1, v0, v1);
                let color = image.get(x, y);
                sum[0] += color.x as f64 * area;
                sum[1] += color.y as f64 * area;
                sum[2] += color.z as f64 * area;
            }
        }
        sum
    }

    #[test]
    fn mip_weighting_total_solid_angle_is_four_pi() {
        for size in SIZES {
            let mut face_area = 0.0;
            for y in 0..size {
                let (v0, v1) = solid_angle_cell_bounds(y, size);
                for x in 0..size {
                    let (u0, u1) = solid_angle_cell_bounds(x, size);
                    let area = spherical_rectangle_area(u0, u1, v0, v1);
                    assert!(area > 0.0);
                    face_area += area;
                }
            }
            assert!((face_area * 6.0 - 4.0 * std::f64::consts::PI).abs() < 2.0e-11);
        }
        let exact = spherical_rectangle_area(-1.0, 1.0, -1.0, 1.0);
        assert!((exact - numerical_rectangle_area(-1.0, 1.0, -1.0, 1.0)).abs() < 1.0e-11);
    }

    #[test]
    fn mip_weighting_positive_weights_cover_every_source_pixel() {
        for size in SIZES {
            let weights = SolidAngleDownsampleWeights::new(size);
            let mut coverage = vec![0.0_f64; size as usize * size as usize];
            for (target_index, taps) in weights.pixels.iter().enumerate() {
                let x = target_index as u32 % weights.target_size;
                let y = target_index as u32 / weights.target_size;
                let (u0, u1) = solid_angle_cell_bounds(x, weights.target_size);
                let (v0, v1) = solid_angle_cell_bounds(y, weights.target_size);
                let area = spherical_rectangle_area(u0, u1, v0, v1);
                assert!((taps.iter().map(|tap| tap.weight).sum::<f64>() - 1.0).abs() < 2.0e-10);
                for tap in taps {
                    assert!(tap.weight > 0.0);
                    coverage[tap.source_index] += tap.weight * area;
                }
            }
            for y in 0..size {
                let (v0, v1) = solid_angle_cell_bounds(y, size);
                for x in 0..size {
                    let (u0, u1) = solid_angle_cell_bounds(x, size);
                    let expected = spherical_rectangle_area(u0, u1, v0, v1);
                    let actual = coverage[y as usize * size as usize + x as usize];
                    assert!(
                        (actual - expected).abs() < 2.0e-12,
                        "size={size} x={x} y={y}"
                    );
                }
            }
        }
    }

    #[test]
    fn mip_weighting_constant_and_discrete_spherical_sum_are_preserved() {
        for size in SIZES {
            for constant in [Vec3::ONE, Vec3::new(0.0, 0.25, 35000.0)] {
                let faces = std::array::from_fn(|_| image(size, |_, _| constant));
                for level in build_solid_angle_cubemap_mip_chain(&faces) {
                    assert!(level.iter().flat_map(|face| &face.pixels).all(|pixel| {
                        (*pixel - constant).abs().max_element()
                            <= 2.0e-6 * constant.abs().max_element().max(1.0)
                    }));
                }
            }
            let faces = std::array::from_fn(|face| {
                image(size, |x, y| {
                    Vec3::new(
                        (x + face as u32) as f32 / size as f32,
                        (y + 1) as f32 / size as f32,
                        if x == size - 1 || y == size - 1 {
                            17.0
                        } else {
                            0.0
                        },
                    )
                })
            });
            let expected: Vec<_> = faces.iter().map(weighted_sum).collect();
            for level in build_solid_angle_cubemap_mip_chain(&faces) {
                for (face, original) in level.iter().zip(&expected) {
                    let actual = weighted_sum(face);
                    for component in 0..3 {
                        assert!(
                            (actual[component] - original[component]).abs()
                                <= 2.0e-6 * original[component].abs().max(1.0)
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn mip_weighting_npot_boundary_light_matches_numerical_rectangles() {
        for size in [3, 5, 6, 7, 255] {
            let source = image(size, |x, y| {
                Vec3::new(
                    if x == size - 1 { 1.0 } else { 0.0 },
                    if y == size - 1 { 1.0 } else { 0.0 },
                    if x == size - 1 && y == size - 1 {
                        1.0
                    } else {
                        0.0
                    },
                )
            });
            let weights = SolidAngleDownsampleWeights::new(size);
            let actual = weights.downsample(&source);
            let target = weights.target_size;
            for y in 0..target {
                let (v0, v1) = solid_angle_cell_bounds(y, target);
                for x in 0..target {
                    // Interior pixels are zero by independent support reasoning.
                    if x + 1 != target && y + 1 != target {
                        assert_eq!(actual.get(x, y), Vec3::ZERO);
                        continue;
                    }
                    let (u0, u1) = solid_angle_cell_bounds(x, target);
                    let area = numerical_rectangle_area(u0, u1, v0, v1);
                    let last = 1.0 - 2.0 / size as f64;
                    let right = if u1 > last {
                        numerical_rectangle_area(u0.max(last), u1, v0, v1) / area
                    } else {
                        0.0
                    };
                    let bottom = if v1 > last {
                        numerical_rectangle_area(u0, u1, v0.max(last), v1) / area
                    } else {
                        0.0
                    };
                    let corner = if u1 > last && v1 > last {
                        numerical_rectangle_area(u0.max(last), u1, v0.max(last), v1) / area
                    } else {
                        0.0
                    };
                    let expected = Vec3::new(right as f32, bottom as f32, corner as f32);
                    assert!(
                        (actual.get(x, y) - expected).abs().max_element() < 2.0e-6,
                        "size={size} x={x} y={y}"
                    );
                }
            }
        }
    }

    #[test]
    fn mip_weighting_seamless_sampling_survives_all_weighted_levels() {
        for size in SIZES {
            let faces = std::array::from_fn(|index| {
                image(size, |x, y| {
                    let uv = Vec2::new(
                        2.0 * (x as f32 + 0.5) / size as f32 - 1.0,
                        2.0 * (y as f32 + 0.5) / size as f32 - 1.0,
                    );
                    cubemap_direction(Face::all()[index], uv) * 0.5 + Vec3::splat(0.5)
                })
            });
            let levels = build_solid_angle_cubemap_mip_chain(&faces);
            let borders: Vec<_> = levels.iter().map(CubemapBorders::new).collect();
            let epsilon = 1.0e-6;
            let mut boundaries = Vec::new();
            for zero_axis in 0..3 {
                for a in [-1.0, 1.0] {
                    for b in [-1.0, 1.0] {
                        let mut corner = Vec3::ZERO;
                        corner[(zero_axis + 1) % 3] = a;
                        corner[(zero_axis + 2) % 3] = b;
                        boundaries.push(corner);
                    }
                }
            }
            for x in [-1.0, 1.0] {
                for y in [-1.0, 1.0] {
                    for z in [-1.0, 1.0] {
                        boundaries.push(Vec3::new(x, y, z));
                    }
                }
            }
            for boundary in boundaries {
                for level in 0..levels.len() {
                    for fraction in [0.0, 0.375] {
                        let samples: Vec<_> = (0..3)
                            .filter(|&axis| boundary[axis] != 0.0)
                            .map(|axis| {
                                let mut direction = boundary;
                                direction[axis] *= 1.0 + epsilon;
                                sample_cubemap_lod(
                                    &levels,
                                    &borders,
                                    direction,
                                    level as f32 + fraction,
                                )
                            })
                            .collect();
                        for sample in &samples {
                            assert!(
                                (*sample - samples[0]).abs().max_element() <= 1.0e-5,
                                "size={size} level={level} boundary={boundary:?}"
                            );
                        }
                    }
                }
            }
        }
    }
}

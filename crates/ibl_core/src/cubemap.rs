use glam::{Vec2, Vec3};

use crate::source_image::SourceImage;
use crate::Face;

/// Cached pixels outside each face, with no copies of the face interiors.
/// Each ring stores top, bottom, left, right, then four averaged corners.
#[derive(Debug, Clone, PartialEq)]
pub(crate) struct CubemapBorders {
    size: u32,
    rings: [Vec<Vec3>; 6],
}

impl CubemapBorders {
    pub(crate) fn new(faces: &[SourceImage; 6]) -> Self {
        let size = faces[0].width;
        debug_assert!(size > 0);
        debug_assert!(faces
            .iter()
            .all(|image| image.width == size && image.height == size));

        let rings = std::array::from_fn(|index| {
            let face = Face::all()[index];
            let mut ring = Vec::with_capacity(4 * size as usize + 4);
            for side in 0..4 {
                for offset in 0..size {
                    let (x, y) = match side {
                        0 => (offset as i32, -1),
                        1 => (offset as i32, size as i32),
                        2 => (-1, offset as i32),
                        _ => (size as i32, offset as i32),
                    };
                    let uv = Vec2::new(
                        2.0 * (x as f32 + 0.5) / size as f32 - 1.0,
                        2.0 * (y as f32 + 0.5) / size as f32 - 1.0,
                    );
                    let (neighbor, neighbor_uv) = direction_to_face_uv(face_direction(face, uv));
                    let nx = ((neighbor_uv.x * size as f32) as u32).min(size - 1);
                    let ny = ((neighbor_uv.y * size as f32) as u32).min(size - 1);
                    ring.push(faces[neighbor.index()].get(nx, ny));
                }
            }

            for y in [-1.0, 1.0] {
                for x in [-1.0, 1.0] {
                    ring.push(average_corner(faces, face_direction(face, Vec2::new(x, y))));
                }
            }
            ring
        });
        Self { size, rings }
    }

    /// `uv` uses [0, 1] face coordinates, with pixel centers at (i + 0.5) / size.
    #[inline]
    pub(crate) fn sample_bilinear(&self, faces: &[SourceImage; 6], face: Face, uv: Vec2) -> Vec3 {
        let size = self.size as f32;
        let x = (uv.x.clamp(0.0, 1.0) * size - 0.5).clamp(-0.5, size - 0.5);
        let y = (uv.y.clamp(0.0, 1.0) * size - 0.5).clamp(-0.5, size - 0.5);
        let floor_x = x.floor();
        let floor_y = y.floor();
        let x0 = floor_x as i32;
        let y0 = floor_y as i32;
        let tx = x - floor_x;
        let ty = y - floor_y;
        let image = &faces[face.index()];

        if x0 >= 0 && y0 >= 0 && x0 + 1 < self.size as i32 && y0 + 1 < self.size as i32 {
            let start = y0 as usize * self.size as usize + x0 as usize;
            let bottom = start + self.size as usize;
            let top_color = image.pixels[start].lerp(image.pixels[start + 1], tx);
            let bottom_color = image.pixels[bottom].lerp(image.pixels[bottom + 1], tx);
            return top_color.lerp(bottom_color, ty);
        }

        let ring = &self.rings[face.index()];
        let top = self
            .pixel(image, ring, x0, y0)
            .lerp(self.pixel(image, ring, x0 + 1, y0), tx);
        let bottom = self
            .pixel(image, ring, x0, y0 + 1)
            .lerp(self.pixel(image, ring, x0 + 1, y0 + 1), tx);
        top.lerp(bottom, ty)
    }

    #[inline]
    fn pixel(&self, image: &SourceImage, ring: &[Vec3], x: i32, y: i32) -> Vec3 {
        let size = self.size as i32;
        let outside_x = x < 0 || x >= size;
        let outside_y = y < 0 || y >= size;
        if outside_x && outside_y {
            return ring
                [4 * self.size as usize + usize::from(y >= size) * 2 + usize::from(x >= size)];
        }
        if y < 0 {
            return ring[x as usize];
        }
        if y >= size {
            return ring[self.size as usize + x as usize];
        }
        if x < 0 {
            return ring[2 * self.size as usize + y as usize];
        }
        if x >= size {
            return ring[3 * self.size as usize + y as usize];
        }
        image.get(x as u32, y as u32)
    }
}

/// Inverse face projection. The direction need not be normalized.
#[inline]
pub(crate) fn direction_to_face_uv(direction: Vec3) -> (Face, Vec2) {
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
    (
        face,
        Vec2::new(0.5 * (u / major_axis + 1.0), 0.5 * (v / major_axis + 1.0)),
    )
}

/// Forward face projection. `uv` uses [-1, 1], preserving the output orientation.
pub(crate) fn cubemap_direction(face: Face, uv: Vec2) -> Vec3 {
    face_direction(face, uv).normalize_or_zero()
}

fn face_direction(face: Face, uv: Vec2) -> Vec3 {
    match face {
        Face::PositiveX => Vec3::new(1.0, -uv.y, -uv.x),
        Face::NegativeX => Vec3::new(-1.0, -uv.y, uv.x),
        Face::PositiveY => Vec3::new(uv.x, 1.0, uv.y),
        Face::NegativeY => Vec3::new(uv.x, -1.0, -uv.y),
        Face::PositiveZ => Vec3::new(uv.x, -uv.y, 1.0),
        Face::NegativeZ => Vec3::new(-uv.x, -uv.y, -1.0),
    }
}

fn average_corner(faces: &[SourceImage; 6], corner: Vec3) -> Vec3 {
    let neighbors = [
        if corner.x >= 0.0 {
            Face::PositiveX
        } else {
            Face::NegativeX
        },
        if corner.y >= 0.0 {
            Face::PositiveY
        } else {
            Face::NegativeY
        },
        if corner.z >= 0.0 {
            Face::PositiveZ
        } else {
            Face::NegativeZ
        },
    ];
    let colors = neighbors.map(|face| {
        // At a cube corner every signed component has unit magnitude.
        let (u, v) = match face {
            Face::PositiveX => (-corner.z, -corner.y),
            Face::NegativeX => (corner.z, -corner.y),
            Face::PositiveY => (corner.x, corner.z),
            Face::NegativeY => (corner.x, -corner.z),
            Face::PositiveZ => (corner.x, -corner.y),
            Face::NegativeZ => (-corner.x, -corner.y),
        };
        let image = &faces[face.index()];
        image.get(
            if u < 0.0 { 0 } else { image.width - 1 },
            if v < 0.0 { 0 } else { image.height - 1 },
        )
    });
    // A finite HDR corner can overflow an f32 sum before division by three.
    ((colors[0].as_dvec3() + colors[1].as_dvec3() + colors[2].as_dvec3()) / 3.0).as_vec3()
}

#[cfg(test)]
mod tests {
    use super::*;

    const SIZES: [u32; 7] = [1, 2, 3, 4, 16, 32, 256];

    // Independent face basis table: normal, increasing image x, increasing image y.
    const BASES: [(Vec3, Vec3, Vec3); 6] = [
        (Vec3::X, Vec3::NEG_Z, Vec3::NEG_Y),
        (Vec3::NEG_X, Vec3::Z, Vec3::NEG_Y),
        (Vec3::Y, Vec3::X, Vec3::Z),
        (Vec3::NEG_Y, Vec3::X, Vec3::NEG_Z),
        (Vec3::Z, Vec3::X, Vec3::NEG_Y),
        (Vec3::NEG_Z, Vec3::NEG_X, Vec3::NEG_Y),
    ];

    fn direction_field(size: u32) -> [SourceImage; 6] {
        std::array::from_fn(|index| {
            let (normal, right, down) = BASES[index];
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
        })
    }

    fn sample(faces: &[SourceImage; 6], borders: &CubemapBorders, direction: Vec3) -> Vec3 {
        let (face, uv) = direction_to_face_uv(direction);
        borders.sample_bilinear(faces, face, uv)
    }

    #[test]
    fn every_border_copies_the_expected_neighbor_edge_and_orientation() {
        // For each face: top, bottom, left, right. The last field reverses offsets.
        const NEIGHBORS: [[(usize, usize, bool); 4]; 6] = [
            [(2, 3, true), (3, 3, false), (4, 3, false), (5, 2, false)],
            [(2, 2, false), (3, 2, true), (5, 3, false), (4, 2, false)],
            [(5, 0, true), (4, 0, false), (1, 0, false), (0, 0, true)],
            [(4, 1, false), (5, 1, true), (1, 1, true), (0, 1, false)],
            [(2, 1, false), (3, 0, false), (1, 3, false), (0, 2, false)],
            [(2, 0, true), (3, 1, true), (0, 3, false), (1, 2, false)],
        ];
        for size in SIZES {
            let faces = std::array::from_fn(|index| {
                let mut image = SourceImage::new(size, size);
                for y in 0..size {
                    for x in 0..size {
                        image.set(x, y, Vec3::new(index as f32 + 0.125, x as f32, y as f32));
                    }
                }
                image
            });
            let borders = CubemapBorders::new(&faces);
            for (face, neighbors) in NEIGHBORS.iter().enumerate() {
                for (side, &(neighbor, neighbor_side, reverse)) in neighbors.iter().enumerate() {
                    for offset in 0..size {
                        let position = if reverse { size - 1 - offset } else { offset };
                        let (x, y) = match neighbor_side {
                            0 => (position, 0),
                            1 => (position, size - 1),
                            2 => (0, position),
                            _ => (size - 1, position),
                        };
                        assert_eq!(
                            borders.rings[face][side * size as usize + offset as usize],
                            faces[neighbor].get(x, y),
                            "size {size}, face {face}, side {side}, offset {offset}"
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn each_corner_samples_the_mean_of_its_three_incident_face_pixels() {
        for size in SIZES {
            let faces = std::array::from_fn(|index| {
                SourceImage::from_pixels(
                    size,
                    size,
                    vec![Vec3::splat(index as f32); (size * size) as usize],
                )
            });
            let borders = CubemapBorders::new(&faces);
            for x in [-1.0, 1.0] {
                for y in [-1.0, 1.0] {
                    for z in [-1.0, 1.0] {
                        let corner = Vec3::new(x, y, z);
                        let mut expected = Vec3::ZERO;
                        for (index, &(normal, _, _)) in BASES.iter().enumerate() {
                            if normal.dot(corner) > 0.0 {
                                expected += Vec3::splat(index as f32);
                            }
                        }
                        expected /= 3.0;
                        for (index, &(normal, right, down)) in BASES.iter().enumerate() {
                            if normal.dot(corner) > 0.0 {
                                let uv = Vec2::new(right.dot(corner), down.dot(corner)) * 0.5
                                    + Vec2::splat(0.5);
                                let actual =
                                    borders.sample_bilinear(&faces, Face::all()[index], uv);
                                assert!((actual - expected).abs().max_element() <= 1.0e-6);
                            }
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn face_projection_preserves_axes_pixel_centers_and_orientation() {
        for size in SIZES {
            let faces = direction_field(size);
            let borders = CubemapBorders::new(&faces);
            for face in Face::all() {
                let (normal, right, down) = BASES[face.index()];
                assert_eq!(cubemap_direction(*face, Vec2::ZERO), normal);
                for uv in [Vec2::new(-0.3, 0.6), Vec2::new(0.7, -0.4)] {
                    let expected = (normal + right * uv.x + down * uv.y).normalize();
                    assert!(
                        (cubemap_direction(*face, uv) - expected)
                            .abs()
                            .max_element()
                            < 1.0e-7
                    );
                }
                for y in 0..size {
                    for x in 0..size {
                        let uv = Vec2::new(
                            (x as f32 + 0.5) / size as f32,
                            (y as f32 + 0.5) / size as f32,
                        );
                        let actual = borders.sample_bilinear(&faces, *face, uv);
                        assert!(
                            (actual - faces[face.index()].get(x, y)).abs().max_element() <= 2.0e-7
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn all_edges_and_corners_are_continuous_at_every_source_size() {
        let epsilon = 1.0e-6;
        for size in SIZES {
            let faces = direction_field(size);
            let borders = CubemapBorders::new(&faces);
            // Three axis pairs times four sign pairs cover all twelve cube edges.
            for (a, b, c) in [(0, 1, 2), (0, 2, 1), (1, 2, 0)] {
                for sign_a in [-1.0, 1.0] {
                    for sign_b in [-1.0, 1.0] {
                        for tangent in [-0.999, -0.75, -0.25, 0.0, 0.25, 0.75, 0.999] {
                            let mut from_a = Vec3::ZERO;
                            from_a[a] = sign_a * (1.0 + epsilon);
                            from_a[b] = sign_b;
                            from_a[c] = tangent;
                            let mut from_b = from_a;
                            from_b[a] = sign_a;
                            from_b[b] = sign_b * (1.0 + epsilon);
                            let jump = (sample(&faces, &borders, from_a)
                                - sample(&faces, &borders, from_b))
                            .abs()
                            .max_element();
                            assert!(
                                jump <= 1.0e-5,
                                "edge jump {jump} at size {size}, axes {a}/{b}"
                            );
                        }
                    }
                }
            }
            for x in [-1.0, 1.0] {
                for y in [-1.0, 1.0] {
                    for z in [-1.0, 1.0] {
                        let corner = Vec3::new(x, y, z);
                        let samples: [Vec3; 3] = std::array::from_fn(|axis| {
                            let mut direction = corner;
                            direction[axis] *= 1.0 + epsilon;
                            sample(&faces, &borders, direction)
                        });
                        for a in 0..3 {
                            for b in a + 1..3 {
                                let jump = (samples[a] - samples[b]).abs().max_element();
                                assert!(
                                    jump <= 1.0e-5,
                                    "corner jump {jump} at size {size}, corner {corner}"
                                );
                            }
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn borders_preserve_constant_hdr_colors_and_store_only_a_ring() {
        for size in SIZES {
            for color in [
                Vec3::ZERO,
                Vec3::ONE,
                Vec3::new(0.125, 16.0, 4096.0),
                Vec3::splat(f32::MAX * 0.5),
            ] {
                let faces = std::array::from_fn(|_| {
                    SourceImage::from_pixels(size, size, vec![color; (size * size) as usize])
                });
                let borders = CubemapBorders::new(&faces);
                assert!(borders
                    .rings
                    .iter()
                    .all(|ring| ring.len() == 4 * size as usize + 4));
                for face in Face::all() {
                    for uv in [
                        Vec2::ZERO,
                        Vec2::ONE,
                        Vec2::new(0.0, 1.0),
                        Vec2::new(1.0, 0.0),
                        Vec2::splat(0.5),
                        Vec2::new(0.0, 0.73),
                        Vec2::new(1.0, 0.21),
                    ] {
                        let actual = borders.sample_bilinear(&faces, *face, uv);
                        assert!(actual.is_finite());
                        assert!(
                            (actual - color).abs().max_element()
                                <= 2.0e-6 * color.max_element().max(1.0)
                        );
                    }
                }
            }
        }
    }
}

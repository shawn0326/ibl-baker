// Included only in generated experiment snapshots, inside bake_pipeline.

#[allow(dead_code)]
pub(crate) struct MipProbeBatch {
    pub(crate) distribution: &'static str,
    pub(crate) roughness: f32,
    pub(crate) requested_proposals: u32,
    pub(crate) kernel_proposals: u32,
    pub(crate) accepted_light_samples: Vec<u32>,
    pub(crate) colors: Vec<Vec3>,
}

#[allow(dead_code)]
pub(crate) struct MipProbeExport {
    pub(crate) source_mips: Vec<CubemapFaces>,
    pub(crate) batches: Vec<MipProbeBatch>,
}

#[allow(dead_code)]
pub(crate) fn measure_fixed_mip_probes(
    source: &EnvironmentSource,
    size: u32,
    rotation_degrees: f32,
    directions: &[Vec3],
) -> MipProbeExport {
    let mut context = BakeContext::new(source, size, rotation_degrees);
    let mut batches = Vec::new();
    for requested_proposals in [256, 1024] {
        for (distribution, roughness) in [
            (Distribution::Ggx, 0.05),
            (Distribution::Ggx, 0.2),
            (Distribution::Ggx, 0.5),
            (Distribution::Ggx, 0.7),
            (Distribution::Ggx, 1.0),
            (Distribution::Lambertian, 1.0),
        ] {
            context.ensure_kernel(distribution, roughness, requested_proposals);
            let kernel = context
                .kernel_cache
                .kernel(distribution, roughness, requested_proposals);
            let colors = directions
                .par_iter()
                .map(|&direction| {
                    filter_direction(
                        &context.cubemap_mips,
                        &context.cubemap_borders,
                        direction,
                        kernel,
                        distribution,
                        roughness,
                        size,
                    )
                })
                .collect();
            let accepted_light_samples = directions
                .iter()
                .map(|&direction| {
                    if distribution == Distribution::Lambertian {
                        return kernel.len() as u32;
                    }
                    let normal = direction.normalize_or_zero();
                    let tbn = generate_tbn(normal);
                    kernel
                        .iter()
                        .filter(|sample| {
                            let half_vector = (tbn * sample.local_direction).normalize_or_zero();
                            let light = (2.0 * normal.dot(half_vector) * half_vector - normal)
                                .normalize_or_zero();
                            normal.dot(light).max(0.0) > 0.0
                        })
                        .count() as u32
                })
                .collect();
            batches.push(MipProbeBatch {
                distribution: if distribution == Distribution::Ggx {
                    "ggx"
                } else {
                    "lambert"
                },
                roughness,
                requested_proposals,
                kernel_proposals: kernel.len() as u32,
                accepted_light_samples,
                colors,
            });
        }
    }
    MipProbeExport {
        source_mips: context.cubemap_mips,
        batches,
    }
}

#[cfg(test)]
mod mip_weighting_probe_tests {
    use super::*;

    #[test]
    fn mip_weighting_probe_budgets_are_exact_and_constants_are_preserved() {
        let directions = [
            Vec3::X,
            Vec3::Y,
            Vec3::Z,
            Vec3::new(1.0, 1.0, 1.0).normalize(),
        ];
        for size in [1, 7, 16] {
            let color = Vec3::new(0.25, 3.0, 35000.0);
            let source = EnvironmentSource::Cubemap(std::array::from_fn(|_| {
                SourceImage::from_pixels(size, size, vec![color; size as usize * size as usize])
            }));
            let measured = measure_fixed_mip_probes(&source, size, 37.0, &directions);
            assert_eq!(measured.batches.len(), 12);
            for batch in measured.batches {
                assert!([256, 1024].contains(&batch.requested_proposals));
                assert_eq!(batch.requested_proposals, batch.kernel_proposals);
                assert_eq!(batch.colors.len(), directions.len());
                assert_eq!(batch.accepted_light_samples.len(), directions.len());
                assert!(batch
                    .accepted_light_samples
                    .iter()
                    .all(|&count| count > 0 && count <= batch.kernel_proposals));
                for actual in batch.colors {
                    assert!((actual - color).abs().max_element() <= 2.0e-5 * color.max_element());
                }
            }
        }
    }
}

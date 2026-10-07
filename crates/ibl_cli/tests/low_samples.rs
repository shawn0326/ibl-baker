use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use image::codecs::hdr::HdrEncoder;

struct Workspace {
    path: PathBuf,
    parent: PathBuf,
}

impl Workspace {
    fn new() -> Self {
        let parent = std::env::temp_dir()
            .canonicalize()
            .expect("temporary directory should exist");
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time should be after UNIX_EPOCH")
            .as_nanos();
        let path = parent.join(format!(
            "ibl-baker-low-samples-{}-{timestamp}",
            std::process::id()
        ));
        fs::create_dir(&path).expect("test workspace should be created");
        let path = path
            .canonicalize()
            .expect("test workspace should resolve to an absolute path");
        Self { path, parent }
    }
}

impl Drop for Workspace {
    fn drop(&mut self) {
        let is_owned_workspace = self.path.parent() == Some(self.parent.as_path())
            && self
                .path
                .file_name()
                .is_some_and(|name| name.to_string_lossy().starts_with("ibl-baker-low-samples-"));
        if is_owned_workspace {
            let _ = fs::remove_dir_all(&self.path);
        }
    }
}

fn assert_ibla_payload(path: &Path, size: u32, mip_count: u32, samples: u32) {
    let asset = ibl_core::read_asset(path).expect("IBLA output should parse");
    let report = ibl_core::validate_asset(&asset);
    assert!(report.is_valid, "IBLA issues: {:?}", report.issues);
    assert_eq!((asset.manifest.width, asset.manifest.height), (size, size));
    assert_eq!(asset.manifest.mip_count, mip_count);
    assert_eq!(asset.manifest.face_count, 6);
    assert_eq!(asset.manifest.build.sample_count, samples.max(1));
    assert_eq!(asset.manifest.encoding, "rgbd-srgb");
    assert_eq!(asset.chunks.len(), (mip_count * 6) as usize);

    for chunk in &asset.chunks {
        let image = image::load_from_memory(&chunk.bytes)
            .expect("PNG payload should decode")
            .into_rgba8();
        let mip_size = (size >> chunk.mip_level).max(1);
        assert_eq!(image.dimensions(), (mip_size, mip_size));
        for pixel in image.pixels() {
            let divisor = pixel[3] as f32 / 255.0;
            assert!(divisor > 0.0, "RGBD divisor should be positive");
            for (channel, expected) in pixel.0[..3].iter().zip([0.5, 0.25, 0.125]) {
                let srgb = *channel as f32 / 255.0;
                let linear = if srgb <= 0.04045 {
                    srgb / 12.92
                } else {
                    ((srgb + 0.055) / 1.055).powf(2.4)
                } / divisor;
                assert!(linear.is_finite());
                assert!((linear - expected).abs() < 0.01);
            }
        }
    }
}

fn assert_ktx2_structure(path: &Path, size: u32, mip_count: u32) {
    let bytes = fs::read(path).expect("KTX2 output should exist");
    assert!(bytes.len() >= 80 + mip_count as usize * 24);
    assert_eq!(&bytes[..12], b"\xabKTX 20\xbb\r\n\x1a\n");
    let u32_at = |offset| u32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap());
    let u64_at = |offset| u64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap());
    assert_eq!(u32_at(12), 143); // BC6H_UFLOAT_BLOCK
    assert_eq!(u32_at(16), 1);
    assert_eq!((u32_at(20), u32_at(24)), (size, size));
    assert_eq!((u32_at(28), u32_at(32), u32_at(36)), (0, 0, 6));
    assert_eq!(u32_at(40), mip_count);
    assert_eq!(u32_at(44), 2); // zstd
    for level in 0..mip_count as usize {
        let index = 80 + level * 24;
        let offset = usize::try_from(u64_at(index)).unwrap();
        let length = usize::try_from(u64_at(index + 8)).unwrap();
        // A 1x1 or 2x2 face occupies one 16-byte BC6H block, across six faces.
        assert_eq!(u64_at(index + 16), 96);
        assert!(offset >= 80 + mip_count as usize * 24);
        assert!(length >= 4 && offset.checked_add(length).unwrap() <= bytes.len());
        assert_eq!(&bytes[offset..offset + 4], b"\x28\xb5\x2f\xfd");
    }
}

#[test]
fn low_sample_requests_bake_both_formats_for_every_quality() {
    let workspace = Workspace::new();
    let input = workspace.path.join("input.hdr");
    HdrEncoder::new(fs::File::create(&input).expect("HDR input should be created"))
        .encode(&[image::Rgb([0.5, 0.25, 0.125]); 8], 4, 2)
        .expect("constant HDR input should encode");

    for quality in ["low", "medium", "high"] {
        for samples in ["0", "1", "7", "8"] {
            for size in [1_u32, 2] {
                let output_dir = workspace.path.join(format!("{quality}-{samples}-{size}"));
                let output = Command::new(env!("CARGO_BIN_EXE_ibl-baker"))
                    .env("RAYON_NUM_THREADS", "2")
                    .arg("bake")
                    .arg(&input)
                    .arg("--out-dir")
                    .arg(&output_dir)
                    .args([
                        "--target",
                        "specular",
                        "--output-format",
                        "both",
                        "--quality",
                        quality,
                        "--samples",
                        samples,
                        "--size",
                        &size.to_string(),
                    ])
                    .output()
                    .expect("CLI should run");
                let stdout = String::from_utf8(output.stdout).expect("stdout should be UTF-8");
                let stderr = String::from_utf8(output.stderr).expect("stderr should be UTF-8");
                assert!(
                    output.status.success(),
                    "quality {quality}, samples {samples}, size {size}: status {}\nstdout: {stdout}\nstderr: {stderr}",
                    output.status
                );
                assert!(stderr.is_empty(), "stderr: {stderr}");
                let mip_count = size; // The controls are exactly 1x1 and 2x2 -> 1x1.
                for name in ["specular.ibla", "specular.ktx2"] {
                    assert!(stdout.contains(name), "stdout: {stdout}");
                }
                assert_ibla_payload(
                    &output_dir.join("specular.ibla"),
                    size,
                    mip_count,
                    samples.parse().unwrap(),
                );
                assert_ktx2_structure(&output_dir.join("specular.ktx2"), size, mip_count);
            }
        }
    }
}

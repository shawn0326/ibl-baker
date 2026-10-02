use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use image::codecs::hdr::HdrEncoder;

static NEXT_WORKSPACE: AtomicU64 = AtomicU64::new(0);

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
        let id = NEXT_WORKSPACE.fetch_add(1, Ordering::Relaxed);
        let path = parent.join(format!(
            "ibl-baker-hdr-warnings-{}-{timestamp}-{id}",
            std::process::id()
        ));
        fs::create_dir(&path).expect("test workspace should be created");
        let path = path
            .canonicalize()
            .expect("test workspace should resolve to an absolute path");
        Self { path, parent }
    }

    fn hdr(&self, rgb: [f32; 3]) -> PathBuf {
        let path = self.path.join("input.hdr");
        let file = fs::File::create(&path).expect("HDR input should be created");
        HdrEncoder::new(file)
            .encode(&[image::Rgb(rgb); 8], 4, 2)
            .expect("constant HDR input should encode");
        path
    }

    fn bake(&self, input: &Path, extra_args: &[&str]) -> BakeResult {
        BakeResult::new(self.run_bake(input, extra_args), self.path.join("outputs"))
    }

    fn run_bake(&self, input: &Path, extra_args: &[&str]) -> Output {
        let output_dir = self.path.join("outputs");
        Command::new(env!("CARGO_BIN_EXE_ibl-baker"))
            .arg("bake")
            .arg(input)
            .arg("--out-dir")
            .arg(&output_dir)
            .args([
                "--size",
                "4",
                "--irradiance-size",
                "2",
                "--samples",
                "8",
                "--quality",
                "low",
            ])
            .args(extra_args)
            .output()
            .expect("CLI should run")
    }
}

impl Drop for Workspace {
    fn drop(&mut self) {
        let is_owned_workspace = self.path.parent() == Some(self.parent.as_path())
            && self.path.file_name().is_some_and(|name| {
                name.to_string_lossy()
                    .starts_with("ibl-baker-hdr-warnings-")
            });
        if is_owned_workspace {
            let _ = fs::remove_dir_all(&self.path);
        }
    }
}

struct BakeResult {
    stdout: String,
    stderr: String,
    output_dir: PathBuf,
}

impl BakeResult {
    fn new(output: Output, output_dir: PathBuf) -> Self {
        let stdout = String::from_utf8(output.stdout).expect("stdout should be UTF-8");
        let stderr = String::from_utf8(output.stderr).expect("stderr should be UTF-8");
        assert!(
            output.status.success(),
            "bake should succeed, got status {}\nstdout: {stdout}\nstderr: {stderr}",
            output.status
        );
        assert!(stdout.contains("Baked "), "stdout: {stdout}");
        assert!(!stdout.contains("Warning:"), "stdout: {stdout}");
        Self {
            stdout,
            stderr,
            output_dir,
        }
    }

    fn warnings(&self) -> Vec<&str> {
        self.stderr
            .lines()
            .filter(|line| line.starts_with("Warning:"))
            .collect()
    }

    fn assert_warning(&self, file_name: &str, clamped_pixels: u32, upper_bound: u32) {
        let warnings = self.warnings();
        let matching = warnings
            .into_iter()
            .filter(|line| line.contains(file_name))
            .collect::<Vec<_>>();
        assert_eq!(matching.len(), 1, "stderr: {}", self.stderr);
        assert!(
            matching[0].contains(&format!(
                "{clamped_pixels} of {clamped_pixels} pixels had RGB channels clamped to [0, {upper_bound}]"
            )),
            "stderr: {}",
            self.stderr
        );
        assert!(
            matching[0].contains("pre-clip RGB range:"),
            "stderr: {}",
            self.stderr
        );
        self.assert_output(file_name);
    }

    fn assert_output(&self, file_name: &str) {
        assert!(self.output_dir.join(file_name).is_file());
        assert!(self.stdout.contains(file_name), "stdout: {}", self.stdout);
    }
}

#[test]
fn in_range_hdr_outputs_are_quiet() {
    let workspace = Workspace::new();
    let input = workspace.hdr([0.5, 0.25, 0.125]);
    let result = workspace.bake(
        &input,
        &[
            "--target",
            "specular",
            "--target",
            "irradiance",
            "--output-format",
            "both",
        ],
    );

    assert!(result.stderr.is_empty(), "stderr: {}", result.stderr);
    for name in [
        "specular.ibla",
        "specular.ktx2",
        "irradiance.ibla",
        "irradiance.ktx2",
    ] {
        result.assert_output(name);
    }
}

#[test]
fn both_warns_only_for_the_format_that_clamps() {
    let workspace = Workspace::new();
    let input = workspace.hdr([512.0, 128.0, 64.0]);
    let result = workspace.bake(&input, &["--target", "specular", "--output-format", "both"]);

    assert_eq!(result.warnings().len(), 1, "stderr: {}", result.stderr);
    result.assert_warning("specular.ibla", 126, 255);
    result.assert_output("specular.ktx2");
}

#[test]
fn both_reports_clamping_separately_for_each_format() {
    let workspace = Workspace::new();
    let input = workspace.hdr([131_072.0, 131_072.0, 131_072.0]);
    let result = workspace.bake(&input, &["--target", "specular", "--output-format", "both"]);

    assert_eq!(result.warnings().len(), 2, "stderr: {}", result.stderr);
    result.assert_warning("specular.ibla", 126, 255);
    result.assert_warning("specular.ktx2", 126, 65_504);
}

#[test]
fn warnings_aggregate_faces_and_mips_for_each_target() {
    let workspace = Workspace::new();
    let input = workspace.hdr([512.0, 512.0, 512.0]);
    let result = workspace.bake(
        &input,
        &[
            "--target",
            "specular",
            "--target",
            "irradiance",
            "--output-format",
            "ibla",
        ],
    );

    assert_eq!(result.warnings().len(), 2, "stderr: {}", result.stderr);
    result.assert_warning("specular.ibla", 126, 255);
    result.assert_warning("irradiance.ibla", 24, 255);
}

#[test]
fn srgb_and_linear_warn_above_one() {
    for encoding in ["srgb", "linear"] {
        let workspace = Workspace::new();
        let input = workspace.hdr([2.0, 0.5, 0.25]);
        let result = workspace.bake(&input, &["--target", "specular", "--encoding", encoding]);

        assert_eq!(result.warnings().len(), 1, "stderr: {}", result.stderr);
        result.assert_warning("specular.ibla", 126, 1);
    }
}

#[test]
fn brdf_lut_does_not_warn_for_hdr_source_range() {
    let workspace = Workspace::new();
    let input = workspace.hdr([131_072.0, 131_072.0, 131_072.0]);
    let result = workspace.bake(&input, &["--target", "lut", "--output-format", "both"]);

    assert!(result.stderr.is_empty(), "stderr: {}", result.stderr);
    result.assert_output("brdf-lut.png");
    let png = fs::read(result.output_dir.join("brdf-lut.png")).expect("LUT PNG should exist");
    assert_eq!(&png[..8], b"\x89PNG\r\n\x1a\n");
    assert!(!result.output_dir.join("specular.ibla").exists());
    assert!(!result.output_dir.join("specular.ktx2").exists());
}

#[test]
fn failed_output_write_does_not_emit_a_clamping_warning() {
    let workspace = Workspace::new();
    let input = workspace.hdr([512.0, 512.0, 512.0]);
    let blocked_output = workspace.path.join("outputs").join("specular.ibla");
    fs::create_dir_all(&blocked_output).expect("output path should be blocked by a directory");

    let output = workspace.run_bake(&input, &["--target", "specular"]);
    let stdout = String::from_utf8(output.stdout).expect("stdout should be UTF-8");
    let stderr = String::from_utf8(output.stderr).expect("stderr should be UTF-8");

    assert_eq!(output.status.code(), Some(1), "stderr: {stderr}");
    assert!(stdout.is_empty(), "stdout: {stdout}");
    assert!(stderr.starts_with("Error:"), "stderr: {stderr}");
    assert!(!stderr.contains("Warning:"), "stderr: {stderr}");
    assert!(blocked_output.is_dir());
}

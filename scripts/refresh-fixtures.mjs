import { mkdirSync, readdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(scriptDir, "..");
const fixtureInputsDir = path.join(rootDir, "fixtures", "inputs");
const fixtureOutputsDir = path.join(rootDir, "fixtures", "outputs");

const hdrFixtures = [
  {
    inputPath: "Cannon_Exterior.hdr",
    outputDirName: "cannon_exterior",
  },
  {
    inputPath: "footprint_court.hdr",
    outputDirName: "footprint_court",
  },
  {
    inputPath: "helipad.hdr",
    outputDirName: "helipad",
  },
  {
    inputPath: "pisa.hdr",
    outputDirName: "pisa",
  },
];

const nonHdrFixtures = [
  {
    inputPath: "spruit_sunrise_2k.jpg",
    outputDirName: "spruit_sunrise_2k",
  },
  {
    inputPath: "spruit_sunrise_2k.jpg",
    outputDirName: "spruit_sunrise_2k_ktx2",
    extraArgs: [
      "--target",
      "specular",
      "--target",
      "irradiance",
      "--output-format",
      "ktx2",
    ],
  },
  {
    inputPath: "Bridge2",
    outputDirName: "bridge2",
    extraArgs: ["--faces", "posx.jpg,negx.jpg,posy.jpg,negy.jpg,posz.jpg,negz.jpg"],
  },
];

function cleanObsoleteOutputs(fixtures) {
  const expectedOutputDirs = new Set(fixtures.map((fixture) => fixture.outputDirName));

  for (const entry of readdirSync(fixtureOutputsDir, { withFileTypes: true })) {
    if (!expectedOutputDirs.has(entry.name)) {
      rmSync(path.join(fixtureOutputsDir, entry.name), { recursive: true, force: true });
    }
  }
}

function bakeFixture(fixture) {
  const inputPath = path.join(fixtureInputsDir, fixture.inputPath);
  const outputDir = path.join(fixtureOutputsDir, fixture.outputDirName);

  rmSync(outputDir, { recursive: true, force: true });
  mkdirSync(outputDir, { recursive: true });

  execFileSync(
    "cargo",
    [
      "run",
      "--release",
      "-p",
      "ibl_cli",
      "--",
      "bake",
      inputPath,
      "--out-dir",
      outputDir,
      ...(fixture.extraArgs ?? []),
    ],
    {
      cwd: rootDir,
      stdio: "inherit",
    },
  );
}

const fixtures = [
  ...hdrFixtures.map((fixture) => ({
    ...fixture,
    extraArgs: [...(fixture.extraArgs ?? []), "--output-format", "both"],
  })),
  ...nonHdrFixtures,
];

cleanObsoleteOutputs(fixtures);

for (const fixture of fixtures) {
  bakeFixture(fixture);
}

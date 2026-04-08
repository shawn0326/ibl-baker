import { mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(scriptDir, "..");
const fixtureInputsDir = path.join(rootDir, "fixtures", "inputs");
const fixtureOutputsDir = path.join(rootDir, "fixtures", "outputs");

const fixtures = [
  {
    inputPath: "royal_esplanade_1k.hdr",
    outputDirName: "royal_esplanade_1k",
  },
  {
    inputPath: "Grand_Canyon_C.hdr",
    outputDirName: "grand_canyon_c",
  },
  {
    inputPath: "spruit_sunrise_2k.jpg",
    outputDirName: "spruit_sunrise_2k",
  },
  {
    inputPath: "pisa",
    outputDirName: "pisa",
  },
  {
    inputPath: "Bridge2",
    outputDirName: "bridge2",
    extraArgs: ["--faces", "posx.jpg,negx.jpg,posy.jpg,negy.jpg,posz.jpg,negz.jpg"],
  },
];

for (const fixture of fixtures) {
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

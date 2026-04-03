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
    inputFile: "royal_esplanade_1k.hdr",
    outputDirName: "royal_esplanade_1k",
  },
  {
    inputFile: "Grand_Canyon_C.hdr",
    outputDirName: "grand_canyon_c",
  },
];

for (const fixture of fixtures) {
  const inputPath = path.join(fixtureInputsDir, fixture.inputFile);
  const outputDir = path.join(fixtureOutputsDir, fixture.outputDirName);

  rmSync(outputDir, { recursive: true, force: true });
  mkdirSync(outputDir, { recursive: true });

  execFileSync(
    "cargo",
    [
      "run",
      "-p",
      "ibl_cli",
      "--",
      "bake",
      inputPath,
      "--out-dir",
      outputDir,
    ],
    {
      cwd: rootDir,
      stdio: "inherit",
    },
  );
}

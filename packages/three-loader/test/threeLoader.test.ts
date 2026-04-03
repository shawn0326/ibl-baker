import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { parseIBLA } from "@ibltools/loader";

import {
  ThreeIBLAError,
  assertCubemap,
  decodeRgbdSrgbPixel,
  groupChunksByMip,
  tonemapLinearPixel,
} from "../src/index.ts";

test("decodeRgbdSrgbPixel reconstructs linear HDR values", () => {
  const [r, g, b] = decodeRgbdSrgbPixel(1, 1, 1, 0.5);

  assert.ok(r > 1.9 && r < 2.1);
  assert.ok(g > 1.9 && g < 2.1);
  assert.ok(b > 1.9 && b < 2.1);
});

test("tonemapLinearPixel compresses bright values into display bytes", () => {
  const [r, g, b] = tonemapLinearPixel(4, 1, 0);

  assert.ok(r > g);
  assert.equal(b, 0);
});

test("assertCubemap rejects non-cubemap topology", () => {
  const parsed = parseIBLA(createMinimal2DAsset());

  assert.throws(() => assertCubemap(parsed, "test asset"), (error) => {
    assert.ok(error instanceof ThreeIBLAError);
    assert.match(error.message, /must be a cubemap/i);
    return true;
  });
});

test("groupChunksByMip preserves committed cubemap mip chain ordering", () => {
  const parsed = parseIBLA(loadCommittedFixture("royal_esplanade_1k", "specular"));
  const grouped = groupChunksByMip(parsed.chunks);

  assert.equal(grouped.length, parsed.manifest.mipCount);
  assert.equal(grouped[0]?.length, 6);
  assert.deepEqual(grouped[0]?.map((chunk) => chunk.face), ["px", "nx", "py", "ny", "pz", "nz"]);
  assert.equal(grouped.at(-1)?.[0]?.width, 1);
  assert.equal(grouped.at(-1)?.[0]?.height, 1);
});

function loadCommittedFixture(
  fixtureName: "royal_esplanade_1k",
  target: "specular",
): Uint8Array {
  const rootDir = path.resolve(import.meta.dirname, "..", "..", "..");
  return fs.readFileSync(path.join(rootDir, "fixtures", "outputs", fixtureName, `${target}.ibla`));
}

function createMinimal2DAsset(): Uint8Array {
  const manifest = {
    generator: "ibl-baker",
    generatorVersion: "0.1.0",
    encoding: "srgb",
    container: "png",
    width: 2,
    height: 2,
    mipCount: 1,
    faceCount: 1,
    build: {
      rotation: 0,
      samples: 16,
      quality: "medium",
      sourceFormat: "png",
    },
  };
  const encoder = new TextEncoder();
  const manifestBytes = encoder.encode(JSON.stringify(manifest));
  const chunkTable = new Uint8Array(8);
  new DataView(chunkTable.buffer).setBigUint64(0, 1n, true);
  const header = new Uint8Array(16);
  const view = new DataView(header.buffer);
  header.set(encoder.encode("IBLA"), 0);
  view.setUint16(4, 1, true);
  view.setUint32(8, manifestBytes.byteLength, true);
  view.setUint32(12, chunkTable.byteLength, true);

  return Uint8Array.from([...header, ...manifestBytes, ...chunkTable, 0xff]);
}

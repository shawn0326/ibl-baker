import assert from "node:assert/strict";
import test from "node:test";
import { detectAssetFormat } from "../src/detect-format.ts";

const KTX2_IDENTIFIER = Uint8Array.of(
  0xab,
  0x4b,
  0x54,
  0x58,
  0x20,
  0x32,
  0x30,
  0xbb,
  0x0d,
  0x0a,
  0x1a,
  0x0a,
);

test("detectAssetFormat identifies IBLA by content", () => {
  assert.equal(detectAssetFormat(new TextEncoder().encode("IBLA\0"), "wrong.ktx2"), "ibla");
});

test("detectAssetFormat identifies KTX2 by content", () => {
  assert.equal(detectAssetFormat(KTX2_IDENTIFIER, "wrong.ibla"), "ktx2");
});

test("detectAssetFormat uses a known extension when content is unavailable", () => {
  assert.equal(detectAssetFormat(new Uint8Array(), "asset.ibla"), "ibla");
  assert.equal(detectAssetFormat(new Uint8Array(), "asset.KTX2"), "ktx2");
});

test("detectAssetFormat returns null for unknown input", () => {
  assert.equal(detectAssetFormat(new Uint8Array([1, 2, 3]), "asset.bin"), null);
});

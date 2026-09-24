import assert from "node:assert/strict";
import test from "node:test";
import { bc6hCopyLayout, isBC6HBaseDimensionSupported } from "../src/bc6h-layout.ts";

test("bc6hCopyLayout aligns compressed copy extents to BC6H blocks", () => {
  assert.deepEqual(bc6hCopyLayout(1, 1), {
    bytesPerRow: 16,
    rowsPerImage: 1,
    width: 4,
    height: 4,
  });
  assert.deepEqual(bc6hCopyLayout(5, 3), {
    bytesPerRow: 32,
    rowsPerImage: 1,
    width: 8,
    height: 4,
  });
});

test("isBC6HBaseDimensionSupported rejects unaligned base textures", () => {
  assert.equal(isBC6HBaseDimensionSupported(512, 256), true);
  assert.equal(isBC6HBaseDimensionSupported(5, 4), false);
  assert.equal(isBC6HBaseDimensionSupported(0, 4), false);
});

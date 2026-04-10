import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { KTX2IBLParseError, parseKTX2IBL } from "../src/index.ts";

const HEADER_BYTE_LENGTH = 48;
const INDEX_BYTE_LENGTH = 32;
const LEVEL_INDEX_START = HEADER_BYTE_LENGTH + INDEX_BYTE_LENGTH;
const LEVEL_INDEX_ENTRY_BYTE_LENGTH = 24;
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
const BC6H_UFLOAT_DFD = Uint8Array.of(
  0x2c,
  0x00,
  0x00,
  0x00,
  0x00,
  0x00,
  0x00,
  0x00,
  0x02,
  0x00,
  0x28,
  0x00,
  0x85,
  0x01,
  0x01,
  0x00,
  0x03,
  0x03,
  0x00,
  0x00,
  0x10,
  0x00,
  0x00,
  0x00,
  0x00,
  0x00,
  0x00,
  0x00,
  0x00,
  0x00,
  0x7f,
  0x80,
  0x00,
  0x00,
  0x00,
  0x00,
  0x00,
  0x00,
  0x00,
  0x00,
  0x00,
  0xe0,
  0x7f,
  0x47,
);
const encoder = new TextEncoder();

test("parseKTX2IBL parses a synthetic BC6H zstd cubemap", () => {
  const bytes = createKtx2Bytes({
    pixelWidth: 8,
    levelPayloads: [Uint8Array.of(1, 2, 3), Uint8Array.of(4, 5)],
  });

  const parsed = parseKTX2IBL(bytes);

  assert.deepEqual(parsed.header, {
    vkFormat: 131,
    typeSize: 1,
    pixelWidth: 8,
    pixelHeight: 8,
    pixelDepth: 0,
    layerCount: 0,
    faceCount: 6,
    levelCount: 2,
    supercompressionScheme: 2,
  });
  assert.equal(parsed.format.vkFormatName, "VK_FORMAT_BC6H_UFLOAT_BLOCK");
  assert.equal(parsed.format.supercompression, "zstd");
  assert.equal(parsed.keyValues.KTXorientation, "rd");
  assert.equal(parsed.keyValues.KTXwriter, "ibl-baker test");
  assert.equal(parsed.levels.length, 2);

  const level0 = expectDefined(parsed.levels[0]);
  const level1 = expectDefined(parsed.levels[1]);
  assert.equal(level0.width, 8);
  assert.equal(level0.height, 8);
  assert.equal(level0.uncompressedByteLength, 384);
  assert.deepEqual([...level0.compressedBytes], [1, 2, 3]);
  assert.deepEqual(level0.faces.map((face) => face.face), ["px", "nx", "py", "ny", "pz", "nz"]);
  assert.deepEqual(summarizeFace(expectDefined(level0.faces[0])), {
    face: "px",
    width: 8,
    height: 8,
    uncompressedByteOffset: 0,
    uncompressedByteLength: 64,
  });
  assert.deepEqual(summarizeFace(expectDefined(level0.faces[5])), {
    face: "nz",
    width: 8,
    height: 8,
    uncompressedByteOffset: 320,
    uncompressedByteLength: 64,
  });

  assert.equal(level1.width, 4);
  assert.equal(level1.height, 4);
  assert.equal(level1.uncompressedByteLength, 96);
  assert.deepEqual([...level1.compressedBytes], [4, 5]);
});

test("parseKTX2IBL parses committed specular fixtures", () => {
  for (const fixtureName of KTX2_FIXTURE_NAMES) {
    const parsed = parseKTX2IBL(loadCommittedFixture(fixtureName, "specular"));

    assert.equal(parsed.header.faceCount, 6);
    assert.ok(parsed.header.pixelWidth >= 128);
    assert.equal(parsed.header.pixelWidth, parsed.header.pixelHeight);
    assert.ok(parsed.header.levelCount >= 1);
    assert.equal(parsed.levels.at(-1)?.width, 1);
    assert.ok(parsed.levels.every((level) => level.faces.length === 6));
    assert.ok(parsed.levels.every((level) => level.byteLength > 0));
  }
});

test("parseKTX2IBL parses committed irradiance fixtures", () => {
  for (const fixtureName of KTX2_FIXTURE_NAMES) {
    const parsed = parseKTX2IBL(loadCommittedFixture(fixtureName, "irradiance"));

    assert.equal(parsed.header.pixelWidth, 32);
    assert.equal(parsed.header.pixelHeight, 32);
    assert.equal(parsed.header.levelCount, 1);
    assert.equal(parsed.levels[0]?.uncompressedByteLength, 6144);
    assert.equal(parsed.levels[0]?.faces[0]?.uncompressedByteLength, 1024);
  }
});

test("parseKTX2IBL throws INVALID_HEADER for bad magic", () => {
  const bytes = createKtx2Bytes({ pixelWidth: 4, levelPayloads: [Uint8Array.of(1)] });
  bytes[0] = 0;

  assertParseError(() => parseKTX2IBL(bytes), "INVALID_HEADER");
});

test("parseKTX2IBL throws UNSUPPORTED_FORMAT for non-BC6H format", () => {
  const bytes = createKtx2Bytes({ pixelWidth: 4, levelPayloads: [Uint8Array.of(1)] });
  new DataView(bytes.buffer).setUint32(12, 37, true);

  assertParseError(() => parseKTX2IBL(bytes), "UNSUPPORTED_FORMAT");
});

test("parseKTX2IBL throws UNSUPPORTED_TOPOLOGY for non-cubemap assets", () => {
  const bytes = createKtx2Bytes({ pixelWidth: 4, levelPayloads: [Uint8Array.of(1)] });
  new DataView(bytes.buffer).setUint32(36, 1, true);

  assertParseError(() => parseKTX2IBL(bytes), "UNSUPPORTED_TOPOLOGY");
});

test("parseKTX2IBL throws INVALID_DATA_FORMAT_DESCRIPTOR for descriptor mismatch", () => {
  const bytes = createKtx2Bytes({ pixelWidth: 4, levelPayloads: [Uint8Array.of(1)] });
  const dfdByteOffset = LEVEL_INDEX_START + LEVEL_INDEX_ENTRY_BYTE_LENGTH;
  bytes[dfdByteOffset + 12] = 0;

  assertParseError(() => parseKTX2IBL(bytes), "INVALID_DATA_FORMAT_DESCRIPTOR");
});

test("parseKTX2IBL throws INVALID_KEY_VALUE_DATA for non-IBL writer metadata", () => {
  const bytes = createKtx2Bytes({
    pixelWidth: 4,
    levelPayloads: [Uint8Array.of(1)],
    keyValues: {
      KTXorientation: "rd",
      KTXwriter: "other-writer",
    },
  });

  assertParseError(() => parseKTX2IBL(bytes), "INVALID_KEY_VALUE_DATA");
});

test("parseKTX2IBL throws INVALID_LEVEL_INDEX for inconsistent uncompressed length", () => {
  const bytes = createKtx2Bytes({ pixelWidth: 4, levelPayloads: [Uint8Array.of(1)] });
  new DataView(bytes.buffer).setBigUint64(LEVEL_INDEX_START + 16, 1n, true);

  assertParseError(() => parseKTX2IBL(bytes), "INVALID_LEVEL_INDEX");
});

function summarizeFace(face: ReturnType<typeof parseKTX2IBL>["levels"][number]["faces"][number]) {
  return {
    face: face.face,
    width: face.width,
    height: face.height,
    uncompressedByteOffset: face.uncompressedByteOffset,
    uncompressedByteLength: face.uncompressedByteLength,
  };
}

function expectDefined<T>(value: T): Exclude<T, undefined> {
  assert.notEqual(value, undefined);
  return value as Exclude<T, undefined>;
}

function assertParseError(action: () => unknown, code: string) {
  assert.throws(action, (error) => {
    assert.ok(error instanceof KTX2IBLParseError);
    assert.equal(error.code, code);
    return true;
  });
}

const KTX2_FIXTURE_NAMES = [
  "cannon_exterior",
  "footprint_court",
  "helipad",
  "pisa",
  "spruit_sunrise_2k_ktx2",
] as const;

function loadCommittedFixture(
  fixtureName: (typeof KTX2_FIXTURE_NAMES)[number],
  target: "irradiance" | "specular",
): Uint8Array {
  const rootDir = path.resolve(import.meta.dirname, "..", "..", "..");
  const fixturePath = path.join(rootDir, "fixtures", "outputs", fixtureName, `${target}.ktx2`);
  return fs.readFileSync(fixturePath);
}

function createKtx2Bytes(options: {
  pixelWidth: number;
  levelPayloads: Uint8Array[];
  keyValues?: Record<string, string>;
}): Uint8Array {
  const levelCount = options.levelPayloads.length;
  const levelIndexByteLength = levelCount * LEVEL_INDEX_ENTRY_BYTE_LENGTH;
  const dfdByteOffset = LEVEL_INDEX_START + levelIndexByteLength;
  const kvd = buildKeyValueData(
    options.keyValues ?? {
      KTXorientation: "rd",
      KTXwriter: "ibl-baker test",
    },
  );
  const kvdByteOffset = dfdByteOffset + BC6H_UFLOAT_DFD.byteLength;
  const imageDataStart = kvdByteOffset + kvd.byteLength;

  const levelOffsets = new Array<number>(levelCount);
  let cursor = imageDataStart;
  for (let mipLevel = levelCount - 1; mipLevel >= 0; mipLevel -= 1) {
    levelOffsets[mipLevel] = cursor;
    const payload = expectDefined(options.levelPayloads[mipLevel]);
    cursor += payload.byteLength;
  }

  const out = new Uint8Array(cursor);
  const view = new DataView(out.buffer);
  out.set(KTX2_IDENTIFIER, 0);
  view.setUint32(12, 131, true);
  view.setUint32(16, 1, true);
  view.setUint32(20, options.pixelWidth, true);
  view.setUint32(24, options.pixelWidth, true);
  view.setUint32(28, 0, true);
  view.setUint32(32, 0, true);
  view.setUint32(36, 6, true);
  view.setUint32(40, levelCount, true);
  view.setUint32(44, 2, true);
  view.setUint32(48, dfdByteOffset, true);
  view.setUint32(52, BC6H_UFLOAT_DFD.byteLength, true);
  view.setUint32(56, kvdByteOffset, true);
  view.setUint32(60, kvd.byteLength, true);
  view.setBigUint64(64, 0n, true);
  view.setBigUint64(72, 0n, true);

  for (let mipLevel = 0; mipLevel < levelCount; mipLevel += 1) {
    const entryOffset = LEVEL_INDEX_START + mipLevel * LEVEL_INDEX_ENTRY_BYTE_LENGTH;
    const payload = expectDefined(options.levelPayloads[mipLevel]);
    view.setBigUint64(entryOffset, BigInt(expectDefined(levelOffsets[mipLevel])), true);
    view.setBigUint64(entryOffset + 8, BigInt(payload.byteLength), true);
    view.setBigUint64(entryOffset + 16, BigInt(bc6hLevelByteLength(options.pixelWidth, mipLevel)), true);
  }

  out.set(BC6H_UFLOAT_DFD, dfdByteOffset);
  out.set(kvd, kvdByteOffset);
  for (let mipLevel = levelCount - 1; mipLevel >= 0; mipLevel -= 1) {
    out.set(expectDefined(options.levelPayloads[mipLevel]), expectDefined(levelOffsets[mipLevel]));
  }

  return out;
}

function buildKeyValueData(keyValues: Record<string, string>): Uint8Array {
  return Uint8Array.from(
    Object.entries(keyValues).flatMap(([key, value]) => {
      const keyAndValue = encoder.encode(`${key}\0${value}\0`);
      const padding = (4 - (keyAndValue.byteLength % 4)) % 4;
      const entry = new Uint8Array(4 + keyAndValue.byteLength + padding);
      const view = new DataView(entry.buffer);
      view.setUint32(0, keyAndValue.byteLength, true);
      entry.set(keyAndValue, 4);
      return [...entry];
    }),
  );
}

function bc6hLevelByteLength(baseSize: number, mipLevel: number): number {
  const size = Math.max(1, Math.floor(baseSize / 2 ** mipLevel));
  const blocks = Math.ceil(size / 4);
  return blocks * blocks * 16 * 6;
}

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import {
  IBLAParseError,
  type ParsedIBLA,
  parseIBLA,
} from "../src/index.ts";

const HEADER_BYTE_LENGTH = 16;
const encoder = new TextEncoder();

test("parseIBLA parses a synthetic 2D asset with derived mip metadata", () => {
  const bytes = createIblaBytes({
    manifest: {
      generator: "ibl-baker",
      generatorVersion: "0.1.0",
      encoding: "srgb",
      container: "png",
      width: 4,
      height: 2,
      mipCount: 2,
      faceCount: 1,
      build: {
        rotation: 0,
        samples: 16,
        quality: "medium",
        sourceFormat: "png",
      },
    },
    chunkPayloads: [Uint8Array.of(1, 2, 3, 4), Uint8Array.of(5, 6)],
  });

  const parsed = parseIBLA(bytes);
  assert.deepEqual(parsed.header, { version: 1, flags: 0 });
  assert.deepEqual(parsed.topology, {
    kind: "2d",
    width: 4,
    height: 2,
    mipCount: 2,
    faceCount: 1,
  });
  assert.equal(parsed.chunks.length, 2);
  const firstChunk = expectDefined(parsed.chunks[0]);
  const secondChunk = expectDefined(parsed.chunks[1]);
  assert.deepEqual(summarizeChunk(firstChunk), {
    mipLevel: 0,
    face: null,
    width: 4,
    height: 2,
    byteOffset: 0,
    byteLength: 4,
  });
  assert.deepEqual(summarizeChunk(secondChunk), {
    mipLevel: 1,
    face: null,
    width: 2,
    height: 1,
    byteOffset: 4,
    byteLength: 2,
  });
  assert.deepEqual([...firstChunk.encodedBytes], [1, 2, 3, 4]);
  assert.deepEqual([...secondChunk.encodedBytes], [5, 6]);
});

test("parseIBLA parses a Rust-generated irradiance cubemap", () => {
  const parsed = parseIBLA(loadCommittedFixture("royal_esplanade_1k", "irradiance"));

  assert.equal(parsed.topology.kind, "cubemap");
  assert.equal(parsed.manifest.faceCount, 6);
  assert.equal(parsed.manifest.mipCount, 1);
  assert.deepEqual(parsed.topology.faceOrder, ["px", "nx", "py", "ny", "pz", "nz"]);
  assert.equal(parsed.chunks.length, 6);
  assert.deepEqual(parsed.chunks.map((chunk) => chunk.face), ["px", "nx", "py", "ny", "pz", "nz"]);
  assert.ok(parsed.chunks.every((chunk) => chunk.width === 32 && chunk.height === 32));
  assert.ok(parsed.chunks.every((chunk) => chunk.encodedBytes.byteLength > 0));
});

test("parseIBLA parses a Rust-generated specular cubemap with mip chain", () => {
  const parsed = parseIBLA(loadCommittedFixture("royal_esplanade_1k", "specular"));

  assert.equal(parsed.topology.kind, "cubemap");
  assert.equal(parsed.manifest.faceCount, 6);
  assert.equal(parsed.manifest.mipCount, 9);
  assert.equal(parsed.chunks.length, 54);
  assert.deepEqual(parsed.chunks.slice(0, 6).map((chunk) => chunk.face), [
    "px",
    "nx",
    "py",
    "ny",
    "pz",
    "nz",
  ]);
  const firstChunk = expectDefined(parsed.chunks[0]);
  assert.equal(firstChunk.width, 256);
  assert.equal(firstChunk.height, 256);
  assert.equal(parsed.chunks.at(-1)?.width, 1);
  assert.equal(parsed.chunks.at(-1)?.height, 1);
});

test("parseIBLA parses the committed Grand Canyon specular cubemap fixture", () => {
  const parsed = parseIBLA(loadCommittedFixture("grand_canyon_c", "specular"));

  assert.equal(parsed.topology.kind, "cubemap");
  assert.equal(parsed.manifest.faceCount, 6);
  assert.equal(parsed.manifest.mipCount, 8);
  assert.equal(parsed.chunks.length, 48);
  assert.equal(parsed.manifest.build.sourceFormat, "hdr");
  assert.equal(parsed.manifest.width, 128);
  assert.equal(parsed.manifest.height, 128);
  assert.deepEqual(parsed.chunks.slice(0, 6).map((chunk) => chunk.face), [
    "px",
    "nx",
    "py",
    "ny",
    "pz",
    "nz",
  ]);
});

test("parseIBLA parses the committed Grand Canyon irradiance cubemap fixture", () => {
  const parsed = parseIBLA(loadCommittedFixture("grand_canyon_c", "irradiance"));

  assert.equal(parsed.topology.kind, "cubemap");
  assert.equal(parsed.manifest.faceCount, 6);
  assert.equal(parsed.manifest.mipCount, 1);
  assert.equal(parsed.chunks.length, 6);
  assert.ok(parsed.chunks.every((chunk) => chunk.width === 32 && chunk.height === 32));
});

test("parseIBLA throws INVALID_HEADER for bad magic", () => {
  assertParseError(
    () =>
      parseIBLA(
        Uint8Array.from([
          0x42,
          0x41,
          0x44,
          0x21,
          ...new Uint8Array(HEADER_BYTE_LENGTH - 4),
        ]),
      ),
    "INVALID_HEADER",
  );
});

test("parseIBLA throws UNSUPPORTED_VERSION for non-v1 assets", () => {
  const bytes = createIblaBytes({
    version: 2,
    manifest: baseManifest(),
    chunkPayloads: [Uint8Array.of(1, 2, 3)],
  });

  assertParseError(() => parseIBLA(bytes), "UNSUPPORTED_VERSION");
});

test("parseIBLA throws INVALID_MANIFEST for malformed JSON", () => {
  const bytes = createRawIblaBytes({
    manifestText: "{not-json",
    chunkTableByteLengths: [3],
    chunkPayloads: [Uint8Array.of(1, 2, 3)],
  });

  assertParseError(() => parseIBLA(bytes), "INVALID_MANIFEST");
});

test("parseIBLA throws UNSUPPORTED_FACE_COUNT for unsupported topology", () => {
  const bytes = createIblaBytes({
    manifest: {
      ...baseManifest(),
      faceCount: 2,
    },
    chunkPayloads: [Uint8Array.of(1), Uint8Array.of(2)],
  });

  assertParseError(() => parseIBLA(bytes), "UNSUPPORTED_FACE_COUNT");
});

test("parseIBLA throws INVALID_CUBEMAP_DIMENSIONS for non-square cubemaps", () => {
  const bytes = createIblaBytes({
    manifest: {
      ...baseManifest(),
      width: 8,
      height: 4,
      faceCount: 6,
      encoding: "rgbd-srgb",
      build: {
        rotation: 0,
        samples: 128,
        quality: "medium",
        sourceFormat: "hdr",
      },
    },
    chunkPayloads: Array.from({ length: 6 }, (_, index) => Uint8Array.of(index)),
  });

  assertParseError(() => parseIBLA(bytes), "INVALID_CUBEMAP_DIMENSIONS");
});

test("parseIBLA throws INVALID_CHUNK_TABLE_LENGTH for inconsistent table bytes", () => {
  const manifest = {
    ...baseManifest(),
    mipCount: 2,
  };
  const bytes = createRawIblaBytes({
    manifestText: JSON.stringify(manifest),
    chunkTableByteLengths: [4],
    declaredChunkTableByteLength: 8,
    chunkPayloads: [Uint8Array.of(1, 2, 3, 4)],
  });

  assertParseError(() => parseIBLA(bytes), "INVALID_CHUNK_TABLE_LENGTH");
});

test("parseIBLA throws CHUNK_RANGE_OUT_OF_BOUNDS when payload exceeds binary section", () => {
  const bytes = createIblaBytes({
    manifest: baseManifest(),
    chunkPayloads: [Uint8Array.of(1, 2, 3)],
    chunkTableByteLengths: [6],
  });

  assertParseError(() => parseIBLA(bytes), "CHUNK_RANGE_OUT_OF_BOUNDS");
});

function summarizeChunk(chunk: ParsedIBLA["chunks"][number]) {
  return {
    mipLevel: chunk.mipLevel,
    face: chunk.face,
    width: chunk.width,
    height: chunk.height,
    byteOffset: chunk.byteOffset,
    byteLength: chunk.byteLength,
  };
}

function expectDefined<T>(value: T): Exclude<T, undefined> {
  assert.notEqual(value, undefined);
  return value as Exclude<T, undefined>;
}

function assertParseError(action: () => unknown, code: string) {
  assert.throws(action, (error) => {
    assert.ok(error instanceof IBLAParseError);
    assert.equal(error.code, code);
    return true;
  });
}

function loadCommittedFixture(
  fixtureName: "royal_esplanade_1k" | "grand_canyon_c",
  target: "irradiance" | "specular",
): Uint8Array {
  const rootDir = path.resolve(import.meta.dirname, "..", "..", "..");
  const fixturePath = path.join(rootDir, "fixtures", "outputs", fixtureName, `${target}.ibla`);
  return fs.readFileSync(fixturePath);
}

function baseManifest() {
  return {
    generator: "ibl-baker",
    generatorVersion: "0.1.0",
    encoding: "srgb",
    container: "png",
    width: 4,
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
}

function createIblaBytes(options: {
  version?: number;
  manifest: Record<string, unknown>;
  chunkPayloads: Uint8Array[];
  chunkTableByteLengths?: number[];
}) {
  return createRawIblaBytes({
    version: options.version ?? 1,
    manifestText: JSON.stringify(options.manifest),
    chunkTableByteLengths:
      options.chunkTableByteLengths ?? options.chunkPayloads.map((payload) => payload.byteLength),
    chunkPayloads: options.chunkPayloads,
  });
}

function createRawIblaBytes(options: {
  version?: number;
  flags?: number;
  manifestText: string;
  chunkTableByteLengths: number[];
  chunkPayloads: Uint8Array[];
  declaredChunkTableByteLength?: number;
}) {
  const manifestBytes = encoder.encode(options.manifestText);
  const chunkTableByteLength =
    options.declaredChunkTableByteLength ?? options.chunkTableByteLengths.length * 8;
  const header = new Uint8Array(HEADER_BYTE_LENGTH);
  const headerView = new DataView(header.buffer);

  header.set(encoder.encode("IBLA"), 0);
  headerView.setUint16(4, options.version ?? 1, true);
  headerView.setUint16(6, options.flags ?? 0, true);
  headerView.setUint32(8, manifestBytes.byteLength, true);
  headerView.setUint32(12, chunkTableByteLength, true);

  const chunkTable = new Uint8Array(options.chunkTableByteLengths.length * 8);
  const chunkTableView = new DataView(chunkTable.buffer);
  options.chunkTableByteLengths.forEach((byteLength, index) => {
    chunkTableView.setBigUint64(index * 8, BigInt(byteLength), true);
  });

  return Uint8Array.from([
    ...header,
    ...manifestBytes,
    ...chunkTable,
    ...options.chunkPayloads.flatMap((payload) => [...payload]),
  ]);
}

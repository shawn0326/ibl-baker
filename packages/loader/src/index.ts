export type FaceName = "px" | "nx" | "py" | "ny" | "pz" | "nz";

export type BakeQuality = "low" | "medium" | "high";

export type IBLAParseErrorCode =
  | "INVALID_HEADER"
  | "UNSUPPORTED_VERSION"
  | "INVALID_MANIFEST"
  | "UNSUPPORTED_FACE_COUNT"
  | "INVALID_CUBEMAP_DIMENSIONS"
  | "INVALID_CHUNK_TABLE_LENGTH"
  | "CHUNK_RANGE_OUT_OF_BOUNDS";

export class IBLAParseError extends Error {
  readonly code: IBLAParseErrorCode;

  constructor(code: IBLAParseErrorCode, message: string) {
    super(message);
    this.name = "IBLAParseError";
    this.code = code;
  }
}

export type TextureTopology =
  | {
      kind: "2d";
      width: number;
      height: number;
      mipCount: number;
      faceCount: 1;
    }
  | {
      kind: "cubemap";
      width: number;
      height: number;
      mipCount: number;
      faceCount: 6;
      faceOrder: readonly ["px", "nx", "py", "ny", "pz", "nz"];
    };

export interface ParsedIBLA {
  header: {
    version: number;
    flags: number;
  };
  manifest: {
    generator: string;
    generatorVersion: string;
    encoding: "rgbd-srgb" | "srgb" | "linear";
    container: "png";
    width: number;
    height: number;
    mipCount: number;
    faceCount: 1 | 6;
    build: {
      rotation: number;
      samples: number;
      quality: BakeQuality;
      sourceFormat: "hdr" | "exr" | "png" | "jpg" | "jpeg" | "unknown";
    };
  };
  topology: TextureTopology;
  chunks: ParsedChunk[];
}

export interface ParsedChunk {
  index: number;
  mipLevel: number;
  face: FaceName | null;
  width: number;
  height: number;
  byteOffset: number;
  byteLength: number;
  encodedBytes: Uint8Array;
}

const HEADER_BYTE_LENGTH = 16;
const FORMAT_MAGIC = "IBLA";
const FORMAT_VERSION = 1;
const CHUNK_TABLE_ENTRY_BYTE_LENGTH = 8;
const FACE_ORDER = ["px", "nx", "py", "ny", "pz", "nz"] as const;
const SUPPORTED_ENCODINGS = new Set(["rgbd-srgb", "srgb", "linear"]);
const SUPPORTED_QUALITIES = new Set(["low", "medium", "high"]);
const SUPPORTED_SOURCE_FORMATS = new Set([
  "hdr",
  "exr",
  "png",
  "jpg",
  "jpeg",
  "unknown",
]);

const utf8Decoder = new TextDecoder("utf-8", { fatal: true });

export function parseIBLA(buffer: ArrayBuffer | Uint8Array): ParsedIBLA {
  const bytes = toUint8Array(buffer);
  if (bytes.byteLength < HEADER_BYTE_LENGTH) {
    throw new IBLAParseError(
      "INVALID_HEADER",
      `Expected at least ${HEADER_BYTE_LENGTH} header bytes, received ${bytes.byteLength}.`,
    );
  }

  const headerView = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const magic = decodeAscii(bytes.subarray(0, 4));
  if (magic !== FORMAT_MAGIC) {
    throw new IBLAParseError(
      "INVALID_HEADER",
      `Unexpected file magic "${magic}", expected "${FORMAT_MAGIC}".`,
    );
  }

  const version = headerView.getUint16(4, true);
  if (version !== FORMAT_VERSION) {
    throw new IBLAParseError(
      "UNSUPPORTED_VERSION",
      `Unsupported .ibla version ${version}; expected ${FORMAT_VERSION}.`,
    );
  }

  const flags = headerView.getUint16(6, true);
  const manifestByteLength = headerView.getUint32(8, true);
  const chunkTableByteLength = headerView.getUint32(12, true);
  const manifestStart = HEADER_BYTE_LENGTH;
  const manifestEnd = manifestStart + manifestByteLength;
  const chunkTableEnd = manifestEnd + chunkTableByteLength;

  if (chunkTableEnd > bytes.byteLength) {
    throw new IBLAParseError(
      "INVALID_HEADER",
      "Header section lengths exceed the available file size.",
    );
  }

  const manifestBytes = bytes.subarray(manifestStart, manifestEnd);
  const manifestText = decodeUtf8Manifest(manifestBytes);
  const manifest = parseManifest(manifestText);
  const topology = buildTopology(manifest);
  const expectedChunkCount = manifest.mipCount * manifest.faceCount;
  const expectedChunkTableByteLength = expectedChunkCount * CHUNK_TABLE_ENTRY_BYTE_LENGTH;
  if (chunkTableByteLength !== expectedChunkTableByteLength) {
    throw new IBLAParseError(
      "INVALID_CHUNK_TABLE_LENGTH",
      `Chunk table byte length ${chunkTableByteLength} does not match expected ${expectedChunkTableByteLength}.`,
    );
  }

  const chunkTableBytes = bytes.subarray(manifestEnd, chunkTableEnd);
  const binarySection = bytes.subarray(chunkTableEnd);
  const chunkTableView = new DataView(
    chunkTableBytes.buffer,
    chunkTableBytes.byteOffset,
    chunkTableBytes.byteLength,
  );

  const chunks: ParsedChunk[] = [];
  let byteOffset = 0;
  for (let index = 0; index < expectedChunkCount; index += 1) {
    const byteLength = readSafeU64(
      chunkTableView,
      index * CHUNK_TABLE_ENTRY_BYTE_LENGTH,
      "INVALID_CHUNK_TABLE_LENGTH",
    );
    const end = byteOffset + byteLength;
    if (end > binarySection.byteLength) {
      throw new IBLAParseError(
        "CHUNK_RANGE_OUT_OF_BOUNDS",
        `Chunk ${index} exceeds the binary section (${end} > ${binarySection.byteLength}).`,
      );
    }

    const { mipLevel, face, width, height } = deriveChunkMetadata(
      manifest.width,
      manifest.height,
      manifest.faceCount,
      index,
    );

    chunks.push({
      index,
      mipLevel,
      face,
      width,
      height,
      byteOffset,
      byteLength,
      encodedBytes: binarySection.subarray(byteOffset, end),
    });
    byteOffset = end;
  }

  return {
    header: {
      version,
      flags,
    },
    manifest,
    topology,
    chunks,
  };
}

function toUint8Array(buffer: ArrayBuffer | Uint8Array): Uint8Array {
  return buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
}

function decodeAscii(bytes: Uint8Array): string {
  return String.fromCharCode(...bytes);
}

function decodeUtf8Manifest(bytes: Uint8Array): string {
  try {
    return utf8Decoder.decode(bytes);
  } catch (error) {
    const message = error instanceof Error ? error.message : "manifest is not valid UTF-8";
    throw new IBLAParseError("INVALID_MANIFEST", message);
  }
}

function parseManifest(text: string): ParsedIBLA["manifest"] {
  let manifestValue: unknown;
  try {
    manifestValue = JSON.parse(text);
  } catch (error) {
    const message = error instanceof Error ? error.message : "manifest JSON is invalid";
    throw new IBLAParseError("INVALID_MANIFEST", message);
  }

  const manifest = asRecord(manifestValue, "Manifest must be a JSON object.");
  const build = asRecord(manifest.build, "Manifest build must be an object.");
  const encoding = readEnum(manifest, "encoding", SUPPORTED_ENCODINGS);
  const container = readLiteral(manifest, "container", "png");
  const width = readPositiveInteger(manifest, "width");
  const height = readPositiveInteger(manifest, "height");
  const mipCount = readPositiveInteger(manifest, "mipCount");
  const faceCount = readPositiveInteger(manifest, "faceCount");

  if (faceCount !== 1 && faceCount !== 6) {
    throw new IBLAParseError(
      "UNSUPPORTED_FACE_COUNT",
      `Unsupported faceCount ${faceCount}; expected 1 or 6.`,
    );
  }

  if (faceCount === 6 && width !== height) {
    throw new IBLAParseError(
      "INVALID_CUBEMAP_DIMENSIONS",
      `Cubemap width and height must match, received ${width}x${height}.`,
    );
  }

  return {
    generator: readString(manifest, "generator"),
    generatorVersion: readString(manifest, "generatorVersion"),
    encoding,
    container,
    width,
    height,
    mipCount,
    faceCount,
    build: {
      rotation: readFiniteNumber(build, "rotation"),
      samples: readPositiveInteger(build, "samples"),
      quality: readEnum(build, "quality", SUPPORTED_QUALITIES) as BakeQuality,
      sourceFormat: readEnum(build, "sourceFormat", SUPPORTED_SOURCE_FORMATS) as
        | "hdr"
        | "exr"
        | "png"
        | "jpg"
        | "jpeg"
        | "unknown",
    },
  };
}

function buildTopology(manifest: ParsedIBLA["manifest"]): TextureTopology {
  if (manifest.faceCount === 1) {
    return {
      kind: "2d",
      width: manifest.width,
      height: manifest.height,
      mipCount: manifest.mipCount,
      faceCount: 1,
    };
  }

  return {
    kind: "cubemap",
    width: manifest.width,
    height: manifest.height,
    mipCount: manifest.mipCount,
    faceCount: 6,
    faceOrder: FACE_ORDER,
  };
}

function deriveChunkMetadata(
  width: number,
  height: number,
  faceCount: 1 | 6,
  index: number,
): { mipLevel: number; face: FaceName | null; width: number; height: number } {
  if (faceCount === 1) {
    const mipLevel = index;
    return {
      mipLevel,
      face: null,
      width: dimensionAtMip(width, mipLevel),
      height: dimensionAtMip(height, mipLevel),
    };
  }

  const mipLevel = Math.floor(index / FACE_ORDER.length);
  const face = FACE_ORDER[index % FACE_ORDER.length];
  const size = dimensionAtMip(width, mipLevel);
  return {
    mipLevel,
    face,
    width: size,
    height: size,
  };
}

function dimensionAtMip(base: number, mipLevel: number): number {
  return Math.max(1, Math.floor(base / 2 ** mipLevel));
}

function readSafeU64(
  view: DataView,
  byteOffset: number,
  code: Extract<IBLAParseErrorCode, "INVALID_CHUNK_TABLE_LENGTH">,
): number {
  const value = view.getBigUint64(byteOffset, true);
  if (value > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new IBLAParseError(code, "Chunk table value exceeds JavaScript safe integer range.");
  }

  return Number(value);
}

function asRecord(value: unknown, message: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new IBLAParseError("INVALID_MANIFEST", message);
  }

  return value as Record<string, unknown>;
}

function readString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string") {
    throw new IBLAParseError("INVALID_MANIFEST", `Manifest field "${key}" must be a string.`);
  }

  return value;
}

function readFiniteNumber(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new IBLAParseError("INVALID_MANIFEST", `Manifest field "${key}" must be a finite number.`);
  }

  return value;
}

function readPositiveInteger(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (!Number.isInteger(value) || (value as number) <= 0) {
    throw new IBLAParseError(
      "INVALID_MANIFEST",
      `Manifest field "${key}" must be a positive integer.`,
    );
  }

  return value as number;
}

function readEnum<T extends string>(
  record: Record<string, unknown>,
  key: string,
  allowed: Set<T>,
): T {
  const value = readString(record, key);
  if (!allowed.has(value as T)) {
    throw new IBLAParseError(
      "INVALID_MANIFEST",
      `Manifest field "${key}" has unsupported value "${value}".`,
    );
  }

  return value as T;
}

function readLiteral<T extends string>(
  record: Record<string, unknown>,
  key: string,
  expected: T,
): T {
  const value = readString(record, key);
  if (value !== expected) {
    throw new IBLAParseError(
      "INVALID_MANIFEST",
      `Manifest field "${key}" must be "${expected}", received "${value}".`,
    );
  }

  return expected;
}

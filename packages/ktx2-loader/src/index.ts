export type KTX2IBLFaceName = "px" | "nx" | "py" | "ny" | "pz" | "nz";

export type KTX2IBLParseErrorCode =
  | "INVALID_HEADER"
  | "UNSUPPORTED_FORMAT"
  | "UNSUPPORTED_TOPOLOGY"
  | "INVALID_INDEX"
  | "INVALID_LEVEL_INDEX"
  | "INVALID_DATA_FORMAT_DESCRIPTOR"
  | "INVALID_KEY_VALUE_DATA";

export class KTX2IBLParseError extends Error {
  readonly code: KTX2IBLParseErrorCode;

  constructor(code: KTX2IBLParseErrorCode, message: string) {
    super(message);
    this.name = "KTX2IBLParseError";
    this.code = code;
  }
}

export interface ParsedKTX2IBL {
  header: {
    vkFormat: 131;
    typeSize: 1;
    pixelWidth: number;
    pixelHeight: number;
    pixelDepth: 0;
    layerCount: 0;
    faceCount: 6;
    levelCount: number;
    supercompressionScheme: 2;
  };
  format: {
    vkFormatName: "VK_FORMAT_BC6H_UFLOAT_BLOCK";
    supercompression: "zstd";
    blockWidth: 4;
    blockHeight: 4;
    bytesPerBlock: 16;
  };
  keyValues: Record<string, string>;
  levels: ParsedKTX2IBLLevel[];
}

export interface ParsedKTX2IBLLevel {
  mipLevel: number;
  width: number;
  height: number;
  byteOffset: number;
  byteLength: number;
  uncompressedByteLength: number;
  compressedBytes: Uint8Array;
  faces: ParsedKTX2IBLFace[];
}

export interface ParsedKTX2IBLFace {
  face: KTX2IBLFaceName;
  width: number;
  height: number;
  uncompressedByteOffset: number;
  uncompressedByteLength: number;
}

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
const HEADER_BYTE_LENGTH = 48;
const INDEX_BYTE_LENGTH = 32;
const LEVEL_INDEX_ENTRY_BYTE_LENGTH = 24;
const LEVEL_INDEX_START = HEADER_BYTE_LENGTH + INDEX_BYTE_LENGTH;
const VK_FORMAT_BC6H_UFLOAT_BLOCK = 131;
const SUPERCOMPRESSION_ZSTD = 2;
const CUBEMAP_FACE_COUNT = 6;
const BLOCK_WIDTH = 4;
const BLOCK_HEIGHT = 4;
const BYTES_PER_BC6H_BLOCK = 16;
const FACE_ORDER = ["px", "nx", "py", "ny", "pz", "nz"] as const;

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

const utf8Decoder = new TextDecoder("utf-8", { fatal: true });

export function parseKTX2IBL(buffer: ArrayBuffer | Uint8Array): ParsedKTX2IBL {
  const bytes = toUint8Array(buffer);
  if (bytes.byteLength < LEVEL_INDEX_START) {
    throw new KTX2IBLParseError(
      "INVALID_HEADER",
      `Expected at least ${LEVEL_INDEX_START} KTX2 header bytes, received ${bytes.byteLength}.`,
    );
  }

  if (!bytesEqual(bytes.subarray(0, KTX2_IDENTIFIER.byteLength), KTX2_IDENTIFIER)) {
    throw new KTX2IBLParseError("INVALID_HEADER", "Unexpected KTX2 identifier bytes.");
  }

  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const header = {
    vkFormat: readU32(view, 12),
    typeSize: readU32(view, 16),
    pixelWidth: readU32(view, 20),
    pixelHeight: readU32(view, 24),
    pixelDepth: readU32(view, 28),
    layerCount: readU32(view, 32),
    faceCount: readU32(view, 36),
    levelCount: readU32(view, 40),
    supercompressionScheme: readU32(view, 44),
  };

  validateHeaderProfile(header);

  const dfdByteOffset = readU32(view, 48);
  const dfdByteLength = readU32(view, 52);
  const kvdByteOffset = readU32(view, 56);
  const kvdByteLength = readU32(view, 60);
  const sgdByteOffset = readSafeU64(view, 64, "INVALID_INDEX");
  const sgdByteLength = readSafeU64(view, 72, "INVALID_INDEX");

  if (sgdByteOffset !== 0 || sgdByteLength !== 0) {
    throw new KTX2IBLParseError("INVALID_INDEX", "IBL KTX2 assets must not contain supercompression global data.");
  }

  const levelIndexEnd = checkedAdd(
    LEVEL_INDEX_START,
    checkedMultiply(header.levelCount, LEVEL_INDEX_ENTRY_BYTE_LENGTH, "INVALID_INDEX"),
    "INVALID_INDEX",
  );
  const expectedDfdOffset = levelIndexEnd;
  if (dfdByteOffset !== expectedDfdOffset) {
    throw new KTX2IBLParseError(
      "INVALID_INDEX",
      `Unexpected DFD byte offset ${dfdByteOffset}; expected ${expectedDfdOffset}.`,
    );
  }

  const dfdEnd = checkedAdd(dfdByteOffset, dfdByteLength, "INVALID_INDEX");
  const kvdEnd = checkedAdd(kvdByteOffset, kvdByteLength, "INVALID_INDEX");
  validateRange(dfdByteOffset, dfdByteLength, bytes.byteLength, "INVALID_INDEX", "DFD");
  validateRange(kvdByteOffset, kvdByteLength, bytes.byteLength, "INVALID_INDEX", "key/value data");

  if (kvdByteOffset !== dfdEnd) {
    throw new KTX2IBLParseError(
      "INVALID_INDEX",
      `Unexpected key/value byte offset ${kvdByteOffset}; expected ${dfdEnd}.`,
    );
  }

  if (!bytesEqual(bytes.subarray(dfdByteOffset, dfdEnd), BC6H_UFLOAT_DFD)) {
    throw new KTX2IBLParseError(
      "INVALID_DATA_FORMAT_DESCRIPTOR",
      "KTX2 data format descriptor does not match the supported BC6H UFLOAT descriptor.",
    );
  }

  const keyValues = parseKeyValueData(bytes.subarray(kvdByteOffset, kvdEnd));
  if (keyValues.KTXorientation !== "rd") {
    throw new KTX2IBLParseError("INVALID_KEY_VALUE_DATA", 'Expected KTXorientation to be "rd".');
  }
  const writer = keyValues.KTXwriter;
  if (writer === undefined || !writer.startsWith("ibl-baker ")) {
    throw new KTX2IBLParseError(
      "INVALID_KEY_VALUE_DATA",
      'Expected KTXwriter metadata to start with "ibl-baker ".',
    );
  }

  const levels = parseLevels(bytes, view, header.pixelWidth, header.levelCount, kvdEnd);

  return {
    header: {
      vkFormat: VK_FORMAT_BC6H_UFLOAT_BLOCK,
      typeSize: 1,
      pixelWidth: header.pixelWidth,
      pixelHeight: header.pixelHeight,
      pixelDepth: 0,
      layerCount: 0,
      faceCount: 6,
      levelCount: header.levelCount,
      supercompressionScheme: SUPERCOMPRESSION_ZSTD,
    },
    format: {
      vkFormatName: "VK_FORMAT_BC6H_UFLOAT_BLOCK",
      supercompression: "zstd",
      blockWidth: 4,
      blockHeight: 4,
      bytesPerBlock: 16,
    },
    keyValues,
    levels,
  };
}

function validateHeaderProfile(header: {
  vkFormat: number;
  typeSize: number;
  pixelWidth: number;
  pixelHeight: number;
  pixelDepth: number;
  layerCount: number;
  faceCount: number;
  levelCount: number;
  supercompressionScheme: number;
}): void {
  if (header.vkFormat !== VK_FORMAT_BC6H_UFLOAT_BLOCK) {
    throw new KTX2IBLParseError(
      "UNSUPPORTED_FORMAT",
      `Unsupported vkFormat ${header.vkFormat}; expected ${VK_FORMAT_BC6H_UFLOAT_BLOCK}.`,
    );
  }
  if (header.typeSize !== 1) {
    throw new KTX2IBLParseError("UNSUPPORTED_FORMAT", `Unsupported typeSize ${header.typeSize}; expected 1.`);
  }
  if (header.supercompressionScheme !== SUPERCOMPRESSION_ZSTD) {
    throw new KTX2IBLParseError(
      "UNSUPPORTED_FORMAT",
      `Unsupported supercompression scheme ${header.supercompressionScheme}; expected ${SUPERCOMPRESSION_ZSTD}.`,
    );
  }
  if (header.pixelWidth <= 0 || header.pixelHeight <= 0) {
    throw new KTX2IBLParseError("UNSUPPORTED_TOPOLOGY", "KTX2 cubemap dimensions must be positive.");
  }
  if (header.pixelWidth !== header.pixelHeight) {
    throw new KTX2IBLParseError(
      "UNSUPPORTED_TOPOLOGY",
      `KTX2 cubemap dimensions must be square, received ${header.pixelWidth}x${header.pixelHeight}.`,
    );
  }
  if (header.pixelDepth !== 0 || header.layerCount !== 0 || header.faceCount !== CUBEMAP_FACE_COUNT) {
    throw new KTX2IBLParseError(
      "UNSUPPORTED_TOPOLOGY",
      "Only non-array 2D cubemaps with exactly 6 faces are supported.",
    );
  }
  if (header.levelCount <= 0) {
    throw new KTX2IBLParseError("UNSUPPORTED_TOPOLOGY", "KTX2 IBL assets must contain at least one mip level.");
  }
}

function parseLevels(
  bytes: Uint8Array,
  view: DataView,
  baseSize: number,
  levelCount: number,
  imageDataStart: number,
): ParsedKTX2IBLLevel[] {
  const levels: ParsedKTX2IBLLevel[] = [];

  for (let mipLevel = 0; mipLevel < levelCount; mipLevel += 1) {
    const entryOffset = LEVEL_INDEX_START + mipLevel * LEVEL_INDEX_ENTRY_BYTE_LENGTH;
    const byteOffset = readSafeU64(view, entryOffset, "INVALID_LEVEL_INDEX");
    const byteLength = readSafeU64(view, entryOffset + 8, "INVALID_LEVEL_INDEX");
    const uncompressedByteLength = readSafeU64(view, entryOffset + 16, "INVALID_LEVEL_INDEX");
    validateRange(byteOffset, byteLength, bytes.byteLength, "INVALID_LEVEL_INDEX", `mip level ${mipLevel}`);

    const size = dimensionAtMip(baseSize, mipLevel);
    const faceByteLength = bc6hFaceByteLength(size);
    const expectedUncompressedByteLength = checkedMultiply(
      faceByteLength,
      CUBEMAP_FACE_COUNT,
      "INVALID_LEVEL_INDEX",
    );
    if (uncompressedByteLength !== expectedUncompressedByteLength) {
      throw new KTX2IBLParseError(
        "INVALID_LEVEL_INDEX",
        `Mip level ${mipLevel} declares ${uncompressedByteLength} uncompressed bytes, expected ${expectedUncompressedByteLength}.`,
      );
    }

    levels.push({
      mipLevel,
      width: size,
      height: size,
      byteOffset,
      byteLength,
      uncompressedByteLength,
      compressedBytes: bytes.subarray(byteOffset, byteOffset + byteLength),
      faces: FACE_ORDER.map((face, faceIndex) => ({
        face,
        width: size,
        height: size,
        uncompressedByteOffset: faceIndex * faceByteLength,
        uncompressedByteLength: faceByteLength,
      })),
    });
  }

  validateLevelPacking(levels, imageDataStart, bytes.byteLength);
  return levels;
}

function validateLevelPacking(levels: ParsedKTX2IBLLevel[], imageDataStart: number, fileByteLength: number): void {
  let cursor = imageDataStart;
  const sorted = [...levels].sort((left, right) => left.byteOffset - right.byteOffset);

  for (const level of sorted) {
    if (level.byteOffset !== cursor) {
      throw new KTX2IBLParseError(
        "INVALID_LEVEL_INDEX",
        `Mip level ${level.mipLevel} starts at ${level.byteOffset}, expected packed offset ${cursor}.`,
      );
    }
    cursor = checkedAdd(cursor, level.byteLength, "INVALID_LEVEL_INDEX");
  }

  if (cursor !== fileByteLength) {
    throw new KTX2IBLParseError(
      "INVALID_LEVEL_INDEX",
      `Level payloads end at ${cursor}, but file length is ${fileByteLength}.`,
    );
  }
}

function parseKeyValueData(bytes: Uint8Array): Record<string, string> {
  const entries: Record<string, string> = {};
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let byteOffset = 0;

  while (byteOffset < bytes.byteLength) {
    if (byteOffset + 4 > bytes.byteLength) {
      throw new KTX2IBLParseError("INVALID_KEY_VALUE_DATA", "Truncated key/value entry length.");
    }

    const keyAndValueByteLength = view.getUint32(byteOffset, true);
    const entryStart = byteOffset + 4;
    const entryEnd = checkedAdd(entryStart, keyAndValueByteLength, "INVALID_KEY_VALUE_DATA");
    if (entryEnd > bytes.byteLength) {
      throw new KTX2IBLParseError("INVALID_KEY_VALUE_DATA", "Key/value entry exceeds the KVD section.");
    }

    const entryBytes = bytes.subarray(entryStart, entryEnd);
    const keyEnd = entryBytes.indexOf(0);
    if (keyEnd <= 0) {
      throw new KTX2IBLParseError("INVALID_KEY_VALUE_DATA", "Key/value entry is missing a non-empty NUL-terminated key.");
    }

    const valueBytes = entryBytes.subarray(keyEnd + 1);
    const valueEnd = valueBytes.indexOf(0);
    if (valueEnd < 0 || valueEnd !== valueBytes.byteLength - 1) {
      throw new KTX2IBLParseError("INVALID_KEY_VALUE_DATA", "Key/value entry must contain one NUL-terminated string value.");
    }

    const key = decodeUtf8(entryBytes.subarray(0, keyEnd));
    const value = decodeUtf8(valueBytes.subarray(0, valueEnd));
    entries[key] = value;

    const padding = (4 - (keyAndValueByteLength % 4)) % 4;
    const nextEntryOffset = checkedAdd(entryEnd, padding, "INVALID_KEY_VALUE_DATA");
    if (nextEntryOffset > bytes.byteLength) {
      throw new KTX2IBLParseError("INVALID_KEY_VALUE_DATA", "Key/value entry padding exceeds the KVD section.");
    }
    for (let paddingOffset = entryEnd; paddingOffset < nextEntryOffset; paddingOffset += 1) {
      if (bytes[paddingOffset] !== 0) {
        throw new KTX2IBLParseError("INVALID_KEY_VALUE_DATA", "Key/value entry padding must be zero-filled.");
      }
    }

    byteOffset = nextEntryOffset;
  }

  return entries;
}

function toUint8Array(buffer: ArrayBuffer | Uint8Array): Uint8Array {
  return buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
}

function bytesEqual(left: Uint8Array, right: Uint8Array): boolean {
  if (left.byteLength !== right.byteLength) {
    return false;
  }

  for (let index = 0; index < left.byteLength; index += 1) {
    if (left[index] !== right[index]) {
      return false;
    }
  }

  return true;
}

function decodeUtf8(bytes: Uint8Array): string {
  try {
    return utf8Decoder.decode(bytes);
  } catch (error) {
    const message = error instanceof Error ? error.message : "key/value data is not valid UTF-8";
    throw new KTX2IBLParseError("INVALID_KEY_VALUE_DATA", message);
  }
}

function readU32(view: DataView, byteOffset: number): number {
  return view.getUint32(byteOffset, true);
}

function readSafeU64(view: DataView, byteOffset: number, code: KTX2IBLParseErrorCode): number {
  const value = view.getBigUint64(byteOffset, true);
  if (value > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new KTX2IBLParseError(code, "KTX2 u64 value exceeds JavaScript safe integer range.");
  }

  return Number(value);
}

function validateRange(
  byteOffset: number,
  byteLength: number,
  fileByteLength: number,
  code: KTX2IBLParseErrorCode,
  label: string,
): void {
  const end = checkedAdd(byteOffset, byteLength, code);
  if (end > fileByteLength) {
    throw new KTX2IBLParseError(
      code,
      `${label} byte range exceeds the file (${end} > ${fileByteLength}).`,
    );
  }
}

function checkedAdd(left: number, right: number, code: KTX2IBLParseErrorCode): number {
  const value = left + right;
  if (!Number.isSafeInteger(value)) {
    throw new KTX2IBLParseError(code, "KTX2 integer addition exceeds JavaScript safe integer range.");
  }

  return value;
}

function checkedMultiply(left: number, right: number, code: KTX2IBLParseErrorCode): number {
  const value = left * right;
  if (!Number.isSafeInteger(value)) {
    throw new KTX2IBLParseError(code, "KTX2 integer multiplication exceeds JavaScript safe integer range.");
  }

  return value;
}

function dimensionAtMip(base: number, mipLevel: number): number {
  return Math.max(1, Math.floor(base / 2 ** mipLevel));
}

function bc6hFaceByteLength(faceSize: number): number {
  const blocksX = Math.ceil(faceSize / BLOCK_WIDTH);
  const blocksY = Math.ceil(faceSize / BLOCK_HEIGHT);
  return blocksX * blocksY * BYTES_PER_BC6H_BLOCK;
}

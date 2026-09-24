export type AssetFormat = "ibla" | "ktx2";

const IBLA_MAGIC = new TextEncoder().encode("IBLA");
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

export function detectAssetFormat(bytes: Uint8Array, fileName = ""): AssetFormat | null {
  if (bytesEqual(bytes.subarray(0, IBLA_MAGIC.length), IBLA_MAGIC)) {
    return "ibla";
  }

  if (bytesEqual(bytes.subarray(0, KTX2_IDENTIFIER.length), KTX2_IDENTIFIER)) {
    return "ktx2";
  }

  const lowerName = fileName.toLowerCase();
  if (lowerName.endsWith(".ibla")) {
    return "ibla";
  }

  if (lowerName.endsWith(".ktx2")) {
    return "ktx2";
  }

  return null;
}

function bytesEqual(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) {
    return false;
  }

  return left.every((value, index) => value === right[index]);
}

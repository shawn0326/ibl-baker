import {
  IBLAParseError,
  parseIBLA,
  type FaceName,
  type ParsedChunk,
  type ParsedIBLA,
} from "@ibltools/ibla-loader";
import { formatBytes, renderLevels as renderLevelTable, renderSummary as renderSummaryCards } from "../ui.ts";
import { ViewerPreviewError, type FormatSession, type LevelTable, type SummaryCard, type ViewerElements } from "./types.ts";

type DecodedChunk = { chunk: ParsedChunk; canvas: HTMLCanvasElement };

const FACE_ORDER = ["px", "nx", "py", "ny", "pz", "nz"] as const satisfies readonly FaceName[];
const FACE_SLOTS: Record<FaceName, { column: number; row: number }> = {
  px: { column: 2, row: 1 },
  nx: { column: 0, row: 1 },
  py: { column: 1, row: 0 },
  ny: { column: 1, row: 2 },
  pz: { column: 1, row: 1 },
  nz: { column: 3, row: 1 },
};
const MAX_PREVIEW_FACE_SIZE = 256;
const MIN_PREVIEW_FACE_SIZE = 64;
const MAX_2D_PREVIEW_SIZE = 1024;
const CROSS_COLUMNS = 4;
const CROSS_ROWS = 3;

export async function loadIBLA(
  bytes: Uint8Array,
  fileName: string,
  fileSize: number,
  elements: ViewerElements,
  signal: AbortSignal,
): Promise<FormatSession> {
  const parsed = parseIBLAAsset(bytes);
  renderSummary(elements, fileName, fileSize, parsed, null);
  renderLevels(elements, parsed, null);

  let decodedChunks: DecodedChunk[];
  try {
    decodedChunks = await Promise.all(parsed.chunks.map(async (chunk) => ({
      chunk,
      canvas: await decodeChunkToCanvas(chunk, parsed.manifest.encoding),
    })));
  } catch (error) {
    throw new ViewerPreviewError(errorMessage("PNG preview decode failed", error), parsed.manifest.mipCount);
  }

  signal.throwIfAborted();

  renderSummary(elements, fileName, fileSize, parsed, decodedChunks);
  renderLevels(elements, parsed, decodedChunks);
  renderPreview(parsed, decodedChunks, elements.previewCanvas, 0);

  const message = [
    `Parsed ${fileName}.`,
    "Preview ready.",
    `File size: ${formatBytes(fileSize)}`,
    `Encoding: ${parsed.manifest.encoding}`,
    `Mip levels: ${parsed.manifest.mipCount}`,
    `Chunks: ${parsed.chunks.length}`,
    `PNG payload: ${formatBytes(totalChunkBytes(parsed))}`,
  ].join("\n");

  return {
    format: "ibla",
    levelCount: parsed.manifest.mipCount,
    previewAvailable: true,
    cubemap: parsed.manifest.faceCount === 6,
    mips: groupChunksByMip(parsed.chunks).map(({ mipLevel, chunks }) => {
      const firstChunk = chunks[0];
      return {
        value: mipLevel,
        label: firstChunk === undefined ? `Mip ${mipLevel}` : `Mip ${mipLevel} (${firstChunk.width} x ${firstChunk.height})`,
      };
    }),
    message,
    renderMip: (mipLevel) => renderPreview(parsed, decodedChunks, elements.previewCanvas, mipLevel),
    destroy: () => undefined,
  };
}

function parseIBLAAsset(bytes: Uint8Array): ParsedIBLA {
  try {
    return parseIBLA(bytes);
  } catch (error) {
    if (error instanceof IBLAParseError) {
      throw new Error(`${error.name} [${error.code}]: ${error.message}`);
    }
    throw error;
  }
}

async function decodeChunkToCanvas(chunk: ParsedChunk, encoding: ParsedIBLA["manifest"]["encoding"]): Promise<HTMLCanvasElement> {
  const bitmap = await decodePngToBitmap(chunk.encodedBytes);
  const sourceCanvas = document.createElement("canvas");
  sourceCanvas.width = chunk.width;
  sourceCanvas.height = chunk.height;
  const sourceContext = sourceCanvas.getContext("2d", { willReadFrequently: true });
  if (sourceContext === null) {
    bitmap.close();
    throw new Error("Could not create a 2D canvas context.");
  }

  sourceContext.drawImage(bitmap, 0, 0);
  bitmap.close();
  const sourceImageData = sourceContext.getImageData(0, 0, chunk.width, chunk.height);
  const outputImageData = sourceContext.createImageData(chunk.width, chunk.height);

  for (let pixelIndex = 0; pixelIndex < chunk.width * chunk.height; pixelIndex += 1) {
    const offset = pixelIndex * 4;
    const encodedR = readPixelByte(sourceImageData.data, offset) / 255;
    const encodedG = readPixelByte(sourceImageData.data, offset + 1) / 255;
    const encodedB = readPixelByte(sourceImageData.data, offset + 2) / 255;
    const encodedA = readPixelByte(sourceImageData.data, offset + 3) / 255;
    const [linearR, linearG, linearB] = decodeLinearPixel(encoding, encodedR, encodedG, encodedB, encodedA);
    outputImageData.data[offset] = linearToPreviewByte(reinhard(linearR));
    outputImageData.data[offset + 1] = linearToPreviewByte(reinhard(linearG));
    outputImageData.data[offset + 2] = linearToPreviewByte(reinhard(linearB));
    outputImageData.data[offset + 3] = 255;
  }

  const outputCanvas = document.createElement("canvas");
  outputCanvas.width = chunk.width;
  outputCanvas.height = chunk.height;
  const outputContext = outputCanvas.getContext("2d");
  if (outputContext === null) {
    throw new Error("Could not create an output canvas context.");
  }
  outputContext.putImageData(outputImageData, 0, 0);
  return outputCanvas;
}

async function decodePngToBitmap(bytes: Uint8Array): Promise<ImageBitmap> {
  const blob = new Blob([toOwnedArrayBuffer(bytes)], { type: "image/png" });
  try {
    return await createImageBitmap(blob, { colorSpaceConversion: "none" });
  } catch {
    return createImageBitmap(blob);
  }
}

function decodeLinearPixel(
  encoding: ParsedIBLA["manifest"]["encoding"],
  encodedR: number,
  encodedG: number,
  encodedB: number,
  encodedA: number,
): [number, number, number] {
  if (encoding === "rgbd-srgb") {
    if (encodedA <= 0) {
      return [0, 0, 0];
    }
    return [srgbToLinearUnit(encodedR) / encodedA, srgbToLinearUnit(encodedG) / encodedA, srgbToLinearUnit(encodedB) / encodedA];
  }
  if (encoding === "srgb") {
    return [srgbToLinearUnit(encodedR), srgbToLinearUnit(encodedG), srgbToLinearUnit(encodedB)];
  }
  return [encodedR, encodedG, encodedB];
}

function renderPreview(parsed: ParsedIBLA, decoded: DecodedChunk[], canvas: HTMLCanvasElement, mipLevel: number): void {
  const chunks = decoded.filter((entry) => entry.chunk.mipLevel === mipLevel).sort((left, right) => faceSortIndex(left.chunk.face) - faceSortIndex(right.chunk.face));
  const firstChunk = chunks[0]?.chunk;
  if (firstChunk === undefined) {
    return;
  }

  const context = canvas.getContext("2d");
  if (context === null) {
    throw new Error("Could not create a preview canvas context.");
  }
  context.imageSmoothingEnabled = false;

  if (parsed.manifest.faceCount === 6) {
    const facePreviewSize = clampInteger(firstChunk.width, MIN_PREVIEW_FACE_SIZE, MAX_PREVIEW_FACE_SIZE);
    canvas.width = facePreviewSize * CROSS_COLUMNS;
    canvas.height = facePreviewSize * CROSS_ROWS;
    context.clearRect(0, 0, canvas.width, canvas.height);
    for (const faceName of FACE_ORDER) {
      const entry = chunks.find((candidate) => candidate.chunk.face === faceName);
      if (entry === undefined) {
        continue;
      }
      const slot = FACE_SLOTS[faceName];
      context.drawImage(entry.canvas, slot.column * facePreviewSize, slot.row * facePreviewSize, facePreviewSize, facePreviewSize);
    }
    return;
  }

  const scale = Math.min(MAX_2D_PREVIEW_SIZE / firstChunk.width, MAX_2D_PREVIEW_SIZE / firstChunk.height);
  const previewScale = Math.max(1, scale);
  const previewWidth = Math.max(MIN_PREVIEW_FACE_SIZE, Math.round(firstChunk.width * previewScale));
  const previewHeight = Math.max(MIN_PREVIEW_FACE_SIZE, Math.round(firstChunk.height * previewScale));
  canvas.width = previewWidth;
  canvas.height = previewHeight;
  context.clearRect(0, 0, previewWidth, previewHeight);
  const image = chunks[0]?.canvas;
  if (image !== undefined) {
    context.drawImage(image, 0, 0, previewWidth, previewHeight);
  }
}

function renderSummary(elements: ViewerElements, fileName: string, fileSize: number, parsed: ParsedIBLA, decoded: DecodedChunk[] | null): void {
  const cards: SummaryCard[] = [
    { title: "File", value: fileName, detail: formatBytes(fileSize) },
    { title: "Topology", value: `${parsed.manifest.width} x ${parsed.manifest.height}`, detail: `${parsed.manifest.mipCount} mip(s) - ${parsed.manifest.faceCount} face(s)` },
    { title: "Encoding", value: parsed.manifest.encoding, detail: `${parsed.manifest.container} payload - ${parsed.manifest.build.sourceFormat} source` },
    { title: "Payload", value: formatBytes(totalChunkBytes(parsed)), detail: decoded === null ? "Decode pending" : `${decoded.length} decoded chunk(s)` },
    { title: "Build", value: parsed.manifest.build.quality, detail: `Samples ${parsed.manifest.build.samples} - rotation ${parsed.manifest.build.rotation}` },
  ];
  renderSummaryCards(elements, cards);
}

function renderLevels(elements: ViewerElements, parsed: ParsedIBLA, decoded: DecodedChunk[] | null): void {
  const decodedKeys = new Set(decoded?.map((entry) => chunkKey(entry.chunk)));
  const table: LevelTable = {
    headers: ["Mip", "Size", "Chunks", "PNG bytes", "Decoded", "Faces"],
    rows: groupChunksByMip(parsed.chunks).flatMap(({ mipLevel, chunks }) => {
      const firstChunk = chunks[0];
      if (firstChunk === undefined) {
        return [];
      }
      const decodedCount = chunks.filter((chunk) => decodedKeys.has(chunkKey(chunk))).length;
      return [[String(mipLevel), `${firstChunk.width} x ${firstChunk.height}`, String(chunks.length), formatBytes(sumChunkBytes(chunks)), decoded === null ? "pending" : `${decodedCount} / ${chunks.length}`, chunks.map((chunk) => chunk.face ?? "image").join(" ")]];
    }),
  };
  renderLevelTable(elements, table);
}

function groupChunksByMip(chunks: ParsedChunk[]): Array<{ mipLevel: number; chunks: ParsedChunk[] }> {
  const grouped = new Map<number, ParsedChunk[]>();
  for (const chunk of chunks) {
    const entries = grouped.get(chunk.mipLevel);
    if (entries === undefined) grouped.set(chunk.mipLevel, [chunk]);
    else entries.push(chunk);
  }
  return [...grouped.entries()].sort((left, right) => left[0] - right[0]).map(([mipLevel, mipChunks]) => ({
    mipLevel,
    chunks: mipChunks.length === FACE_ORDER.length ? [...mipChunks].sort((left, right) => faceSortIndex(left.face) - faceSortIndex(right.face)) : mipChunks,
  }));
}

function totalChunkBytes(parsed: ParsedIBLA): number {
  return parsed.chunks.reduce((total, chunk) => total + chunk.byteLength, 0);
}

function sumChunkBytes(chunks: ParsedChunk[]): number {
  return chunks.reduce((total, chunk) => total + chunk.byteLength, 0);
}

function chunkKey(chunk: ParsedChunk): string {
  return `${chunk.mipLevel}:${chunk.face ?? "image"}:${chunk.byteOffset}:${chunk.byteLength}`;
}

function readPixelByte(pixels: Uint8ClampedArray, offset: number): number {
  const value = pixels[offset];
  if (value === undefined) throw new Error("Decoded PNG pixel buffer was truncated.");
  return value;
}

function faceSortIndex(face: ParsedChunk["face"]): number {
  if (face === null) return 0;
  const index = FACE_ORDER.indexOf(face);
  return index >= 0 ? index : Number.MAX_SAFE_INTEGER;
}

function srgbToLinearUnit(value: number): number {
  if (value <= 0.04045) return value / 12.92;
  return Math.pow((value + 0.055) / 1.055, 2.4);
}

function linearToPreviewByte(value: number): number {
  return Math.round(Math.pow(clampUnit(value), 1 / 2.2) * 255);
}

function reinhard(value: number): number {
  const clamped = Math.max(0, value);
  return clamped / (1 + clamped);
}

function clampUnit(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function clampInteger(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function toOwnedArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  if (bytes.buffer instanceof ArrayBuffer) return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  return Uint8Array.from(bytes).buffer;
}

function errorMessage(prefix: string, error: unknown): string {
  if (error instanceof Error) return `${prefix}: ${error.message}`;
  return `${prefix}: ${String(error)}`;
}

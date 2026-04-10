import {
  IBLAParseError,
  parseIBLA,
  type FaceName,
  type ParsedChunk,
  type ParsedIBLA,
} from "@ibltools/ibla-loader";

type ViewerStatus = "idle" | "loading" | "ok" | "parse-error" | "preview-error";

interface ViewerState {
  status: ViewerStatus;
  fileName: string | null;
  fileSize: number;
  message: string;
  levelCount: number;
  chunkCount: number;
  previewAvailable: boolean;
}

interface DecodedChunk {
  chunk: ParsedChunk;
  canvas: HTMLCanvasElement;
}

declare global {
  interface Window {
    __IBLA_VIEWER__?: ViewerState;
  }
}

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

const statusElement = mustGetElement<HTMLPreElement>("status");
const summaryElement = mustGetElement<HTMLElement>("summary");
const levelsPanel = mustGetElement<HTMLElement>("levels-panel");
const levelsElement = mustGetElement<HTMLElement>("levels");
const previewPanel = mustGetElement<HTMLElement>("preview-panel");
const previewCanvas = mustGetElement<HTMLCanvasElement>("preview-canvas");
const mipSelect = mustGetElement<HTMLSelectElement>("mip-select");
const dropZone = mustGetElement<HTMLElement>("drop-zone");
const fileInput = mustGetElement<HTMLInputElement>("file-input");
const faceLabels = mustGetElement<HTMLElement>("face-labels");

let decodedChunks: DecodedChunk[] = [];
let parsedAsset: ParsedIBLA | null = null;
let loadGeneration = 0;

setViewerState({
  status: "idle",
  fileName: null,
  fileSize: 0,
  message: "Idle. Choose or drop a .ibla file.",
  levelCount: 0,
  chunkCount: 0,
  previewAvailable: false,
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files?.[0];
  if (file !== undefined) {
    void loadFile(file);
  }
});

dropZone.addEventListener("dragenter", (event) => {
  event.preventDefault();
  dropZone.classList.add("dragging");
});

dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("dragging");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("dragging");
});

dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragging");

  const file = event.dataTransfer?.files[0];
  if (file !== undefined) {
    void loadFile(file);
  }
});

mipSelect.addEventListener("change", () => {
  const mipLevel = Number.parseInt(mipSelect.value, 10);
  if (Number.isInteger(mipLevel) && parsedAsset !== null) {
    renderPreview(parsedAsset, decodedChunks, mipLevel);
  }
});

async function loadFile(file: File): Promise<void> {
  const generation = ++loadGeneration;
  resetResult();
  setStatus("loading", `Loading ${file.name}...`, "loading");
  setViewerState({
    status: "loading",
    fileName: file.name,
    fileSize: file.size,
    message: "Loading file.",
    levelCount: 0,
    chunkCount: 0,
    previewAvailable: false,
  });

  let bytes: Uint8Array;
  try {
    bytes = new Uint8Array(await file.arrayBuffer());
  } catch (error) {
    const message = errorMessage("File read failed", error);
    setStatus("preview-error", message, "error");
    setViewerState({
      status: "preview-error",
      fileName: file.name,
      fileSize: file.size,
      message,
      levelCount: 0,
      chunkCount: 0,
      previewAvailable: false,
    });
    return;
  }

  if (generation !== loadGeneration) {
    return;
  }

  let parsed: ParsedIBLA;
  try {
    parsed = parseIBLA(bytes);
  } catch (error) {
    const message =
      error instanceof IBLAParseError
        ? `${error.name} [${error.code}]: ${error.message}`
        : errorMessage("Parse failed", error);
    setStatus("parse-error", message, "error");
    setViewerState({
      status: "parse-error",
      fileName: file.name,
      fileSize: file.size,
      message,
      levelCount: 0,
      chunkCount: 0,
      previewAvailable: false,
    });
    return;
  }

  parsedAsset = parsed;
  renderSummary(file, parsed, null);
  renderLevels(parsed, null);

  try {
    decodedChunks = await Promise.all(
      parsed.chunks.map(async (chunk) => ({
        chunk,
        canvas: await decodeChunkToCanvas(chunk, parsed.manifest.encoding),
      })),
    );
  } catch (error) {
    const message = errorMessage("PNG preview decode failed", error);
    setStatus("preview-error", `Parsed ${file.name}.\n${message}`, "error");
    setViewerState({
      status: "preview-error",
      fileName: file.name,
      fileSize: file.size,
      message,
      levelCount: parsed.manifest.mipCount,
      chunkCount: parsed.chunks.length,
      previewAvailable: false,
    });
    return;
  }

  if (generation !== loadGeneration) {
    return;
  }

  renderSummary(file, parsed, decodedChunks);
  renderLevels(parsed, decodedChunks);
  populateMipSelect(parsed);
  previewPanel.hidden = false;
  faceLabels.hidden = parsed.manifest.faceCount !== 6;
  renderPreview(parsed, decodedChunks, 0);

  const message = [
    `Parsed ${file.name}.`,
    "Preview ready.",
    `File size: ${formatBytes(file.size)}`,
    `Encoding: ${parsed.manifest.encoding}`,
    `Mip levels: ${parsed.manifest.mipCount}`,
    `Chunks: ${parsed.chunks.length}`,
    `PNG payload: ${formatBytes(totalChunkBytes(parsed))}`,
  ].join("\n");
  setStatus("ok", message, "ok");
  setViewerState({
    status: "ok",
    fileName: file.name,
    fileSize: file.size,
    message,
    levelCount: parsed.manifest.mipCount,
    chunkCount: parsed.chunks.length,
    previewAvailable: true,
  });
}

async function decodeChunkToCanvas(
  chunk: ParsedChunk,
  encoding: ParsedIBLA["manifest"]["encoding"],
): Promise<HTMLCanvasElement> {
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

    return [
      srgbToLinearUnit(encodedR) / encodedA,
      srgbToLinearUnit(encodedG) / encodedA,
      srgbToLinearUnit(encodedB) / encodedA,
    ];
  }

  if (encoding === "srgb") {
    return [srgbToLinearUnit(encodedR), srgbToLinearUnit(encodedG), srgbToLinearUnit(encodedB)];
  }

  return [encodedR, encodedG, encodedB];
}

function renderPreview(parsed: ParsedIBLA, decoded: DecodedChunk[], mipLevel: number): void {
  const chunks = decoded
    .filter((entry) => entry.chunk.mipLevel === mipLevel)
    .sort((left, right) => faceSortIndex(left.chunk.face) - faceSortIndex(right.chunk.face));

  const firstChunk = chunks[0]?.chunk;
  if (firstChunk === undefined) {
    return;
  }

  const context = previewCanvas.getContext("2d");
  if (context === null) {
    throw new Error("Could not create a preview canvas context.");
  }
  context.imageSmoothingEnabled = false;

  if (parsed.manifest.faceCount === 6) {
    const facePreviewSize = clampInteger(firstChunk.width, MIN_PREVIEW_FACE_SIZE, MAX_PREVIEW_FACE_SIZE);
    previewCanvas.width = facePreviewSize * CROSS_COLUMNS;
    previewCanvas.height = facePreviewSize * CROSS_ROWS;
    context.clearRect(0, 0, previewCanvas.width, previewCanvas.height);

    for (const faceName of FACE_ORDER) {
      const entry = chunks.find((candidate) => candidate.chunk.face === faceName);
      if (entry === undefined) {
        continue;
      }

      const slot = FACE_SLOTS[faceName];
      context.drawImage(
        entry.canvas,
        slot.column * facePreviewSize,
        slot.row * facePreviewSize,
        facePreviewSize,
        facePreviewSize,
      );
    }
    return;
  }

  const scale = Math.min(MAX_2D_PREVIEW_SIZE / firstChunk.width, MAX_2D_PREVIEW_SIZE / firstChunk.height);
  const previewScale = Math.max(1, scale);
  const previewWidth = Math.max(MIN_PREVIEW_FACE_SIZE, Math.round(firstChunk.width * previewScale));
  const previewHeight = Math.max(MIN_PREVIEW_FACE_SIZE, Math.round(firstChunk.height * previewScale));
  previewCanvas.width = previewWidth;
  previewCanvas.height = previewHeight;
  context.clearRect(0, 0, previewWidth, previewHeight);

  const image = chunks[0]?.canvas;
  if (image !== undefined) {
    context.drawImage(image, 0, 0, previewWidth, previewHeight);
  }
}

function renderSummary(file: File, parsed: ParsedIBLA, decoded: DecodedChunk[] | null): void {
  const cards = [
    {
      title: "File",
      value: file.name,
      detail: formatBytes(file.size),
    },
    {
      title: "Topology",
      value: `${parsed.manifest.width} x ${parsed.manifest.height}`,
      detail: `${parsed.manifest.mipCount} mip(s) - ${parsed.manifest.faceCount} face(s)`,
    },
    {
      title: "Encoding",
      value: parsed.manifest.encoding,
      detail: `${parsed.manifest.container} payload - ${parsed.manifest.build.sourceFormat} source`,
    },
    {
      title: "Payload",
      value: formatBytes(totalChunkBytes(parsed)),
      detail: decoded === null ? "Decode pending" : `${decoded.length} decoded chunk(s)`,
    },
    {
      title: "Build",
      value: parsed.manifest.build.quality,
      detail: `Samples ${parsed.manifest.build.samples} - rotation ${parsed.manifest.build.rotation}`,
    },
  ];

  summaryElement.replaceChildren(
    ...cards.map((card) => {
      const element = document.createElement("article");
      element.className = "summary-card";

      const title = document.createElement("strong");
      title.textContent = card.title;

      const value = document.createElement("span");
      value.textContent = card.value;

      const detail = document.createElement("small");
      detail.textContent = card.detail;

      element.append(title, value, detail);
      return element;
    }),
  );
}

function renderLevels(parsed: ParsedIBLA, decoded: DecodedChunk[] | null): void {
  levelsPanel.hidden = false;
  const chunksByMip = groupChunksByMip(parsed.chunks);
  if (chunksByMip.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No mip levels.";
    levelsElement.replaceChildren(empty);
    return;
  }

  const decodedKeys = new Set(decoded?.map((entry) => chunkKey(entry.chunk)));
  const table = document.createElement("table");
  table.className = "level-table";

  const head = document.createElement("thead");
  head.innerHTML = `
    <tr>
      <th>Mip</th>
      <th>Size</th>
      <th>Chunks</th>
      <th>PNG bytes</th>
      <th>Decoded</th>
      <th>Faces</th>
    </tr>
  `;

  const body = document.createElement("tbody");
  for (const { mipLevel, chunks } of chunksByMip) {
    const firstChunk = chunks[0];
    if (firstChunk === undefined) {
      continue;
    }

    const decodedCount = chunks.filter((chunk) => decodedKeys.has(chunkKey(chunk))).length;
    const row = document.createElement("tr");
    row.replaceChildren(
      tableCell(String(mipLevel)),
      tableCell(`${firstChunk.width} x ${firstChunk.height}`),
      tableCell(String(chunks.length)),
      tableCell(formatBytes(sumChunkBytes(chunks))),
      tableCell(decoded === null ? "pending" : `${decodedCount} / ${chunks.length}`),
      tableCell(chunks.map((chunk) => chunk.face ?? "image").join(" ")),
    );
    body.append(row);
  }

  table.append(head, body);
  levelsElement.replaceChildren(table);
}

function populateMipSelect(parsed: ParsedIBLA): void {
  const chunksByMip = groupChunksByMip(parsed.chunks);
  mipSelect.replaceChildren(
    ...chunksByMip.map(({ mipLevel, chunks }) => {
      const firstChunk = chunks[0];
      const option = document.createElement("option");
      option.value = String(mipLevel);
      option.textContent =
        firstChunk === undefined
          ? `Mip ${mipLevel}`
          : `Mip ${mipLevel} (${firstChunk.width} x ${firstChunk.height})`;
      return option;
    }),
  );
  mipSelect.value = "0";
}

function groupChunksByMip(chunks: ParsedChunk[]): Array<{ mipLevel: number; chunks: ParsedChunk[] }> {
  const grouped = new Map<number, ParsedChunk[]>();
  for (const chunk of chunks) {
    const entries = grouped.get(chunk.mipLevel);
    if (entries === undefined) {
      grouped.set(chunk.mipLevel, [chunk]);
    } else {
      entries.push(chunk);
    }
  }

  return [...grouped.entries()]
    .sort((left, right) => left[0] - right[0])
    .map(([mipLevel, mipChunks]) => ({
      mipLevel,
      chunks:
        mipChunks.length === FACE_ORDER.length
          ? [...mipChunks].sort((left, right) => faceSortIndex(left.face) - faceSortIndex(right.face))
          : mipChunks,
    }));
}

function resetResult(): void {
  parsedAsset = null;
  decodedChunks = [];
  previewPanel.hidden = true;
  levelsPanel.hidden = true;
  faceLabels.hidden = true;
  summaryElement.replaceChildren();
  levelsElement.replaceChildren();
  mipSelect.replaceChildren();
  const context = previewCanvas.getContext("2d");
  context?.clearRect(0, 0, previewCanvas.width, previewCanvas.height);
}

function setStatus(status: ViewerStatus, message: string, tone: "loading" | "ok" | "warning" | "error"): void {
  statusElement.textContent = message;
  statusElement.className = `status ${tone === "loading" ? "" : tone}`.trim();
  statusElement.dataset.status = status;
}

function setViewerState(state: ViewerState): void {
  window.__IBLA_VIEWER__ = state;
}

function tableCell(text: string): HTMLTableCellElement {
  const cell = document.createElement("td");
  cell.textContent = text;
  return cell;
}

function mustGetElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!(element instanceof HTMLElement)) {
    throw new Error(`Missing element #${id}.`);
  }

  return element as T;
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
  if (value === undefined) {
    throw new Error("Decoded PNG pixel buffer was truncated.");
  }

  return value;
}

function faceSortIndex(face: ParsedChunk["face"]): number {
  if (face === null) {
    return 0;
  }

  const index = FACE_ORDER.indexOf(face);
  return index >= 0 ? index : Number.MAX_SAFE_INTEGER;
}

function srgbToLinearUnit(value: number): number {
  if (value <= 0.04045) {
    return value / 12.92;
  }

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
  if (bytes.buffer instanceof ArrayBuffer) {
    return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  }

  return Uint8Array.from(bytes).buffer;
}

function errorMessage(prefix: string, error: unknown): string {
  if (error instanceof Error) {
    return `${prefix}: ${error.message}`;
  }

  return `${prefix}: ${String(error)}`;
}

function formatBytes(byteLength: number): string {
  if (byteLength < 1024) {
    return `${byteLength} B`;
  }

  const kilobytes = byteLength / 1024;
  if (kilobytes < 1024) {
    return `${kilobytes.toFixed(1)} KB`;
  }

  return `${(kilobytes / 1024).toFixed(2)} MB`;
}

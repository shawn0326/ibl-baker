import { parseIBLA, type ParsedChunk, type ParsedIBLA } from "@ibltools/loader";

import royalSpecularUrl from "../../../fixtures/outputs/royal_esplanade_1k/specular.ibla?url";
import royalIrradianceUrl from "../../../fixtures/outputs/royal_esplanade_1k/irradiance.ibla?url";
import grandSpecularUrl from "../../../fixtures/outputs/grand_canyon_c/specular.ibla?url";
import grandIrradianceUrl from "../../../fixtures/outputs/grand_canyon_c/irradiance.ibla?url";
import spruitSpecularUrl from "../../../fixtures/outputs/spruit_sunrise_2k/specular.ibla?url";
import spruitIrradianceUrl from "../../../fixtures/outputs/spruit_sunrise_2k/irradiance.ibla?url";

type FixtureName = "royal_esplanade_1k" | "grand_canyon_c" | "spruit_sunrise_2k";
type AssetName = "specular" | "irradiance";

interface FixtureDescriptor {
  label: string;
  assets: Record<AssetName, string>;
}

interface DecodedChunk {
  chunk: ParsedChunk;
  canvas: HTMLCanvasElement;
}

declare global {
  interface Window {
    __IBL_E2E__?: {
      fixture: FixtureName;
      asset: AssetName;
      status: "ok" | "error" | "loading";
      message: string;
      chunkCount: number;
      mipCount: number;
    };
  }
}

const FIXTURES: Record<FixtureName, FixtureDescriptor> = {
  royal_esplanade_1k: {
    label: "Royal Esplanade 1K",
    assets: {
      specular: royalSpecularUrl,
      irradiance: royalIrradianceUrl,
    },
  },
  grand_canyon_c: {
    label: "Grand Canyon C",
    assets: {
      specular: grandSpecularUrl,
      irradiance: grandIrradianceUrl,
    },
  },
  spruit_sunrise_2k: {
    label: "Spruit Sunrise 2K",
    assets: {
      specular: spruitSpecularUrl,
      irradiance: spruitIrradianceUrl,
    },
  },
};

const ASSET_LABELS: Record<AssetName, string> = {
  specular: "Specular Cubemap",
  irradiance: "Irradiance Cubemap",
};

const FIXTURE_NAMES = Object.keys(FIXTURES) as FixtureName[];
const ASSET_NAMES = Object.keys(ASSET_LABELS) as AssetName[];
const CANONICAL_FACE_ORDER = ["px", "nx", "py", "ny", "pz", "nz"] as const;
const DEFAULT_FIXTURE: FixtureName = "royal_esplanade_1k";
const DEFAULT_ASSET: AssetName = "specular";

void main();

async function main(): Promise<void> {
  const fixtureSelect = mustGetElement<HTMLSelectElement>("fixture-select");
  const assetSelect = mustGetElement<HTMLSelectElement>("asset-select");

  populateSelect(
    fixtureSelect,
    FIXTURE_NAMES.map((name) => ({ value: name, label: FIXTURES[name].label })),
  );
  populateSelect(
    assetSelect,
    ASSET_NAMES.map((name) => ({ value: name, label: ASSET_LABELS[name] })),
  );

  const state = readQueryState();
  fixtureSelect.value = state.fixture;
  assetSelect.value = state.asset;

  fixtureSelect.addEventListener("change", () => {
    const nextState = { fixture: fixtureSelect.value as FixtureName, asset: assetSelect.value as AssetName };
    writeQueryState(nextState);
    void renderSelection(nextState);
  });

  assetSelect.addEventListener("change", () => {
    const nextState = { fixture: fixtureSelect.value as FixtureName, asset: assetSelect.value as AssetName };
    writeQueryState(nextState);
    void renderSelection(nextState);
  });

  await renderSelection(state);
}

async function renderSelection(state: { fixture: FixtureName; asset: AssetName }): Promise<void> {
  const statusElement = mustGetElement<HTMLPreElement>("status");
  const summaryElement = mustGetElement<HTMLDivElement>("summary");
  const gridElement = mustGetElement<HTMLElement>("grid");
  const fixtureSelect = mustGetElement<HTMLSelectElement>("fixture-select");
  const assetSelect = mustGetElement<HTMLSelectElement>("asset-select");

  fixtureSelect.disabled = true;
  assetSelect.disabled = true;
  statusElement.textContent = "Loading fixture…";
  statusElement.classList.add("loading");
  summaryElement.replaceChildren();
  gridElement.replaceChildren();
  window.__IBL_E2E__ = {
    fixture: state.fixture,
    asset: state.asset,
    status: "loading",
    message: "Loading fixture…",
    chunkCount: 0,
    mipCount: 0,
  };

  try {
    const buffer = await fetchBuffer(FIXTURES[state.fixture].assets[state.asset]);
    const parsed = parseIBLA(buffer);
    const decodedChunks = await Promise.all(
      parsed.chunks.map(async (chunk) => ({
        chunk,
        canvas: await decodeChunkToCanvas(chunk, parsed.manifest.encoding),
      })),
    );

    renderSummary(summaryElement, parsed, state, buffer.byteLength);
    renderGrid(gridElement, parsed, decodedChunks);

    const message = [
      `fixture: ${state.fixture}`,
      `asset: ${state.asset}`,
      "status: ok",
      `file size: ${formatBytes(buffer.byteLength)}`,
      `encoding: ${parsed.manifest.encoding}`,
      `container: ${parsed.manifest.container}`,
      `mip count: ${parsed.manifest.mipCount}`,
      `chunk count: ${parsed.chunks.length}`,
      `face count: ${parsed.manifest.faceCount}`,
      `build: quality=${parsed.manifest.build.quality}, samples=${parsed.manifest.build.samples}, source=${parsed.manifest.build.sourceFormat}`,
    ].join("\n");

    statusElement.textContent = message;
    statusElement.classList.remove("loading");
    window.__IBL_E2E__ = {
      fixture: state.fixture,
      asset: state.asset,
      status: "ok",
      message,
      chunkCount: parsed.chunks.length,
      mipCount: parsed.manifest.mipCount,
    };
  } catch (error) {
    const message =
      error instanceof Error ? `${error.name}: ${error.message}` : `Unknown error: ${String(error)}`;
    statusElement.textContent = message;
    statusElement.classList.remove("loading");
    window.__IBL_E2E__ = {
      fixture: state.fixture,
      asset: state.asset,
      status: "error",
      message,
      chunkCount: 0,
      mipCount: 0,
    };
  } finally {
    fixtureSelect.disabled = false;
    assetSelect.disabled = false;
  }
}

function renderSummary(
  summaryElement: HTMLDivElement,
  parsed: ParsedIBLA,
  state: { fixture: FixtureName; asset: AssetName },
  fileByteLength: number,
): void {
  const cards = [
    {
      title: "Fixture",
      value: FIXTURES[state.fixture].label,
      detail: `Asset: ${ASSET_LABELS[state.asset]}`,
    },
    {
      title: "Topology",
      value: `${parsed.manifest.faceCount === 6 ? "cubemap" : "2d"} · ${parsed.manifest.faceCount} face`,
      detail: `${parsed.manifest.width} x ${parsed.manifest.height} · ${parsed.manifest.mipCount} mip(s)`,
    },
    {
      title: "Payload",
      value: formatBytes(fileByteLength),
      detail: `${parsed.chunks.length} chunk(s) · ${parsed.manifest.encoding} · ${parsed.manifest.container}`,
    },
    {
      title: "Build",
      value: parsed.manifest.build.quality,
      detail: `Samples ${parsed.manifest.build.samples} · Source ${parsed.manifest.build.sourceFormat}`,
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

function renderGrid(gridElement: HTMLElement, parsed: ParsedIBLA, decodedChunks: DecodedChunk[]): void {
  const byIdentity = new Map(decodedChunks.map((entry) => [chunkKey(entry.chunk), entry]));
  const chunksByMip = groupChunksByMip(parsed.chunks);
  const faceOrder = parsed.manifest.faceCount === 6 ? [...CANONICAL_FACE_ORDER] : (["image"] as const);

  gridElement.replaceChildren(
    ...chunksByMip.map(({ mipLevel, chunks }) => {
      const row = document.createElement("section");
      row.className = "mip-row";

      const firstChunk = chunks[0];
      if (firstChunk === undefined) {
        return row;
      }

      const header = document.createElement("div");
      header.className = "mip-header";

      const title = document.createElement("div");
      title.className = "mip-title";
      title.textContent = `Mip ${mipLevel}`;

      const meta = document.createElement("div");
      meta.className = "mip-meta";
      meta.textContent = `${firstChunk.width} x ${firstChunk.height} · ${chunks.length} chunk(s) · ${formatBytes(sumChunkBytes(chunks))}`;

      header.append(title, meta);

      const tiles = document.createElement("div");
      tiles.className = "tile-grid";

      faceOrder.forEach((faceName) => {
        const chunk = chunks.find((candidate) =>
          parsed.manifest.faceCount === 6 ? candidate.face === faceName : candidate.face === null,
        );

        if (chunk === undefined) {
          return;
        }

        const decoded = byIdentity.get(chunkKey(chunk));
        if (decoded === undefined) {
          return;
        }

        const tile = document.createElement("article");
        tile.className = "tile-card";

        const label = document.createElement("strong");
        label.textContent = parsed.manifest.faceCount === 6 ? String(faceName).toUpperCase() : "Image";

        const frame = document.createElement("div");
        frame.className = "tile-frame";
        frame.append(decoded.canvas);

        tile.append(label, frame);
        tiles.append(tile);
      });

      row.append(header, tiles);
      return row;
    }),
  );
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
        mipChunks.length === CANONICAL_FACE_ORDER.length
          ? [...mipChunks].sort((left, right) => faceSortIndex(left.face) - faceSortIndex(right.face))
          : mipChunks,
    }));
}

async function decodeChunkToCanvas(
  chunk: ParsedChunk,
  encoding: ParsedIBLA["manifest"]["encoding"],
): Promise<HTMLCanvasElement> {
  const sourceImage = await decodePngToImage(chunk.encodedBytes);
  const sourceCanvas = document.createElement("canvas");
  sourceCanvas.width = chunk.width;
  sourceCanvas.height = chunk.height;

  const sourceContext = sourceCanvas.getContext("2d");
  if (sourceContext === null) {
    throw new Error("Could not create a 2D canvas context.");
  }

  sourceContext.drawImage(sourceImage, 0, 0);
  const sourceImageData = sourceContext.getImageData(0, 0, chunk.width, chunk.height);
  const outputImageData = sourceContext.createImageData(chunk.width, chunk.height);

  for (let pixelIndex = 0; pixelIndex < chunk.width * chunk.height; pixelIndex += 1) {
    const offset = pixelIndex * 4;
    const encodedR = readPixelByte(sourceImageData.data, offset) / 255;
    const encodedG = readPixelByte(sourceImageData.data, offset + 1) / 255;
    const encodedB = readPixelByte(sourceImageData.data, offset + 2) / 255;
    const encodedA = readPixelByte(sourceImageData.data, offset + 3) / 255;

    const [displayR, displayG, displayB] = decodeDisplayPixel(
      encoding,
      encodedR,
      encodedG,
      encodedB,
      encodedA,
    );

    outputImageData.data[offset] = displayR;
    outputImageData.data[offset + 1] = displayG;
    outputImageData.data[offset + 2] = displayB;
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

function decodeDisplayPixel(
  encoding: ParsedIBLA["manifest"]["encoding"],
  encodedR: number,
  encodedG: number,
  encodedB: number,
  encodedA: number,
): [number, number, number] {
  if (encoding === "srgb") {
    return [
      Math.round(clampUnit(encodedR) * 255),
      Math.round(clampUnit(encodedG) * 255),
      Math.round(clampUnit(encodedB) * 255),
    ];
  }

  const [linearR, linearG, linearB] =
    encoding === "rgbd-srgb"
      ? decodeRgbdSrgb(encodedR, encodedG, encodedB, encodedA)
      : [encodedR, encodedG, encodedB];

  return [
    linearToDisplayByte(reinhard(linearR)),
    linearToDisplayByte(reinhard(linearG)),
    linearToDisplayByte(reinhard(linearB)),
  ];
}

function decodeRgbdSrgb(
  encodedR: number,
  encodedG: number,
  encodedB: number,
  encodedA: number,
): [number, number, number] {
  if (encodedA <= 0) {
    return [0, 0, 0];
  }

  return [
    srgbToLinearUnit(encodedR) / encodedA,
    srgbToLinearUnit(encodedG) / encodedA,
    srgbToLinearUnit(encodedB) / encodedA,
  ];
}

async function decodePngToImage(bytes: Uint8Array): Promise<HTMLImageElement> {
  const blob = new Blob([toOwnedArrayBuffer(bytes)], { type: "image/png" });
  const objectUrl = URL.createObjectURL(blob);

  try {
    return await new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error("PNG decode failed."));
      image.src = objectUrl;
    });
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

function populateSelect(
  select: HTMLSelectElement,
  options: Array<{ value: string; label: string }>,
): void {
  select.replaceChildren(
    ...options.map((option) => {
      const element = document.createElement("option");
      element.value = option.value;
      element.textContent = option.label;
      return element;
    }),
  );
}

function readQueryState(): { fixture: FixtureName; asset: AssetName } {
  const params = new URL(window.location.href).searchParams;
  const fixture = params.get("fixture");
  const asset = params.get("asset");

  return {
    fixture: isFixtureName(fixture) ? fixture : DEFAULT_FIXTURE,
    asset: isAssetName(asset) ? asset : DEFAULT_ASSET,
  };
}

function writeQueryState(state: { fixture: FixtureName; asset: AssetName }): void {
  const url = new URL(window.location.href);
  url.searchParams.set("fixture", state.fixture);
  url.searchParams.set("asset", state.asset);
  window.history.replaceState({}, "", url);
}

function isFixtureName(value: string | null): value is FixtureName {
  return value !== null && value in FIXTURES;
}

function isAssetName(value: string | null): value is AssetName {
  return value !== null && value in ASSET_LABELS;
}

function mustGetElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!(element instanceof HTMLElement)) {
    throw new Error(`Missing element #${id}.`);
  }

  return element as T;
}

function fetchBuffer(url: string): Promise<Uint8Array> {
  return fetch(url).then(async (response) => {
    if (!response.ok) {
      throw new Error(`Failed to fetch ${url}: ${response.status} ${response.statusText}`);
    }

    return new Uint8Array(await response.arrayBuffer());
  });
}

function toOwnedArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  if (bytes.buffer instanceof ArrayBuffer) {
    return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  }

  return Uint8Array.from(bytes).buffer;
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

  const index = CANONICAL_FACE_ORDER.indexOf(face);
  return index >= 0 ? index : Number.MAX_SAFE_INTEGER;
}

function srgbToLinearUnit(value: number): number {
  if (value <= 0.04045) {
    return value / 12.92;
  }

  return Math.pow((value + 0.055) / 1.055, 2.4);
}

function linearToDisplayByte(value: number): number {
  const srgb =
    value <= 0.0031308
      ? value * 12.92
      : 1.055 * Math.pow(value, 1 / 2.4) - 0.055;
  return Math.round(clampUnit(srgb) * 255);
}

function reinhard(value: number): number {
  const clamped = Math.max(0, value);
  return clamped / (1 + clamped);
}

function clampUnit(value: number): number {
  return Math.max(0, Math.min(1, value));
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

function sumChunkBytes(chunks: ParsedChunk[]): number {
  return chunks.reduce((total, chunk) => total + chunk.byteLength, 0);
}

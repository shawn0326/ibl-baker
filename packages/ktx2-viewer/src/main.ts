import {
  KTX2IBLParseError,
  parseKTX2IBL,
  type ParsedKTX2IBL,
  type ParsedKTX2IBLLevel,
} from "@ibltools/ktx2-loader";
import { ZSTDDecoder } from "zstddec";

type ViewerStatus = "idle" | "loading" | "ok" | "parse-error" | "preview-unavailable" | "preview-error";

interface ViewerState {
  status: ViewerStatus;
  fileName: string | null;
  fileSize: number;
  message: string;
  levelCount: number;
  previewAvailable: boolean;
}

interface DecodedLevel {
  level: ParsedKTX2IBLLevel;
  bytes: Uint8Array;
}

interface PreviewRenderer {
  renderMip(mipLevel: number): void;
  destroy(): void;
}

declare global {
  interface Window {
    __KTX2_VIEWER__?: ViewerState;
  }
}

const FACE_COUNT = 6;
const FACE_ORDER = ["px", "nx", "py", "ny", "pz", "nz"] as const;
const BC6H_FORMAT = "bc6h-rgb-ufloat" as GPUTextureFormat;
const CANVAS_FORMAT_FALLBACK = "bgra8unorm" as GPUTextureFormat;
const BC6H_BLOCK_SIZE = 4;
const BC6H_BYTES_PER_BLOCK = 16;
const MAX_PREVIEW_FACE_SIZE = 256;
const MIN_PREVIEW_FACE_SIZE = 64;
const CROSS_COLUMNS = 4;
const CROSS_ROWS = 3;
const TEXTURE_USAGE_TEXTURE_BINDING = 0x04;
const TEXTURE_USAGE_COPY_DST = 0x02;
const BUFFER_USAGE_COPY_DST = 0x08;
const BUFFER_USAGE_UNIFORM = 0x40;

const statusElement = mustGetElement<HTMLPreElement>("status");
const summaryElement = mustGetElement<HTMLElement>("summary");
const levelsPanel = mustGetElement<HTMLElement>("levels-panel");
const levelsElement = mustGetElement<HTMLElement>("levels");
const previewPanel = mustGetElement<HTMLElement>("preview-panel");
const previewCanvas = mustGetElement<HTMLCanvasElement>("preview-canvas");
const mipSelect = mustGetElement<HTMLSelectElement>("mip-select");
const dropZone = mustGetElement<HTMLElement>("drop-zone");
const fileInput = mustGetElement<HTMLInputElement>("file-input");

let activeRenderer: PreviewRenderer | null = null;
let loadGeneration = 0;
let zstdDecoderPromise: Promise<ZSTDDecoder> | null = null;

setViewerState({
  status: "idle",
  fileName: null,
  fileSize: 0,
  message: "Idle. Choose or drop a .ktx2 file.",
  levelCount: 0,
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
  if (Number.isInteger(mipLevel) && activeRenderer !== null) {
    activeRenderer.renderMip(mipLevel);
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
      previewAvailable: false,
    });
    return;
  }

  if (generation !== loadGeneration) {
    return;
  }

  let parsed: ParsedKTX2IBL;
  try {
    parsed = parseKTX2IBL(bytes);
  } catch (error) {
    const message =
      error instanceof KTX2IBLParseError
        ? `${error.name} [${error.code}]: ${error.message}`
        : errorMessage("Parse failed", error);
    setStatus("parse-error", message, "error");
    setViewerState({
      status: "parse-error",
      fileName: file.name,
      fileSize: file.size,
      message,
      levelCount: 0,
      previewAvailable: false,
    });
    return;
  }

  renderSummary(file, parsed, null);
  renderLevels(parsed, null);

  let decodedLevels: DecodedLevel[];
  try {
    decodedLevels = await decodeLevels(parsed);
  } catch (error) {
    const message = errorMessage("Zstd decode failed", error);
    renderSummary(file, parsed, null);
    renderLevels(parsed, null);
    setStatus("preview-error", `Parsed ${file.name}.\n${message}`, "error");
    setViewerState({
      status: "preview-error",
      fileName: file.name,
      fileSize: file.size,
      message,
      levelCount: parsed.levels.length,
      previewAvailable: false,
    });
    return;
  }

  if (generation !== loadGeneration) {
    return;
  }

  renderSummary(file, parsed, decodedLevels);
  renderLevels(parsed, decodedLevels);
  populateMipSelect(parsed.levels);

  const previewResult = await createPreviewRenderer(parsed, decodedLevels, previewCanvas);
  if (generation !== loadGeneration) {
    previewResult.kind === "ok" && previewResult.renderer.destroy();
    return;
  }

  if (previewResult.kind === "ok") {
    activeRenderer = previewResult.renderer;
    previewPanel.hidden = false;
    activeRenderer.renderMip(0);

    const message = [
      `Parsed ${file.name}.`,
      "Preview ready.",
      `File size: ${formatBytes(file.size)}`,
      `Mip levels: ${parsed.levels.length}`,
      `Compressed payload: ${formatBytes(totalCompressedBytes(parsed))}`,
      `Decompressed payload: ${formatBytes(totalDecodedBytes(decodedLevels))}`,
    ].join("\n");
    setStatus("ok", message, "ok");
    setViewerState({
      status: "ok",
      fileName: file.name,
      fileSize: file.size,
      message,
      levelCount: parsed.levels.length,
      previewAvailable: true,
    });
    return;
  }

  const message = [
    `Parsed ${file.name}.`,
    `Preview unavailable: ${previewResult.reason}`,
    `File size: ${formatBytes(file.size)}`,
    `Mip levels: ${parsed.levels.length}`,
    `Compressed payload: ${formatBytes(totalCompressedBytes(parsed))}`,
    `Decompressed payload: ${formatBytes(totalDecodedBytes(decodedLevels))}`,
  ].join("\n");
  setStatus("preview-unavailable", message, "warning");
  setViewerState({
    status: "preview-unavailable",
    fileName: file.name,
    fileSize: file.size,
    message,
    levelCount: parsed.levels.length,
    previewAvailable: false,
  });
}

async function decodeLevels(parsed: ParsedKTX2IBL): Promise<DecodedLevel[]> {
  const decoder = await getZstdDecoder();
  return parsed.levels.map((level) => {
    const bytes = decoder.decode(level.compressedBytes, level.uncompressedByteLength);
    if (bytes.byteLength !== level.uncompressedByteLength) {
      throw new Error(
        `Mip ${level.mipLevel} decoded to ${bytes.byteLength} bytes, expected ${level.uncompressedByteLength}.`,
      );
    }

    return { level, bytes };
  });
}

async function getZstdDecoder(): Promise<ZSTDDecoder> {
  if (zstdDecoderPromise === null) {
    zstdDecoderPromise = (async () => {
      const decoder = new ZSTDDecoder();
      await decoder.init();
      return decoder;
    })();
  }

  return zstdDecoderPromise;
}

async function createPreviewRenderer(
  parsed: ParsedKTX2IBL,
  decodedLevels: DecodedLevel[],
  canvas: HTMLCanvasElement,
): Promise<{ kind: "ok"; renderer: PreviewRenderer } | { kind: "unavailable"; reason: string }> {
  if (!("gpu" in navigator) || navigator.gpu === undefined) {
    return { kind: "unavailable", reason: "WebGPU is not available in this browser." };
  }

  const adapter = await navigator.gpu.requestAdapter();
  if (adapter === null) {
    return { kind: "unavailable", reason: "No WebGPU adapter was found." };
  }

  if (!adapter.features.has("texture-compression-bc" as GPUFeatureName)) {
    return { kind: "unavailable", reason: "The WebGPU adapter does not support texture-compression-bc." };
  }

  try {
    const device = await adapter.requestDevice({
      requiredFeatures: ["texture-compression-bc" as GPUFeatureName],
    });
    const canvasFormat =
      typeof navigator.gpu.getPreferredCanvasFormat === "function"
        ? navigator.gpu.getPreferredCanvasFormat()
        : CANVAS_FORMAT_FALLBACK;
    const context = canvas.getContext("webgpu") as GPUCanvasContext | null;
    if (context === null) {
      return { kind: "unavailable", reason: "Could not create a WebGPU canvas context." };
    }

    const texture = device.createTexture({
      label: "KTX2 BC6H cubemap preview texture",
      size: {
        width: parsed.header.pixelWidth,
        height: parsed.header.pixelHeight,
        depthOrArrayLayers: FACE_COUNT,
      },
      mipLevelCount: parsed.header.levelCount,
      dimension: "2d",
      format: BC6H_FORMAT,
      usage: TEXTURE_USAGE_TEXTURE_BINDING | TEXTURE_USAGE_COPY_DST,
    });

    for (const decoded of decodedLevels) {
      uploadDecodedLevel(device, texture, decoded);
    }

    const shader = device.createShaderModule({
      label: "KTX2 viewer shader",
      code: PREVIEW_SHADER,
    });
    const pipeline = device.createRenderPipeline({
      label: "KTX2 viewer pipeline",
      layout: "auto",
      vertex: {
        module: shader,
        entryPoint: "vertexMain",
      },
      fragment: {
        module: shader,
        entryPoint: "fragmentMain",
        targets: [{ format: canvasFormat }],
      },
      primitive: {
        topology: "triangle-list",
      },
    });
    const sampler = device.createSampler({
      label: "KTX2 viewer sampler",
      magFilter: "nearest",
      minFilter: "nearest",
      mipmapFilter: "nearest",
    });
    const uniformBuffer = device.createBuffer({
      label: "KTX2 viewer uniforms",
      size: 16,
      usage: BUFFER_USAGE_UNIFORM | BUFFER_USAGE_COPY_DST,
    });
    const bindGroup = device.createBindGroup({
      label: "KTX2 viewer bind group",
      layout: pipeline.getBindGroupLayout(0),
      entries: [
        {
          binding: 0,
          resource: texture.createView({
            dimension: "2d-array",
            baseArrayLayer: 0,
            arrayLayerCount: FACE_COUNT,
            baseMipLevel: 0,
            mipLevelCount: parsed.header.levelCount,
          }),
        },
        {
          binding: 1,
          resource: sampler,
        },
        {
          binding: 2,
          resource: {
            buffer: uniformBuffer,
          },
        },
      ],
    });

    return {
      kind: "ok",
      renderer: {
        renderMip(mipLevel: number): void {
          const level = parsed.levels[mipLevel];
          if (level === undefined) {
            return;
          }

          const facePreviewSize = clampInteger(level.width, MIN_PREVIEW_FACE_SIZE, MAX_PREVIEW_FACE_SIZE);
          canvas.width = facePreviewSize * CROSS_COLUMNS;
          canvas.height = facePreviewSize * CROSS_ROWS;
          context.configure({
            device,
            format: canvasFormat,
            alphaMode: "opaque",
          });

          device.queue.writeBuffer(uniformBuffer, 0, new Float32Array([mipLevel, level.width, 0, 0]));

          const encoder = device.createCommandEncoder({ label: "KTX2 viewer command encoder" });
          const pass = encoder.beginRenderPass({
            label: "KTX2 viewer render pass",
            colorAttachments: [
              {
                view: context.getCurrentTexture().createView(),
                clearValue: { r: 0.04, g: 0.05, b: 0.06, a: 1 },
                loadOp: "clear",
                storeOp: "store",
              },
            ],
          });
          pass.setPipeline(pipeline);
          pass.setBindGroup(0, bindGroup);
          pass.draw(6, FACE_COUNT);
          pass.end();
          device.queue.submit([encoder.finish()]);
        },
        destroy(): void {
          texture.destroy();
          uniformBuffer.destroy();
        },
      },
    };
  } catch (error) {
    return { kind: "unavailable", reason: errorMessage("WebGPU preview failed", error) };
  }
}

function uploadDecodedLevel(device: GPUDevice, texture: GPUTexture, decoded: DecodedLevel): void {
  for (let faceIndex = 0; faceIndex < FACE_COUNT; faceIndex += 1) {
    const face = decoded.level.faces[faceIndex];
    if (face === undefined) {
      throw new Error(`Mip ${decoded.level.mipLevel} is missing face ${faceIndex}.`);
    }

    const faceEnd = face.uncompressedByteOffset + face.uncompressedByteLength;
    const faceBytes = decoded.bytes.subarray(face.uncompressedByteOffset, faceEnd);
    const blocksX = Math.ceil(decoded.level.width / BC6H_BLOCK_SIZE);
    const blocksY = Math.ceil(decoded.level.height / BC6H_BLOCK_SIZE);
    device.queue.writeTexture(
      {
        texture,
        mipLevel: decoded.level.mipLevel,
        origin: {
          x: 0,
          y: 0,
          z: faceIndex,
        },
      },
      faceBytes,
      {
        bytesPerRow: blocksX * BC6H_BYTES_PER_BLOCK,
        rowsPerImage: blocksY,
      },
      {
        width: blocksX * BC6H_BLOCK_SIZE,
        height: blocksY * BC6H_BLOCK_SIZE,
        depthOrArrayLayers: 1,
      },
    );
  }
}

function renderSummary(file: File, parsed: ParsedKTX2IBL, decodedLevels: DecodedLevel[] | null): void {
  const decodedBytes = decodedLevels === null ? null : totalDecodedBytes(decodedLevels);
  const cards = [
    {
      title: "File",
      value: file.name,
      detail: formatBytes(file.size),
    },
    {
      title: "Topology",
      value: `${parsed.header.pixelWidth} x ${parsed.header.pixelHeight}`,
      detail: `${parsed.header.levelCount} mip(s) - ${parsed.header.faceCount} faces`,
    },
    {
      title: "Format",
      value: parsed.format.vkFormatName,
      detail: `${parsed.format.supercompression} - ${parsed.format.blockWidth}x${parsed.format.blockHeight} blocks`,
    },
    {
      title: "Payload",
      value: formatBytes(totalCompressedBytes(parsed)),
      detail: decodedBytes === null ? "Decode pending" : `${formatBytes(decodedBytes)} after zstd decode`,
    },
    {
      title: "Orientation",
      value: parsed.keyValues.KTXorientation ?? "unknown",
      detail: parsed.keyValues.KTXwriter ?? "Missing KTXwriter",
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

function renderLevels(parsed: ParsedKTX2IBL, decodedLevels: DecodedLevel[] | null): void {
  levelsPanel.hidden = false;
  if (parsed.levels.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No mip levels.";
    levelsElement.replaceChildren(empty);
    return;
  }

  const decodedByMip = new Map(decodedLevels?.map((decoded) => [decoded.level.mipLevel, decoded.bytes.byteLength]));
  const table = document.createElement("table");
  table.className = "level-table";

  const head = document.createElement("thead");
  head.innerHTML = `
    <tr>
      <th>Mip</th>
      <th>Size</th>
      <th>File offset</th>
      <th>Compressed</th>
      <th>Decompressed</th>
      <th>Face bytes</th>
    </tr>
  `;

  const body = document.createElement("tbody");
  for (const level of parsed.levels) {
    const row = document.createElement("tr");
    const decodedByteLength = decodedByMip.get(level.mipLevel);
    row.replaceChildren(
      tableCell(String(level.mipLevel)),
      tableCell(`${level.width} x ${level.height}`),
      tableCell(String(level.byteOffset)),
      tableCell(formatBytes(level.byteLength)),
      tableCell(
        decodedByteLength === undefined
          ? `${formatBytes(level.uncompressedByteLength)} expected`
          : formatBytes(decodedByteLength),
      ),
      tableCell(`${FACE_ORDER.length} x ${formatBytes(level.faces[0]?.uncompressedByteLength ?? 0)}`),
    );
    body.append(row);
  }

  table.append(head, body);
  levelsElement.replaceChildren(table);
}

function populateMipSelect(levels: ParsedKTX2IBLLevel[]): void {
  mipSelect.replaceChildren(
    ...levels.map((level) => {
      const option = document.createElement("option");
      option.value = String(level.mipLevel);
      option.textContent = `Mip ${level.mipLevel} (${level.width} x ${level.height})`;
      return option;
    }),
  );
  mipSelect.value = "0";
}

function resetResult(): void {
  activeRenderer?.destroy();
  activeRenderer = null;
  previewPanel.hidden = true;
  levelsPanel.hidden = true;
  summaryElement.replaceChildren();
  levelsElement.replaceChildren();
  mipSelect.replaceChildren();
}

function setStatus(status: ViewerStatus, message: string, tone: "loading" | "ok" | "warning" | "error"): void {
  statusElement.textContent = message;
  statusElement.className = `status ${tone === "loading" ? "" : tone}`.trim();
  statusElement.dataset.status = status;
}

function setViewerState(state: ViewerState): void {
  window.__KTX2_VIEWER__ = state;
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

function totalCompressedBytes(parsed: ParsedKTX2IBL): number {
  return parsed.levels.reduce((total, level) => total + level.byteLength, 0);
}

function totalDecodedBytes(decodedLevels: DecodedLevel[]): number {
  return decodedLevels.reduce((total, decoded) => total + decoded.bytes.byteLength, 0);
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

function clampInteger(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

const PREVIEW_SHADER = /* wgsl */ `
struct PreviewParams {
  mipLevel: f32,
  mipSize: f32,
  _pad1: f32,
  _pad2: f32,
};

struct VertexOut {
  @builtin(position) position: vec4<f32>,
  @location(0) uv: vec2<f32>,
  @location(1) faceIndex: f32,
};

@group(0) @binding(0) var sourceTexture: texture_2d_array<f32>;
@group(0) @binding(1) var sourceSampler: sampler;
@group(0) @binding(2) var<uniform> params: PreviewParams;

@vertex
fn vertexMain(@builtin(vertex_index) vertexIndex: u32, @builtin(instance_index) instanceIndex: u32) -> VertexOut {
  var positions = array<vec2<f32>, 6>(
    vec2<f32>(0.0, 0.0),
    vec2<f32>(1.0, 0.0),
    vec2<f32>(0.0, 1.0),
    vec2<f32>(0.0, 1.0),
    vec2<f32>(1.0, 0.0),
    vec2<f32>(1.0, 1.0),
  );
  var crossSlots = array<vec2<f32>, 6>(
    vec2<f32>(2.0, 1.0),
    vec2<f32>(0.0, 1.0),
    vec2<f32>(1.0, 0.0),
    vec2<f32>(1.0, 2.0),
    vec2<f32>(1.0, 1.0),
    vec2<f32>(3.0, 1.0),
  );

  let local = positions[vertexIndex];
  let tileSize = vec2<f32>(1.0 / 4.0, 1.0 / 3.0);
  let atlasPosition = (crossSlots[instanceIndex] + local) * tileSize;

  var out: VertexOut;
  out.position = vec4<f32>(atlasPosition.x * 2.0 - 1.0, 1.0 - atlasPosition.y * 2.0, 0.0, 1.0);
  out.uv = local;
  out.faceIndex = f32(instanceIndex);
  return out;
}

@fragment
fn fragmentMain(in: VertexOut) -> @location(0) vec4<f32> {
  let mipSize = max(params.mipSize, 1.0);
  let boundedUv = min(max(in.uv, vec2<f32>(0.0)), vec2<f32>(0.999999));
  let texelCenterUv = (floor(boundedUv * mipSize) + vec2<f32>(0.5)) / mipSize;
  let hdr = textureSampleLevel(sourceTexture, sourceSampler, texelCenterUv, i32(in.faceIndex), params.mipLevel).rgb;
  let mapped = max(hdr, vec3<f32>(0.0)) / (vec3<f32>(1.0) + max(hdr, vec3<f32>(0.0)));
  let srgb = pow(mapped, vec3<f32>(1.0 / 2.2));
  return vec4<f32>(srgb, 1.0);
}
`;

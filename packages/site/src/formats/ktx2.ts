import {
  KTX2IBLParseError,
  parseKTX2IBL,
  type ParsedKTX2IBL,
  type ParsedKTX2IBLLevel,
} from "@ibltools/ktx2-loader";
import { ZSTDDecoder } from "zstddec";
import { bc6hCopyLayout, isBC6HBaseDimensionSupported } from "../bc6h-layout.ts";
import { ViewerPreviewError, type FormatSession, type LevelTable, type SummaryCard, type ViewerElements } from "./types.ts";
import { formatBytes, renderLevels as renderLevelTable, renderSummary as renderSummaryCards } from "../ui.ts";

const FACE_COUNT = 6;
const FACE_ORDER = ["px", "nx", "py", "ny", "pz", "nz"] as const;
const BC6H_FORMAT = "bc6h-rgb-ufloat" as GPUTextureFormat;
const CANVAS_FORMAT_FALLBACK = "bgra8unorm" as GPUTextureFormat;
const MAX_PREVIEW_FACE_SIZE = 256;
const MIN_PREVIEW_FACE_SIZE = 64;
const CROSS_COLUMNS = 4;
const CROSS_ROWS = 3;
const TEXTURE_USAGE_TEXTURE_BINDING = 0x04;
const TEXTURE_USAGE_COPY_DST = 0x02;
const BUFFER_USAGE_COPY_DST = 0x08;
const BUFFER_USAGE_UNIFORM = 0x40;

interface DecodedLevel {
  level: ParsedKTX2IBLLevel;
  bytes: Uint8Array;
}

interface PreviewRenderer {
  renderMip(mipLevel: number): void;
  destroy(): void;
}

let zstdDecoderPromise: Promise<ZSTDDecoder> | null = null;

export async function loadKTX2(
  bytes: Uint8Array,
  fileName: string,
  fileSize: number,
  elements: ViewerElements,
  signal: AbortSignal,
  onPreviewError: (error: Error) => void,
): Promise<FormatSession> {
  const parsed = parseKTX2(bytes);
  renderSummary(elements, fileName, fileSize, parsed, null);
  renderLevels(elements, parsed, null);

  let decodedLevels: DecodedLevel[];
  try {
    decodedLevels = await decodeLevels(parsed, signal);
  } catch (error) {
    if (signal.aborted) {
      throw error;
    }
    throw new ViewerPreviewError(errorMessage("Zstd decode failed", error), parsed.levels.length);
  }

  signal.throwIfAborted();

  renderSummary(elements, fileName, fileSize, parsed, decodedLevels);
  renderLevels(elements, parsed, decodedLevels);

  const previewResult = await createPreviewRenderer(
    parsed,
    decodedLevels,
    elements.previewCanvas,
    signal,
    onPreviewError,
  );
  if (signal.aborted) {
    if (previewResult.kind === "ok") {
      previewResult.renderer.destroy();
    }
    signal.throwIfAborted();
  }
  if (previewResult.kind === "unavailable") {
    const message = [
      `Parsed ${fileName}.`,
      `Preview unavailable: ${previewResult.reason}`,
      `File size: ${formatBytes(fileSize)}`,
      `Mip levels: ${parsed.levels.length}`,
      `Compressed payload: ${formatBytes(totalCompressedBytes(parsed))}`,
      `Decompressed payload: ${formatBytes(totalDecodedBytes(decodedLevels))}`,
    ].join("\n");
    return {
      format: "ktx2",
      levelCount: parsed.levels.length,
      previewAvailable: false,
      cubemap: true,
      mips: parsed.levels.map((level) => ({ value: level.mipLevel, label: mipLabel(level) })),
      message,
      renderMip: () => undefined,
      destroy: () => undefined,
    };
  }

  try {
    previewResult.renderer.renderMip(0);
  } catch (error) {
    previewResult.renderer.destroy();
    throw new ViewerPreviewError(errorMessage("WebGPU preview failed", error), parsed.levels.length);
  }
  const message = [
    `Parsed ${fileName}.`,
    "Preview ready.",
    `File size: ${formatBytes(fileSize)}`,
    `Mip levels: ${parsed.levels.length}`,
    `Compressed payload: ${formatBytes(totalCompressedBytes(parsed))}`,
    `Decompressed payload: ${formatBytes(totalDecodedBytes(decodedLevels))}`,
  ].join("\n");

  return {
    format: "ktx2",
    levelCount: parsed.levels.length,
    previewAvailable: true,
    cubemap: true,
    mips: parsed.levels.map((level) => ({ value: level.mipLevel, label: mipLabel(level) })),
    message,
    renderMip: previewResult.renderer.renderMip,
    destroy: previewResult.renderer.destroy,
  };
}

function parseKTX2(bytes: Uint8Array): ParsedKTX2IBL {
  try {
    return parseKTX2IBL(bytes);
  } catch (error) {
    if (error instanceof KTX2IBLParseError) {
      throw new Error(`${error.name} [${error.code}]: ${error.message}`);
    }
    throw error;
  }
}

async function decodeLevels(parsed: ParsedKTX2IBL, signal: AbortSignal): Promise<DecodedLevel[]> {
  const decoder = await getZstdDecoder();
  const decodedLevels: DecodedLevel[] = [];
  for (const level of parsed.levels) {
    signal.throwIfAborted();
    const bytes = decoder.decode(level.compressedBytes, level.uncompressedByteLength);
    if (bytes.byteLength !== level.uncompressedByteLength) {
      throw new Error(
        `Mip ${level.mipLevel} decoded to ${bytes.byteLength} bytes, expected ${level.uncompressedByteLength}.`,
      );
    }

    decodedLevels.push({ level, bytes });
  }
  return decodedLevels;
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
  signal: AbortSignal,
  onPreviewError: (error: Error) => void,
): Promise<{ kind: "ok"; renderer: PreviewRenderer } | { kind: "unavailable"; reason: string }> {
  signal.throwIfAborted();
  if (!isBC6HBaseDimensionSupported(parsed.header.pixelWidth, parsed.header.pixelHeight)) {
    return {
      kind: "unavailable",
      reason: "WebGPU BC6H preview requires base dimensions aligned to 4-pixel compression blocks.",
    };
  }
  if (!("gpu" in navigator) || navigator.gpu === undefined) {
    return { kind: "unavailable", reason: "WebGPU is not available in this browser." };
  }

  let adapter: GPUAdapter | null;
  try {
    adapter = await navigator.gpu.requestAdapter();
  } catch (error) {
    return { kind: "unavailable", reason: errorMessage("WebGPU adapter request failed", error) };
  }
  signal.throwIfAborted();
  if (adapter === null) {
    return { kind: "unavailable", reason: "No WebGPU adapter was found." };
  }

  if (!adapter.features.has("texture-compression-bc" as GPUFeatureName)) {
    return { kind: "unavailable", reason: "The WebGPU adapter does not support texture-compression-bc." };
  }

  let device: GPUDevice | null = null;
  let texture: GPUTexture | null = null;
  let uniformBuffer: GPUBuffer | null = null;
  try {
    device = await adapter.requestDevice({
      requiredFeatures: ["texture-compression-bc" as GPUFeatureName],
    });
    signal.throwIfAborted();
    const canvasFormat =
      typeof navigator.gpu.getPreferredCanvasFormat === "function"
        ? navigator.gpu.getPreferredCanvasFormat()
        : CANVAS_FORMAT_FALLBACK;
    const context = canvas.getContext("webgpu") as GPUCanvasContext | null;
    if (context === null) {
      throw new Error("Could not create a WebGPU canvas context.");
    }

    const activeDevice = device;
    texture = activeDevice.createTexture({
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
      signal.throwIfAborted();
      uploadDecodedLevel(activeDevice, texture, decoded);
    }

    const shader = activeDevice.createShaderModule({ label: "KTX2 viewer shader", code: PREVIEW_SHADER });
    const pipeline = activeDevice.createRenderPipeline({
      label: "KTX2 viewer pipeline",
      layout: "auto",
      vertex: { module: shader, entryPoint: "vertexMain" },
      fragment: { module: shader, entryPoint: "fragmentMain", targets: [{ format: canvasFormat }] },
      primitive: { topology: "triangle-list" },
    });
    const sampler = activeDevice.createSampler({ magFilter: "nearest", minFilter: "nearest", mipmapFilter: "nearest" });
    uniformBuffer = activeDevice.createBuffer({
      label: "KTX2 viewer uniforms",
      size: 16,
      usage: BUFFER_USAGE_UNIFORM | BUFFER_USAGE_COPY_DST,
    });
    const bindGroup = activeDevice.createBindGroup({
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
        { binding: 1, resource: sampler },
        { binding: 2, resource: { buffer: uniformBuffer } },
      ],
    });

    const renderer: PreviewRenderer = {
      renderMip(mipLevel: number): void {
        const level = parsed.levels[mipLevel];
        if (level === undefined) {
          return;
        }

        const facePreviewSize = clampInteger(level.width, MIN_PREVIEW_FACE_SIZE, MAX_PREVIEW_FACE_SIZE);
        canvas.width = facePreviewSize * CROSS_COLUMNS;
        canvas.height = facePreviewSize * CROSS_ROWS;
        context.configure({ device: activeDevice, format: canvasFormat, alphaMode: "opaque" });
        activeDevice.queue.writeBuffer(uniformBuffer as GPUBuffer, 0, new Float32Array([mipLevel, level.width, 0, 0]));

        const encoder = activeDevice.createCommandEncoder({ label: "KTX2 viewer command encoder" });
        const pass = encoder.beginRenderPass({
          label: "KTX2 viewer render pass",
          colorAttachments: [{
            view: context.getCurrentTexture().createView(),
            clearValue: { r: 0.04, g: 0.05, b: 0.06, a: 1 },
            loadOp: "clear",
            storeOp: "store",
          }],
        });
        pass.setPipeline(pipeline);
        pass.setBindGroup(0, bindGroup);
        pass.draw(6, FACE_COUNT);
        pass.end();
        activeDevice.queue.submit([encoder.finish()]);
      },
      destroy(): void {
        texture?.destroy();
        uniformBuffer?.destroy();
        device?.destroy();
        texture = null;
        uniformBuffer = null;
        device = null;
      },
    };
    let destroyed = false;
    const handleUncapturedError = (event: GPUUncapturedErrorEvent): void => {
      event.preventDefault();
      if (!destroyed) {
        onPreviewError(new Error(`WebGPU validation failed: ${event.error.message}`));
      }
    };
    activeDevice.addEventListener("uncapturederror", handleUncapturedError);
    const destroyRenderer = renderer.destroy;
    renderer.destroy = (): void => {
      if (destroyed) {
        return;
      }
      destroyed = true;
      activeDevice.removeEventListener("uncapturederror", handleUncapturedError);
      destroyRenderer();
    };
    void activeDevice.lost.then((info) => {
      if (!destroyed) {
        onPreviewError(new Error(`WebGPU device was lost${info.message ? `: ${info.message}` : "."}`));
      }
    });

    return {
      kind: "ok",
      renderer,
    };
  } catch (error) {
    texture?.destroy();
    uniformBuffer?.destroy();
    device?.destroy();
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
    const layout = bc6hCopyLayout(decoded.level.width, decoded.level.height);
    device.queue.writeTexture(
      { texture, mipLevel: decoded.level.mipLevel, origin: { x: 0, y: 0, z: faceIndex } },
      faceBytes,
      { bytesPerRow: layout.bytesPerRow, rowsPerImage: layout.rowsPerImage },
      { width: layout.width, height: layout.height, depthOrArrayLayers: 1 },
    );
  }
}

function renderSummary(
  elements: ViewerElements,
  fileName: string,
  fileSize: number,
  parsed: ParsedKTX2IBL,
  decodedLevels: DecodedLevel[] | null,
): void {
  const decodedBytes = decodedLevels === null ? null : totalDecodedBytes(decodedLevels);
  const cards: SummaryCard[] = [
    { title: "File", value: fileName, detail: formatBytes(fileSize) },
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
  renderSummaryCards(elements, cards);
}

function renderLevels(elements: ViewerElements, parsed: ParsedKTX2IBL, decodedLevels: DecodedLevel[] | null): void {
  const decodedByMip = new Map(decodedLevels?.map((decoded) => [decoded.level.mipLevel, decoded.bytes.byteLength]));
  const table: LevelTable = {
    headers: ["Mip", "Size", "File offset", "Compressed", "Decompressed", "Face bytes"],
    rows: parsed.levels.map((level) => {
      const decodedByteLength = decodedByMip.get(level.mipLevel);
      return [
        String(level.mipLevel),
        `${level.width} x ${level.height}`,
        String(level.byteOffset),
        formatBytes(level.byteLength),
        decodedByteLength === undefined ? `${formatBytes(level.uncompressedByteLength)} expected` : formatBytes(decodedByteLength),
        `${FACE_ORDER.length} x ${formatBytes(level.faces[0]?.uncompressedByteLength ?? 0)}`,
      ];
    }),
  };
  renderLevelTable(elements, table);
}

function mipLabel(level: ParsedKTX2IBLLevel): string {
  return `Mip ${level.mipLevel} (${level.width} x ${level.height})`;
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
    vec2<f32>(0.0, 0.0), vec2<f32>(1.0, 0.0), vec2<f32>(0.0, 1.0),
    vec2<f32>(0.0, 1.0), vec2<f32>(1.0, 0.0), vec2<f32>(1.0, 1.0),
  );
  var crossSlots = array<vec2<f32>, 6>(
    vec2<f32>(2.0, 1.0), vec2<f32>(0.0, 1.0), vec2<f32>(1.0, 0.0),
    vec2<f32>(1.0, 2.0), vec2<f32>(1.0, 1.0), vec2<f32>(3.0, 1.0),
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

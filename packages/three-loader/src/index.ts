import * as THREE from "three";

import {
  IBLAParseError,
  parseIBLA,
  type ParsedChunk,
  type ParsedIBLA,
} from "@ibltools/loader";

export class ThreeIBLAError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ThreeIBLAError";
  }
}

export interface LoadIBLACubemapOptions {
  label?: string;
}

export async function loadIBLACubemap(
  buffer: ArrayBuffer | Uint8Array,
  options: LoadIBLACubemapOptions = {},
): Promise<THREE.CubeTexture> {
  const parsed = parseIBLA(buffer);
  const groupedChunks = assertCubemap(parsed, options.label ?? "IBLA cubemap");
  const mipmaps = await Promise.all(
    groupedChunks.map(async (chunks) => ({
      images: await Promise.all(chunks.map((chunk) => decodeChunkToCanvas(chunk, parsed.manifest.encoding))),
      width: chunks[0]?.width ?? 0,
      height: chunks[0]?.height ?? 0,
    })),
  );

  const baseLevel = mipmaps[0];
  if (baseLevel === undefined) {
    throw new ThreeIBLAError("Expected at least one mip level.");
  }

  const texture = new THREE.CubeTexture(baseLevel.images);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.generateMipmaps = mipmaps.length <= 1;
  texture.needsUpdate = true;
  texture.name = options.label ?? "IBLA cubemap";

  // three stores extra mip levels on the generic texture.mipmaps field.
  // We keep the face order intact so browser integration tests can consume the baked chain.
  texture.mipmaps = mipmaps.map((mip) => mip.images);

  return texture;
}

export async function loadIBLAIrradianceCubemap(
  buffer: ArrayBuffer | Uint8Array,
  options: LoadIBLACubemapOptions = {},
): Promise<THREE.CubeTexture> {
  return loadIBLACubemap(buffer, {
    label: options.label ?? "IBLA irradiance cubemap",
  });
}

export function assertCubemap(parsed: ParsedIBLA, label: string): ParsedChunk[][] {
  if (parsed.topology.kind !== "cubemap" || parsed.manifest.faceCount !== 6) {
    throw new ThreeIBLAError(`${label} must be a cubemap .ibla asset.`);
  }

  return groupChunksByMip(parsed.chunks);
}

export function groupChunksByMip(chunks: ParsedChunk[]): ParsedChunk[][] {
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
    .map(([, mipChunks]) => mipChunks);
}

export function decodeRgbdSrgbPixel(
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

export function tonemapLinearPixel(linearR: number, linearG: number, linearB: number): [number, number, number] {
  return [
    linearToDisplayByte(reinhard(linearR)),
    linearToDisplayByte(reinhard(linearG)),
    linearToDisplayByte(reinhard(linearB)),
  ];
}

async function decodeChunkToCanvas(
  chunk: ParsedChunk,
  encoding: ParsedIBLA["manifest"]["encoding"],
): Promise<HTMLCanvasElement> {
  const image = await decodePngToImage(chunk.encodedBytes);
  const sourceCanvas = document.createElement("canvas");
  sourceCanvas.width = chunk.width;
  sourceCanvas.height = chunk.height;

  const sourceContext = sourceCanvas.getContext("2d");
  if (sourceContext === null) {
    throw new ThreeIBLAError("Could not create a 2D canvas context.");
  }

  sourceContext.drawImage(image, 0, 0);
  const sourceImageData = sourceContext.getImageData(0, 0, sourceCanvas.width, sourceCanvas.height);
  const outputImageData = sourceContext.createImageData(sourceCanvas.width, sourceCanvas.height);
  const sourcePixels = sourceImageData.data;
  const outputPixels = outputImageData.data;

  for (let pixelIndex = 0; pixelIndex < sourceCanvas.width * sourceCanvas.height; pixelIndex += 1) {
    const rgbaOffset = pixelIndex * 4;
    const encodedR = sourcePixels[rgbaOffset] / 255;
    const encodedG = sourcePixels[rgbaOffset + 1] / 255;
    const encodedB = sourcePixels[rgbaOffset + 2] / 255;
    const encodedA = sourcePixels[rgbaOffset + 3] / 255;

    const [linearR, linearG, linearB] =
      encoding === "rgbd-srgb"
        ? decodeRgbdSrgbPixel(encodedR, encodedG, encodedB, encodedA)
        : encoding === "srgb"
          ? [
              srgbToLinearUnit(encodedR),
              srgbToLinearUnit(encodedG),
              srgbToLinearUnit(encodedB),
            ]
          : [encodedR, encodedG, encodedB];

    const [displayR, displayG, displayB] = tonemapLinearPixel(linearR, linearG, linearB);
    outputPixels[rgbaOffset] = displayR;
    outputPixels[rgbaOffset + 1] = displayG;
    outputPixels[rgbaOffset + 2] = displayB;
    outputPixels[rgbaOffset + 3] = 255;
  }

  const outputCanvas = document.createElement("canvas");
  outputCanvas.width = chunk.width;
  outputCanvas.height = chunk.height;
  const outputContext = outputCanvas.getContext("2d");
  if (outputContext === null) {
    throw new ThreeIBLAError("Could not create an output canvas context.");
  }

  outputContext.putImageData(outputImageData, 0, 0);
  return outputCanvas;
}

async function decodePngToImage(bytes: Uint8Array): Promise<HTMLImageElement> {
  const blob = new Blob([bytes], { type: "image/png" });
  const objectUrl = URL.createObjectURL(blob);

  try {
    return await new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new ThreeIBLAError("PNG decode failed."));
      image.src = objectUrl;
    });
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
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
  return Math.min(1, Math.max(0, value));
}

export { IBLAParseError };

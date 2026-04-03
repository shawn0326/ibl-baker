import * as THREE from "three";
import { HDRLoader } from "three/addons/loaders/HDRLoader.js";

import {
  loadIBLACubemap,
  loadIBLAIrradianceCubemap,
  ThreeIBLAError,
} from "@ibltools/three-loader";

import royalHdrUrl from "../../../fixtures/inputs/royal_esplanade_1k.hdr?url";
import grandHdrUrl from "../../../fixtures/inputs/Grand_Canyon_C.hdr?url";
import royalSpecularUrl from "../../../fixtures/outputs/royal_esplanade_1k/specular.ibla?url";
import royalIrradianceUrl from "../../../fixtures/outputs/royal_esplanade_1k/irradiance.ibla?url";
import grandSpecularUrl from "../../../fixtures/outputs/grand_canyon_c/specular.ibla?url";
import grandIrradianceUrl from "../../../fixtures/outputs/grand_canyon_c/irradiance.ibla?url";

interface FixtureDescriptor {
  hdrUrl: string;
  specularUrl: string;
  irradianceUrl: string;
}

interface RenderResources {
  hdrTexture: THREE.Texture;
  iblaSpecular: THREE.CubeTexture;
  iblaMipCount: number;
  pmremMaxMip: number;
  pmremCubeSize: number;
}

interface TextSpriteOptions {
  width: number;
  height: number;
  fontSize: number;
  fontWeight?: string;
  color?: string;
  letterSpacing?: number;
}

const FACE_ORDER = ["px", "nx", "py", "ny", "pz", "nz"] as const;
const TILE_SIZE = 1;
const TILE_GAP = 0.14;
const FACE_GAP = 0.34;
const ROW_GAP = 0.16;

declare global {
  interface Window {
    __IBL_E2E__?: {
      fixture: string;
      hdrLoaded: boolean;
      specularLoaded: boolean;
      irradianceLoaded: boolean;
      status: "ok" | "error";
      message: string;
    };
  }
}

const fixtures: Record<string, FixtureDescriptor> = {
  royal_esplanade_1k: {
    hdrUrl: royalHdrUrl,
    specularUrl: royalSpecularUrl,
    irradianceUrl: royalIrradianceUrl,
  },
  grand_canyon_c: {
    hdrUrl: grandHdrUrl,
    specularUrl: grandSpecularUrl,
    irradianceUrl: grandIrradianceUrl,
  },
};

void main();

async function main(): Promise<void> {
  const fixture = new URL(window.location.href).searchParams.get("fixture") ?? "royal_esplanade_1k";
  const descriptor = fixtures[fixture];
  const statusElement = mustGetElement<HTMLPreElement>("status");
  const viewportElement = mustGetElement<HTMLDivElement>("viewport");

  if (descriptor === undefined) {
    const message = `Unknown fixture "${fixture}".`;
    statusElement.textContent = message;
    window.__IBL_E2E__ = {
      fixture,
      hdrLoaded: false,
      specularLoaded: false,
      irradianceLoaded: false,
      status: "error",
      message,
    };
    return;
  }

  try {
    const [specularBuffer, irradianceBuffer] = await Promise.all([
      fetchBuffer(descriptor.specularUrl),
      fetchBuffer(descriptor.irradianceUrl),
    ]);

    const [hdrTexture, specularTexture, irradianceTexture] = await Promise.all([
      loadHdrEnvironment(descriptor.hdrUrl),
      loadIBLACubemap(specularBuffer, { label: `${fixture} specular` }),
      loadIBLAIrradianceCubemap(irradianceBuffer, { label: `${fixture} irradiance` }),
    ]);

    const resources = createRenderResources(hdrTexture, specularTexture);
    renderScene(viewportElement, resources);

    const message = [
      `fixture: ${fixture}`,
      "status: ok",
      "layout: rows = mip levels, face groups = px nx py ny pz nz",
      "pairing: left tile = baked IBLA cubemap, right tile = source HDR through three PMREM",
      `ibla mip count: ${resources.iblaMipCount}`,
      `pmrem cube size: ${resources.pmremCubeSize}`,
      `pmrem mip span: sharp ${resources.pmremMaxMip} -> blur -2`,
      `specular name: ${specularTexture.name}`,
      `irradiance name: ${irradianceTexture.name} (loaded for contract coverage, not visualized)`,
    ].join("\n");

    statusElement.textContent = message;
    window.__IBL_E2E__ = {
      fixture,
      hdrLoaded: true,
      specularLoaded: true,
      irradianceLoaded: true,
      status: "ok",
      message,
    };
  } catch (error) {
    const message =
      error instanceof Error ? `${error.name}: ${error.message}` : `Unknown error: ${String(error)}`;
    statusElement.textContent = message;
    window.__IBL_E2E__ = {
      fixture,
      hdrLoaded: false,
      specularLoaded: false,
      irradianceLoaded: false,
      status: "error",
      message,
    };
  }
}

function createRenderResources(
  hdrTexture: THREE.Texture,
  iblaSpecular: THREE.CubeTexture,
): RenderResources {
  iblaSpecular.colorSpace = THREE.NoColorSpace;
  iblaSpecular.needsUpdate = true;

  const pmremMaxMip = Math.floor(Math.log2(readTextureWidth(hdrTexture) / 4));
  const pmremCubeSize = 2 ** pmremMaxMip;

  return {
    hdrTexture,
    iblaSpecular,
    iblaMipCount: iblaSpecular.mipmaps.length + 1,
    pmremMaxMip,
    pmremCubeSize,
  };
}

function renderScene(viewportElement: HTMLDivElement, resources: RenderResources): void {
  viewportElement.replaceChildren();

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: false,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const viewportWidth = Math.max(780, Math.round(viewportElement.clientWidth || 1320));
  const viewportHeight = Math.max(720, Math.round(viewportElement.clientHeight || 1080));
  renderer.setSize(viewportWidth, viewportHeight, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.setClearColor(new THREE.Color("#120f0d"));
  viewportElement.append(renderer.domElement);

  const pmremGenerator = new THREE.PMREMGenerator(renderer);
  pmremGenerator.compileEquirectangularShader();
  const pmremRenderTarget = pmremGenerator.fromEquirectangular(resources.hdrTexture);
  pmremRenderTarget.texture.name = `${resources.iblaSpecular.name} PMREM`;

  const rowCount = resources.iblaMipCount;
  const pairWidth = TILE_SIZE * 2 + TILE_GAP;
  const contentWidth = FACE_ORDER.length * pairWidth + (FACE_ORDER.length - 1) * FACE_GAP;
  const contentHeight = rowCount * TILE_SIZE + (rowCount - 1) * ROW_GAP;
  const contentLeft = -contentWidth / 2;
  const contentTop = contentHeight / 2;

  const scene = new THREE.Scene();

  const camera = new THREE.OrthographicCamera(
    -contentWidth / 2 - 1.35,
    contentWidth / 2 + 0.8,
    contentHeight / 2 + 1.05,
    -contentHeight / 2 - 0.55,
    0.1,
    20,
  );
  camera.position.z = 8;

  const tileGeometry = new THREE.PlaneGeometry(TILE_SIZE, TILE_SIZE);
  const frameGeometry = new THREE.PlaneGeometry(TILE_SIZE + 0.08, TILE_SIZE + 0.08);
  const groupGeometry = new THREE.PlaneGeometry(pairWidth + 0.18, contentHeight + 0.52);

  FACE_ORDER.forEach((faceName, faceIndex) => {
    const pairStart = contentLeft + faceIndex * (pairWidth + FACE_GAP);
    const pairCenter = pairStart + pairWidth / 2;
    const faceTint = new THREE.Color(faceIndex % 2 === 0 ? "#241d18" : "#1c1713");

    const groupPanel = new THREE.Mesh(
      groupGeometry,
      new THREE.MeshBasicMaterial({ color: faceTint, transparent: true, opacity: 0.9 }),
    );
    groupPanel.position.set(pairCenter, 0, -0.18);
    scene.add(groupPanel);

    const faceLabel = createTextSprite(faceName.toUpperCase(), {
      width: pairWidth,
      height: 0.3,
      fontSize: 34,
      fontWeight: "700",
      color: "#efe4d6",
      letterSpacing: 1.5,
    });
    faceLabel.position.set(pairCenter, contentTop + 0.4, 0.15);
    scene.add(faceLabel);

    for (let mipLevel = 0; mipLevel < rowCount; mipLevel += 1) {
      const y = contentTop - TILE_SIZE / 2 - mipLevel * (TILE_SIZE + ROW_GAP);
      const leftX = pairStart + TILE_SIZE / 2;
      const rightX = pairStart + TILE_SIZE + TILE_GAP + TILE_SIZE / 2;

      scene.add(createTileFrame(frameGeometry, leftX, y));
      scene.add(createTileFrame(frameGeometry, rightX, y));
      const iblaTile = new THREE.Mesh(
        tileGeometry,
        createIBLAMaterial(resources.iblaSpecular, faceIndex, mipLevel),
      );
      iblaTile.position.set(leftX, y, 0);
      scene.add(iblaTile);

      const pmremMip = clamp(resources.pmremMaxMip - mipLevel, -2, resources.pmremMaxMip);
      const pmremTile = new THREE.Mesh(
        tileGeometry,
        createPMREMMaterial(
          pmremRenderTarget.texture,
          faceIndex,
          pmremMipToRoughness(pmremMip),
          resources.pmremMaxMip,
        ),
      );
      pmremTile.position.set(rightX, y, 0);
      scene.add(pmremTile);
    }
  });

  for (let mipLevel = 0; mipLevel < rowCount; mipLevel += 1) {
    const y = contentTop - TILE_SIZE / 2 - mipLevel * (TILE_SIZE + ROW_GAP);
    const label = createTextSprite(`mip ${mipLevel}`, {
      width: 0.92,
      height: 0.24,
      fontSize: 24,
      color: "#cbb8a5",
    });
    label.position.set(-contentWidth / 2 - 0.72, y, 0.12);
    scene.add(label);
  }

  renderer.render(scene, camera);
  pmremGenerator.dispose();
  pmremRenderTarget.dispose();
}

function createTileFrame(geometry: THREE.PlaneGeometry, x: number, y: number): THREE.Mesh {
  const frame = new THREE.Mesh(
    geometry,
    new THREE.MeshBasicMaterial({ color: new THREE.Color("#43362a"), transparent: true, opacity: 0.92 }),
  );
  frame.position.set(x, y, -0.05);
  return frame;
}

function createIBLAMaterial(
  texture: THREE.CubeTexture,
  faceIndex: number,
  mipLevel: number,
): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    glslVersion: THREE.GLSL3,
    uniforms: {
      envMap: { value: texture },
      faceIndex: { value: faceIndex },
      mipLevel: { value: mipLevel },
    },
    vertexShader: commonVertexShader,
    fragmentShader: `
      precision highp float;

      uniform samplerCube envMap;
      uniform int faceIndex;
      uniform float mipLevel;

      in vec2 vUv;

      out vec4 outColor;

      ${faceDirectionShaderChunk}

      void main() {
        vec3 sampleDirection = faceUvToDirection(faceIndex, vUv);
        vec3 color = textureLod(envMap, sampleDirection, mipLevel).rgb;
        outColor = vec4(color, 1.0);
      }
    `,
  });
}

function createPMREMMaterial(
  texture: THREE.Texture,
  faceIndex: number,
  roughness: number,
  pmremMaxMip: number,
): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    glslVersion: THREE.GLSL3,
    uniforms: {
      envMap: { value: texture },
      faceIndex: { value: faceIndex },
      roughness: { value: roughness },
    },
    defines: {
      CUBEUV_TEXEL_WIDTH: (1 / readTextureWidth(texture)).toFixed(8),
      CUBEUV_TEXEL_HEIGHT: (1 / readTextureHeight(texture)).toFixed(8),
      CUBEUV_MAX_MIP: `${pmremMaxMip}.0`,
    },
    vertexShader: commonVertexShader,
    fragmentShader: `
      precision highp float;

      uniform sampler2D envMap;
      uniform int faceIndex;
      uniform float roughness;

      in vec2 vUv;

      out vec4 outColor;

      ${faceDirectionShaderChunk}
      ${cubeUvShaderChunk}

      vec3 reinhardTonemap(vec3 color) {
        vec3 clamped = max(color, vec3(0.0));
        return clamped / (1.0 + clamped);
      }

      vec3 linearToSrgb(vec3 color) {
        vec3 cutoff = step(color, vec3(0.0031308));
        vec3 lower = color * 12.92;
        vec3 higher = 1.055 * pow(max(color, vec3(0.0)), vec3(1.0 / 2.4)) - 0.055;
        return mix(higher, lower, cutoff);
      }

      void main() {
        vec3 sampleDirection = faceUvToDirection(faceIndex, vUv);
        vec3 color = textureCubeUV(envMap, sampleDirection, roughness).rgb;
        outColor = vec4(linearToSrgb(reinhardTonemap(color)), 1.0);
      }
    `,
  });
}

async function loadHdrEnvironment(url: string): Promise<THREE.Texture> {
  const loader = new HDRLoader();
  const texture = await loader.loadAsync(url);
  texture.mapping = THREE.EquirectangularReflectionMapping;
  return texture;
}

async function fetchBuffer(url: string): Promise<ArrayBuffer> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new ThreeIBLAError(`Failed to fetch ${url}: ${response.status}`);
  }

  return response.arrayBuffer();
}

function createTextSprite(text: string, options: TextSpriteOptions): THREE.Sprite {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 128;

  const context = canvas.getContext("2d");
  if (context === null) {
    throw new Error("Could not create a 2D canvas context for labels.");
  }

  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = options.color ?? "#ffffff";
  context.font = `${options.fontWeight ?? "600"} ${options.fontSize}px "Segoe UI", sans-serif`;
  context.textAlign = "center";
  context.textBaseline = "middle";

  if (options.letterSpacing !== undefined) {
    drawSpacedText(context, text, canvas.width / 2, canvas.height / 2, options.letterSpacing);
  } else {
    context.fillText(text, canvas.width / 2, canvas.height / 2);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;

  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      depthTest: false,
      depthWrite: false,
    }),
  );
  sprite.scale.set(options.width, options.height, 1);
  return sprite;
}

function drawSpacedText(
  context: CanvasRenderingContext2D,
  text: string,
  centerX: number,
  centerY: number,
  letterSpacing: number,
): void {
  const glyphs = [...text];
  const textWidth = glyphs.reduce((sum, glyph) => sum + context.measureText(glyph).width, 0);
  const totalWidth = textWidth + letterSpacing * Math.max(0, glyphs.length - 1);
  let cursorX = centerX - totalWidth / 2;

  glyphs.forEach((glyph) => {
    const glyphWidth = context.measureText(glyph).width;
    context.fillText(glyph, cursorX + glyphWidth / 2, centerY);
    cursorX += glyphWidth + letterSpacing;
  });
}

function readTextureWidth(texture: THREE.Texture): number {
  const image = texture.image as { width?: number } | undefined;
  const width = image?.width;
  if (typeof width !== "number" || Number.isNaN(width) || width <= 0) {
    throw new ThreeIBLAError("Texture width is not available.");
  }

  return width;
}

function readTextureHeight(texture: THREE.Texture): number {
  const image = texture.image as { height?: number } | undefined;
  const height = image?.height;
  if (typeof height !== "number" || Number.isNaN(height) || height <= 0) {
    throw new ThreeIBLAError("Texture height is not available.");
  }

  return height;
}

function pmremMipToRoughness(mip: number): number {
  if (mip <= -1) {
    return clamp(1 - (mip + 2) / 5, 0.8, 1);
  }

  if (mip <= 2) {
    return clamp(0.8 - (mip + 1) / 7.5, 0.4, 0.8);
  }

  if (mip <= 3) {
    return clamp(0.4 - (mip - 2) * 0.095, 0.305, 0.4);
  }

  if (mip <= 4) {
    return clamp(0.305 - (mip - 3) * 0.095, 0.21, 0.305);
  }

  return clamp(Math.pow(2, -mip / 2) / 1.16, 0, 0.21);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function mustGetElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error(`Missing element #${id}.`);
  }

  return element as T;
}

const commonVertexShader = `
  out vec2 vUv;

  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const faceDirectionShaderChunk = `
  vec3 faceUvToDirection(int face, vec2 uv) {
    vec2 p = uv * 2.0 - 1.0;

    if (face == 0) {
      return normalize(vec3(1.0, p.y, p.x));
    }

    if (face == 1) {
      return normalize(vec3(-1.0, p.y, -p.x));
    }

    if (face == 2) {
      return normalize(vec3(-p.x, 1.0, -p.y));
    }

    if (face == 3) {
      return normalize(vec3(-p.x, -1.0, p.y));
    }

    if (face == 4) {
      return normalize(vec3(-p.x, p.y, 1.0));
    }

    return normalize(vec3(p.x, p.y, -1.0));
  }
`;

const cubeUvShaderChunk = `
  #define cubeUV_minMipLevel 4.0
  #define cubeUV_minTileSize 16.0
  #define cubeUV_r0 1.0
  #define cubeUV_m0 -2.0
  #define cubeUV_r1 0.8
  #define cubeUV_m1 -1.0
  #define cubeUV_r4 0.4
  #define cubeUV_m4 2.0
  #define cubeUV_r5 0.305
  #define cubeUV_m5 3.0
  #define cubeUV_r6 0.21
  #define cubeUV_m6 4.0

  float getFace(vec3 direction) {
    vec3 absDirection = abs(direction);
    float face = -1.0;

    if (absDirection.x > absDirection.z) {
      if (absDirection.x > absDirection.y) {
        face = direction.x > 0.0 ? 0.0 : 3.0;
      } else {
        face = direction.y > 0.0 ? 1.0 : 4.0;
      }
    } else {
      if (absDirection.z > absDirection.y) {
        face = direction.z > 0.0 ? 2.0 : 5.0;
      } else {
        face = direction.y > 0.0 ? 1.0 : 4.0;
      }
    }

    return face;
  }

  vec2 getUV(vec3 direction, float face) {
    vec2 uv;

    if (face == 0.0) {
      uv = vec2(direction.z, direction.y) / abs(direction.x);
    } else if (face == 1.0) {
      uv = vec2(-direction.x, -direction.z) / abs(direction.y);
    } else if (face == 2.0) {
      uv = vec2(-direction.x, direction.y) / abs(direction.z);
    } else if (face == 3.0) {
      uv = vec2(-direction.z, direction.y) / abs(direction.x);
    } else if (face == 4.0) {
      uv = vec2(-direction.x, direction.z) / abs(direction.y);
    } else {
      uv = vec2(direction.x, direction.y) / abs(direction.z);
    }

    return 0.5 * (uv + 1.0);
  }

  vec3 bilinearCubeUV(sampler2D map, vec3 direction, float mipInt) {
    float face = getFace(direction);
    float filterInt = max(cubeUV_minMipLevel - mipInt, 0.0);
    mipInt = max(mipInt, cubeUV_minMipLevel);
    float faceSize = exp2(mipInt);
    vec2 uv = getUV(direction, face) * (faceSize - 2.0) + 1.0;

    if (face > 2.0) {
      uv.y += faceSize;
      face -= 3.0;
    }

    uv.x += face * faceSize;
    uv.x += filterInt * 3.0 * cubeUV_minTileSize;
    uv.y += 4.0 * (exp2(CUBEUV_MAX_MIP) - faceSize);
    uv.x *= CUBEUV_TEXEL_WIDTH;
    uv.y *= CUBEUV_TEXEL_HEIGHT;

    return texture(map, uv).rgb;
  }

  float roughnessToMip(float value) {
    float mip = 0.0;

    if (value >= cubeUV_r1) {
      mip = (cubeUV_r0 - value) * (cubeUV_m1 - cubeUV_m0) / (cubeUV_r0 - cubeUV_r1) + cubeUV_m0;
    } else if (value >= cubeUV_r4) {
      mip = (cubeUV_r1 - value) * (cubeUV_m4 - cubeUV_m1) / (cubeUV_r1 - cubeUV_r4) + cubeUV_m1;
    } else if (value >= cubeUV_r5) {
      mip = (cubeUV_r4 - value) * (cubeUV_m5 - cubeUV_m4) / (cubeUV_r4 - cubeUV_r5) + cubeUV_m4;
    } else if (value >= cubeUV_r6) {
      mip = (cubeUV_r5 - value) * (cubeUV_m6 - cubeUV_m5) / (cubeUV_r5 - cubeUV_r6) + cubeUV_m5;
    } else {
      mip = -2.0 * log2(1.16 * value);
    }

    return mip;
  }

  vec4 textureCubeUV(sampler2D map, vec3 sampleDir, float value) {
    float mip = clamp(roughnessToMip(value), cubeUV_m0, CUBEUV_MAX_MIP);
    float mipFraction = fract(mip);
    float mipFloor = floor(mip);
    vec3 color0 = bilinearCubeUV(map, sampleDir, mipFloor);

    if (mipFraction == 0.0) {
      return vec4(color0, 1.0);
    }

    vec3 color1 = bilinearCubeUV(map, sampleDir, mipFloor + 1.0);
    return vec4(mix(color0, color1, mipFraction), 1.0);
  }
`;

import * as THREE from "three";

import {
  loadIBLACubemap,
  loadIBLAIrradianceCubemap,
  ThreeIBLAError,
} from "@ibltools/three-loader";

import royalSpecularUrl from "../../../fixtures/outputs/royal_esplanade_1k/specular.ibla?url";
import royalIrradianceUrl from "../../../fixtures/outputs/royal_esplanade_1k/irradiance.ibla?url";
import grandSpecularUrl from "../../../fixtures/outputs/grand_canyon_c/specular.ibla?url";
import grandIrradianceUrl from "../../../fixtures/outputs/grand_canyon_c/irradiance.ibla?url";

interface FixtureDescriptor {
  specularUrl: string;
  irradianceUrl: string;
}

declare global {
  interface Window {
    __IBL_E2E__?: {
      fixture: string;
      specularLoaded: boolean;
      irradianceLoaded: boolean;
      status: "ok" | "error";
      message: string;
    };
  }
}

const fixtures: Record<string, FixtureDescriptor> = {
  royal_esplanade_1k: {
    specularUrl: royalSpecularUrl,
    irradianceUrl: royalIrradianceUrl,
  },
  grand_canyon_c: {
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

    const [specularTexture, irradianceTexture] = await Promise.all([
      loadIBLACubemap(specularBuffer, { label: `${fixture} specular` }),
      loadIBLAIrradianceCubemap(irradianceBuffer, { label: `${fixture} irradiance` }),
    ]);

    renderScene(viewportElement, specularTexture, irradianceTexture);

    const message = [
      `fixture: ${fixture}`,
      "status: ok",
      `specular name: ${specularTexture.name}`,
      `irradiance name: ${irradianceTexture.name}`,
    ].join("\n");

    statusElement.textContent = message;
    window.__IBL_E2E__ = {
      fixture,
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
      specularLoaded: false,
      irradianceLoaded: false,
      status: "error",
      message,
    };
  }
}

function renderScene(
  viewportElement: HTMLDivElement,
  specularTexture: THREE.CubeTexture,
  irradianceTexture: THREE.CubeTexture,
): void {
  viewportElement.replaceChildren();

  const renderer = new THREE.WebGLRenderer({
    antialias: false,
    alpha: false,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(1);
  renderer.setSize(960, 720, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  viewportElement.append(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = specularTexture;
  scene.environment = specularTexture;

  const camera = new THREE.PerspectiveCamera(35, 960 / 720, 0.1, 100);
  camera.position.set(0, 0.75, 5.5);
  camera.lookAt(0, 0.4, 0);

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(12, 12),
    new THREE.MeshStandardMaterial({
      color: new THREE.Color("#d7c8b6"),
      roughness: 0.95,
      metalness: 0.02,
      envMap: irradianceTexture,
      envMapIntensity: 0.9,
    }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -1.1;
  scene.add(floor);

  const geometry = new THREE.SphereGeometry(0.95, 64, 32);
  const leftSphere = new THREE.Mesh(
    geometry,
    new THREE.MeshStandardMaterial({
      color: new THREE.Color("#d9d7d1"),
      roughness: 0.08,
      metalness: 1.0,
      envMap: specularTexture,
      envMapIntensity: 1.1,
    }),
  );
  leftSphere.position.set(-1.25, 0, 0);
  scene.add(leftSphere);

  const rightSphere = new THREE.Mesh(
    geometry,
    new THREE.MeshStandardMaterial({
      color: new THREE.Color("#d0c5b5"),
      roughness: 0.82,
      metalness: 0.18,
      envMap: irradianceTexture,
      envMapIntensity: 0.85,
    }),
  );
  rightSphere.position.set(1.25, 0, 0);
  scene.add(rightSphere);

  const keyLight = new THREE.DirectionalLight(0xffffff, 0.6);
  keyLight.position.set(3, 4, 2);
  scene.add(keyLight);

  renderer.render(scene, camera);
}

async function fetchBuffer(url: string): Promise<ArrayBuffer> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new ThreeIBLAError(`Failed to fetch ${url}: ${response.status}`);
  }

  return response.arrayBuffer();
}

function mustGetElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error(`Missing element #${id}.`);
  }

  return element as T;
}

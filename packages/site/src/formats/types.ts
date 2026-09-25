import type { AssetFormat } from "../detect-format.ts";

export interface ViewerElements {
  status: HTMLPreElement;
  summary: HTMLElement;
  levelsPanel: HTMLElement;
  levels: HTMLElement;
  previewPanel: HTMLElement;
  previewCanvas: HTMLCanvasElement;
  mipSelect: HTMLSelectElement;
  dropZone: HTMLElement;
  fileInput: HTMLInputElement;
  faceLabels: HTMLElement;
}

export interface ViewerState {
  status: "idle" | "loading" | "ok" | "parse-error" | "preview-unavailable" | "preview-error";
  format: AssetFormat | null;
  fileName: string | null;
  fileSize: number;
  message: string;
  levelCount: number;
  previewAvailable: boolean;
}

export interface SummaryCard {
  title: string;
  value: string;
  detail: string;
}

export interface LevelTable {
  headers: string[];
  rows: string[][];
}

export interface MipOption {
  value: number;
  label: string;
}

export interface FormatSession {
  format: AssetFormat;
  levelCount: number;
  previewAvailable: boolean;
  mips: MipOption[];
  message: string;
  cubemap: boolean;
  renderMip(mipLevel: number): void;
  destroy(): void;
}

export class ViewerPreviewError extends Error {
  readonly levelCount: number;

  constructor(message: string, levelCount: number) {
    super(message);
    this.name = "ViewerPreviewError";
    this.levelCount = levelCount;
  }
}

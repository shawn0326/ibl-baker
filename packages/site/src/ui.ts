import type {
  LevelTable,
  MipOption,
  SummaryCard,
  ViewerElements,
  ViewerState,
} from "./formats/types.ts";

declare global {
  interface Window {
    __IBL_SITE__?: ViewerState;
  }
}

export function createViewerElements(): ViewerElements {
  return {
    status: mustGetElement<HTMLPreElement>("status"),
    summary: mustGetElement<HTMLElement>("summary"),
    levelsPanel: mustGetElement<HTMLElement>("levels-panel"),
    levels: mustGetElement<HTMLElement>("levels"),
    previewPanel: mustGetElement<HTMLElement>("preview-panel"),
    previewCanvas: mustGetElement<HTMLCanvasElement>("preview-canvas"),
    mipSelect: mustGetElement<HTMLSelectElement>("mip-select"),
    dropZone: mustGetElement<HTMLElement>("drop-zone"),
    fileInput: mustGetElement<HTMLInputElement>("file-input"),
    faceLabels: mustGetElement<HTMLElement>("face-labels"),
  };
}

export function resetResult(elements: ViewerElements): void {
  elements.previewPanel.hidden = true;
  elements.levelsPanel.hidden = true;
  elements.faceLabels.hidden = true;
  elements.summary.replaceChildren();
  elements.levels.replaceChildren();
  elements.mipSelect.replaceChildren();
  const replacementCanvas = document.createElement("canvas");
  replacementCanvas.id = elements.previewCanvas.id;
  elements.previewCanvas.replaceWith(replacementCanvas);
  elements.previewCanvas = replacementCanvas;
}

export function setStatus(
  elements: ViewerElements,
  status: ViewerState["status"],
  message: string,
  tone: "loading" | "ok" | "warning" | "error",
): void {
  elements.status.textContent = message;
  elements.status.className = `status ${tone === "loading" ? "" : tone}`.trim();
  elements.status.dataset.status = status;
}

export function setViewerState(state: ViewerState): void {
  window.__IBL_SITE__ = state;
}

export function renderSummary(elements: ViewerElements, cards: SummaryCard[]): void {
  elements.summary.replaceChildren(
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

export function renderLevels(elements: ViewerElements, table: LevelTable): void {
  elements.levelsPanel.hidden = false;
  const tableElement = document.createElement("table");
  tableElement.className = "level-table";

  const head = document.createElement("thead");
  const headerRow = document.createElement("tr");
  headerRow.append(...table.headers.map((header) => tableCell(header, "th")));
  head.append(headerRow);

  const body = document.createElement("tbody");
  for (const rowValues of table.rows) {
    const row = document.createElement("tr");
    row.append(...rowValues.map((value) => tableCell(value, "td")));
    body.append(row);
  }

  tableElement.append(head, body);
  elements.levels.replaceChildren(tableElement);
}

export function populateMipSelect(elements: ViewerElements, options: MipOption[]): void {
  elements.mipSelect.replaceChildren(
    ...options.map((option) => {
      const element = document.createElement("option");
      element.value = String(option.value);
      element.textContent = option.label;
      return element;
    }),
  );
  elements.mipSelect.value = String(options[0]?.value ?? 0);
}

export function showPreview(elements: ViewerElements, cubemap: boolean): void {
  elements.previewPanel.hidden = false;
  elements.faceLabels.hidden = !cubemap;
}

export function hidePreview(elements: ViewerElements): void {
  elements.previewPanel.hidden = true;
}

export function formatBytes(byteLength: number): string {
  if (byteLength < 1024) {
    return `${byteLength} B`;
  }

  const kilobytes = byteLength / 1024;
  if (kilobytes < 1024) {
    return `${kilobytes.toFixed(1)} KB`;
  }

  return `${(kilobytes / 1024).toFixed(2)} MB`;
}

export function errorMessage(prefix: string, error: unknown): string {
  if (error instanceof Error) {
    return `${prefix}: ${error.message}`;
  }

  return `${prefix}: ${String(error)}`;
}

function tableCell(text: string, type: "th" | "td"): HTMLTableCellElement {
  const cell = document.createElement(type);
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

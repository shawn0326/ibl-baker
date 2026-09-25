import { detectAssetFormat, type AssetFormat } from "./detect-format.ts";
import { loadIBLA } from "./formats/ibla.ts";
import { loadKTX2 } from "./formats/ktx2.ts";
import { ViewerPreviewError, type FormatSession, type ViewerElements, type ViewerState } from "./formats/types.ts";
import {
  createViewerElements,
  errorMessage,
  hidePreview,
  populateMipSelect,
  resetResult,
  setStatus,
  setViewerState,
  showPreview,
} from "./ui.ts";

const elements = createViewerElements();
let activeSession: FormatSession | null = null;
let activeLoad: AbortController | null = null;
let activeFile: File | null = null;
let loadGeneration = 0;

setViewerState({
  status: "idle",
  format: null,
  fileName: null,
  fileSize: 0,
  message: "Idle. Choose or drop a .ibla or .ktx2 file.",
  levelCount: 0,
  previewAvailable: false,
});

elements.fileInput.addEventListener("change", () => {
  const file = elements.fileInput.files?.[0];
  if (file !== undefined) {
    void loadFile(file);
  }
  elements.fileInput.value = "";
});

elements.dropZone.addEventListener("dragenter", (event) => {
  event.preventDefault();
  elements.dropZone.classList.add("dragging");
});

elements.dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  elements.dropZone.classList.add("dragging");
});

elements.dropZone.addEventListener("dragleave", () => {
  elements.dropZone.classList.remove("dragging");
});

elements.dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  elements.dropZone.classList.remove("dragging");
  const file = event.dataTransfer?.files[0];
  if (file !== undefined) {
    void loadFile(file);
  }
});

elements.mipSelect.addEventListener("change", () => {
  const mipLevel = Number.parseInt(elements.mipSelect.value, 10);
  if (Number.isInteger(mipLevel) && activeSession !== null) {
    const session = activeSession;
    try {
      session.renderMip(mipLevel);
    } catch (error) {
      session.destroy();
      activeSession = null;
      hidePreview(elements);
      if (activeFile !== null) {
        showError(
          activeFile,
          session.format,
          "preview-error",
          errorMessage("Preview failed", error),
          session.levelCount,
        );
      }
    }
  }
});

async function loadFile(file: File): Promise<void> {
  const generation = ++loadGeneration;
  activeLoad?.abort();
  const loadController = new AbortController();
  activeLoad = loadController;
  activeFile = file;
  activeSession?.destroy();
  activeSession = null;
  resetResult(elements);
  setStatus(elements, "loading", `Loading ${file.name}...`, "loading");
  setViewerState({
    status: "loading",
    format: null,
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
    if (generation !== loadGeneration) {
      return;
    }
    showError(file, null, "preview-error", errorMessage("File read failed", error), 0);
    return;
  }

  if (generation !== loadGeneration) {
    return;
  }

  const format = detectAssetFormat(bytes, file.name);
  if (format === null) {
    showError(file, null, "parse-error", "Unsupported file format. Choose an .ibla or .ktx2 asset.", 0);
    return;
  }

  setViewerState({
    status: "loading",
    format,
    fileName: file.name,
    fileSize: file.size,
    message: "Parsing file.",
    levelCount: 0,
    previewAvailable: false,
  });

  try {
    const session = await loadFormat(format, bytes, file, elements, loadController.signal);
    if (generation !== loadGeneration) {
      session.destroy();
      return;
    }

    activeSession = session;
    populateMipSelect(elements, session.mips);
    if (session.previewAvailable) {
      showPreview(elements, session.cubemap);
    } else {
      hidePreview(elements);
    }
    setStatus(elements, session.previewAvailable ? "ok" : "preview-unavailable", session.message, session.previewAvailable ? "ok" : "warning");
    setViewerState({
      status: session.previewAvailable ? "ok" : "preview-unavailable",
      format: session.format,
      fileName: file.name,
      fileSize: file.size,
      message: session.message,
      levelCount: session.levelCount,
      previewAvailable: session.previewAvailable,
    });
  } catch (error) {
    if (generation !== loadGeneration) {
      return;
    }

    const isPreviewError = error instanceof ViewerPreviewError;
    const message = errorMessage(isPreviewError ? "Preview failed" : "Parse failed", error);
    showError(file, format, isPreviewError ? "preview-error" : "parse-error", message, isPreviewError ? error.levelCount : 0);
  }
}

function loadFormat(
  format: AssetFormat,
  bytes: Uint8Array,
  file: File,
  viewerElements: ViewerElements,
  signal: AbortSignal,
): Promise<FormatSession> {
  return format === "ibla"
    ? loadIBLA(bytes, file.name, file.size, viewerElements, signal)
    : loadKTX2(bytes, file.name, file.size, viewerElements, signal, (error) => {
        if (signal.aborted || activeSession === null) {
          return;
        }
        const levelCount = activeSession.levelCount;
        activeSession.destroy();
        activeSession = null;
        hidePreview(elements);
        showError(file, "ktx2", "preview-error", errorMessage("WebGPU preview failed", error), levelCount);
      });
}

function showError(
  file: File,
  format: AssetFormat | null,
  status: Extract<ViewerState["status"], "parse-error" | "preview-error">,
  message: string,
  levelCount: number,
): void {
  const fullMessage = `${message}\nFile: ${file.name}`;
  setStatus(elements, status, fullMessage, "error");
  setViewerState({
    status,
    format,
    fileName: file.name,
    fileSize: file.size,
    message: fullMessage,
    levelCount,
    previewAvailable: false,
  });
}

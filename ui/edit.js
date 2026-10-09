let api;
let number = 0;
let slot = 0;
let outputGroup = 1;
let output = [];
let excluded = [];
let active = 0;
let rotation = 0;
let split = false;
let previewEpoch = 0;
let viewScale = 1;
let rerenderTimer = 0;
let suppressSpy = false;
let skipClick = false;
let stampFrame = null;
let stampLabel = "";
let stampPhase = null;
let stampDrag = null;
let stampMoved = false;
let stampBusy = false;
let masking = false;
let maskDrag = null;
let masks = [];
let pageWidth = 595;
let pageHeight = 842;
let maskChain = Promise.resolve();
let trimLive = null;
let trimDrag = null;
let trimKeyPiece = null;
let trimBusy = false;
let skewLive = null;
let skewBusy = false;
let skewRepeat = 0;
let skewFromPointer = false;
const TRIM_EDGES = [
  ["top", "上"],
  ["bottom", "下"],
  ["left", "左"],
  ["right", "右"],
];
const thumbCache = new Map();
const previewCache = new Map();
const pending = [];
let inflight = 0;
let navObserver;
let pageObserver;

window.loadEditor = (nextNumber, nextSlot) => {
  const next = Number(nextNumber);
  const nextSlotIndex = Number(nextSlot);
  const same = api && number === next && slot === nextSlotIndex && output.length > 0;
  number = next;
  slot = nextSlotIndex;
  if (!api || same) return;
  openCurrent();
};

window.retarget = (nextNumber, nextSlot) => {
  number = Number(nextNumber);
  slot = Number(nextSlot);
  if (!api) return;
  refreshContext(true);
};

window.invalidatePreview = () => {
  previewEpoch += 1;
  previewCache.clear();
  if (!api) return;
  refreshContext(false).then(() => observePages());
};

window.reloadAppearance = async () => {
  previewEpoch += 1;
  previewCache.clear();
  thumbCache.clear();
  if (!api) return;
  await refreshContext(false);
  if (output.length) draw();
};

window.addEventListener("pywebviewready", () => {
  api = window.pywebview.api;
  if (number) openCurrent();
});

document.getElementById("mask").addEventListener("click", () => {
  masking = !masking;
  if (!masking) cancelMaskDrag();
  paintMaskMode();
});

document.getElementById("trim-clear").addEventListener("click", () => {
  const piece = output[active];
  if (!piece || trimBusy) return;
  commitTrim(piece, zeroTrim());
});

document.getElementById("skew-left").addEventListener("pointerdown", (event) => onSkewPointerDown(-1, event));
document.getElementById("skew-right").addEventListener("pointerdown", (event) => onSkewPointerDown(1, event));
for (const id of ["skew-left", "skew-right"]) {
  const button = document.getElementById(id);
  button.addEventListener("pointerup", onSkewPointerUp);
  button.addEventListener("pointercancel", onSkewPointerUp);
}
document.getElementById("skew-left").addEventListener("click", () => onSkewClick(-1));
document.getElementById("skew-right").addEventListener("click", () => onSkewClick(1));
document.getElementById("skew-readout").addEventListener("dblclick", (event) => {
  event.preventDefault();
  const piece = output[active];
  if (!piece || skewBusy || shownSkew(piece) === 0) return;
  const baked = skewLive && skewLive.key === skewKey(piece) ? skewLive.baked : savedSkew(piece);
  commitSkew(piece, 0, baked);
});

document.getElementById("reset").addEventListener("click", async () => {
  const result = await api.reset_pages(number, slot);
  if (result && result.ok === false) showBanner(result.message || "元に戻せません。");
  previewEpoch += 1;
  previewCache.clear();
  await loadPages();
  jumpTo(0);
});

document.getElementById("nav").addEventListener("dragover", (event) => {
  event.preventDefault();
  const nav = event.currentTarget;
  const rect = nav.getBoundingClientRect();
  if (event.clientY < rect.top + 28) nav.scrollTop -= 14;
  if (event.clientY > rect.bottom - 28) nav.scrollTop += 14;
});

document.getElementById("pages").addEventListener("pointerdown", onMaskPointerDown);
document.getElementById("pages").addEventListener("pointermove", onMaskPointerMove);
document.getElementById("pages").addEventListener("pointerup", onMaskPointerUp);
document.getElementById("pages").addEventListener("pointercancel", onMaskPointerUp);

document.getElementById("pages").addEventListener("scroll", () => {
  if (suppressSpy || !output.length) return;
  const root = document.getElementById("pages");
  const line = root.scrollTop + 24;
  let index = 0;
  for (const sheet of root.children) {
    if (sheet.offsetTop <= line) index = Number(sheet.dataset.index);
  }
  setActive(index, true);
});

document.getElementById("pages").addEventListener("wheel", (event) => {
  if (!event.ctrlKey || !event.deltaY) return;
  event.preventDefault();
  const step = event.deltaY > 0 ? 1 / 1.1 : 1.1;
  zoomAt(event.clientX, event.clientY, viewScale * step);
}, { passive: false });

document.getElementById("zoom-out").addEventListener("click", () => {
  zoomAtCenter(viewScale / 1.1);
});
document.getElementById("zoom-in").addEventListener("click", () => {
  zoomAtCenter(viewScale * 1.1);
});
document.getElementById("zoom-label").addEventListener("click", () => {
  zoomAtCenter(1);
});

window.addEventListener("resize", () => {
  layoutSheets();
  scheduleRerender();
});

async function openCurrent() {
  active = 0;
  viewScale = 1;
  stampPhase = null;
  stampDrag = null;
  stampMoved = false;
  trimLive = null;
  trimDrag = null;
  trimKeyPiece = null;
  previewEpoch += 1;
  previewCache.clear();
  await refreshContext(false);
  await loadPages();
  jumpTo(0);
}

async function refreshContext(redraw) {
  const context = await api.context();
  if (!context || context.ok === false) return;
  number = context.number;
  slot = context.slot;
  rotation = context.rotation || 0;
  split = Boolean(context.split);
  stampFrame = context.stampFrame || null;
  stampLabel = context.label || "";
  pageWidth = context.pageWidth || (stampFrame && stampFrame.pageWidth) || pageWidth;
  pageHeight = context.pageHeight || (stampFrame && stampFrame.pageHeight) || pageHeight;
  document.getElementById("heading").textContent = context.label || "ページ編集";
  paintStamp();
  if (redraw) observePages();
}

async function loadPages() {
  const data = await api.editor(number, slot);
  if (!data || data.ok === false) {
    showBanner((data && data.message) || "ページを読めません。");
    return;
  }
  const shown = (data.columns || []).find((column) => column.group !== 0) || { group: 1, pages: [] };
  const hidden = (data.columns || []).find((column) => column.group === 0) || { pages: [] };
  outputGroup = shown.group;
  output = shown.pages.slice();
  excluded = hidden.pages.slice();
  masks = data.masks || [];
  if (active >= output.length) active = Math.max(0, output.length - 1);
  draw();
}

function draw() {
  drawNav();
  drawPages();
}

function drawNav() {
  const nav = document.getElementById("nav");
  nav.innerHTML = "";
  output.forEach((piece, index) => {
    const item = document.createElement("div");
    item.className = index === active ? "thumb is-active" : "thumb";
    item.draggable = true;
    item.dataset.index = String(index);
    const image = document.createElement("img");
    image.alt = "";
    const mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = pieceMark(piece, index);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove";
    remove.textContent = "×";
    remove.setAttribute("aria-label", "このページを外す");
    remove.disabled = output.length <= 1;
    remove.addEventListener("pointerdown", (event) => event.stopPropagation());
    remove.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      removePage(index);
    });
    item.append(image, mark, remove);
    item.addEventListener("dragstart", (event) => {
      if (event.target.closest(".remove")) {
        event.preventDefault();
        return;
      }
      skipClick = true;
      event.dataTransfer.setData("text/plain", String(index));
      event.dataTransfer.effectAllowed = "move";
    });
    item.addEventListener("dragend", () => {
      setTimeout(() => { skipClick = false; }, 0);
    });
    item.addEventListener("dragover", (event) => event.preventDefault());
    item.addEventListener("drop", (event) => {
      event.preventDefault();
      const from = Number(event.dataTransfer.getData("text/plain"));
      if (!Number.isInteger(from) || from === index || from < 0 || from >= output.length) return;
      const [moved] = output.splice(from, 1);
      output.splice(index, 0, moved);
      commit(index);
    });
    item.addEventListener("click", () => {
      if (skipClick) {
        skipClick = false;
        return;
      }
      jumpTo(index);
    });
    nav.appendChild(item);
  });
  if (navObserver) navObserver.disconnect();
  navObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const index = Number(entry.target.dataset.index);
      const image = entry.target.querySelector("img");
      if (output[index]) loadThumb(image, output[index]);
    }
  }, { root: nav, rootMargin: "160px" });
  for (const item of nav.children) navObserver.observe(item);
}

function drawPages() {
  const root = document.getElementById("pages");
  const top = root.scrollTop;
  root.innerHTML = "";
  output.forEach((piece, index) => {
    const sheet = document.createElement("div");
    sheet.className = "sheet";
    sheet.dataset.index = String(index);
    const image = document.createElement("img");
    image.className = "page";
    image.alt = pieceMark(piece, index);
    image.draggable = false;
    image.addEventListener("load", () => {
      if (Number(sheet.dataset.index) === active) releaseSkewOverlay();
    });
    sheet.appendChild(image);
    if (index === 0 && stampFrame) sheet.appendChild(stampButton());
    root.appendChild(sheet);
  });
  layoutSheets();
  trimDrag = null;
  trimKeyPiece = null;
  trimLive = null;
  stopSkewRepeat();
  paintMasks();
  paintTrim();
  paintSkew();
  root.scrollTop = top;
  observePages();
}

function observePages() {
  const root = document.getElementById("pages");
  if (pageObserver) pageObserver.disconnect();
  pageObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      const image = entry.target.querySelector("img.page");
      if (!entry.isIntersecting) {
        if (image) image.removeAttribute("src");
        continue;
      }
      loadSheet(entry.target, image);
    }
  }, { root, rootMargin: "240px" });
  for (const sheet of root.children) pageObserver.observe(sheet);
}

function pieceMark(piece, index) {
  const part = piece.part === 1 ? "前" : piece.part === 2 ? "後" : "";
  return part ? `${index + 1}${part}` : String(index + 1);
}

function fitWidth() {
  const root = document.getElementById("pages");
  return Math.max(240, root.clientWidth - 32);
}

function maxScale() {
  const cap = (4 * 595) / (fitWidth() * (window.devicePixelRatio || 1));
  return Math.max(0.5, Math.min(2, cap));
}

function clampScale(value) {
  return Math.min(maxScale(), Math.max(0.5, value));
}

function sheetCssWidth() {
  return fitWidth() * viewScale;
}

function sheetZoom() {
  const zoom = (sheetCssWidth() / 595) * (window.devicePixelRatio || 1);
  return Math.min(4, Math.max(0.2, zoom));
}

function layoutSheets() {
  const width = `${sheetCssWidth()}px`;
  document.querySelectorAll("#pages .sheet").forEach((sheet) => {
    sheet.style.width = width;
  });
  paintStamp();
  paintZoom();
}

function paintZoom() {
  const label = document.getElementById("zoom-label");
  if (label) label.textContent = `${Math.round(viewScale * 100)}%`;
  const zoomOut = document.getElementById("zoom-out");
  const zoomIn = document.getElementById("zoom-in");
  if (zoomOut) zoomOut.disabled = viewScale <= 0.5 + 0.001;
  if (zoomIn) zoomIn.disabled = viewScale >= maxScale() - 0.001;
}

function zoomAt(clientX, clientY, nextScale) {
  const root = document.getElementById("pages");
  const rect = root.getBoundingClientRect();
  const after = clampScale(nextScale);
  const before = viewScale;
  if (Math.abs(after - before) < 0.001) {
    paintZoom();
    return;
  }
  const anchorX = clientX - rect.left + root.scrollLeft;
  const anchorY = clientY - rect.top + root.scrollTop;
  const ratio = after / before;
  viewScale = after;
  layoutSheets();
  root.scrollLeft = anchorX * ratio - (clientX - rect.left);
  root.scrollTop = anchorY * ratio - (clientY - rect.top);
  scheduleRerender();
}

function zoomAtCenter(nextScale) {
  const root = document.getElementById("pages");
  const rect = root.getBoundingClientRect();
  zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, nextScale);
}

function scheduleRerender() {
  clearTimeout(rerenderTimer);
  rerenderTimer = setTimeout(() => {
    previewEpoch += 1;
    previewCache.clear();
    observePages();
  }, 150);
}

function thumbZoom() {
  return Math.min(0.8, Math.max(0.2, (140 / 595) * (window.devicePixelRatio || 1)));
}

function thumbKey(piece) {
  const zoom = thumbZoom();
  const covered = masks
    .filter((mask) => mask.source === piece.source && mask.page === piece.page && mask.part === piece.part)
    .map((mask) => `${mask.sx},${mask.sy},${mask.sw},${mask.sh}`)
    .join(";");
  const trim = savedTrim(piece);
  return `${piece.source}:${piece.page}:${piece.part}:${rotation}:${split ? 1 : 0}:${zoom.toFixed(2)}:${covered}:${trim.top}:${trim.right}:${trim.bottom}:${trim.left}:${savedSkew(piece)}`;
}

function loadThumb(image, piece) {
  const zoom = thumbZoom();
  const key = thumbKey(piece);
  if (thumbCache.has(key)) {
    image.src = thumbCache.get(key);
    return;
  }
  enqueue(() => api.piece(number, piece.source, piece.page, piece.part, zoom, slot)).then((result) => {
    if (!image.isConnected || key !== thumbKey(piece) || !result || result.ok === false || !result.image) return;
    const src = `data:image/jpeg;base64,${result.image}`;
    thumbCache.set(key, src);
    image.src = src;
  });
}

function loadSheet(sheet, image) {
  const index = Number(sheet.dataset.index);
  const epoch = previewEpoch;
  const zoom = Number(sheetZoom().toFixed(2));
  const request = sheetRequest(index);
  const key = `${epoch}:${index}:${zoom}:${request.dx}:${request.dy}:${request.bare ? 1 : 0}:${request.trim}:${request.skew}`;
  if (previewCache.has(key)) {
    image.src = previewCache.get(key);
    return;
  }
  enqueue(() => api.preview(number, slot, index, zoom, request.bare)).then((result) => {
    const now = sheetRequest(index);
    if (epoch !== previewEpoch || now.bare !== request.bare || now.dx !== request.dx || now.dy !== request.dy || now.trim !== request.trim || now.skew !== request.skew) return;
    if (!result || result.ok === false || !result.image) return;
    const src = `data:image/jpeg;base64,${result.image}`;
    previewCache.set(key, src);
    if (sheet.isConnected) image.src = src;
  });
}

function enqueue(task) {
  return new Promise((resolve) => {
    pending.push({ task, resolve });
    pump();
  });
}

function pump() {
  while (inflight < 3 && pending.length) {
    const job = pending.shift();
    inflight += 1;
    Promise.resolve()
      .then(job.task)
      .then(job.resolve, () => job.resolve(null))
      .finally(() => {
        inflight -= 1;
        pump();
      });
  }
}

async function removePage(index) {
  if (output.length <= 1) return;
  const [piece] = output.splice(index, 1);
  excluded.push({ ...piece, group: 0 });
  const next = Math.min(active > index ? active - 1 : active, output.length - 1);
  await commit(next);
}

async function commit(nextActive) {
  active = nextActive;
  draw();
  const pages = output.map((piece) => ({ ...piece, group: outputGroup }));
  for (const piece of excluded) pages.push({ ...piece, group: 0 });
  const result = await api.set_pages(number, slot, pages);
  if (result && result.ok === false) {
    showBanner(result.message || "ページを保存できません。");
    await loadPages();
    return;
  }
  previewEpoch += 1;
  previewCache.clear();
  observePages();
  jumpTo(nextActive);
}

function jumpTo(index) {
  const root = document.getElementById("pages");
  const sheet = root.querySelector(`[data-index="${index}"]`);
  if (!sheet) return;
  suppressSpy = true;
  setActive(index, true);
  root.scrollTo({ top: sheet.offsetTop, behavior: "auto" });
  requestAnimationFrame(() => { suppressSpy = false; });
}

function setActive(index, scrollNav) {
  if (index < 0 || index >= output.length || index === active && !scrollNav) return;
  const changed = index !== active;
  active = index;
  document.querySelectorAll("#nav .thumb").forEach((item) => {
    item.classList.toggle("is-active", Number(item.dataset.index) === index);
  });
  if (changed) {
    paintTrim();
    paintSkew();
  }
  if (!scrollNav || !changed) return;
  const thumb = document.querySelector(`#nav .thumb[data-index="${index}"]`);
  if (thumb) thumb.scrollIntoView({ block: "nearest" });
}

function showBanner(text) {
  const banner = document.getElementById("banner");
  banner.hidden = !text;
  banner.textContent = text || "";
}

const STAMP_FONT_PT = 11;
const STAMP_BORDER_PT = 1;
const STAMP_ARROWS = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

function sheetRequest(index) {
  const piece = output[index];
  const trim = piece ? savedTrim(piece) : zeroTrim();
  return {
    bare: index === 0 && (stampPhase != null || maskCoversStamp()),
    dx: stampFrame ? stampFrame.dx : 0,
    dy: stampFrame ? stampFrame.dy : 0,
    trim: `${trim.top}:${trim.right}:${trim.bottom}:${trim.left}`,
    skew: piece ? savedSkew(piece) : 0,
  };
}

function stampOffset() {
  if (stampPhase) return { dx: stampPhase.dx, dy: stampPhase.dy };
  if (stampFrame) return { dx: stampFrame.dx, dy: stampFrame.dy };
  return { dx: 0, dy: 0 };
}

function clampStamp(frame, dx, dy) {
  // 画面上の端の丸めは stamp.clamp_stamp_offset と同じにする。
  const minDx = Math.ceil(-frame.originX - 1e-6);
  const maxDx = Math.floor(frame.pageWidth - frame.boxWidth - frame.originX + 1e-6);
  const minDy = Math.ceil(-frame.originY - 1e-6);
  const maxDy = Math.floor(frame.pageHeight - frame.boxHeight - frame.originY + 1e-6);
  return {
    dx: Math.min(maxDx, Math.max(minDx, Math.round(dx))),
    dy: Math.min(maxDy, Math.max(minDy, Math.round(dy))),
  };
}

function stampButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "stamp";
  button.draggable = false;
  button.addEventListener("pointerdown", onStampPointerDown);
  button.addEventListener("pointermove", onStampPointerMove);
  button.addEventListener("pointerup", onStampPointerUp);
  button.addEventListener("pointercancel", onStampPointerUp);
  button.addEventListener("dblclick", onStampDoubleClick);
  button.addEventListener("keydown", onStampKeyDown);
  button.addEventListener("keyup", onStampKeyUp);
  return button;
}

function paintStamp() {
  const button = document.querySelector("#pages .stamp");
  if (!button || !stampFrame) return;
  const offset = stampOffset();
  const live = stampPhase != null || maskCoversStamp();
  const x = stampFrame.originX + offset.dx;
  const y = stampFrame.originY + offset.dy;
  const scale = button.parentElement.clientWidth / stampFrame.pageWidth;
  button.style.left = `${(x / stampFrame.pageWidth) * 100}%`;
  button.style.top = `${(y / stampFrame.pageHeight) * 100}%`;
  button.style.width = `${(stampFrame.boxWidth / stampFrame.pageWidth) * 100}%`;
  button.style.height = `${(stampFrame.boxHeight / stampFrame.pageHeight) * 100}%`;
  const fontSize = stampFrame.fontSize || STAMP_FONT_PT;
  const border = stampFrame.borderWidth || STAMP_BORDER_PT;
  const color = stampFrame.color || "#ff0000";
  button.style.color = color;
  button.style.borderColor = live ? color : "transparent";
  button.style.fontFamily = stampFrame.fontFamily || '"Yu Mincho", "YuMincho", "游明朝", serif';
  button.style.fontSize = `${fontSize * scale}px`;
  button.style.borderWidth = live ? `${border * scale}px` : "0";
  button.classList.toggle("is-live", live);
  button.textContent = live ? stampLabel : "";
  button.setAttribute("aria-label", `${stampLabel || "証拠番号"}の位置`);
  button.disabled = stampBusy;
  button.tabIndex = masking ? -1 : 0;
}

function reloadSheet(index) {
  const sheet = document.querySelector(`#pages .sheet[data-index="${index}"]`);
  const image = sheet?.querySelector("img.page");
  if (!sheet || !image) return;
  loadSheet(sheet, image);
}

async function commitStamp(dx, dy) {
  if (!stampFrame || stampBusy) return;
  const next = clampStamp(stampFrame, dx, dy);
  if (next.dx === stampFrame.dx && next.dy === stampFrame.dy) {
    stampPhase = null;
    paintStamp();
    reloadSheet(0);
    return;
  }
  stampBusy = true;
  stampPhase = { kind: "drag", dx: next.dx, dy: next.dy };
  paintStamp();
  try {
    const result = await api.set_stamp_offset(number, slot, next.dx, next.dy);
    if (!stampPhase || stampPhase.dx !== next.dx || stampPhase.dy !== next.dy) return;
    if (!result || result.ok === false || !result.stampFrame) {
      stampPhase = null;
      showBanner((result && result.message) || "印の位置を保存できませんでした。");
      paintStamp();
      reloadSheet(0);
      return;
    }
    stampFrame = result.stampFrame;
    stampPhase = { kind: "wait", dx: result.dx, dy: result.dy };
    paintStamp();
    waitForStamped(result.dx, result.dy);
  } catch (error) {
    if (stampPhase && stampPhase.dx === next.dx && stampPhase.dy === next.dy) stampPhase = null;
    showBanner("印の位置を保存できませんでした。");
    paintStamp();
    reloadSheet(0);
  } finally {
    stampBusy = false;
    paintStamp();
  }
}

function waitForStamped(dx, dy) {
  const sheet = document.querySelector('#pages .sheet[data-index="0"]');
  const image = sheet?.querySelector("img.page");
  if (!sheet || !image) return;
  const epoch = previewEpoch;
  const zoom = Number(sheetZoom().toFixed(2));
  const key = `${epoch}:0:${zoom}:${dx}:${dy}:0`;
  enqueue(() => api.preview(number, slot, 0, zoom, false)).then((result) => {
    if (!stampPhase || stampPhase.kind !== "wait" || stampPhase.dx !== dx || stampPhase.dy !== dy) return;
    if (!result || result.ok === false || !result.image) {
      stampPhase = null;
      showBanner("印の位置を表示できませんでした。");
      paintStamp();
      reloadSheet(0);
      return;
    }
    const src = `data:image/jpeg;base64,${result.image}`;
    previewCache.set(key, src);
    const preload = document.createElement("img");
    preload.className = "stamp-preload";
    preload.alt = "";
    preload.addEventListener("load", () => {
      if (!stampPhase || stampPhase.kind !== "wait" || stampPhase.dx !== dx || stampPhase.dy !== dy) return;
      stampPhase = null;
      if (image.isConnected) image.src = src;
      preload.remove();
      paintStamp();
    });
    preload.addEventListener("error", () => {
      if (!stampPhase || stampPhase.kind !== "wait" || stampPhase.dx !== dx || stampPhase.dy !== dy) return;
      stampPhase = null;
      showBanner("印の位置を表示できませんでした。");
      preload.remove();
      paintStamp();
      reloadSheet(0);
    });
    sheet.appendChild(preload);
    preload.src = src;
  });
}

function onStampPointerDown(event) {
  if (event.button !== 0 || stampBusy || masking || !stampFrame) return;
  const image = event.currentTarget.parentElement?.querySelector("img.page");
  const rect = image?.getBoundingClientRect();
  if (!rect || rect.width < 1) return;
  event.preventDefault();
  event.currentTarget.setPointerCapture(event.pointerId);
  const current = stampOffset();
  stampDrag = {
    pointerId: event.pointerId,
    startClientX: event.clientX,
    startClientY: event.clientY,
    startDx: current.dx,
    startDy: current.dy,
    scale: rect.width / stampFrame.pageWidth,
  };
  stampMoved = false;
  const resting = stampPhase == null;
  stampPhase = { kind: "drag", dx: current.dx, dy: current.dy };
  paintStamp();
  if (resting) reloadSheet(0);
}

function onStampPointerMove(event) {
  if (!stampDrag || event.pointerId !== stampDrag.pointerId || !stampFrame) return;
  const dx = stampDrag.startDx + (event.clientX - stampDrag.startClientX) / stampDrag.scale;
  const dy = stampDrag.startDy + (event.clientY - stampDrag.startClientY) / stampDrag.scale;
  const next = clampStamp(stampFrame, dx, dy);
  if (next.dx !== stampDrag.startDx || next.dy !== stampDrag.startDy) stampMoved = true;
  stampPhase = { kind: "drag", dx: next.dx, dy: next.dy };
  paintStamp();
}

function onStampPointerUp(event) {
  if (!stampDrag || event.pointerId !== stampDrag.pointerId) return;
  stampDrag = null;
  const current = stampPhase;
  if (!stampFrame || !current) return;
  if (!stampMoved || (current.dx === stampFrame.dx && current.dy === stampFrame.dy)) {
    stampPhase = null;
    paintStamp();
    reloadSheet(0);
    return;
  }
  commitStamp(current.dx, current.dy);
}

function onStampDoubleClick(event) {
  event.preventDefault();
  if (stampMoved) return;
  stampDrag = null;
  commitStamp(0, 0);
}

function onStampKeyDown(event) {
  const delta = STAMP_ARROWS[event.key];
  if (!delta || stampBusy || masking || !stampFrame) return;
  event.preventDefault();
  event.stopPropagation();
  const current = stampOffset();
  const next = clampStamp(stampFrame, current.dx + delta[0], current.dy + delta[1]);
  const resting = stampPhase == null;
  stampPhase = { kind: "drag", dx: next.dx, dy: next.dy };
  paintStamp();
  if (resting) reloadSheet(0);
}

function zeroTrim() {
  return { top: 0, right: 0, bottom: 0, left: 0 };
}

function pieceKey(piece) {
  return `${piece.source}:${piece.page}:${piece.part}`;
}

function clampTrimEdge(value) {
  const number = Number(value);
  if (!Number.isInteger(number) || number < 0) return 0;
  return Math.min(400, number);
}

function snapTrimEdge(value) {
  return clampTrimEdge(Math.round(Number(value) / 10) * 10);
}

function normalizeTrim(trim) {
  return {
    top: clampTrimEdge(trim && trim.top),
    right: clampTrimEdge(trim && trim.right),
    bottom: clampTrimEdge(trim && trim.bottom),
    left: clampTrimEdge(trim && trim.left),
  };
}

function sameTrim(left, right) {
  return left.top === right.top && left.right === right.right && left.bottom === right.bottom && left.left === right.left;
}

function savedTrim(piece) {
  return normalizeTrim(piece && piece.trim);
}

function savedBox(piece) {
  const box = piece && piece.imageBox;
  if (!box || !(box.w > 0) || !(box.h > 0)) return { x: 0, y: 0, w: 1, h: 1 };
  return box;
}

function shownTrim(piece) {
  if (trimLive && piece && trimLive.key === pieceKey(piece)) return normalizeTrim(trimLive);
  return savedTrim(piece);
}

function trimBands(box, trim) {
  const top = trim.top / 1000;
  const right = trim.right / 1000;
  const bottom = trim.bottom / 1000;
  const left = trim.left / 1000;
  return [
    { left: `${box.x * 100}%`, top: `${box.y * 100}%`, width: `${box.w * 100}%`, height: `${box.h * top * 100}%` },
    {
      left: `${(box.x + box.w * (1 - right)) * 100}%`,
      top: `${box.y * 100}%`,
      width: `${box.w * right * 100}%`,
      height: `${box.h * 100}%`,
    },
    {
      left: `${box.x * 100}%`,
      top: `${(box.y + box.h * (1 - bottom)) * 100}%`,
      width: `${box.w * 100}%`,
      height: `${box.h * bottom * 100}%`,
    },
    { left: `${box.x * 100}%`, top: `${box.y * 100}%`, width: `${box.w * left * 100}%`, height: `${box.h * 100}%` },
  ].filter((band) => !band.width.startsWith("0%") && !band.height.startsWith("0%"));
}

function trimBarStyle(box, trim, edge) {
  const top = trim.top / 1000;
  const right = trim.right / 1000;
  const bottom = trim.bottom / 1000;
  const left = trim.left / 1000;
  if (edge === "top" || edge === "bottom") {
    const cut = edge === "top" ? box.y + box.h * top : box.y + box.h * (1 - bottom);
    return { left: `${box.x * 100}%`, width: `${box.w * 100}%`, top: `${cut * 100}%` };
  }
  const cut = edge === "left" ? box.x + box.w * left : box.x + box.w * (1 - right);
  return { top: `${box.y * 100}%`, height: `${box.h * 100}%`, left: `${cut * 100}%` };
}

function trimKeyStep(edge, key) {
  if (edge === "top" && key === "ArrowDown") return 10;
  if (edge === "top" && key === "ArrowUp") return -10;
  if (edge === "bottom" && key === "ArrowUp") return 10;
  if (edge === "bottom" && key === "ArrowDown") return -10;
  if (edge === "left" && key === "ArrowRight") return 10;
  if (edge === "left" && key === "ArrowLeft") return -10;
  if (edge === "right" && key === "ArrowLeft") return 10;
  if (edge === "right" && key === "ArrowRight") return -10;
  return 0;
}

function clampSkew(value) {
  const number = Math.round(Number(value));
  if (!Number.isInteger(number)) return 0;
  return Math.min(100, Math.max(-100, number));
}

function skewKey(piece) {
  return `${piece.source}:${piece.page}`;
}

function savedSkew(piece) {
  return clampSkew(piece && piece.skewTenths);
}

function shownSkew(piece) {
  if (skewLive && piece && skewLive.key === skewKey(piece)) return skewLive.tenths;
  return piece ? savedSkew(piece) : 0;
}

function skewDegrees(tenths) {
  return (clampSkew(tenths) / 10).toFixed(1);
}

function stopSkewRepeat() {
  if (!skewRepeat) return;
  clearInterval(skewRepeat);
  skewRepeat = 0;
}

function paintSkew() {
  const piece = output[active];
  const tenths = piece ? shownSkew(piece) : 0;
  const readout = document.getElementById("skew-readout");
  readout.textContent = `傾き${skewDegrees(tenths)}°`;
  const canReset = Boolean(piece) && !skewBusy && tenths !== 0;
  readout.classList.toggle("is-resettable", canReset);
  readout.title = canReset ? "ダブルクリックで0度に戻す" : "";
  document.getElementById("skew-left").disabled = skewBusy || !piece || tenths <= -100;
  document.getElementById("skew-right").disabled = skewBusy || !piece || tenths >= 100;
  paintSkewOverlay();
}

function paintSkewOverlay() {
  document.querySelectorAll("#pages .skew-preview").forEach((node) => node.remove());
  const piece = output[active];
  if (!piece || !skewLive || skewLive.key !== skewKey(piece) || skewLive.tenths === skewLive.baked) return;
  const sheet = document.querySelector(`#pages .sheet[data-index="${active}"]`);
  const image = sheet?.querySelector("img.page");
  if (!sheet || !image || !image.src) return;
  const box = savedBox(piece);
  const frame = document.createElement("div");
  frame.className = "skew-preview";
  frame.style.left = `${box.x * 100}%`;
  frame.style.top = `${box.y * 100}%`;
  frame.style.width = `${box.w * 100}%`;
  frame.style.height = `${box.h * 100}%`;
  const copy = document.createElement("img");
  copy.alt = "";
  copy.src = image.src;
  copy.style.width = `${100 / box.w}%`;
  copy.style.height = `${100 / box.h}%`;
  copy.style.left = `${(-box.x / box.w) * 100}%`;
  copy.style.top = `${(-box.y / box.h) * 100}%`;
  copy.style.transform = `rotate(${(skewLive.tenths - skewLive.baked) / 10}deg)`;
  copy.style.transformOrigin = `${(box.x + box.w / 2) * 100}% ${(box.y + box.h / 2) * 100}%`;
  frame.appendChild(copy);
  sheet.appendChild(frame);
}

function releaseSkewOverlay() {
  const piece = output[active];
  if (!skewLive || !piece || skewLive.key !== skewKey(piece)) return;
  if (savedSkew(piece) !== skewLive.tenths) return;
  skewLive = null;
  paintSkew();
}

function stepSkew(delta) {
  const piece = output[active];
  if (!piece || skewBusy) return null;
  const key = skewKey(piece);
  const baked = skewLive && skewLive.key === key ? skewLive.baked : savedSkew(piece);
  const base = skewLive && skewLive.key === key ? skewLive.tenths : savedSkew(piece);
  const tenths = clampSkew(base + delta);
  skewLive = { key, tenths, baked };
  paintSkew();
  return { piece, tenths, baked };
}

function finishSkewStep() {
  const piece = output[active];
  if (!skewLive || !piece || skewKey(piece) !== skewLive.key || skewBusy) return;
  commitSkew(piece, skewLive.tenths, skewLive.baked);
}

function onSkewPointerDown(delta, event) {
  if (event.button !== 0 || skewBusy) return;
  event.preventDefault();
  skewFromPointer = true;
  try {
    event.currentTarget.setPointerCapture(event.pointerId);
  } catch (error) {
    // ポインタを捕捉できない環境でも、1回分の移動は行う。
  }
  stopSkewRepeat();
  stepSkew(delta);
  skewRepeat = setInterval(() => stepSkew(delta), 140);
}

function onSkewPointerUp(event) {
  if (event.type !== "pointercancel" && event.button !== 0) return;
  stopSkewRepeat();
  finishSkewStep();
  setTimeout(() => {
    skewFromPointer = false;
  }, 0);
}

function onSkewClick(delta) {
  if (skewFromPointer) {
    skewFromPointer = false;
    return;
  }
  const stepped = stepSkew(delta);
  if (!stepped) return;
  commitSkew(stepped.piece, stepped.tenths, stepped.baked);
}

function applySkew(source, page, tenths) {
  for (const piece of output.concat(excluded)) {
    if (piece.source === source && piece.page === page) piece.skewTenths = tenths;
  }
}

function reloadSkewed(source, page) {
  output.forEach((piece, index) => {
    if (piece.source !== source || piece.page !== page) return;
    reloadSheet(index);
    const thumb = document.querySelector(`#nav .thumb[data-index="${index}"] img`);
    if (thumb) loadThumb(thumb, piece);
  });
}

async function commitSkew(piece, tenths, baked) {
  if (!piece) return;
  const key = skewKey(piece);
  const normalized = clampSkew(tenths);
  const base = baked == null ? savedSkew(piece) : baked;
  skewLive = { key, tenths: normalized, baked: base };
  paintSkew();
  if (savedSkew(piece) === normalized) {
    if (base === normalized) {
      skewLive = null;
      paintSkew();
    }
    return;
  }
  skewBusy = true;
  paintSkew();
  try {
    const result = await api.set_skew(number, slot, piece.source, piece.page, normalized);
    if (skewLive && skewLive.key === key && skewLive.tenths !== normalized) return;
    if (!result || result.ok === false || result.skewTenths == null) {
      skewLive = null;
      showBanner((result && result.message) || "傾きを保存できませんでした。");
      paintSkew();
      return;
    }
    applySkew(piece.source, piece.page, result.skewTenths);
    if (Array.isArray(result.masks)) {
      masks = result.masks;
      paintMasks();
    }
    previewEpoch += 1;
    previewCache.clear();
    reloadSkewed(piece.source, piece.page);
  } catch (error) {
    skewLive = null;
    showBanner("傾きを保存できませんでした。");
    paintSkew();
  } finally {
    skewBusy = false;
    paintSkew();
  }
}

function paintTrimClear() {
  const button = document.getElementById("trim-clear");
  const piece = output[active];
  const trim = piece ? shownTrim(piece) : zeroTrim();
  button.disabled = trimBusy || !piece || sameTrim(trim, zeroTrim());
}

function paintTrim() {
  if (trimDrag || trimKeyPiece) return;
  document.querySelectorAll("#pages .trim-band, #pages .trim-bar").forEach((node) => node.remove());
  const piece = output[active];
  const sheet = document.querySelector(`#pages .sheet[data-index="${active}"]`);
  if (!piece || !sheet) {
    paintTrimClear();
    return;
  }
  const trim = shownTrim(piece);
  const box = savedBox(piece);
  for (const style of trimBands(box, trim)) {
    const band = document.createElement("div");
    band.className = "trim-band";
    Object.assign(band.style, style);
    sheet.appendChild(band);
  }
  for (const [edge, label] of TRIM_EDGES) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `trim-bar is-${edge}`;
    button.draggable = false;
    Object.assign(button.style, trimBarStyle(box, trim, edge));
    const percent = Math.round(trim[edge] / 10);
    button.setAttribute("role", "slider");
    button.setAttribute("aria-label", `${label}の端`);
    button.setAttribute("aria-valuemin", "0");
    button.setAttribute("aria-valuemax", "40");
    button.setAttribute("aria-valuenow", String(percent));
    button.setAttribute("aria-valuetext", `${percent}%`);
    button.disabled = trimBusy;
    button.tabIndex = masking ? -1 : 0;
    const caption = document.createElement("span");
    caption.className = "trim-label";
    caption.textContent = `${percent}%`;
    button.appendChild(caption);
    button.addEventListener("pointerdown", (event) => onTrimPointerDown(edge, event));
    button.addEventListener("pointermove", onTrimPointerMove);
    button.addEventListener("pointerup", onTrimPointerUp);
    button.addEventListener("pointercancel", onTrimPointerUp);
    button.addEventListener("keydown", (event) => onTrimKeyDown(edge, event));
    button.addEventListener("keyup", (event) => onTrimKeyUp(edge, event));
    button.addEventListener("blur", onTrimBlur);
    sheet.appendChild(button);
  }
  paintTrimClear();
}

function syncTrimPaint() {
  const piece = output[active];
  const sheet = document.querySelector(`#pages .sheet[data-index="${active}"]`);
  if (!piece || !sheet) return;
  const trim = shownTrim(piece);
  const box = savedBox(piece);
  sheet.querySelectorAll(".trim-band").forEach((node) => node.remove());
  for (const style of trimBands(box, trim)) {
    const band = document.createElement("div");
    band.className = "trim-band";
    Object.assign(band.style, style);
    sheet.appendChild(band);
  }
  for (const [edge] of TRIM_EDGES) {
    const button = sheet.querySelector(`.trim-bar.is-${edge}`);
    if (!button) continue;
    Object.assign(button.style, trimBarStyle(box, trim, edge));
    const percent = Math.round(trim[edge] / 10);
    button.setAttribute("aria-valuenow", String(percent));
    button.setAttribute("aria-valuetext", `${percent}%`);
    const caption = button.querySelector(".trim-label");
    if (caption) caption.textContent = `${percent}%`;
  }
}

async function commitTrim(piece, next) {
  trimDrag = null;
  if (!piece) return;
  const normalized = normalizeTrim(next);
  const key = pieceKey(piece);
  trimLive = { key, ...normalized };
  syncTrimPaint();
  if (sameTrim(savedTrim(piece), normalized)) {
    trimLive = null;
    trimKeyPiece = null;
    paintTrim();
    return;
  }
  trimBusy = true;
  paintTrimClear();
  document.querySelectorAll("#pages .trim-bar").forEach((button) => {
    button.disabled = true;
  });
  try {
    const result = await api.set_trim(
      number,
      slot,
      piece.source,
      piece.page,
      piece.part,
      normalized.top,
      normalized.right,
      normalized.bottom,
      normalized.left,
    );
    if (trimLive && trimLive.key === key && !sameTrim(normalizeTrim(trimLive), normalized)) return;
    if (!result || result.ok === false || !result.trim) {
      trimLive = null;
      trimBusy = false;
      showBanner((result && result.message) || "端を削れませんでした。");
      paintTrim();
      return;
    }
    piece.trim = result.trim;
    trimLive = null;
    trimBusy = false;
    previewEpoch += 1;
    previewCache.clear();
    paintTrim();
    const index = output.indexOf(piece);
    if (index >= 0) {
      reloadSheet(index);
      const thumb = document.querySelector(`#nav .thumb[data-index="${index}"] img`);
      if (thumb) loadThumb(thumb, piece);
    }
  } catch (error) {
    trimLive = null;
    trimBusy = false;
    showBanner("端を削れませんでした。");
    paintTrim();
  } finally {
    trimBusy = false;
    paintTrimClear();
  }
}

function onTrimPointerDown(edge, event) {
  if (event.button !== 0 || trimBusy) return;
  const piece = output[active];
  if (!piece) return;
  event.preventDefault();
  event.stopPropagation();
  try {
    event.currentTarget.setPointerCapture(event.pointerId);
  } catch (error) {
    // ポインタを捕捉できない環境でも、移動の計算は続ける。
  }
  const start = shownTrim(piece);
  trimDrag = {
    pointerId: event.pointerId,
    edge,
    piece,
    start,
    startX: event.clientX,
    startY: event.clientY,
  };
  trimLive = { key: pieceKey(piece), ...start };
  syncTrimPaint();
}

function onTrimPointerMove(event) {
  const drag = trimDrag;
  if (!drag || event.pointerId !== drag.pointerId) return;
  const sheet = event.currentTarget.closest(".sheet");
  const rect = sheet && sheet.getBoundingClientRect();
  const box = savedBox(drag.piece);
  const vertical = drag.edge === "top" || drag.edge === "bottom";
  const span = rect ? (vertical ? rect.height * box.h : rect.width * box.w) : 0;
  if (!rect || span < 1) return;
  let deltaPx = event.clientX - drag.startX;
  if (drag.edge === "top") deltaPx = event.clientY - drag.startY;
  else if (drag.edge === "bottom") deltaPx = drag.startY - event.clientY;
  else if (drag.edge === "right") deltaPx = drag.startX - event.clientX;
  const permille = snapTrimEdge(drag.start[drag.edge] + (deltaPx / span) * 1000);
  if (trimLive && trimLive[drag.edge] === permille) return;
  trimLive = { key: pieceKey(drag.piece), ...normalizeTrim(drag.start), [drag.edge]: permille };
  syncTrimPaint();
  paintTrimClear();
}

function onTrimPointerUp(event) {
  const drag = trimDrag;
  if (!drag || event.pointerId !== drag.pointerId) return;
  trimDrag = null;
  commitTrim(drag.piece, trimLive || drag.start);
}

function onTrimKeyDown(edge, event) {
  const step = trimKeyStep(edge, event.key);
  if (!step) return;
  event.preventDefault();
  event.stopPropagation();
  if (trimBusy || trimDrag) return;
  const piece = output[active];
  if (!piece) return;
  const base = shownTrim(piece);
  trimKeyPiece = piece;
  trimLive = { key: pieceKey(piece), ...base, [edge]: clampTrimEdge(base[edge] + step) };
  syncTrimPaint();
  paintTrimClear();
}

function onTrimKeyUp(edge, event) {
  if (!trimKeyStep(edge, event.key)) return;
  event.preventDefault();
  const piece = trimKeyPiece;
  if (!piece || trimDrag) return;
  trimKeyPiece = null;
  commitTrim(piece, trimLive);
}

function onTrimBlur() {
  if (trimDrag || !trimKeyPiece) return;
  const piece = trimKeyPiece;
  trimKeyPiece = null;
  commitTrim(piece, trimLive);
}

function paintMaskMode() {
  const button = document.getElementById("mask");
  button.classList.toggle("is-on", masking);
  button.setAttribute("aria-pressed", masking ? "true" : "false");
  document.body.classList.toggle("is-masking", masking);
  paintStamp();
  paintTrim();
}

function maskCoversStamp() {
  if (!stampFrame || !output.length) return false;
  const piece = output[0];
  const offset = stampOffset();
  const stamp = {
    x: stampFrame.originX + offset.dx,
    y: stampFrame.originY + offset.dy,
    w: stampFrame.boxWidth,
    h: stampFrame.boxHeight,
  };
  return masks.some((mask) => {
    if (mask.source !== piece.source || mask.page !== piece.page || mask.part !== piece.part) return false;
    return mask.x < stamp.x + stamp.w && stamp.x < mask.x + mask.w && mask.y < stamp.y + stamp.h && stamp.y < mask.y + mask.h;
  });
}

function paintMasks() {
  document.querySelectorAll("#pages .mask, #pages .mask-x").forEach((node) => node.remove());
  document.querySelectorAll("#pages .sheet").forEach((sheet) => {
    const piece = output[Number(sheet.dataset.index)];
    if (!piece) return;
    for (const mask of masks) {
      if (mask.source !== piece.source || mask.page !== piece.page || mask.part !== piece.part) continue;
      const box = document.createElement("div");
      box.className = "mask";
      box.style.left = `${(mask.x / pageWidth) * 100}%`;
      box.style.top = `${(mask.y / pageHeight) * 100}%`;
      box.style.width = `${(mask.w / pageWidth) * 100}%`;
      box.style.height = `${(mask.h / pageHeight) * 100}%`;
      const close = document.createElement("button");
      close.type = "button";
      close.className = "mask-x";
      close.textContent = "×";
      close.setAttribute("aria-label", "このマスキングを解除");
      close.style.left = `${((mask.x + mask.w) / pageWidth) * 100}%`;
      close.style.top = `${(mask.y / pageHeight) * 100}%`;
      close.addEventListener("pointerdown", (event) => event.stopPropagation());
      close.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        enqueueMask(() => api.remove_mask(number, slot, mask.source, mask.page, mask.sx, mask.sy, mask.sw, mask.sh).then(applyMaskResult));
      });
      sheet.appendChild(box);
      sheet.appendChild(close);
    }
  });
  paintStamp();
}

function enqueueMask(task) {
  maskChain = maskChain.then(task, task).catch(() => {
    showBanner("マスキングを保存できませんでした。");
  });
}

function applyMaskResult(result) {
  const covered = maskCoversStamp();
  if (!result || result.ok === false || !result.masks) {
    showBanner((result && result.message) || "マスキングを保存できませんでした。");
    paintMasks();
    return;
  }
  masks = result.masks;
  paintMasks();
  thumbCache.clear();
  document.querySelectorAll("#nav .thumb").forEach((item) => {
    const piece = output[Number(item.dataset.index)];
    const image = item.querySelector("img");
    if (piece && image) loadThumb(image, piece);
  });
  if (covered !== maskCoversStamp()) {
    previewEpoch += 1;
    previewCache.clear();
    reloadSheet(0);
  }
}

function cancelMaskDrag() {
  if (!maskDrag) return;
  maskDrag.draft.remove();
  maskDrag = null;
}

function onMaskPointerDown(event) {
  if (!masking || event.button !== 0 || event.target.closest(".mask-x, .trim-bar")) return;
  const sheet = event.target.closest("#pages .sheet");
  const image = sheet?.querySelector("img.page");
  const rect = image?.getBoundingClientRect();
  if (!sheet || !rect || rect.width < 1 || !output[Number(sheet.dataset.index)]) return;
  event.preventDefault();
  sheet.setPointerCapture(event.pointerId);
  const draft = document.createElement("div");
  draft.className = "mask is-draft";
  sheet.appendChild(draft);
  maskDrag = {
    pointerId: event.pointerId,
    sheet,
    rect,
    startX: event.clientX,
    startY: event.clientY,
    draft,
  };
  placeDraft(maskDrag, event.clientX, event.clientY);
}

function onMaskPointerMove(event) {
  if (!maskDrag || event.pointerId !== maskDrag.pointerId) return;
  placeDraft(maskDrag, event.clientX, event.clientY);
}

function onMaskPointerUp(event) {
  if (!maskDrag || event.pointerId !== maskDrag.pointerId) return;
  const drag = maskDrag;
  maskDrag = null;
  const box = drag.draft;
  box.remove();
  if (event.type === "pointercancel") return;
  const piece = output[Number(drag.sheet.dataset.index)];
  const span = outputSpan(drag.rect, drag.startX, drag.startY, event.clientX, event.clientY);
  if (!piece || !span || span.w < 4 || span.h < 4) return;
  enqueueMask(() => api.add_mask(
    number,
    slot,
    piece.source,
    piece.page,
    piece.part,
    span.x,
    span.y,
    span.w,
    span.h,
  ).then(applyMaskResult));
}

function placeDraft(drag, clientX, clientY) {
  const span = outputSpan(drag.rect, drag.startX, drag.startY, clientX, clientY);
  if (!span) return;
  drag.draft.style.left = `${(span.x / pageWidth) * 100}%`;
  drag.draft.style.top = `${(span.y / pageHeight) * 100}%`;
  drag.draft.style.width = `${(span.w / pageWidth) * 100}%`;
  drag.draft.style.height = `${(span.h / pageHeight) * 100}%`;
}

function outputSpan(rect, startX, startY, endX, endY) {
  const x0 = Math.min(rect.right, Math.max(rect.left, startX));
  const y0 = Math.min(rect.bottom, Math.max(rect.top, startY));
  const x1 = Math.min(rect.right, Math.max(rect.left, endX));
  const y1 = Math.min(rect.bottom, Math.max(rect.top, endY));
  return {
    x: ((Math.min(x0, x1) - rect.left) / rect.width) * pageWidth,
    y: ((Math.min(y0, y1) - rect.top) / rect.height) * pageHeight,
    w: (Math.abs(x1 - x0) / rect.width) * pageWidth,
    h: (Math.abs(y1 - y0) / rect.height) * pageHeight,
  };
}

function onStampKeyUp(event) {
  if (!STAMP_ARROWS[event.key]) return;
  event.preventDefault();
  if (!stampFrame || stampPhase?.kind !== "drag") return;
  if (stampPhase.dx === stampFrame.dx && stampPhase.dy === stampFrame.dy) {
    stampPhase = null;
    paintStamp();
    reloadSheet(0);
    return;
  }
  commitStamp(stampPhase.dx, stampPhase.dy);
}

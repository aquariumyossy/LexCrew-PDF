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

window.addEventListener("pywebviewready", () => {
  api = window.pywebview.api;
  if (number) openCurrent();
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
  document.getElementById("heading").textContent = context.label || "ページ編集";
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
    image.alt = pieceMark(piece, index);
    sheet.appendChild(image);
    root.appendChild(sheet);
  });
  layoutSheets();
  root.scrollTop = top;
  observePages();
}

function observePages() {
  const root = document.getElementById("pages");
  if (pageObserver) pageObserver.disconnect();
  pageObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      const image = entry.target.querySelector("img");
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

function loadThumb(image, piece) {
  const zoom = thumbZoom();
  const key = `${piece.source}:${piece.page}:${piece.part}:${rotation}:${split ? 1 : 0}:${zoom.toFixed(2)}`;
  if (thumbCache.has(key)) {
    image.src = thumbCache.get(key);
    return;
  }
  enqueue(() => api.piece(number, piece.source, piece.page, piece.part, zoom, slot)).then((result) => {
    if (!image.isConnected || !result || result.ok === false || !result.image) return;
    const src = `data:image/jpeg;base64,${result.image}`;
    thumbCache.set(key, src);
    image.src = src;
  });
}

function loadSheet(sheet, image) {
  const index = Number(sheet.dataset.index);
  const epoch = previewEpoch;
  const zoom = Number(sheetZoom().toFixed(2));
  const key = `${epoch}:${index}:${zoom}`;
  if (previewCache.has(key)) {
    image.src = previewCache.get(key);
    return;
  }
  enqueue(() => api.preview(number, slot, index, zoom)).then((result) => {
    if (epoch !== previewEpoch || !result || result.ok === false || !result.image) return;
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
  if (!scrollNav || !changed) return;
  const thumb = document.querySelector(`#nav .thumb[data-index="${index}"]`);
  if (thumb) thumb.scrollIntoView({ block: "nearest" });
}

function showBanner(text) {
  const banner = document.getElementById("banner");
  banner.hidden = !text;
  banner.textContent = text || "";
}

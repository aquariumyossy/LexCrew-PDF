let api;
let view;
let generating = false;
let refreshSerial = 0;

window.showBanner = showBanner;
window.refreshApp = refreshApp;

window.addEventListener("pywebviewready", () => {
  api = window.pywebview.api;
  refreshApp();
});

document.addEventListener("dragover", (event) => {
  event.preventDefault();
  if (!event.target.closest("[data-drop]")) window.__lexDrop = null;
});

async function refreshApp() {
  const serial = ++refreshSerial;
  const next = await api.state();
  if (serial !== refreshSerial) return;
  view = next;
  render();
  for (const card of view.cards) {
    if (!card.hasFile) continue;
    let media;
    try {
      media = await api.media(card.number);
    } catch (error) {
      showBanner("原本を開けません。");
      continue;
    }
    if (serial !== refreshSerial) return;
    if (media && media.ok === false && media.message) showBanner(media.message);
    card.splittable = Boolean(media && media.splittable);
    for (const slot of (media && media.slots) || []) {
      const image = document.querySelector(`[data-thumb="${card.number}-${slot.index}"]`);
      if (image && slot.thumb) image.src = `data:image/jpeg;base64,${slot.thumb}`;
      const pages = document.querySelector(`[data-pages="${card.number}-${slot.index}"]`);
      if (pages && Number.isInteger(slot.pageCount)) {
        pages.hidden = false;
        pages.textContent = `${slot.pageCount}ページ`;
      }
    }
  }
  if (serial === refreshSerial) renderSplitButtons();
}

function render() {
  const series = document.getElementById("series");
  if (document.activeElement !== series) series.value = view.labelTemplate || "";
  document.getElementById("output").textContent = view.outputDir ? `保存先 ${view.outputDir}` : "";
  document.getElementById("generate").disabled = generating;
  const root = document.getElementById("cards");
  root.innerHTML = "";
  for (const card of view.cards) {
    card.slots.forEach((slot, index) => {
      root.appendChild(slotCard(card, slot, index === card.slots.length - 1));
    });
  }
  root.appendChild(addCardButton());
}

function addCardButton() {
  const button = document.createElement("button");
  button.id = "add-card";
  button.type = "button";
  button.className = "add-card";
  button.textContent = "カードを追加";
  button.addEventListener("click", () => addCard());
  return button;
}

async function addCard() {
  if (!api) return;
  const button = document.getElementById("add-card");
  if (button) button.disabled = true;
  try {
    const next = await api.add_card();
    await applyView(next);
    const cards = document.querySelectorAll("#cards article");
    const added = cards[cards.length - 1];
    if (added) added.scrollIntoView({ block: "nearest" });
  } catch (error) {
    showBanner(error && error.message ? error.message : "カードを追加できません。");
    if (button) button.disabled = false;
  }
}

function cardLocked(card) {
  return Boolean(view && view.editor && view.editor.number === card.number);
}

function slotCard(card, slot, isLast) {
  const article = document.createElement("article");
  const locked = cardLocked(card);
  article.className = locked ? "evidence-card is-locked" : "evidence-card";
  article.dataset.number = String(card.number);
  article.dataset.slot = String(slot.index);
  const filled = slot.files.length > 0;
  if (filled) {
    const open = document.createElement("button");
    open.type = "button";
    open.className = "evidence-open";
    if (!locked) rememberDrop(open, card.number, slot.index, null, true);
    const image = document.createElement("img");
    image.alt = "";
    image.dataset.thumb = `${card.number}-${slot.index}`;
    open.appendChild(image);
    open.addEventListener("click", () => openEditorWindow(card, slot));
    article.appendChild(open);
  } else {
    const sheet = document.createElement("div");
    sheet.className = "evidence-sheet evidence-sheet-empty";
    if (!locked) rememberDrop(sheet, card.number, slot.index, null);
    const add = document.createElement("button");
    add.type = "button";
    add.className = "btn primary evidence-add";
    add.textContent = "ファイルを追加";
    add.disabled = locked;
    add.addEventListener("click", () => api.choose_pdf(card.number, slot.index, false).then(applyView));
    sheet.appendChild(add);
    article.appendChild(sheet);
  }

  const meta = document.createElement("div");
  meta.className = "evidence-meta";
  const label = document.createElement("div");
  label.className = "evidence-label";
  label.textContent = slot.label;
  const title = document.createElement("input");
  title.className = "evidence-name";
  title.value = slot.filename || "";
  title.setAttribute("aria-label", "ファイル名");
  title.disabled = locked;
  title.addEventListener("change", () => api.set_title(card.number, titleFromFilename(title.value), slot.index).then(applyView));
  meta.append(label, title);

  if (filled) {
    for (const file of slot.files) {
      const source = document.createElement("div");
      source.className = "evidence-source";
      source.textContent = `原本: ${file.name}`;
      if (!locked) rememberDrop(source, card.number, slot.index, file.index);
      meta.appendChild(source);
    }
    const pages = document.createElement("div");
    pages.className = "evidence-pages";
    pages.dataset.pages = `${card.number}-${slot.index}`;
    pages.hidden = true;
    meta.appendChild(pages);
    const actions = document.createElement("div");
    actions.className = "evidence-actions";
    actions.append(
      miniButton("差替", () => api.choose_pdf(card.number, slot.index, true).then(applyView)),
      miniButton("右に90°", () => api.rotate(card.number, slot.index).then(applyView)),
    );
    const split = miniButton("A4分割", () => api.set_split(card.number, !card.splitA4).then(applyView));
    split.className = card.splitA4 ? "btn mini evidence-split is-on" : "btn mini evidence-split";
    split.dataset.split = String(card.number);
    split.hidden = !card.splitA4;
    actions.appendChild(split);
    if (slot.rotation) {
      const angle = document.createElement("span");
      angle.className = "evidence-rotation";
      angle.textContent = `${slot.rotation}°`;
      actions.appendChild(angle);
    }
    if (isLast) actions.appendChild(branchButton(card));
    actions.appendChild(deleteButton(card, slot));
    if (!locked) actions.appendChild(reorderHandle(article, card, slot));
    freezeActions(actions, locked);
    meta.appendChild(actions);
  } else {
    const actions = document.createElement("div");
    actions.className = "evidence-actions";
    if (isLast) actions.appendChild(branchButton(card));
    actions.appendChild(deleteButton(card, slot));
    if (!locked) actions.appendChild(reorderHandle(article, card, slot));
    freezeActions(actions, locked);
    meta.appendChild(actions);
  }
  if (locked) {
    const badge = document.createElement("div");
    badge.className = "evidence-lock";
    badge.textContent = "編集中";
    meta.appendChild(badge);
  }
  if (card.message && slot.index === 0) {
    const error = document.createElement("p");
    error.className = "evidence-message";
    error.textContent = card.message;
    meta.appendChild(error);
  }
  article.appendChild(meta);
  return article;
}

function titleFromFilename(text) {
  const value = String(text || "").trim();
  const marked = value.match(/^[^\d]+\d{3}(?:-\d+)?：(.+?)(?:\.pdf)?$/);
  if (marked) return marked[1];
  const half = value.match(/^[^\d]+\d{3}(?:-\d+)?:(.+?)(?:\.pdf)?$/);
  if (half) return half[1];
  return value.replace(/\.pdf$/i, "");
}

function freezeActions(actions, locked) {
  if (!locked) return;
  actions.querySelectorAll("button").forEach((button) => { button.disabled = true; });
}

function openEditorWindow(card, slot) {
  api.open_editor(card.number, slot.index).then((result) => {
    if (result && result.message && result.ok === false) showBanner(result.message);
    if (result && result.cards) applyView(result);
  });
}

function miniButton(text, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn mini";
  button.textContent = text;
  button.addEventListener("click", onClick);
  return button;
}

function branchButton(card) {
  return miniButton("枝番", () => api.add_branch(card.number).then(applyView));
}

function deleteButton(card, slot) {
  const button = miniButton("削除", () => api.delete_slot(card.number, slot.index).then(applyView));
  button.className = "btn mini danger";
  return button;
}

function renderSplitButtons() {
  for (const card of view.cards) {
    document.querySelectorAll(`[data-split="${card.number}"]`).forEach((button) => {
      button.hidden = !(card.splittable || card.splitA4);
    });
  }
}

function reorderHandle(article, card, slot) {
  const handle = document.createElement("div");
  handle.className = "reorder-handle";
  handle.draggable = true;
  handle.setAttribute("role", "button");
  handle.setAttribute("aria-label", "順番を入れ替える");
  for (let dot = 0; dot < 6; dot += 1) handle.appendChild(document.createElement("span"));
  handle.addEventListener("dragstart", (event) => {
    window.__lexReorder = { number: card.number, slot: slot.index };
    window.__lexDrop = null;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("application/x-lexcrew-order", `${card.number}:${slot.index}`);
    event.dataTransfer.setDragImage(article, 24, 24);
    article.classList.add("is-dragging");
  });
  handle.addEventListener("dragend", () => {
    window.__lexReorder = null;
    clearReorderMarker();
    document.querySelectorAll(".evidence-card.is-dragging").forEach((node) => node.classList.remove("is-dragging"));
  });
  return handle;
}

function cardGroups() {
  const groups = [];
  for (const article of document.querySelectorAll("#cards article")) {
    const number = Number(article.dataset.number);
    const last = groups[groups.length - 1];
    if (!last || last.number !== number) groups.push({ number, articles: [article] });
    else last.articles.push(article);
  }
  return groups;
}

function containsPoint(article, x, y) {
  const rect = article.getBoundingClientRect();
  return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
}

function distanceToRect(x, y, rect) {
  const cx = Math.max(rect.left, Math.min(x, rect.right));
  const cy = Math.max(rect.top, Math.min(y, rect.bottom));
  return (x - cx) ** 2 + (y - cy) ** 2;
}

function reorderPlace(x, y, sourceNumber) {
  const groups = cardGroups();
  const source = groups.find((group) => group.number === sourceNumber);
  if (source && source.articles.some((article) => containsPoint(article, x, y))) return { cancel: true };
  let best = null;
  for (const group of groups) {
    for (const article of group.articles) {
      const rect = article.getBoundingClientRect();
      const dist = distanceToRect(x, y, rect);
      if (!best || dist < best.dist) best = { dist, group, rect };
    }
  }
  if (!best || best.group.number === sourceNumber) return { cancel: true };
  if (x < (best.rect.left + best.rect.right) / 2) return { before: best.group.number };
  const index = groups.findIndex((group) => group.number === best.group.number);
  const next = groups[index + 1];
  return { before: next ? next.number : null };
}

function clearReorderMarker() {
  const marker = document.getElementById("reorder-marker");
  if (marker) marker.hidden = true;
}

function showReorderMarker(place) {
  let marker = document.getElementById("reorder-marker");
  if (!marker) {
    marker = document.createElement("div");
    marker.id = "reorder-marker";
    document.body.appendChild(marker);
  }
  if (!place || place.cancel) {
    marker.hidden = true;
    return;
  }
  const groups = cardGroups();
  let left = 0;
  let top = 0;
  let height = 0;
  if (place.before == null) {
    const last = groups[groups.length - 1];
    const box = last.articles[last.articles.length - 1].getBoundingClientRect();
    left = box.right + 6;
    top = box.top;
    height = box.height;
  } else {
    const group = groups.find((item) => item.number === place.before);
    const box = group.articles[0].getBoundingClientRect();
    left = box.left - 8;
    top = box.top;
    height = box.height;
  }
  marker.hidden = false;
  marker.style.left = `${left}px`;
  marker.style.top = `${top}px`;
  marker.style.height = `${height}px`;
}

function rememberDrop(element, number, slot, file, replace) {
  element.dataset.drop = "1";
  element.addEventListener("dragover", (event) => {
    if (window.__lexReorder) return;
    event.preventDefault();
    window.__lexDrop = { number, slot, file, replace: Boolean(replace) };
    element.classList.add("drop");
  });
  element.addEventListener("dragleave", () => element.classList.remove("drop"));
  element.addEventListener("drop", () => element.classList.remove("drop"));
}

function applyView(next) {
  refreshSerial += 1;
  if (!next || !next.cards) {
    if (next && next.message) showBanner(next.message);
    return refreshApp();
  }
  view = next;
  if (next.message) showBanner(next.message);
  render();
  return refreshApp();
}

function showBanner(text) {
  const banner = document.getElementById("banner");
  banner.hidden = !text;
  banner.textContent = text || "";
}

const seriesInput = document.getElementById("series");
const seriesMenu = document.getElementById("series-menu");
const seriesOpen = document.getElementById("series-open");

function commitSeries() {
  const value = seriesInput.value.trim();
  if (view && value === view.labelTemplate) return;
  api.set_series(value).then((result) => {
    if (result && result.ok === false && result.message) showBanner(result.message);
    applyView(result);
  });
}

function openSeriesMenu() {
  const current = seriesInput.value.trim();
  seriesMenu.querySelectorAll("button").forEach((button) => {
    button.hidden = false;
    button.classList.toggle("is-current", button.dataset.value === current);
  });
  seriesMenu.hidden = false;
  seriesOpen.setAttribute("aria-expanded", "true");
}

function closeSeriesMenu() {
  seriesMenu.hidden = true;
  seriesOpen.setAttribute("aria-expanded", "false");
}

seriesOpen.addEventListener("mousedown", (event) => {
  event.preventDefault();
  if (seriesMenu.hidden) openSeriesMenu();
  else closeSeriesMenu();
});
seriesInput.addEventListener("focus", openSeriesMenu);
seriesInput.addEventListener("input", () => {
  if (!seriesMenu.hidden) openSeriesMenu();
});
seriesInput.addEventListener("change", commitSeries);
seriesInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    closeSeriesMenu();
    commitSeries();
  } else if (event.key === "Escape") {
    closeSeriesMenu();
  }
});
seriesMenu.addEventListener("mousedown", (event) => event.preventDefault());
seriesMenu.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  seriesInput.value = button.dataset.value;
  closeSeriesMenu();
  commitSeries();
});
document.addEventListener("mousedown", (event) => {
  if (!event.target.closest(".series-field")) closeSeriesMenu();
});
const cardList = document.getElementById("cards");
cardList.addEventListener("dragover", (event) => {
  if (!window.__lexReorder) return;
  event.preventDefault();
  showReorderMarker(reorderPlace(event.clientX, event.clientY, window.__lexReorder.number));
});
cardList.addEventListener("drop", (event) => {
  const drag = window.__lexReorder;
  if (!drag) return;
  event.preventDefault();
  const place = reorderPlace(event.clientX, event.clientY, drag.number);
  window.__lexReorder = null;
  clearReorderMarker();
  if (place.cancel) return;
  api.move_slot(drag.number, drag.slot, place.before).then((result) => {
    if (result && result.ok === false && result.message) showBanner(result.message);
    applyView(result);
  });
});

document.getElementById("generate").addEventListener("click", async () => {
  generating = true;
  document.getElementById("generate").disabled = true;
  const result = await api.generate();
  generating = false;
  if (result && result.message) showBanner(result.message);
  applyView(result);
});

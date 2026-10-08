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
    freezeActions(actions, locked);
    meta.appendChild(actions);
  } else {
    const actions = document.createElement("div");
    actions.className = "evidence-actions";
    if (isLast) actions.appendChild(branchButton(card));
    actions.appendChild(deleteButton(card, slot));
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

function rememberDrop(element, number, slot, file, replace) {
  element.dataset.drop = "1";
  element.addEventListener("dragover", (event) => {
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
document.getElementById("generate").addEventListener("click", async () => {
  generating = true;
  document.getElementById("generate").disabled = true;
  const result = await api.generate();
  generating = false;
  if (result && result.message) showBanner(result.message);
  applyView(result);
});

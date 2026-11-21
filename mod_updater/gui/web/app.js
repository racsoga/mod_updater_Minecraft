/* Mod Updater: interfaz. Habla con Python vía window.pywebview.api (ver gui/api.py).
   Python avisa con window.onBackend(evento, datos). Textos: locales/<idioma>.json. */
"use strict";

const $ = sel => document.querySelector(sel);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const api = () => window.pywebview.api;

/* ================================================================ idioma */

let STR = {};
let LANG = "en";

/** t("clave", {count, ...}): plural con clave_one / clave_other y parámetros {nombre}. */
function t(key, params = {}) {
  let k = key;
  if (params.count !== undefined) {
    const plural = params.count === 1 ? `${key}_one` : `${key}_other`;
    if (plural in STR) k = plural;
  }
  const text = STR[k] ?? key;
  return text.replace(/\{(\w+)\}/g, (m, name) => (name in params ? String(params[name]) : m));
}

function joinList(names) {
  return names.length < 2 ? names.join("") : names.slice(0, -1).join(", ") + t("ui.and") + names.at(-1);
}

function applyStrings(lang, strings) {
  LANG = lang;
  STR = strings;
  document.documentElement.lang = lang;
  for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll("[data-i18n-placeholder]")) el.placeholder = t(el.dataset.i18nPlaceholder);
  for (const el of document.querySelectorAll("[data-i18n-title]")) el.title = t(el.dataset.i18nTitle);
  for (const el of document.querySelectorAll("[data-i18n-aria-label]")) el.setAttribute("aria-label", t(el.dataset.i18nAriaLabel));
}

let state = null;          // get_state() de Python
let setupMode = "setup";   // "setup" (primera vez) o "settings"
let pendingFolder = null;  // carpeta elegida y aún no guardada

/* ================================================================ pantallas */

function show(screen) {
  for (const s of ["setup", "scan", "recover", "results", "apply", "done"]) $(`#screen-${s}`).hidden = s !== screen;
  $("#btn-settings").hidden = screen === "setup" || screen === "apply";
  $("#btn-rescan").hidden = screen !== "results";
  $("#actionbar").hidden = screen !== "results";
  for (const chip of [$("#chip-folder"), $("#chip-env")]) chip.hidden = screen === "setup" || !chip.textContent.trim();
  window.scrollTo(0, 0);
}

function setTopbarEnv(env) {
  if (!env) return;
  $("#chip-folder").innerHTML = `${esc(t("ui.folder_chip"))} <strong>${esc(shortPath(env.mods_dir))}</strong>`;
  $("#chip-folder").title = env.mods_dir;
  $("#chip-env").innerHTML = `${esc(env.loader)} <strong>${esc(env.minecraft_version)}</strong>`;
}

function shortPath(p) {
  const parts = String(p).split(/[\\/]/).filter(Boolean);
  return parts.length > 2 ? parts.slice(-2).join("\\") : p;
}

/* ================================================================ bienvenida / ajustes */

const labelLoader = v => (state.loaders.find(l => l.value === v) || { label: v }).label;

function folderHelp(folder) {
  const help = $("#folder-help");
  help.className = "help";
  if (!folder.exists) { help.textContent = t("ui.folder_missing"); help.classList.add("bad"); }
  else if (!folder.jars) { help.textContent = t("ui.folder_empty"); help.classList.add("bad"); }
  else help.textContent = t("ui.folder_found", { count: folder.jars });
}

function envHelp(folder) {
  const v = $("#mc-version").value, l = $("#loader").value;
  const detected = folder.minecraft_version && folder.loader;
  $("#env-help").textContent = !detected ? t("ui.env_unknown")
    : folder.minecraft_version === v && folder.loader === l ? t("ui.env_detected")
    : t("ui.env_differs", { loader: labelLoader(folder.loader), version: folder.minecraft_version });
}

function fillVersions(versions, selected) {
  const list = versions.includes(selected) ? versions : [selected, ...versions];
  $("#mc-version").innerHTML = list.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
  $("#mc-version").value = selected;
}

function keyStatus() {
  const el = $("#key-status");
  el.className = "key-status";
  if (state.key_source === "keyring") el.textContent = t("ui.key_in_use_windows", { hint: state.key_hint });
  else if (state.key_source === "env") el.textContent = t("ui.key_in_use_env");
  else { el.textContent = t("ui.key_none"); el.classList.add("none"); }
  $("#cf-key").placeholder = state.has_key ? t("ui.key_placeholder_change") : t("ui.key_placeholder");
  $("#btn-forget").hidden = state.key_source !== "keyring";
}

function fillLanguages(selected) {
  $("#language").innerHTML = state.languages.map(l =>
    `<option value="${esc(l.value)}">${esc(l.value === "auto" ? t("ui.language_auto") : l.label)}</option>`).join("");
  $("#language").value = selected;
}

async function openSetup(mode) {
  setupMode = mode;
  pendingFolder = null;
  const s = state.settings, folder = state.folder;
  const first = mode === "setup";
  $("#setup-title").textContent = first ? t("ui.setup_title") : t("ui.settings_title");
  $("#setup-deck").textContent = first ? t("ui.setup_deck") : t("ui.settings_deck");
  $("#folder-path").textContent = s.mods_dir;
  folderHelp(folder);

  $("#loader").innerHTML = state.loaders.map(l => `<option value="${esc(l.value)}">${esc(l.label)}</option>`).join("");
  // Primera vez: proponer lo deducido de los mods. Después: lo guardado.
  const version = (first && folder.minecraft_version) || s.minecraft_version;
  fillVersions([], version);
  $("#loader").value = (first && folder.loader) || s.loader;
  envHelp(folder);
  api().mc_versions([version, folder.minecraft_version].filter(Boolean)).then(list => {
    const current = $("#mc-version").value;
    fillVersions(list, current);
    envHelp(state.folder);
  });

  $("#cf-key").value = "";
  $("#key-help").className = "help";
  $("#key-help").textContent = "";
  keyStatus();

  $("#advanced").hidden = first;
  if (!first) refreshBackups();
  $("#allow-beta").checked = !!s.allow_beta;
  $("#backups").value = s.backups_to_keep;
  fillLanguages(s.language || "auto");
  $("#btn-nokey").hidden = $("#nokey-note").hidden = !first || state.has_key;
  $("#btn-cancel-settings").hidden = first;
  $("#btn-save").textContent = first ? t("ui.save_first") : t("ui.save_settings");
  show("setup");
}

async function saveSetup(useCurseforge) {
  const btn = $("#btn-save");
  btn.disabled = true;
  try {
    const res = await api().save_setup({
      mods_dir: pendingFolder || state.settings.mods_dir,
      minecraft_version: $("#mc-version").value,
      loader: $("#loader").value,
      key: $("#cf-key").value.trim(),
      use_curseforge: useCurseforge,
      allow_beta: $("#allow-beta").checked,
      backups_to_keep: Number($("#backups").value) || 1,
      language: $("#language").value,
    });
    $("#cf-key").value = "";
    if (!res.ok) {
      const target = { mods_dir: "#folder-help", minecraft_version: "#env-help", loader: "#env-help", key: "#key-help" }[res.field] || "#folder-help";
      $(target).className = "help bad";
      $(target).textContent = res.message;
      return;
    }
    state = res.state;
    applyStrings(state.lang, state.strings);
    startScan();
  } finally {
    btn.disabled = false;
  }
}

/* ================================================================ escaneo */

const STEPS = ["read", "cf", "mr", "deps"];
const BASE = { read: 0, cf: 60, mr: 75, deps: 90 };

function startScan() {
  $("#scan-error").hidden = true;
  $("#scan-label").textContent = t("ui.scan_preparing");
  setProgress(0);
  for (const li of document.querySelectorAll("#scan-steps li")) li.className = "";
  $(".step-cf").textContent = state.has_key && state.settings.use_curseforge ? t("ui.step_cf") : t("ui.step_cf_skipped");
  show("scan");
  api().start_scan();
}

function setProgress(pct) {
  $("#scan-bar > span").style.width = `${pct}%`;
  $("#scan-bar").setAttribute("aria-valuenow", String(Math.round(pct)));
}

function onProgress(p) {
  $("#scan-label").textContent = p.label;
  const idx = STEPS.indexOf(p.phase);
  document.querySelectorAll("#scan-steps li").forEach((li, i) => {
    li.className = i < idx ? "done" : i === idx ? "now" : "";
  });
  let pct = BASE[p.phase] ?? 0;
  if (p.phase === "read" && p.total) pct = (p.done / p.total) * 55;
  setProgress(pct);
}

/* ================================================================ resultados */

const selectable = m => m.s === "up" || m.s === "dep";
const isAttention = m => m.s === "manual" || m.s === "missing" || m.s === "unreadable";
const GROUPS = [
  { key: "attention", title: "ui.group_attention", match: isAttention },
  { key: "changes", title: "ui.group_changes", match: selectable },
  { key: "ok", title: "ui.group_ok", match: m => m.s === "ok", collapsible: true },
];
const FILTERS = [
  { key: "all", label: "ui.filter_all", match: () => true },
  { key: "changes", label: "ui.filter_changes", match: selectable },
  { key: "ok", label: "ui.filter_ok", match: m => m.s === "ok" },
  { key: "attention", label: "ui.filter_attention", match: isAttention },
];
const arrow = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M4.2 1.8 8.4 6l-4.2 4.2-1-1L6.4 6 3.2 2.8z"/></svg>';

let DATA = null, MODS = [], byName = {};
let filter = "all", query = "", okOpen = false;

function showResults(data) {
  DATA = data;
  MODS = data.rows;
  byName = Object.fromEntries(MODS.filter(m => m.s !== "dep").map(m => [m.name, m]));
  filter = "all"; query = ""; okOpen = false;
  $("#q").value = "";
  setTopbarEnv(data.env);
  // Cabecera: solo lo que afecta a lo que ves (p. ej. revisión sin key).
  $("#notices").innerHTML = (data.warnings || []).map(n => `<li class="bad">${esc(n)}</li>`).join("")
    + data.notices.map(n => `<li>${esc(n)}</li>`).join("");
  // Detalles: avisos que no requieren nada de ti.
  $("#details").hidden = !data.details.length;
  $("#details-summary").textContent = t("ui.details", { count: data.details.length });
  $("#details-list").innerHTML = data.details.map(d => `<li>${esc(d)}</li>`).join("");
  show("results");
  render();
}

const depsBrokenBy = m => (m.s === "dep" && !m.checked ? m.neededBy : []);

function setChecked(m, value) {
  m.checked = value;
  if (value) {  // si un mod que se actualiza necesita una dependencia, van juntos
    for (const d of MODS) if (d.s === "dep" && d.neededBy.includes(m.name)) d.checked = true;
  }
  if (m.s === "dep" && !value) {
    for (const parent of m.neededBy.map(n => byName[n]).filter(p => p && p.s === "up")) parent.checked = false;
  }
}

function logo(m) {
  if (m.icon) return `<img class="logo" src="${esc(m.icon)}" alt="" loading="lazy" width="32" height="32" referrerpolicy="no-referrer">`;
  const letter = m.name.replace(/[^\p{L}\p{N}]/gu, "").charAt(0).toUpperCase() || "?";
  return `<span class="logo mono" aria-hidden="true">${esc(letter)}</span>`;
}

function betaTag(m) {
  if (!m.beta) return "";
  const note = m.betaNote || "";
  return `<span class="tag"${note ? ` data-tip="${esc(note)}"` : ""}>${esc(t("ui.beta"))}${note ? `<span class="sr-only">: ${esc(note)}</span>` : ""}</span>`;
}

function versions(m) {
  if (!m.to) return `<div class="ver"><span class="new" title="${esc(m.from)}">${esc(m.from || "?")}</span>${betaTag(m)}</div>`;
  const from = m.from ? `<span class="old" title="${esc(m.from)}">${esc(m.from)}</span>` : `<span class="old">${esc(t("ui.not_installed"))}</span>`;
  return `<div class="ver">${from}${arrow}<span class="sr-only">${esc(t("ui.to"))}</span><span class="new" title="${esc(m.to)}">${esc(m.to)}</span>${betaTag(m)}</div>`;
}

function sub(m) {
  if (m.s === "dep") {
    const broken = depsBrokenBy(m);
    if (broken.length) return `<div class="sub warn">${esc(t("ui.dep_warning", { dep: m.name, names: joinList(broken) }))}</div>`;
    return `<div class="sub">${esc(t("ui.needed_by", { names: joinList(m.neededBy) }))}</div>`;
  }
  return m.sub ? `<div class="sub" title="${esc(m.sub)}">${esc(m.sub)}</div>` : "";
}

function row(m) {
  const helpId = `help-${m.id}`;
  const action = m.s === "dep" ? t("ui.install_x", { name: m.name }) : t("ui.update_x", { name: m.name });
  const cb = selectable(m)
    ? `<input class="check" type="checkbox" data-id="${m.id}" ${m.checked ? "checked" : ""} aria-label="${esc(action)}" aria-describedby="${helpId}">`
    : `<span class="slot" aria-hidden="true"></span>`;
  const source = m.s === "manual" && m.url ? `<a href="${esc(m.url)}" data-external>${esc(t("ui.open_page"))}</a>` : esc(m.src);
  const help = t(`status_help.${m.s}`);
  return `<div class="row ${m.s}">
    ${cb}${logo(m)}
    <div class="name"><div class="title" title="${esc(m.name)}">${esc(m.name)}</div>${sub(m)}</div>
    ${versions(m)}
    <span class="badge ${m.s}" data-tip="${esc(help)}"><span class="dot" aria-hidden="true"></span>${esc(t(`status.${m.s}`))}<span class="sr-only" id="${helpId}">. ${esc(help)}</span></span>
    <span class="source">${source}</span>
  </div>`;
}

function visible(m) {
  const f = FILTERS.find(f => f.key === filter);
  return f.match(m) && (!query || m.name.toLowerCase().includes(query));
}

function render() {
  const a = document.activeElement;
  const ds = (a && a.dataset) || {};
  const focusKey = (ds.f && `[data-f="${ds.f}"]`) || (ds.id && `[data-id="${ds.id}"]`)
    || ("ok" in ds && "[data-ok]") || ("all" in ds && "[data-all]") || ("clear" in ds && "#q") || null;

  $("#filters").innerHTML = FILTERS.map(f => {
    const n = MODS.filter(f.match).length;
    return `<button type="button" data-f="${f.key}" aria-pressed="${f.key === filter}">${esc(t(f.label))} <span class="n">${n}</span></button>`;
  }).join("");

  let html = "";
  for (const g of GROUPS) {
    const items = MODS.filter(m => g.match(m) && visible(m));
    if (!items.length) continue;
    const forced = filter === "ok" || query;
    const open = !g.collapsible || okOpen || forced;
    let extra = "";
    if (g.key === "changes") {
      const n = items.filter(m => m.checked).length;
      extra = `<label class="master"><input class="check" type="checkbox" data-all ${n === items.length ? "checked" : ""}> ${esc(t("ui.select_all"))}</label>`;
    } else if (g.collapsible && !forced) {
      extra = `<button class="linkbtn" type="button" data-ok aria-expanded="${okOpen}">${esc(okOpen ? t("ui.hide") : t("ui.show_n", { count: items.length }))}</button>`;
    }
    html += `<div class="group-head" data-g="${g.key}"><h3>${esc(t(g.title))}</h3><span class="count">${items.length}</span><span class="grow"></span>${extra}</div>`;
    if (open) html += items.map(row).join("");
  }
  $("#list").innerHTML = html || (!MODS.length
    ? `<div class="empty">${esc(t("ui.list_empty"))} <button class="linkbtn" type="button" data-go-settings>${esc(t("ui.open_settings"))}</button></div>`
    : `<div class="empty">${esc(t("ui.no_match", { query }))} <button class="linkbtn" type="button" data-clear>${esc(t("ui.clear_search"))}</button></div>`);

  const master = $("[data-all]");
  if (master) {
    const items = MODS.filter(m => selectable(m) && visible(m));
    const n = items.filter(m => m.checked).length;
    master.indeterminate = n > 0 && n < items.length;
  }
  if (focusKey) document.querySelector(focusKey)?.focus();
  summary();
}

function summary() {
  const ups = MODS.filter(m => m.s === "up"), deps = MODS.filter(m => m.s === "dep");
  const okN = MODS.filter(m => m.s === "ok").length, attN = MODS.filter(isAttention).length;

  if (!MODS.length) {  // carpeta sin mods
    $("#headline").textContent = t("ui.head_empty");
    $("#deck").textContent = t("ui.deck_empty");
    $("#go").hidden = true;
    $("#btn-recheck").hidden = false;
    $("#summary").innerHTML = `<span class="count">${esc(t("ui.head_empty"))}</span>`;
    return;
  }
  let head;
  if (!ups.length && !deps.length) head = t("ui.head_all_ok");
  else if (ups.length && deps.length) head = t("ui.head_both", { updates: t("ui.head_updates", { count: ups.length }), deps: t("ui.head_deps", { count: deps.length }) });
  else head = ups.length ? t("ui.head_updates", { count: ups.length }) : t("ui.head_deps", { count: deps.length });
  $("#headline").textContent = head.charAt(0).toUpperCase() + head.slice(1) + ".";
  const depLines = deps.map(d => t("ui.deck_dep", { dep: d.name, names: joinList(d.neededBy) })).join(" ");
  $("#deck").innerHTML = `<b>${esc(t("ui.deck_ok", { count: okN }))}</b> `
    + (attN ? esc(t("ui.deck_attention", { count: attN })) + " " : "") + esc(depLines);

  // Nada que actualizar: sin botón de acción, solo "Todo al día" y "Volver a revisar".
  const nothing = !ups.length && !deps.length;
  $("#go").hidden = nothing;
  $("#btn-recheck").hidden = !nothing;
  if (nothing) {
    $("#summary").innerHTML = `<span class="count">${esc(t("ui.all_up_to_date"))}</span>`
      + `<span class="safe">${esc(t("ui.deck_ok", { count: okN }))}</span>`;
    return;
  }

  const sel = MODS.filter(m => m.checked);
  const selUp = sel.filter(m => m.s === "up").length, selDep = sel.filter(m => m.s === "dep").length;
  const btn = $("#go");
  btn.disabled = sel.length === 0;
  btn.textContent = !sel.length ? t("ui.go_choose")
    : selDep && selUp ? t("ui.go_both", { updates: selUp, installs: selDep })
    : selDep ? t("ui.go_install", { count: selDep })
    : t("ui.go_update", { count: selUp });

  const broken = deps.flatMap(depsBrokenBy);
  const warn = broken.length
    ? `<span class="warn">${esc(t("ui.dep_warning", { dep: joinList(deps.filter(d => !d.checked).map(d => d.name)), names: joinList(broken) }))}</span>` : "";
  $("#summary").innerHTML = `<span class="count">${esc(t("ui.selected", { count: ups.length + deps.length, selected: sel.length }))}</span>`
    + (warn || `<span class="safe">${esc(t("ui.safe"))}</span>`);
}

/* ================================================================ actualizando / final */

let APPLY = [];  // filas que se están aplicando

async function startApply() {
  const chosen = MODS.filter(m => m.checked);
  const res = await api().apply(chosen.map(m => m.id));
  if (!res.ok) {
    $("#summary").innerHTML = `<span class="count">${esc(t("ui.cannot_start"))}</span><span class="warn">${esc(res.message)}</span>`;
    return;
  }
  APPLY = chosen.map(m => ({ ...m, state: "queued", message: "" }));
  $("#apply-label").textContent = t("ui.apply_count", { done: 0, count: APPLY.length });
  $("#apply-bar > span").style.width = "0%";
  renderApply();
  show("apply");
}

function renderApply() {
  $("#apply-list").innerHTML = APPLY.map(m => `<div class="row apply-row">
    ${logo(m)}
    <div class="name"><div class="title">${esc(m.name)}</div>${m.message ? `<div class="sub warn">${esc(m.message)}</div>` : ""}</div>
    ${versions(m)}
    <span class="state ${m.state}">${esc(t(`ui.state_${m.state}`))}</span>
  </div>`).join("");
}

function onApplyProgress(p) {
  const m = APPLY.find(x => x.id === p.id);
  if (m) { m.state = p.state; m.message = p.message || ""; }
  $("#apply-label").textContent = t("ui.apply_count", { done: p.done, count: p.total });
  const pct = (p.done / p.total) * 100;
  $("#apply-bar > span").style.width = `${pct}%`;
  $("#apply-bar").setAttribute("aria-valuenow", String(Math.round(pct)));
  renderApply();
}

function showDone(r) {
  const parts = [];
  if (r.updated) parts.push(t("ui.done_updated", { count: r.updated }));
  if (r.installed) parts.push(t("ui.done_installed", { count: r.installed }));
  const title = parts.length ? parts.join(t("ui.and")) : t("ui.done_none");
  $("#done-title").textContent = title.charAt(0).toUpperCase() + title.slice(1) + ".";
  const deck = [];
  if (r.error) deck.push(r.error);
  if (r.backup && r.backup.changes) deck.push(t("ui.done_backup", { path: shortPath(r.backup.path) }));
  if (r.updated || r.installed) deck.push(t("ui.done_restart"));
  $("#done-deck").textContent = deck.join(" ");
  $("#btn-undo").hidden = !(r.backup && r.backup.undoable);
  $("#btn-undo").disabled = false;
  $("#undo-help").textContent = "";
  $("#done-failed").hidden = !r.failed.length;
  $("#done-failed-title").textContent = t("ui.done_failed", { count: r.failed.length });
  $("#done-failed-list").innerHTML = r.failed.map(f => `<li><b>${esc(f.name)}</b>: ${esc(f.message)}</li>`).join("");
  DATA = null;  // la revisión anterior ya no vale
  show("done");
}

async function refreshBackups(clearHelp = true) {
  const info = await api().backups_info();
  const undo = $("#btn-undo-last"), clear = $("#btn-clear-backups");
  undo.disabled = !(info.last && info.last.undoable);
  undo.title = info.last && info.last.undoable
    ? t("ui.undo_last_info", { date: formatDate(info.last.date), count: info.last.changes }) : t("ui.undo_last_none");
  clear.disabled = !info.count;
  clear.dataset.count = String(info.count);
  delete clear.dataset.confirm;
  clear.classList.remove("danger");
  clear.textContent = t("ui.clear_backups");
  if (clearHelp) {
    $("#backups-help").className = "help";
    $("#backups-help").textContent = info.count ? t("ui.backups_count", { count: info.count }) : t("ui.no_backups");
  }
}

function formatDate(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleString(LANG, { dateStyle: "medium", timeStyle: "short" }); } catch { return iso; }
}

/* ================================================================ eventos */

window.onBackend = (event, payload) => {
  if (event === "apply_progress") onApplyProgress(payload);
  else if (event === "apply_wait") $("#apply-label").textContent = payload.label;
  else if (event === "apply_done") showDone(payload);
  else if (event === "progress") onProgress(payload);
  else if (event === "results") { setProgress(100); showResults(payload); }
  else if (event === "error") {
    $("#scan-error-text").textContent = payload.message;
    $("#scan-error").hidden = false;
    $("#scan-label").textContent = t("ui.scan_unfinished");
  }
};

document.addEventListener("click", async e => {
  const el = e.target;
  const ext = el.closest("[data-external]");
  if (ext) { e.preventDefault(); api().open_url(ext.getAttribute("href")); return; }
  const f = el.closest("[data-f]");
  if (f) { filter = f.dataset.f; render(); return; }
  if (el.closest("[data-ok]")) { okOpen = !okOpen; render(); return; }
  if (el.closest("[data-clear]")) { $("#q").value = ""; query = ""; render(); $("#q").focus(); return; }
  if (el.closest("[data-go-settings]")) { openSetup("settings"); return; }
});

document.addEventListener("change", e => {
  const el = e.target;
  if (!el.dataset) return;
  if ("all" in el.dataset) {
    MODS.filter(m => selectable(m) && visible(m)).forEach(m => setChecked(m, el.checked));
    render(); return;
  }
  if (el.dataset.id !== undefined && el.classList.contains("check")) { setChecked(MODS[el.dataset.id], el.checked); render(); }
});

document.addEventListener("keydown", e => {
  if ($("#screen-results").hidden) return;
  if (e.key === "/" && !["INPUT", "SELECT"].includes(document.activeElement.tagName)) { e.preventDefault(); $("#q").focus(); }
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !$("#go").disabled) $("#go").click();
});

function wire() {
  $("#q").addEventListener("input", e => { query = e.target.value.trim().toLowerCase(); render(); });
  $("#btn-settings").addEventListener("click", () => openSetup("settings"));
  $("#btn-rescan").addEventListener("click", startScan);
  $("#btn-retry").addEventListener("click", startScan);
  $("#btn-recheck").addEventListener("click", startScan);
  $("#btn-cancel-settings").addEventListener("click", async () => {
    // Deshacer la vista previa del idioma si se cancela.
    const s = await api().get_strings(state.settings.language || "auto");
    applyStrings(s.lang, s.strings);
    if (DATA) { showResults(DATA); } else startScan();
  });
  $("#btn-save").addEventListener("click", () => saveSetup(true));
  $("#btn-nokey").addEventListener("click", () => saveSetup(false));
  $("#mc-version").addEventListener("change", () => envHelp(state.folder));
  $("#loader").addEventListener("change", () => envHelp(state.folder));
  $("#language").addEventListener("change", async e => {
    // Vista previa inmediata; se guarda con el botón principal.
    const s = await api().get_strings(e.target.value);
    applyStrings(s.lang, s.strings);
    const keep = { version: $("#mc-version").value, loader: $("#loader").value, lang: e.target.value };
    $("#setup-title").textContent = setupMode === "setup" ? t("ui.setup_title") : t("ui.settings_title");
    $("#setup-deck").textContent = setupMode === "setup" ? t("ui.setup_deck") : t("ui.settings_deck");
    $("#btn-save").textContent = setupMode === "setup" ? t("ui.save_first") : t("ui.save_settings");
    folderHelp(state.folder);
    keyStatus();
    fillLanguages(keep.lang);
    $("#mc-version").value = keep.version;
    $("#loader").value = keep.loader;
    envHelp(state.folder);
  });
  $("#btn-folder").addEventListener("click", async () => {
    const res = await api().choose_folder();
    if (!res) return;
    pendingFolder = res.path;
    state.folder = res.folder;
    $("#folder-path").textContent = res.path;
    folderHelp(res.folder);
    if (res.folder.minecraft_version) {
      const list = [...$("#mc-version").options].map(o => o.value);
      fillVersions(list, res.folder.minecraft_version);
    }
    if (res.folder.loader) $("#loader").value = res.folder.loader;
    envHelp(res.folder);
  });
  $("#btn-test").addEventListener("click", async () => {
    const help = $("#key-help");
    help.className = "help";
    help.textContent = t("ui.key_testing");
    const res = await api().test_key($("#cf-key").value);
    help.className = `help ${res.ok ? "ok" : "bad"}`;
    help.textContent = res.message;
  });
  $("#btn-forget").addEventListener("click", async () => {
    const fresh = await api().forget_key();
    state = { ...state, has_key: fresh.has_key, key_hint: fresh.key_hint, key_source: fresh.key_source };
    keyStatus();
    $("#key-help").className = fresh.error ? "help bad" : "help";
    $("#key-help").textContent = fresh.error || t("ui.key_forgotten");
  });
  $("#go").addEventListener("click", startApply);
  $("#btn-open-folder").addEventListener("click", () => api().open_mods_folder());
  $("#btn-check-again").addEventListener("click", startScan);
  $("#btn-undo").addEventListener("click", async () => {
    const btn = $("#btn-undo");
    btn.disabled = true;
    const res = await api().undo_last();
    const help = $("#undo-help");
    help.className = `help undo-help ${res.ok ? "ok" : "bad"}`;
    help.textContent = [res.message, ...(res.errors || [])].join(" ");
    if (res.ok || res.restored || res.removed) {
      $("#done-title").textContent = t("ui.undone_title");
      btn.hidden = true;
    } else btn.disabled = false;
  });
  $("#btn-undo-last").addEventListener("click", async () => {
    const res = await api().undo_last();
    $("#backups-help").className = `help ${res.ok ? "ok" : "bad"}`;
    $("#backups-help").textContent = [res.message, ...(res.errors || [])].join(" ");
    refreshBackups(false);
  });
  $("#btn-clear-backups").addEventListener("click", async () => {
    const btn = $("#btn-clear-backups");
    if (!btn.dataset.confirm) {  // primer clic: pedir confirmación en el propio botón
      btn.dataset.confirm = "1";
      btn.textContent = t("ui.clear_confirm", { count: Number(btn.dataset.count || 0) });
      btn.classList.add("danger");
      return;
    }
    const res = await api().clear_backups();
    $("#backups-help").className = "help ok";
    $("#backups-help").textContent = res.message;
    refreshBackups(false);
  });
}

// Al abrir: si la última actualización se cortó a medias, ofrecer restaurarla antes de revisar.
function showRecover(info) {
  $("#recover-title").textContent = t("recover.title");
  $("#recover-deck").textContent = t("recover.deck", { count: info.changes, date: formatDate(info.date) });
  $("#recover-help").textContent = "";
  $("#btn-restore").hidden = false;
  $("#btn-restore").disabled = false;
  $("#btn-recover-skip").textContent = t("recover.skip");
  show("recover");
  $("#btn-restore").focus();
}

function wireRecover() {
  $("#btn-restore").addEventListener("click", async () => {
    const btn = $("#btn-restore");
    btn.disabled = true;
    const res = await api().restore_interrupted();
    const help = $("#recover-help");
    help.className = `help undo-help ${res.ok ? "ok" : "bad"}`;
    help.textContent = [res.message, ...(res.errors || [])].join(" ");
    if (res.ok || res.restored || res.removed) {
      $("#recover-title").textContent = t("recover.done_title");
      $("#recover-deck").textContent = "";
      btn.hidden = true;
      $("#btn-recover-skip").textContent = t("recover.continue");
      $("#btn-recover-skip").focus();
    } else btn.disabled = false;
  });
  $("#btn-recover-skip").addEventListener("click", startScan);
}

async function boot() {
  wire();
  wireRecover();
  state = await api().get_state();
  applyStrings(state.lang, state.strings);
  if (!state.settings.setup_done) return openSetup("setup");
  const pending = await api().interrupted();
  if (pending) showRecover(pending);
  else startScan();
}

if (window.pywebview && window.pywebview.api) boot();
else if (location.search.includes("mock")) {
  const s = document.createElement("script");
  s.src = "dev-mock.js";
  s.onload = boot;
  document.head.appendChild(s);
} else window.addEventListener("pywebviewready", boot, { once: true });

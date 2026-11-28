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

// Pantallas de la sección "Mis mods" (la última visitada se recuerda al volver de Ajustes).
const MODS_SCREENS = ["scan", "recover", "results", "apply", "done"];
let modsScreen = null;

function show(screen) {
  for (const s of ["setup", "analysis", "explore", "suggest", ...MODS_SCREENS]) $(`#screen-${s}`).hidden = s !== screen;
  $("#ex-basket").hidden = screen !== "explore" || !BASKET.size;
  if (MODS_SCREENS.includes(screen)) modsScreen = screen;
  // Pestañas: ocultas en la bienvenida (primera vez) y mientras se actualiza (no se puede salir).
  $("#tabs").hidden = (screen === "setup" && setupMode === "setup") || screen === "apply";
  renderProfileSelect(screen);
  selectTab({ setup: "settings", analysis: "analysis", explore: "explore", suggest: "suggest" }[screen] || "mods");
  $("#btn-rescan").hidden = screen !== "results";
  $("#actionbar").hidden = screen !== "results" || picking;
  $("#pickbar").hidden = screen !== "results" || !picking;
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
  $("#profiles-panel").hidden = first;
  if (!first) renderProfiles();
  if (!first) refreshBackups();
  $("#allow-beta").checked = !!s.allow_beta;
  $("#check-updates").checked = s.check_updates !== false;
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
      check_updates: $("#check-updates").checked,
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
  { key: "off", label: "ui.filter_off", match: m => m.off, hideEmpty: true },
];
const toggleable = m => !!m.file && m.s !== "unreadable";  // instalado y legible: se puede activar/desactivar
let picking = false;
const PICK = new Set();  // ids marcados en el modo "Activar o desactivar varios"
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
  const cl = m.cl ? `<button class="linkbtn cl-btn" type="button" data-cl="${m.id}" aria-haspopup="dialog">${esc(t("cl.open"))}</button>` : "";
  return `<div class="ver">${from}${arrow}<span class="sr-only">${esc(t("ui.to"))}</span><span class="new" title="${esc(m.to)}">${esc(m.to)}</span>${betaTag(m)}${cl}</div>`;
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
  const cb = picking
    ? (toggleable(m) ? `<input class="check" type="checkbox" data-pick="${m.id}" ${PICK.has(m.id) ? "checked" : ""} aria-label="${esc(t("ui.pick_x", { name: m.name }))}">`
      : `<span class="slot" aria-hidden="true"></span>`)
    : selectable(m)
    ? `<input class="check" type="checkbox" data-id="${m.id}" ${m.checked ? "checked" : ""} aria-label="${esc(action)}" aria-describedby="${helpId}">`
    : `<span class="slot" aria-hidden="true"></span>`;
  const source = m.s === "manual" && m.url ? `<a href="${esc(m.url)}" data-external>${esc(t("ui.open_page"))}</a>` : esc(m.src);
  const help = t(`status_help.${m.s}`);
  const sw = toggleable(m)
    ? `<button class="switch" type="button" role="switch" aria-checked="${!m.off}" data-toggle="${m.id}" aria-label="${esc(t("ui.toggle_label", { name: m.name }))}"><span aria-hidden="true"></span></button>`
    : `<span aria-hidden="true"></span>`;
  const off = m.off ? `<span class="tag off">${esc(t("ui.state_off"))}</span>` : "";
  return `<div class="row ${m.s}${m.off ? " is-off" : ""}">
    ${cb}${logo(m)}
    <div class="name"><div class="title" title="${esc(m.name)}"><span class="title-text">${esc(m.name)}</span>${off}</div>${sub(m)}</div>
    ${versions(m)}
    <span class="badge ${m.s}" data-tip="${esc(help)}"><span class="dot" aria-hidden="true"></span>${esc(t(`status.${m.s}`))}<span class="sr-only" id="${helpId}">. ${esc(help)}</span></span>
    <span class="source">${source}</span>
    ${sw}
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
    || (ds.toggle && `[data-toggle="${ds.toggle}"]`) || (ds.pick && `[data-pick="${ds.pick}"]`)
    || ("ok" in ds && "[data-ok]") || ("all" in ds && "[data-all]") || ("clear" in ds && "#q") || null;

  if (filter === "off" && !MODS.some(m => m.off)) filter = "all";  // ya no queda ninguno desactivado
  $("#filters").innerHTML = FILTERS.map(f => {
    const n = MODS.filter(f.match).length;
    if (f.hideEmpty && !n) return "";
    return `<button type="button" data-f="${f.key}" aria-pressed="${f.key === filter}">${esc(t(f.label))} <span class="n">${n}</span></button>`;
  }).join("");

  let html = "";
  for (const g of GROUPS) {
    const items = MODS.filter(m => g.match(m) && visible(m));
    if (!items.length) continue;
    const forced = filter === "ok" || filter === "off" || query;
    const open = !g.collapsible || okOpen || forced;
    let extra = "";
    if (g.key === "changes" && !picking) {
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
  renderPickbar();
}

/* ---------------------------------------------------------------- activar y desactivar */

function flashNotice(text, bad = false) {
  $("#notices").insertAdjacentHTML("afterbegin", `<li${bad ? ' class="bad"' : ""}>${esc(text)}</li>`);
}

// Activa o desactiva (renombra a .jar.disabled). Si una librería la usan mods activos, pregunta antes.
async function setEnabled(ids, enabled, mode = "ask") {
  const res = await api().mods_set_enabled(ids, enabled, mode);
  if (res.reason === "dependents") { askDependents(ids, res); return false; }
  if (!res.ok && res.message) { flashNotice(res.message, true); return false; }
  for (const r of res.rows || []) if (MODS[r.id]) MODS[r.id].off = r.off;
  if (res.also && res.also.length) flashNotice(t("toggle.also", { count: res.also.length, names: joinList(res.also) }));
  for (const f of res.failed || []) flashNotice(t("toggle.failed", { name: f.name, message: f.message }), true);
  render();
  return true;
}

function askDependents(ids, res) {
  const names = ids.map(i => MODS[i] && MODS[i].name).filter(Boolean);
  openExDrawer(t("toggle.title"), joinList(names));
  $("#ex-d-body").innerHTML = `<p class="ex-note warn">${esc(res.message)}</p>`
    + `<ul class="an-list">${res.names.map(n => `<li><span class="an-name">${esc(n)}</span></li>`).join("")}</ul>`
    + `<p class="an-hint">${esc(t("toggle.hint"))}</p>`;
  $("#ex-d-foot").innerHTML = `<button class="btn-secondary" type="button" id="tg-cancel">${esc(t("ui.cancel"))}</button>
    <button class="btn-secondary" type="button" id="tg-only">${esc(t("toggle.only", { name: joinList(names) }))}</button>
    <button class="btn-primary" type="button" id="tg-with">${esc(t("toggle.with"))}</button>`;
  $("#tg-cancel").addEventListener("click", closeExDrawer);
  for (const [id, mode] of [["#tg-only", "only"], ["#tg-with", "with"]]) {
    $(id).addEventListener("click", async () => { closeExDrawer(); if (await setEnabled(ids, false, mode)) endPicking(); });
  }
}

function startPicking() {
  picking = true; PICK.clear();
  $("#actionbar").hidden = true;
  render();
  document.querySelector("[data-pick]")?.focus();
}

function endPicking() {
  if (!picking) return;
  picking = false; PICK.clear();
  $("#actionbar").hidden = $("#screen-results").hidden;
  render();
}

function renderPickbar() {
  const bar = $("#pickbar");
  bar.hidden = !picking || $("#screen-results").hidden;
  $("#btn-pick").setAttribute("aria-pressed", String(picking));
  if (!picking) return;
  const marked = [...PICK].map(i => MODS[i]).filter(Boolean);
  const on = marked.filter(m => !m.off), off = marked.filter(m => m.off);
  $("#pick-count").textContent = t("ui.pick_count", { count: marked.length });
  $("#pick-enable").disabled = !off.length;
  $("#pick-disable").disabled = !on.length;
  $("#pick-enable").textContent = off.length ? `${t("ui.pick_enable")} ${off.length}` : t("ui.pick_enable");
  $("#pick-disable").textContent = on.length ? `${t("ui.pick_disable")} ${on.length}` : t("ui.pick_disable");
}

async function pickApply(enabled) {
  const ids = [...PICK].filter(i => MODS[i] && MODS[i].off === enabled);
  if (ids.length && await setEnabled(ids, enabled)) endPicking();
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
  if (r.added) parts.push(t("ui.done_added", { count: r.added }));  // elegidos en Explorar
  if (r.removed) parts.push(t("ui.done_removed", { count: r.removed }));  // quitados (están en la copia)
  if (r.installed) parts.push(t("ui.done_installed", { count: r.installed }));  // dependencias
  const title = parts.length ? parts.join(t("ui.and")) : t("ui.done_none");
  $("#done-title").textContent = title.charAt(0).toUpperCase() + title.slice(1) + ".";
  const deck = [];
  if (r.error) deck.push(r.error);
  if (r.backup && r.backup.changes) deck.push(t("ui.done_backup", { path: shortPath(r.backup.path) }));
  if (r.updated || r.installed || r.added || r.removed) deck.push(t("ui.done_restart"));
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
  const cl = el.closest("[data-cl]");
  if (cl) { openChangelog(Number(cl.dataset.cl), cl); return; }
  const sw = el.closest("[data-toggle]");
  if (sw) { const m = MODS[Number(sw.dataset.toggle)]; if (m) setEnabled([m.id], m.off); return; }
});

/* ================================================================ changelog */

// Escape cierra el panel abierto aunque el foco no esté en un control (se hizo clic en su texto).
document.addEventListener("keydown", e => {
  if (e.key !== "Escape" || !document.body.classList.contains("drawer-open")) return;
  if (!$("#cl-drawer").hidden) closeChangelog();
  else if (!$("#ex-drawer").hidden) closeExDrawer();
});

let clReturn = null;   // botón al que vuelve el foco al cerrar
let clSeq = 0;         // descarta respuestas de una petición anterior (red lenta)

async function openChangelog(id, trigger) {
  const m = MODS[id];
  clReturn = trigger;
  $("#cl-title").textContent = t("cl.title", { name: m.name });
  $("#cl-range").textContent = `${m.from || ""} → ${m.to || ""}`;
  $("#cl-body").innerHTML = `<p class="cl-loading">${esc(t("cl.loading"))}</p>`;
  $("#cl-backdrop").hidden = $("#cl-drawer").hidden = false;
  document.body.classList.add("drawer-open");
  $("#cl-close").focus();
  const seq = ++clSeq;
  const res = await api().changelog(id);
  if ($("#cl-drawer").hidden || seq !== clSeq) return;  // se cerró o se abrió otro mientras cargaba
  renderChangelog(res);
}

function renderChangelog(res) {
  const body = $("#cl-body");
  if (!res.ok) { body.innerHTML = `<p class="cl-error">${esc(res.message)}</p>`; return; }
  const link = res.url ? `<a href="${esc(res.url)}" data-external>${esc(t("cl.page"))}</a>` : "";
  if (!res.versions.length) { body.innerHTML = `<p class="cl-empty">${esc(t("cl.none"))} ${link}</p>`; return; }
  // El HTML de cada versión ya viene limpio desde Python (changelog.sanitize_html).
  const entries = res.versions.map(v => `<section class="cl-entry">
      <h3><span>${esc(v.version)}</span>${v.channel !== "release" ? `<span class="beta">${esc(t(v.channel === "alpha" ? "ui.alpha" : "ui.beta"))}</span>` : ""}
        <time datetime="${esc(v.date)}">${esc(formatDay(v.date))}</time></h3>
      ${v.html ? `<div class="cl-html">${v.html}</div>` : `<p class="cl-empty">${esc(t("cl.empty"))} ${link}</p>`}
    </section>`).join("");
  const flagged = res.versions.some(v => v.html.includes('class="cl-flag"'));
  body.innerHTML = (flagged ? `<p class="cl-legend"><mark class="cl-flag">${esc(t("cl.flag_word"))}</mark> ${esc(t("cl.flag_legend"))}</p>` : "")
    + entries + (res.more ? `<p class="cl-more">${esc(t("cl.more", { count: res.more }))} ${link}</p>` : "");
}

function formatDay(iso) {
  try { return new Date(iso).toLocaleDateString(LANG, { year: "numeric", month: "short", day: "numeric" }); } catch { return iso; }
}

function closeChangelog() {
  if ($("#cl-drawer").hidden) return;
  $("#cl-backdrop").hidden = $("#cl-drawer").hidden = true;
  document.body.classList.remove("drawer-open");
  if (clReturn && document.contains(clReturn)) clReturn.focus();
}

function wireChangelog() {
  $("#cl-close").addEventListener("click", closeChangelog);
  $("#cl-backdrop").addEventListener("click", closeChangelog);
  $("#cl-drawer").addEventListener("keydown", e => {
    if (e.key === "Escape") { e.preventDefault(); closeChangelog(); return; }
    if (e.key !== "Tab") return;
    // Foco atrapado dentro del panel mientras está abierto.
    const items = [...$("#cl-drawer").querySelectorAll("button, a[href], [tabindex]:not([tabindex='-1'])")];
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
}

document.addEventListener("change", e => {
  const el = e.target;
  if (!el.dataset) return;
  if ("all" in el.dataset) {
    MODS.filter(m => selectable(m) && visible(m)).forEach(m => setChecked(m, el.checked));
    render(); return;
  }
  if (el.dataset.id !== undefined && el.classList.contains("check")) { setChecked(MODS[el.dataset.id], el.checked); render(); }
  if (el.dataset.pick !== undefined) { const i = Number(el.dataset.pick); el.checked ? PICK.add(i) : PICK.delete(i); renderPickbar(); }
});

document.addEventListener("keydown", e => {
  if (document.body.classList.contains("drawer-open")) return;  // con un panel abierto, sus teclas mandan
  if ($("#screen-results").hidden) return;
  if (e.key === "/" && !["INPUT", "SELECT"].includes(document.activeElement.tagName)) { e.preventDefault(); $("#q").focus(); }
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !$("#go").disabled) $("#go").click();
});

function selectTab(name) {
  for (const tab of document.querySelectorAll("#tabs [role=tab]")) {
    const on = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", on ? "true" : "false");
    tab.tabIndex = on ? 0 : -1;
  }
}

async function revertLanguagePreview() {
  // Al salir de Ajustes sin guardar se deshace la vista previa del idioma.
  const s = await api().get_strings(state.settings.language || "auto");
  applyStrings(s.lang, s.strings);
}

function goMods() {
  if (modsScreen && modsScreen !== "apply") show(modsScreen);
  else if (DATA) showResults(DATA);
  else startScan();
}

async function leaveSettings() {
  await revertLanguagePreview();
  goMods();
}

async function openTab(name) {
  const current = document.querySelector('#tabs [aria-selected="true"]').dataset.tab;
  if (name === current) return;
  if (current === "settings") await revertLanguagePreview();
  if (name === "settings") openSetup("settings");
  else if (name === "analysis") openAnalysis();
  else if (name === "explore") openExplore();
  else if (name === "suggest") openSuggest();
  else goMods();
}

/* ================================================================ perfiles */

const LAUNCHER_LABEL = { official: "profile.launcher_official", curseforge: "profile.launcher_curseforge",
  prism: "profile.launcher_prism", multimc: "profile.launcher_multimc", modrinth: "profile.launcher_modrinth" };

function envText(p) {
  const loader = (state.loaders.find(l => l.value === p.loader) || {}).label || p.loader;
  return p.minecraft_version && loader ? `${loader} ${p.minecraft_version}` : t("profile.env_unknown");
}

function renderProfileSelect(screen) {
  const list = state.profiles || [];
  const hide = !list.length || (screen === "setup" && setupMode === "setup") || screen === "apply" || screen === "scan";
  $("#profile-slot").hidden = hide;
  if (hide) return;
  $("#profile-select").innerHTML = list.map(p =>
    `<option value="${esc(p.id)}"${p.active ? " selected" : ""}>${esc(p.name)}${p.exists ? "" : esc(t("profile.missing_suffix"))}</option>`).join("");
}

async function switchProfile(id) {
  const res = await api().profile_switch(id);
  if (!res.ok) { $("#prof-help").className = "help bad"; $("#prof-help").textContent = res.message; renderProfileSelect(); return; }
  setState(res.state);
  // Lo revisado, analizado y buscado era del perfil anterior.
  DATA = null; MODS = []; modsScreen = null; anSelected = null;
  EX.cards = []; EX.started = false; BASKET.clear(); renderBasket();
  $("#ex-results").innerHTML = ""; $("#ex-status").textContent = ""; $("#ex-more").hidden = true;
  SG = { loaded: false, result: null };
  startScan();
}

function setState(next) {
  state = { ...state, ...next };
}

function renderProfiles(help = "") {
  const list = state.profiles || [];
  $("#prof-list").innerHTML = list.map(p => `<li data-prof="${esc(p.id)}">
      <div class="prof-info">
        <span class="prof-name"><span class="prof-label">${esc(p.name)}</span>
          ${p.active ? `<span class="prof-tag">${esc(t("profile.active"))}</span>` : ""}
          ${p.exists ? "" : `<span class="prof-tag bad">${esc(t("profile.missing"))}</span>`}</span>
        <span class="prof-meta" title="${esc(p.mods_dir)}">${esc(envText(p))} · ${esc(p.mods_dir)}</span>
      </div>
      <div class="prof-actions">
        ${p.active ? "" : `<button class="btn-small" type="button" data-prof-use>${esc(t("profile.use"))}</button>`}
        <button class="btn-small" type="button" data-prof-rename>${esc(t("profile.rename"))}</button>
        ${list.length > 1 ? `<button class="btn-small" type="button" data-prof-remove>${esc(t("profile.remove"))}</button>` : ""}
      </div>
    </li>`).join("");
  const others = list.filter(p => !p.active);
  $("#ml-compare-row").hidden = !others.length;
  $("#ml-compare-with").innerHTML = others.map(p => `<option value="${esc(p.id)}">${esc(t("ml.compare_option", { name: p.name }))}</option>`).join("");
  const dup = state.same_folder || [];
  $("#prof-warn").hidden = !dup.length;
  $("#prof-warn").textContent = dup.map(names => t("profile.same_folder", { names: joinList(names) })).join(" ");
  $("#prof-help").className = "help";
  $("#prof-help").textContent = help;
}

async function addProfile(data) {
  const res = await api().profile_add(data);
  if (!res.ok) { $("#prof-help").className = "help bad"; $("#prof-help").textContent = res.message; return; }
  setState(res.state);
  renderProfileSelect("setup");
  $("#prof-found").innerHTML = "";
  renderProfiles(t("profile.added", { name: (res.state.profiles.find(p => p.id === res.id) || {}).name || "" }));
}

function wireProfiles() {
  $("#profile-select").addEventListener("change", e => switchProfile(e.target.value));
  $("#prof-list").addEventListener("click", async e => {
    const li = e.target.closest("[data-prof]");
    if (!li) return;
    const id = li.dataset.prof;
    if (e.target.closest("[data-prof-use]")) { switchProfile(id); return; }
    const rm = e.target.closest("[data-prof-remove]");
    if (rm) {
      if (!rm.dataset.confirm) { rm.dataset.confirm = "1"; rm.textContent = t("profile.remove_confirm"); rm.classList.add("danger"); return; }
      const res = await api().profile_remove(id);
      if (!res.ok) { $("#prof-help").className = "help bad"; $("#prof-help").textContent = res.message; return; }
      setState(res.state);
      if (res.switched) { switchProfile(res.state.settings.active_profile); return; }
      renderProfiles();
      renderProfileSelect("setup");
      return;
    }
    if (e.target.closest("[data-prof-rename]")) {
      const label = li.querySelector(".prof-label");
      const current = label.textContent;
      label.innerHTML = `<input class="prof-rename" maxlength="60" aria-label="${esc(t("profile.name_label"))}" value="${esc(current)}">`;
      const input = label.querySelector("input");
      input.focus(); input.select();
      let done = false;  // al volver a pintar se pierde el foco (blur): no guardar dos veces ni al cancelar
      const save = async () => {
        if (done) return;
        done = true;
        const res = await api().profile_rename(id, input.value);
        if (res.ok) setState(res.state);
        renderProfiles();
        renderProfileSelect("setup");
      };
      input.addEventListener("keydown", ev => {
        if (ev.key === "Enter") { ev.preventDefault(); save(); }
        if (ev.key === "Escape") { ev.preventDefault(); done = true; renderProfiles(); }
      });
      input.addEventListener("blur", save, { once: true });
    }
  });
  $("#prof-detect").addEventListener("click", async () => {
    $("#prof-help").className = "help"; $("#prof-help").textContent = t("profile.detecting");
    const found = await api().profile_detect();
    $("#prof-help").textContent = found.length ? "" : t("profile.detect_none");
    $("#prof-found").innerHTML = found.map((f, i) => `<li>
        <div class="prof-info"><span class="prof-name">${esc(f.name)} <span class="prof-tag">${esc(t(LAUNCHER_LABEL[f.launcher] || "profile.launcher_official"))}</span></span>
          <span class="prof-meta" title="${esc(f.mods_dir)}">${esc(envText(f))} · ${esc(f.mods_dir)}</span></div>
        <div class="prof-actions"><button class="btn-small" type="button" data-found="${i}">${esc(t("profile.add"))}</button></div>
      </li>`).join("");
    $("#prof-found").onclick = e => {
      const b = e.target.closest("[data-found]");
      if (b) addProfile(found[Number(b.dataset.found)]);
    };
  });
  $("#prof-folder").addEventListener("click", async () => {
    const res = await api().choose_folder();
    if (res) addProfile({ mods_dir: res.path });
  });
}

/* ================================================================ lista de mods */

function mlHelp(text, bad = false) {
  $("#ml-help").className = `help${bad ? " bad" : ""}`;
  $("#ml-help").textContent = text;
}

function startApplyRows(rows) {
  APPLY = rows.map(r => ({ ...r, state: "queued", message: "" }));
  $("#apply-label").textContent = t("ui.apply_count", { done: 0, count: APPLY.length });
  $("#apply-bar > span").style.width = "0%";
  renderApply();
  show("apply");
}

async function exportList(kind) {
  mlHelp(t("ex.loading"));
  const res = await api().modlist_export(kind);
  if (res.cancelled) { mlHelp(""); return; }
  if (!res.ok) { mlHelp(res.message, true); return; }
  const parts = [t("ml.saved", { file: res.file })];
  if (res.excluded.length) parts.push(t("ml.excluded", { count: res.excluded.length, names: joinList(res.excluded) }));
  if (res.no_loader_version) parts.push(t("ml.no_loader_version"));
  mlHelp(parts.join(" "));
}

async function importList() {
  mlHelp(t("ex.loading"));
  const res = await api().modlist_import();
  if (res.cancelled) { mlHelp(""); return; }
  if (!res.ok) { mlHelp(res.message, true); return; }
  mlHelp("");
  openExDrawer(t("ml.import_title"), res.file);
  const li = (name, extra = "") => `<li><span class="an-name">${esc(name)}${extra ? `<span class="an-note">${esc(extra)}</span>` : ""}</span></li>`;
  const list = (title, items) => items.length ? `<h3 class="ex-h">${esc(title)}</h3><ul class="an-list">${items.join("")}</ul>` : "";
  const warn = res.mismatch ? `<p class="ex-note warn">${esc(t("ml.mismatch", { file_mc: res.mismatch.minecraft, file_loader: res.mismatch.loader,
    mc: res.profile.minecraft, loader: res.profile.loader }))}</p>` : "";
  $("#ex-d-body").innerHTML = warn
    + list(t("ml.will_add", { count: res.add.length }), res.add.map(m => li(m.name, m.version || "")))
    + list(t("ml.will_change", { count: res.update.length }), res.update.map(m => li(m.name, `${m.have || "?"} → ${m.version || "?"}`)))
    + list(t("ml.unavailable", { count: res.unavailable.length }), res.unavailable.map(m => li(m.name, t("ml.unavailable_hint"))))
    + (res.remove.length ? `<h3 class="ex-h">${esc(t("ml.extra", { count: res.remove.length }))}</h3>
        <label class="toggle"><input type="checkbox" id="ml-remove"> <span>${esc(t("ml.remove_too"))}</span></label>
        <ul class="an-list">${res.remove.map(r => li(r.name, r.version || "")).join("")}</ul>` : "")
    + list(t("deps.kept_title"), (res.kept || []).map(k => li(k)))
    + `<p class="an-hint">${esc(t("ml.same", { count: res.same }))} ${esc(t("ex.safe"))}</p>`;
  const actionable = res.add.length + res.update.length + res.remove.length;
  $("#ex-d-foot").innerHTML = actionable ? `<button class="btn-secondary" type="button" id="ml-cancel">${esc(t("ui.cancel"))}</button>
      <button class="btn-primary" type="button" id="ml-apply">${esc(t("ml.apply"))}</button>` : "";
  if (!actionable) return;
  $("#ml-cancel").addEventListener("click", closeExDrawer);
  $("#ml-apply").addEventListener("click", async () => {
    const remove = !!($("#ml-remove") && $("#ml-remove").checked);
    const go = await api().modlist_import_start(remove);
    if (!go.ok) { $("#ex-d-body").insertAdjacentHTML("afterbegin", `<p class="cl-error">${esc(go.message)}</p>`); return; }
    closeExDrawer();
    if (go.manual.length) mlHelp(t("ml.manual", { names: joinList(go.manual.map(m => m.name)) }));
    startApplyRows(go.rows);
  });
}

async function compareProfiles() {
  const res = await api().compare_profiles($("#ml-compare-with").value);
  if (!res.ok) { mlHelp(res.message, true); return; }
  openExDrawer(t("ml.compare_title", { a: res.a, b: res.b }), t("ml.same", { count: res.same }));
  const list = (title, items) => `<h3 class="ex-h">${esc(title)}</h3>` + (items.length
    ? `<ul class="an-list">${items.map(n => `<li><span class="an-name">${esc(n)}</span></li>`).join("")}</ul>`
    : `<p class="an-hint">${esc(t("ml.none"))}</p>`);
  $("#ex-d-body").innerHTML = list(t("ml.only_in", { name: res.a, count: res.only_a.length }), res.only_a)
    + list(t("ml.only_in", { name: res.b, count: res.only_b.length }), res.only_b)
    + list(t("ml.different", { count: res.different.length }), res.different);
}

async function copyList() {
  const res = await api().copy_list();
  if (res.ok) { mlHelp(t("ml.copied", { count: res.count })); return; }
  if (res.text && navigator.clipboard) {
    try { await navigator.clipboard.writeText(res.text); mlHelp(t("ml.copied", { count: res.text.split("\n").length })); return; } catch {}
  }
  mlHelp(res.message, true);
}

function wireModlist() {
  $("#ml-export").addEventListener("click", () => exportList("modlist"));
  $("#ml-mrpack").addEventListener("click", () => exportList("mrpack"));
  $("#ml-import").addEventListener("click", importList);
  $("#ml-copy").addEventListener("click", copyList);
  $("#ml-compare").addEventListener("click", compareProfiles);
}

/* ================================================================ explorar */

const BASKET = new Map();    // clave "fuente:id" -> tarjeta
let EX = { cards: [], page: 0, started: false, timer: null, seq: 0 };
const exKey = c => `${c.source}:${c.id}`;
const fmtCompact = n => new Intl.NumberFormat(LANG, { notation: "compact", maximumFractionDigits: 1 }).format(n);

function openExplore() {
  show("explore");
  if (!$("#ex-cat").options.length) {
    const cats = ["tecnologia", "magia", "aventura", "mundo", "mobs", "construccion", "almacenamiento", "comida",
      "mapas", "calidad_vida", "rendimiento", "librerias"];
    $("#ex-cat").innerHTML = `<option value="">${esc(t("ex.category_all"))}</option>`
      + cats.map(c => `<option value="${c}">${esc(t(`cat.${c}`))}</option>`).join("");
  }
  if (!EX.started) { EX.started = true; exSearch(0); }
}

function exOpts(page) {
  return { query: $("#ex-q").value, category: $("#ex-cat").value, sort: $("#ex-sort").value,
           hide_installed: $("#ex-hide").checked, page };
}

async function exSearch(page) {
  const seq = ++EX.seq;  // descartar respuestas de búsquedas anteriores
  $("#ex-status").textContent = t("ex.searching");
  $("#ex-more").hidden = true;
  const res = await api().explore_search(exOpts(page));
  if (seq !== EX.seq) return;
  if (!res.ok) { $("#ex-status").textContent = res.message; if (!page) $("#ex-results").innerHTML = ""; return; }
  $("#ex-deck").textContent = t("ex.deck", { loader: res.env.loader, version: res.env.minecraft_version });
  const seen = new Set(page ? EX.cards.map(exKey) : []);
  EX.cards = (page ? EX.cards : []).concat(res.cards.filter(c => !seen.has(exKey(c))));
  EX.page = page;
  $("#ex-status").textContent = EX.cards.length ? t("ex.count", { count: EX.cards.length }) : t("ex.none");
  $("#ex-more").hidden = !res.more;
  renderExplore();
}

function exCard(c, i) {
  const inBasket = BASKET.has(exKey(c));
  const action = c.installed ? `<span class="badge ok"><span class="dot" aria-hidden="true"></span>${esc(t("ex.installed"))}</span>`
    : c.manual ? `<a class="linkbtn" href="${esc(c.url)}" data-external>${esc(t("ex.manual"))}</a>`
    : `<button class="btn-small ex-add${inBasket ? " on" : ""}" type="button" data-ex-add="${i}" aria-pressed="${inBasket}">${esc(inBasket ? t("ex.in_basket") : t("ex.add"))}</button>`;
  const updated = c.updated ? fmtMonth(c.updated) : "";
  return `<article class="ex-card">
    ${c.icon ? `<img class="ex-icon" src="${esc(c.icon)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
             : `<span class="ex-icon mono" aria-hidden="true">${esc(c.name.charAt(0).toUpperCase())}</span>`}
    <div class="ex-main">
      <h3><button class="ex-name" type="button" data-ex-open="${i}">${esc(c.name)}</button></h3>
      <p class="ex-author">${esc(c.author ? t("ex.by", { author: c.author }) : "")}</p>
      <p class="ex-sum">${esc(c.summary)}</p>
      <p class="ex-meta">
        <span class="ex-cat">${catIcon(c.cat, 14)}${esc(t(`cat.${c.cat}`))}</span>
        <span>${esc(t("ex.downloads", { n: fmtCompact(c.downloads) }))}</span>
        ${updated ? `<span>${esc(t("ex.updated", { date: updated }))}</span>` : ""}
        <span>${esc(c.source === "curseforge" ? "CurseForge" : "Modrinth")}</span>
      </p>
    </div>
    <div class="ex-act">${action}</div>
  </article>`;
}

function renderExplore() {
  $("#ex-results").innerHTML = EX.cards.map(exCard).join("");
}

function toggleBasket(c) {
  const k = exKey(c);
  if (BASKET.has(k)) BASKET.delete(k); else BASKET.set(k, c);
  renderBasket();
  renderExplore();
}

function renderBasket() {
  $("#ex-basket").hidden = $("#screen-explore").hidden || !BASKET.size;
  $("#ex-basket-count").textContent = t("ex.basket_count", { count: BASKET.size });
  $("#ex-basket-list").innerHTML = [...BASKET.values()].map(c =>
    `<li>${esc(c.name)} <button class="ex-x" type="button" data-ex-remove="${esc(exKey(c))}" aria-label="${esc(t("ex.remove", { name: c.name }))}">×</button></li>`).join("");
  $("#ex-basket-go").textContent = t("ex.basket_go", { count: BASKET.size });
}

let exReturn = null;
let exSeqDrawer = 0;  // descarta respuestas de una petición anterior del panel de Explorar

function openExDrawer(title, sub, icon) {
  exSeqDrawer++;
  exReturn = document.activeElement;
  $("#ex-d-title").textContent = title;
  $("#ex-d-sub").textContent = sub || "";
  $("#ex-d-icon").hidden = !icon;
  $("#ex-d-icon").innerHTML = icon ? `<img src="${esc(icon)}" alt="" referrerpolicy="no-referrer">` : "";
  $("#ex-d-body").innerHTML = `<p class="cl-loading">${esc(t("ex.loading"))}</p>`;
  $("#ex-d-foot").innerHTML = "";
  $("#ex-backdrop").hidden = $("#ex-drawer").hidden = false;
  document.body.classList.add("drawer-open");
  $("#ex-d-close").focus();
}

function closeExDrawer() {
  if ($("#ex-drawer").hidden) return;
  $("#ex-backdrop").hidden = $("#ex-drawer").hidden = true;
  document.body.classList.remove("drawer-open");
  if (exReturn && document.contains(exReturn)) exReturn.focus();
}

async function openExDetail(c) {
  openExDrawer(c.name, c.author ? t("ex.by", { author: c.author }) : "", c.icon);
  const seq = exSeqDrawer;
  const d = await api().explore_detail(c.source, c.id);
  if ($("#ex-drawer").hidden || seq !== exSeqDrawer) return;
  if (!d.ok) { $("#ex-d-body").innerHTML = `<p class="cl-error">${esc(d.message)}</p>`; return; }
  const inst = d.install;
  const what = !inst ? `<p class="ex-note warn">${esc(t("ex.no_version"))}</p>`
    : `<p class="ex-note">${esc(t("ex.would_install", { version: inst.version, via: inst.via }))}${inst.beta ? ` <span class="beta">${esc(t("ui.beta"))}</span>` : ""}</p>`
      + (inst.manual ? `<p class="ex-note warn">${esc(t("ex.manual_hint"))}</p>` : "")
      + (inst.deps.length ? `<p class="ex-note">${esc(t("ex.needs"))} ${inst.deps.map(x =>
          `<span class="ex-dep">${esc(x.name)}${x.installed ? ` · ${esc(t("ex.dep_installed"))}` : ` · ${esc(t("ex.dep_added"))}`}</span>`).join(" ")}</p>` : "");
  const links = Object.entries(d.links || {}).filter(([, u]) => u)
    .map(([k, u]) => `<a href="${esc(u)}" data-external>${esc(t(`ex.link_${k}`))}</a>`).join(" · ");
  const imgs = d.images.length ? `<div class="ex-shots">${d.images.map(u => `<img src="${esc(u)}" alt="" loading="lazy" referrerpolicy="no-referrer">`).join("")}</div>` : "";
  $("#ex-d-body").innerHTML = `${what}${links ? `<p class="ex-links">${links}</p>` : ""}${imgs}
    ${d.html ? `<p class="ex-desc-label">${esc(t("ex.desc_label"))}</p><div class="cl-html">${d.html}</div>`
             : `<p class="cl-empty">${esc(t("ex.no_description"))}</p>`}`;
  const canAdd = !c.installed && !c.manual && inst && !inst.manual;
  $("#ex-d-foot").innerHTML = c.installed ? `<span class="badge ok"><span class="dot" aria-hidden="true"></span>${esc(t("ex.installed"))}</span>`
    : canAdd ? `<button class="btn-primary" type="button" id="ex-d-add">${esc(BASKET.has(exKey(c)) ? t("ex.in_basket") : t("ex.add"))}</button>`
    : "";
  const add = $("#ex-d-add");
  if (add) add.addEventListener("click", () => { toggleBasket(c); add.textContent = BASKET.has(exKey(c)) ? t("ex.in_basket") : t("ex.add"); });
}

async function reviewBasket() {
  openExDrawer(t("ex.review_title"), t("ex.basket_count", { count: BASKET.size }));
  const seq = exSeqDrawer;
  const res = await api().install_plan([...BASKET.values()].map(c => ({ source: c.source, id: c.id, name: c.name })));
  // Tras instalar, la próxima visita a Explorar vuelve a buscar ("Ya instalado" cambia).
  if (seq === exSeqDrawer) renderPlanReview(res, () => { BASKET.clear(); renderBasket(); EX.started = false; });
}

// Revisión antes de instalar/quitar (la usan la cesta de Explorar y las Sugerencias).
function renderPlanReview(res, onStart) {
  if ($("#ex-drawer").hidden) return;
  if (!res.ok) { $("#ex-d-body").innerHTML = `<p class="cl-error">${esc(res.message)}</p>`; return; }
  const list = (title, items) => items.length ? `<h3 class="ex-h">${esc(title)}</h3><ul class="an-list">${items.join("")}</ul>` : "";
  const li = (name, extra = "") => `<li><span class="an-name">${esc(name)}${extra ? `<span class="an-note">${esc(extra)}</span>` : ""}</span></li>`;
  const installs = res.rows.filter(r => r.s !== "rm");
  const mine = installs.filter(r => !r.neededBy.length), deps = installs.filter(r => r.neededBy.length);
  const removals = res.rows.filter(r => r.s === "rm");
  const ver = r => [r.to, r.size ? fmtSize(r.size) : ""].filter(Boolean).join(" · ");
  $("#ex-d-body").innerHTML = (res.overlaps || []).map(o => `<p class="ex-note warn">${esc(o)}</p>`).join("")
    + list(t("ex.will_install"), mine.map(r => li(r.name, ver(r))))
    + list(t("ex.will_add_deps"), deps.map(r => li(r.name, `${ver(r)} · ${t("ui.needed_by", { names: r.neededBy.join(", ") })}`)))
    + (installs.length && res.size ? `<p class="ex-total">${esc(t("ex.total_size", { size: fmtSize(res.size), count: installs.length }))}</p>` : "")
    + list(t("sg.will_remove"), removals.map(r => li(r.name, r.from || "")))
    + list(t("deps.kept_title"), (res.kept || []).map(k => li(k)))
    + list(t("ex.cant_manual"), res.manual.map(m => `<li><span class="an-name"><a href="${esc(m.url)}" data-external>${esc(m.name)}</a></span></li>`))
    + list(t("ex.cant_blocked"), res.blocked.map(b => li(b.name, b.reason)))
    + list(t("ex.cant_unavailable"), res.unavailable.map(n => li(n)))
    + list(t("ex.already"), res.already.map(n => li(n)))
    + `<p class="an-hint">${esc(t("ex.safe"))}</p>`;
  $("#ex-d-foot").innerHTML = res.rows.length
    ? `<button class="btn-secondary" type="button" id="ex-d-cancel">${esc(t("ui.cancel"))}</button>
       <button class="btn-primary" type="button" id="ex-d-install">${esc(t("sg.apply_n", { count: res.rows.length }))}</button>` : "";
  if (!res.rows.length) return;
  $("#ex-d-cancel").addEventListener("click", closeExDrawer);
  $("#ex-d-install").addEventListener("click", async () => {
    const go = await api().install_start();
    if (!go.ok) { $("#ex-d-body").insertAdjacentHTML("afterbegin", `<p class="cl-error">${esc(go.message)}</p>`); return; }
    closeExDrawer();
    if (onStart) onStart();
    startApplyRows(res.rows);
  });
}

/* ================================================================ sugerencias */

const SG_QUESTIONS = [
  { key: "players", type: "radio", options: ["solo", "amigos", "servidor"] },
  { key: "styles", type: "checkbox", options: ["tecnologia", "magia", "exploracion", "construir", "granjas", "combate", "tranquilo"] },
  { key: "difficulty", type: "radio", options: ["relajada", "normal", "reto"] },
  { key: "pc", type: "radio", options: ["justo", "normal", "potente"] },
  { key: "max", type: "radio", options: ["0", "50", "100", "150"] },
];
const SG_ICON = { tecnologia: "tecnologia", magia: "magia", exploracion: "aventura", construir: "construccion",
  granjas: "comida", combate: "mobs", tranquilo: "calidad_vida" };
let SG = { loaded: false, result: null };

async function openSuggest() {
  show("suggest");
  if (!SG.loaded) {
    $("#sg-results").hidden = true;
    SG.loaded = true;
    renderSuggestForm(await api().suggest_answers());
  }
}

function renderSuggestForm(saved) {
  const defaults = { players: "solo", styles: [], difficulty: "normal", pc: "normal", max: 0 };
  const a = { ...defaults, ...(saved || {}) };
  $("#sg-questions").innerHTML = SG_QUESTIONS.map((q, qi) => `<fieldset class="sg-q">
      <legend><span class="sg-num">${qi + 1}</span>${esc(t(`sg.q_${q.key}`))}</legend>
      <div class="sg-options${q.key === "styles" ? " wide" : ""}">${q.options.map(o => {
        const checked = q.type === "checkbox" ? a.styles.includes(o) : String(a[q.key]) === o;
        const icon = SG_ICON[o] ? catIcon(SG_ICON[o], 22) : "";
        return `<label class="sg-card"><input type="${q.type}" name="sg-${q.key}" value="${esc(o)}"${checked ? " checked" : ""}>
          ${icon}<span>${esc(t(`sg.${q.key}_${o}`))}</span></label>`;
      }).join("")}</div>
    </fieldset>`).join("");
  $("#sg-form").hidden = false;
  $("#sg-results").hidden = true;
}

function readAnswers() {
  const val = k => (document.querySelector(`input[name="sg-${k}"]:checked`) || {}).value;
  return { players: val("players"), difficulty: val("difficulty"), pc: val("pc"), max: Number(val("max") || 0),
           styles: [...document.querySelectorAll('input[name="sg-styles"]:checked')].map(i => i.value) };
}

async function runSuggest() {
  const btn = $("#sg-go");
  btn.disabled = true;
  $("#sg-status").textContent = t("sg.thinking");
  const res = await api().suggest_run(readAnswers());
  btn.disabled = false;
  $("#sg-status").textContent = res.ok ? "" : res.message;
  if (!res.ok) return;
  SG.result = res;
  renderSuggestResults(res);
}

function renderSuggestResults(r) {
  const col = (kind, items, checkable) => `<section class="panel sg-col">
      <h3>${esc(t(`sg.col_${kind}`))} <span class="sg-count">${items.length}</span></h3>
      <p class="an-hint">${esc(t(`sg.col_${kind}_hint`))}</p>
      ${items.length ? `<ul class="sg-list">${items.map((it, i) => `<li>
          ${checkable ? `<input class="check" type="checkbox" id="sg-${kind}-${i}" data-sg="${kind}" data-i="${i}">` : ""}
          <label${checkable ? ` for="sg-${kind}-${i}"` : ""}><span class="sg-name">${esc(it.name)}</span>
            <span class="sg-why">${esc(it.reason)}</span>${it.note ? `<span class="sg-note">${esc(it.note)}</span>` : ""}</label></li>`).join("")}</ul>`
        : `<p class="an-hint">${esc(t("sg.none"))}</p>`}
    </section>`;
  $("#sg-cols").innerHTML = col("remove", r.remove, true) + col("review", r.review, true)
    + col("keep", r.keep, false) + col("add", r.add, true);
  $("#sg-unchanged").hidden = !r.unchanged.length;
  $("#sg-unchanged-title").textContent = t("sg.unchanged", { count: r.unchanged.length });
  $("#sg-unchanged-list").textContent = r.unchanged.join(" · ");
  $("#sg-limit").hidden = !r.over_limit;
  $("#sg-limit").textContent = t("sg.over_limit", { count: r.over_limit, max: r.answers.max });
  $("#sg-form").hidden = true;
  $("#sg-results").hidden = false;
  updateSuggestApply();
  window.scrollTo(0, 0);
}

function updateSuggestApply() {
  const n = document.querySelectorAll("#sg-cols input[data-sg]:checked").length;
  $("#sg-apply").disabled = !n;
  $("#sg-apply").textContent = t("sg.apply_marked", { count: n });
}

async function applySuggestions() {
  if (!SG.result) return;
  const marked = [...document.querySelectorAll("#sg-cols input[data-sg]:checked")];
  const sel = { remove: [], add: [] };
  for (const c of marked) {
    const item = SG.result[c.dataset.sg][Number(c.dataset.i)];
    if (c.dataset.sg === "remove" || c.dataset.sg === "review") sel.remove.push(item.file);
    else sel.add.push({ source: item.source, id: item.id, name: item.name });
  }
  openExDrawer(t("sg.review_title"), t("sg.apply_marked", { count: marked.length }));
  const seq = exSeqDrawer;
  const plan = await api().suggest_plan(sel);
  if (seq === exSeqDrawer) renderPlanReview(plan, () => { SG = { loaded: false, result: null }; });
}

function wireSuggest() {
  $("#sg-go").addEventListener("click", runSuggest);
  $("#sg-edit").addEventListener("click", () => { $("#sg-form").hidden = false; $("#sg-results").hidden = true; });
  $("#sg-cols").addEventListener("change", updateSuggestApply);
  $("#sg-apply").addEventListener("click", applySuggestions);
}

function wireExplore() {
  $("#ex-q").addEventListener("input", () => { clearTimeout(EX.timer); EX.timer = setTimeout(() => exSearch(0), 400); });
  for (const id of ["#ex-cat", "#ex-sort", "#ex-hide"]) $(id).addEventListener("change", () => exSearch(0));
  $("#ex-more").addEventListener("click", () => exSearch(EX.page + 1));
  $("#ex-results").addEventListener("click", e => {
    const add = e.target.closest("[data-ex-add]");
    const card = el => EX.cards[Number(el.dataset.exAdd ?? el.dataset.exOpen)];
    if (add) { if (card(add)) toggleBasket(card(add)); return; }
    const open = e.target.closest("[data-ex-open]");
    if (open && card(open)) openExDetail(card(open));
  });
  $("#ex-basket-list").addEventListener("click", e => {
    const x = e.target.closest("[data-ex-remove]");
    if (x) { BASKET.delete(x.dataset.exRemove); renderBasket(); renderExplore(); }
  });
  $("#ex-basket-clear").addEventListener("click", () => { BASKET.clear(); renderBasket(); renderExplore(); });
  $("#ex-basket-go").addEventListener("click", reviewBasket);
  $("#ex-d-close").addEventListener("click", closeExDrawer);
  $("#ex-backdrop").addEventListener("click", closeExDrawer);
  $("#ex-drawer").addEventListener("keydown", e => {
    if (e.key === "Escape") { e.preventDefault(); closeExDrawer(); return; }
    if (e.key !== "Tab") return;
    const items = [...$("#ex-drawer").querySelectorAll("button, a[href], [tabindex]:not([tabindex='-1'])")];
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
}

/* ================================================================ análisis */

let anLibs = false;       // interruptor "Incluir librerías"
let anSelected = null;    // categoría cuya lista de mods se muestra
let anData = null;

function fmtSize(bytes) {
  const mb = bytes / 1e6;
  return t("an.mb", { value: new Intl.NumberFormat(LANG, { maximumFractionDigits: mb < 100 ? 1 : 0 }).format(mb) });
}

function fmtMonth(iso) {
  try { return new Date(iso).toLocaleDateString(LANG, { year: "numeric", month: "short" }); } catch { return iso; }
}

async function openAnalysis() {
  show("analysis");
  renderAnalysis(await api().analysis(anLibs));
}

function anCard(label, value, sub = "") {
  return `<div class="an-card"><span class="an-card-label">${esc(label)}</span>
    <span class="an-card-value">${esc(value)}</span>${sub ? `<span class="an-card-sub">${esc(sub)}</span>` : ""}</div>`;
}

function renderAnalysis(d) {
  const ready = !!(d && d.ready && d.totals.mods > 0);
  $("#an-title").textContent = ready ? t("an.title") : t("an.empty_title");
  $("#an-deck").textContent = ready ? t("an.deck") : t("an.empty_deck");
  $("#an-empty").hidden = ready;
  $("#an-body").hidden = !ready;
  if (!ready) return;
  anData = d;
  const T = d.totals;
  if (T.disabled) $("#an-deck").textContent = `${t("an.deck")} ${t("an.disabled", { count: T.disabled })}`;

  $("#an-cards").innerHTML = [
    anCard(t("an.card_total"), t("an.files", { count: T.mods }),
      t("an.total_sub", { mods: T.mods - T.libraries, libs: T.libraries })),
    anCard(t("an.card_size"), fmtSize(T.size)),
    anCard(t("an.card_status"), T.up_to_date, t("an.card_updates", { count: T.updates })),
    anCard(t("an.card_sources"), T.sources.curseforge + T.sources.modrinth,
      T.sources.none ? t("an.sources_sub_none", { cf: T.sources.curseforge, mr: T.sources.modrinth, none: T.sources.none })
                     : t("an.sources_sub", { cf: T.sources.curseforge, mr: T.sources.modrinth })),
  ].join("");

  const bars = d.by_category.map(b => ({
    id: b.cat, count: b.count, mods: b.mods,
    name: t(`cat.${b.cat}`), short: t(`cat_short.${b.cat}`), icon: catIcon(b.cat, 26),
  }));
  if (!bars.some(b => b.id === anSelected)) anSelected = bars.length ? bars[0].id : null;
  renderBlockChart($("#an-chart"), bars, {
    selected: anSelected, onSelect: selectCategory,
    label: b => t("an.col_label", { count: b.count, name: b.name }),
  });
  selectCategory(anSelected);

  $("#an-table-body").innerHTML = bars.map(b =>
    `<tr><th scope="row">${esc(b.name)}</th><td>${b.count}</td><td>${esc(b.mods.join(", "))}</td></tr>`).join("");

  $("#an-heavy").innerHTML = d.heaviest.map(h =>
    `<li><span class="an-name">${esc(h.name)}</span><span class="an-num">${esc(fmtSize(h.size))}</span></li>`).join("");

  const sideMax = Math.max(1, ...Object.values(d.sides));
  $("#an-sides").innerHTML = ["client", "server", "both", "unknown"].map(k =>
    `<li><span class="an-name">${esc(t(`an.side_${k}`))}</span>
       <span class="an-meter" aria-hidden="true"><span style="width:${(d.sides[k] / sideMax) * 100}%"></span></span>
       <span class="an-num">${d.sides[k]}</span></li>`).join("");

  const staleRows = list => list.map(s => `<li><span class="an-name">${s.url
      ? `<a href="${esc(s.url)}" data-external>${esc(s.name)}</a>` : esc(s.name)}</span>
      <span class="an-num">${esc(fmtMonth(s.date))}</span></li>`).join("");
  const version = d.game_version || "";
  const { abandoned, no_version: noVersion } = d.stale;
  $("#an-stale").innerHTML = !abandoned.length && !noVersion.length
    ? `<p class="an-hint">${esc(t("an.stale_none"))}</p>`
    : [abandoned.length ? `<h4 class="an-sub">${esc(t("an.abandoned", { count: abandoned.length }))}</h4>
         <p class="an-hint">${esc(t("an.abandoned_hint"))}</p><ul class="an-list">${staleRows(abandoned)}</ul>` : "",
       noVersion.length ? `<h4 class="an-sub">${esc(t("an.no_version", { count: noVersion.length, version }))}</h4>
         <p class="an-hint">${esc(t("an.no_version_hint", { version }))}</p><ul class="an-list">${staleRows(noVersion)}</ul>` : "",
      ].join("");

  $("#an-orphans").innerHTML = d.orphans.length
    ? d.orphans.map(o => {
        const note = o.needed_by_orphans.length ? t("an.orphan_chain", { names: o.needed_by_orphans.join(", ") })
          : o.optional_by.length ? t("an.orphan_optional", { names: o.optional_by.join(", ") }) : "";
        return `<li><span class="an-name">${esc(o.name)}${note ? `<span class="an-note">${esc(note)}</span>` : ""}</span>
          <span class="an-num">${esc(fmtSize(o.size))}</span></li>`;
      }).join("")
    : `<li class="an-none">${esc(t("an.orphans_none"))}</li>`;
}

function selectCategory(id) {
  anSelected = id;
  for (const btn of document.querySelectorAll("#an-chart .block-btn")) {
    const on = btn.dataset.cat === id;
    btn.classList.toggle("on", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  }
  const bar = anData && anData.by_category.find(b => b.cat === id);
  $("#an-detail").innerHTML = bar
    ? `<h4>${catIcon(id, 22)}<span>${esc(t("an.detail_title", { count: bar.count, name: t(`cat.${id}`) }))}</span></h4>
       <ul class="an-chips">${bar.mods.map(m => `<li>${esc(m)}</li>`).join("")}</ul>`
    : "";
}

function wireAnalysis() {
  $("#an-go-scan").addEventListener("click", startScan);
  $("#an-libs").addEventListener("change", async e => {
    anLibs = e.target.checked;
    renderAnalysis(await api().analysis(anLibs));
  });
  $("#an-table-btn").addEventListener("click", () => {
    const table = $("#an-table"), btn = $("#an-table-btn");
    const showTable = table.classList.contains("sr-only");
    table.classList.toggle("sr-only", !showTable);
    $("#an-chart").hidden = $("#an-detail").hidden = showTable;
    btn.setAttribute("aria-expanded", String(showTable));
    btn.textContent = showTable ? t("an.as_chart") : t("an.as_table");
  });
}

function wireTabs() {
  const tabs = [...document.querySelectorAll("#tabs [role=tab]")];
  for (const tab of tabs) tab.addEventListener("click", () => openTab(tab.dataset.tab));
  $("#tabs").addEventListener("keydown", e => {
    // Teclado: flechas, Inicio y Fin mueven el foco y abren la sección (patrón de pestañas).
    const i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    const tab = tabs[(next + tabs.length) % tabs.length];
    tab.focus();
    openTab(tab.dataset.tab);
  });
}

function wirePick() {
  $("#btn-pick").addEventListener("click", () => (picking ? endPicking() : startPicking()));
  $("#pick-cancel").addEventListener("click", endPicking);
  $("#pick-enable").addEventListener("click", () => pickApply(true));
  $("#pick-disable").addEventListener("click", () => pickApply(false));
}

function wire() {
  wirePick();
  wireTabs();
  wireSuggest();
  wireModlist();
  wireProfiles();
  wireExplore();
  wireChangelog();
  wireAnalysis();
  $("#q").addEventListener("input", e => { query = e.target.value.trim().toLowerCase(); render(); });
  $("#btn-rescan").addEventListener("click", startScan);
  $("#btn-retry").addEventListener("click", startScan);
  $("#btn-recheck").addEventListener("click", startScan);
  $("#btn-cancel-settings").addEventListener("click", leaveSettings);
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

/* ================================================================ nuevas versiones de la app */

async function checkAppUpdate() {
  const info = await api().app_update();
  const pill = $("#app-update");
  pill.hidden = !info;
  if (!info) return;
  pill.innerHTML = `<span class="long">${esc(t("up.pill", { version: info.version }))}</span>`
    + `<span class="short">${esc(t("up.pill_short", { version: info.version }))}</span>`;
  pill.title = t("up.pill", { version: info.version });
  pill.onclick = () => {
    openExDrawer(t("up.title", { version: info.version }), t("up.sub"));
    $("#ex-d-body").innerHTML = `<p class="ex-note">${esc(t("up.sha_hint"))}</p>`
      + (info.notes_html ? `<div class="cl-html">${info.notes_html}</div>` : "");
    $("#ex-d-foot").innerHTML = `<button class="btn-primary" type="button" id="up-download">${esc(t("up.download"))}</button>`;
    $("#up-download").addEventListener("click", () => api().open_url(info.url));
  };
}

async function boot() {
  wire();
  wireRecover();
  state = await api().get_state();
  applyStrings(state.lang, state.strings);
  if (state.settings.setup_done) checkAppUpdate();  // en segundo plano; sin red no molesta
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

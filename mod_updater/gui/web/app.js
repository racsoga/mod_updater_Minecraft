/* Mod Updater: interfaz. Habla con Python vía window.pywebview.api (ver gui/api.py).
   Python avisa con window.onBackend(evento, datos). */
"use strict";

const $ = sel => document.querySelector(sel);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const plural = (n, one, many) => (n === 1 ? one : many);
const joinList = names => names.length < 2 ? names.join("") : names.slice(0, -1).join(", ") + " y " + names.at(-1);
const api = () => window.pywebview.api;

let state = null;          // get_state() de Python
let setupMode = "setup";   // "setup" (primera vez) o "settings"
let pendingFolder = null;  // carpeta elegida y aún no guardada

/* ================================================================ pantallas */

function show(screen) {
  for (const s of ["setup", "scan", "results"]) $(`#screen-${s}`).hidden = s !== screen;
  const inApp = screen !== "setup" || setupMode === "settings";
  $("#btn-settings").hidden = screen === "setup";
  $("#btn-rescan").hidden = screen !== "results";
  $("#actionbar").hidden = screen !== "results";
  $("#chip-folder").hidden = $("#chip-env").hidden = !inApp || screen === "setup";
  window.scrollTo(0, 0);
}

function setTopbarEnv(env) {
  if (!env) return;
  $("#chip-folder").innerHTML = `Carpeta <strong>${esc(shortPath(env.mods_dir))}</strong>`;
  $("#chip-folder").title = env.mods_dir;
  $("#chip-env").innerHTML = `${esc(env.loader)} <strong>${esc(env.minecraft_version)}</strong>`;
}

function shortPath(p) {
  const parts = String(p).split(/[\\/]/).filter(Boolean);
  return parts.length > 2 ? parts.slice(-2).join("\\") : p;
}

/* ================================================================ bienvenida / ajustes */

function folderHelp(folder) {
  const help = $("#folder-help");
  help.className = "help";
  if (!folder.exists) {
    help.textContent = "No encuentro esta carpeta. Elige la carpeta mods de tu Minecraft.";
    help.classList.add("bad");
  } else if (!folder.jars) {
    help.textContent = "La carpeta existe pero no tiene archivos .jar.";
    help.classList.add("bad");
  } else {
    help.textContent = `${folder.jars} ${plural(folder.jars, "mod encontrado", "mods encontrados")}.`;
  }
}

function envHelp(folder) {
  const v = $("#mc-version").value.trim(), l = $("#loader").value;
  const detected = folder.minecraft_version && folder.loader;
  $("#env-help").textContent = !detected ? "No se ha podido deducir de tus mods: revisa que sea correcto."
    : folder.minecraft_version === v && folder.loader === l ? "Deducido de tus mods."
    : `Tus mods parecen de ${labelLoader(folder.loader)} ${folder.minecraft_version}.`;
}

const labelLoader = v => (state.loaders.find(l => l.value === v) || { label: v }).label;

function openSetup(mode) {
  setupMode = mode;
  pendingFolder = null;
  const s = state.settings, folder = state.folder;
  const first = mode === "setup";
  $("#setup-title").textContent = first ? "Vamos a revisar tus mods." : "Ajustes";
  $("#setup-deck").textContent = first
    ? "Dinos dónde están y, si quieres, tu key de CurseForge. No se cambia nada hasta que tú lo confirmes."
    : "Los cambios se aplican en la próxima revisión.";
  $("#folder-path").textContent = s.mods_dir;
  folderHelp(folder);

  $("#loader").innerHTML = state.loaders.map(l => `<option value="${esc(l.value)}">${esc(l.label)}</option>`).join("");
  // Primera vez: proponer lo deducido de los mods. Después: lo guardado.
  $("#mc-version").value = (first && folder.minecraft_version) || s.minecraft_version;
  $("#loader").value = (first && folder.loader) || s.loader;
  envHelp(folder);

  const key = $("#cf-key");
  key.value = "";
  key.placeholder = state.has_key ? `Guardada: ${state.key_hint}. Pega otra para cambiarla` : "Pega aquí tu key";
  $("#btn-forget").hidden = state.key_source !== "keyring";
  $("#key-help").className = "help";
  $("#key-help").textContent = state.key_source === "env" ? "Usando la key del archivo .env (modo desarrollo)." : "";

  $("#advanced").hidden = first;
  $("#allow-beta").checked = !!s.allow_beta;
  $("#backups").value = s.backups_to_keep;
  $("#btn-nokey").hidden = $("#nokey-note").hidden = !first || state.has_key;
  $("#btn-cancel-settings").hidden = first;
  $("#btn-save").textContent = first ? "Revisar mis mods" : "Guardar y revisar";
  show("setup");
}

async function saveSetup(useCurseforge) {
  const btn = $("#btn-save");
  btn.disabled = true;
  for (const el of document.querySelectorAll("[aria-invalid]")) el.removeAttribute("aria-invalid");
  try {
    const res = await api().save_setup({
      mods_dir: pendingFolder || state.settings.mods_dir,
      minecraft_version: $("#mc-version").value.trim(),
      loader: $("#loader").value,
      key: $("#cf-key").value.trim(),
      use_curseforge: useCurseforge,
      allow_beta: $("#allow-beta").checked,
      backups_to_keep: Number($("#backups").value) || 1,
    });
    $("#cf-key").value = "";
    if (!res.ok) {
      const target = { mods_dir: "#folder-help", minecraft_version: "#env-help", loader: "#env-help" }[res.field] || "#folder-help";
      $(target).className = "help bad";
      $(target).textContent = res.message;
      if (res.field === "minecraft_version") $("#mc-version").setAttribute("aria-invalid", "true");
      return;
    }
    state = res.state;
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
  $("#scan-label").textContent = "Preparando…";
  setProgress(0);
  for (const li of document.querySelectorAll("#scan-steps li")) li.className = "";
  const cfStep = $('#scan-steps li[data-step="cf"]');
  cfStep.lastChild.textContent = state.has_key && state.settings.use_curseforge ? "Consultar CurseForge" : "Consultar CurseForge (sin key, se omite)";
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

const HELP = {
  up: "Hay una versión nueva compatible.",
  ok: "Ya tienes la última versión.",
  manual: "Hay versión nueva, pero no se puede descargar automáticamente. Abre su página para bajarla.",
  missing: "No está en CurseForge ni en Modrinth (un mod propio o bajado de otro sitio). Se deja como está.",
  dep: "No está en tu carpeta, pero otro mod la necesita para funcionar. Se instalará junto a las actualizaciones.",
};
const BADGE = { up: "Actualizable", ok: "Al día", manual: "Descarga manual", missing: "No encontrado", dep: "Nueva dependencia" };
const selectable = m => m.s === "up" || m.s === "dep";
const isAttention = m => m.s === "manual" || m.s === "missing";
const GROUPS = [
  { key: "attention", title: "Requieren atención", match: isAttention },
  { key: "updates", title: "Actualizaciones", match: selectable },
  { key: "ok", title: "Al día", match: m => m.s === "ok", collapsible: true },
];
const FILTERS = [
  { key: "all", label: "Todos", match: () => true },
  { key: "updates", label: "Actualizaciones", match: selectable },
  { key: "ok", label: "Al día", match: m => m.s === "ok" },
  { key: "attention", label: "Requieren atención", match: isAttention },
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
  const notes = [
    ...data.broken.map(t => ({ t: `Tu carpeta ya tiene un problema: ${t}`, bad: true })),
    ...data.notices.map(t => ({ t })),
    ...data.ignored.map(t => ({ t: `${t}.` })),
  ];
  $("#notices").innerHTML = notes.map(n => `<li class="${n.bad ? "bad" : ""}">${esc(n.t)}</li>`).join("");
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

function versions(m) {
  const beta = m.beta ? '<span class="tag">beta</span>' : "";
  if (m.s === "ok" || m.s === "missing") return `<div class="ver"><span class="new" title="${esc(m.from)}">${esc(m.from || "?")}</span>${m.s === "ok" ? beta : ""}</div>`;
  const from = m.from ? `<span class="old" title="${esc(m.from)}">${esc(m.from)}</span>` : `<span class="old">Sin instalar</span>`;
  return `<div class="ver">${from}${arrow}<span class="sr-only">a</span><span class="new" title="${esc(m.to)}">${esc(m.to || "")}</span>${beta}</div>`;
}

function sub(m) {
  if (m.s === "dep") {
    const broken = depsBrokenBy(m);
    if (broken.length) return `<div class="sub warn">Sin ${esc(m.name)}, ${esc(joinList(broken))} no arrancará.</div>`;
    return `<div class="sub">La necesita ${esc(joinList(m.neededBy))}</div>`;
  }
  return m.sub ? `<div class="sub" title="${esc(m.sub)}">${esc(m.sub)}</div>` : "";
}

function row(m) {
  const helpId = `help-${m.id}`;
  const cb = selectable(m)
    ? `<input class="check" type="checkbox" data-id="${m.id}" ${m.checked ? "checked" : ""} aria-label="${m.s === "dep" ? "Instalar" : "Actualizar"} ${esc(m.name)}" aria-describedby="${helpId}">`
    : `<span class="slot" aria-hidden="true"></span>`;
  const source = m.s === "manual" && m.url ? `<a href="${esc(m.url)}" data-external>Abrir página</a>` : esc(m.src);
  return `<div class="row ${m.s}">
    ${cb}${logo(m)}
    <div class="name"><div class="title">${esc(m.name)}</div>${sub(m)}</div>
    ${versions(m)}
    <span class="badge ${m.s}" data-tip="${esc(HELP[m.s])}"><span class="dot" aria-hidden="true"></span>${BADGE[m.s]}<span class="sr-only" id="${helpId}">. ${esc(HELP[m.s])}</span></span>
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
    return `<button type="button" data-f="${f.key}" aria-pressed="${f.key === filter}">${f.label} <span class="n">${n}</span></button>`;
  }).join("");

  let html = "";
  for (const g of GROUPS) {
    const items = MODS.filter(m => g.match(m) && visible(m));
    if (!items.length) continue;
    const forced = filter === "ok" || query;
    const open = !g.collapsible || okOpen || forced;
    let extra = "";
    if (g.key === "updates") {
      const n = items.filter(m => m.checked).length;
      extra = `<label class="master"><input class="check" type="checkbox" data-all ${n === items.length ? "checked" : ""}> Todas</label>`;
    } else if (g.collapsible && !forced) {
      extra = `<button class="linkbtn" type="button" data-ok aria-expanded="${okOpen}">${okOpen ? "Ocultar" : `Mostrar ${items.length}`}</button>`;
    }
    html += `<div class="group-head"><h3>${g.title}</h3><span class="count">${items.length}</span><span class="grow"></span>${extra}</div>`;
    if (open) html += items.map(row).join("");
  }
  $("#list").innerHTML = html ||
    `<div class="empty">Ningún mod coincide con “${esc(query)}”. <button class="linkbtn" type="button" data-clear>Borrar búsqueda</button></div>`;

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

  let head;
  if (!ups.length && !deps.length) head = "Todo está al día.";
  else {
    head = ups.length ? `${ups.length} ${plural(ups.length, "mod tiene", "mods tienen")} versión nueva` : "";
    if (deps.length) head += `${head ? " y " : ""}${plural(deps.length, "falta 1 dependencia", `faltan ${deps.length} dependencias`)}`;
    head = head.charAt(0).toUpperCase() + head.slice(1) + ".";
  }
  $("#headline").textContent = head;
  const depLines = deps.map(d => `${d.name} hace falta para ${joinList(d.neededBy)}.`).join(" ");
  $("#deck").innerHTML = `<b>${okN} ${plural(okN, "ya está al día.", "ya están al día.")}</b> `
    + (attN ? `${attN} ${plural(attN, "necesita", "necesitan")} que hagas algo. ` : "") + esc(depLines);

  const sel = MODS.filter(m => m.checked);
  const selUp = sel.filter(m => m.s === "up").length, selDep = sel.filter(m => m.s === "dep").length;
  const btn = $("#go");
  btn.disabled = sel.length === 0;
  btn.textContent = !ups.length && !deps.length ? "Nada que actualizar"
    : !sel.length ? "Elige algún mod"
    : selDep && selUp ? `Actualizar ${selUp} e instalar ${selDep}`
    : selDep ? `Instalar ${selDep} ${plural(selDep, "dependencia", "dependencias")}`
    : `Actualizar ${selUp} ${plural(selUp, "mod", "mods")}`;

  const broken = deps.flatMap(depsBrokenBy);
  const warn = broken.length
    ? `<span class="warn">Sin ${esc(joinList(deps.filter(d => !d.checked).map(d => d.name)))}, ${esc(joinList(broken))} no arrancará.</span>` : "";
  $("#summary").innerHTML = `<span class="count">${sel.length} de ${ups.length + deps.length} cambios seleccionados</span>`
    + (warn || `<span class="safe">Antes de cambiar nada se guarda una copia de tus mods. Podrás deshacerlo al terminar.</span>`);
}

/* ================================================================ eventos */

window.onBackend = (event, payload) => {
  if (event === "progress") onProgress(payload);
  else if (event === "results") { setProgress(100); showResults(payload); }
  else if (event === "error") {
    $("#scan-error-text").textContent = payload.message;
    $("#scan-error").hidden = false;
    $("#scan-label").textContent = "La revisión no ha terminado.";
  }
};

document.addEventListener("click", async e => {
  const t = e.target;
  const ext = t.closest("[data-external]");
  if (ext) { e.preventDefault(); api().open_url(ext.getAttribute("href")); return; }
  const f = t.closest("[data-f]");
  if (f) { filter = f.dataset.f; render(); return; }
  if (t.closest("[data-ok]")) { okOpen = !okOpen; render(); return; }
  if (t.closest("[data-clear]")) { $("#q").value = ""; query = ""; render(); $("#q").focus(); return; }
  if (t.closest("[data-go-settings]")) { openSetup("settings"); return; }
});

document.addEventListener("change", e => {
  const t = e.target;
  if (!t.dataset) return;
  if ("all" in t.dataset) {
    MODS.filter(m => selectable(m) && visible(m)).forEach(m => setChecked(m, t.checked));
    render(); return;
  }
  if (t.dataset.id !== undefined && t.classList.contains("check")) { setChecked(MODS[t.dataset.id], t.checked); render(); }
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
  $("#btn-quit").addEventListener("click", () => api().quit());
  $("#btn-cancel-settings").addEventListener("click", () => (DATA ? show("results") : startScan()));
  $("#btn-save").addEventListener("click", () => saveSetup(true));
  $("#btn-nokey").addEventListener("click", () => saveSetup(false));
  $("#mc-version").addEventListener("input", () => envHelp(state.folder));
  $("#loader").addEventListener("change", () => envHelp(state.folder));
  $("#btn-folder").addEventListener("click", async () => {
    const res = await api().choose_folder();
    if (!res) return;
    pendingFolder = res.path;
    state.folder = res.folder;
    $("#folder-path").textContent = res.path;
    folderHelp(res.folder);
    if (res.folder.minecraft_version) $("#mc-version").value = res.folder.minecraft_version;
    if (res.folder.loader) $("#loader").value = res.folder.loader;
    envHelp(res.folder);
  });
  $("#btn-test").addEventListener("click", async () => {
    const help = $("#key-help");
    help.className = "help";
    help.textContent = "Probando…";
    const res = await api().test_key($("#cf-key").value);
    help.className = `help ${res.ok ? "ok" : "bad"}`;
    help.textContent = res.message;
  });
  $("#btn-forget").addEventListener("click", async () => {
    state = await api().forget_key();
    openSetup(setupMode);
    $("#key-help").textContent = "Key borrada.";
  });
  $("#go").addEventListener("click", async () => {
    const ids = MODS.filter(m => m.checked).map(m => m.id);
    const res = await api().apply(ids);
    if (!res.ok) $("#summary").innerHTML = `<span class="count">Aún no disponible</span><span class="warn">${esc(res.message)}</span>`;
  });
}

async function boot() {
  wire();
  state = await api().get_state();
  if (!state.settings.setup_done) openSetup("setup");
  else startScan();
}

if (window.pywebview && window.pywebview.api) boot();
else if (location.search.includes("mock")) {
  const s = document.createElement("script");
  s.src = "dev-mock.js";
  s.onload = boot;
  document.head.appendChild(s);
} else window.addEventListener("pywebviewready", boot, { once: true });

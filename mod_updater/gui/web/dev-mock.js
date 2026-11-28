/* Solo para desarrollo: simula window.pywebview.api para probar la interfaz en un navegador.
   Servir la carpeta mod_updater/ y abrir gui/web/index.html?mock (añadir &lang=en|ca|es, &done).
   No se incluye en el ejecutable. */
"use strict";
(() => {
  const params = new URLSearchParams(location.search);
  const CDN = "https://media.forgecdn.net/avatars/thumbnails/";
  const loaders = ["forge", "fabric", "quilt", "neoforge"].map(v => ({ value: v, label: { neoforge: "NeoForge", forge: "Forge", fabric: "Fabric", quilt: "Quilt" }[v] }));
  const languages = [{ value: "auto", label: null }, { value: "es", label: "Español" }, { value: "en", label: "English" }];
  const settings = { mods_dir: "C:\\Users\\Ana\\AppData\\Roaming\\.minecraft\\mods", minecraft_version: "1.21.1", loader: "neoforge",
    allow_beta: false, backups_to_keep: 1, setup_done: params.has("done"), use_curseforge: true, language: params.get("lang") || "auto" };
  let keySource = params.get("key") || null;   // null | "env" | "keyring"
  const cache = {};
  const load = async code => (cache[code] ??= await (await fetch(`../../locales/${code}.json`)).json());
  const resolve = code => (["es", "en"].includes(code) ? code : "es");
  const strings = async code => ({ ...(await load("en")), ...(await load(resolve(code))) });
  // Perfiles de ejemplo (?oneprofile: solo uno). Carpetas inventadas.
  let profs = [
    { id: "principal", name: "Principal", mods_dir: settings.mods_dir, minecraft_version: "1.21.1", loader: "neoforge", active: true, exists: true },
    { id: "servidor", name: "Servidor con Ana", mods_dir: "C:\\Users\\Ana\\curseforge\\minecraft\\Instances\\Servidor\\mods", minecraft_version: "1.21.1", loader: "neoforge", active: false, exists: true },
    { id: "antiguo", name: "Antiguo 1.20.1", mods_dir: "D:\\Juegos\\viejo\\mods", minecraft_version: "1.20.1", loader: "forge", active: false, exists: false },
  ];
  if (params.has("oneprofile")) profs = profs.slice(0, 1);
  // Los ajustes de arriba reflejan el perfil activo (como en la app real).
  const activeView = () => { const a = profs.find(p => p.active);
    return { mods_dir: a.mods_dir, minecraft_version: a.minecraft_version, loader: a.loader }; };
  const state = async () => ({ settings: { ...settings, ...(params.has("done") ? activeView() : {}), active_profile: profs.find(p => p.active).id },
    profiles: params.has("done") ? profs.map(p => ({ ...p })) : [], same_folder: [], default_mods_dir: settings.mods_dir,
    folder: { exists: true, jars: 125, minecraft_version: "1.21.1", loader: "neoforge" },
    has_key: !!keySource, key_hint: keySource === "keyring" ? "••••3f9a" : keySource === "env" ? "••••c0de" : null, key_source: keySource,
    loaders, languages, lang: resolve(settings.language), strings: await strings(settings.language) });

  const up = (name, from, to, icon, betaNote = null) => ({ s: "up", name, from, to, icon: icon && CDN + icon, beta: !!betaNote, betaNote, src: "CurseForge", sub: "", neededBy: [], checked: true, cl: true });
  const ok = (name, from) => ({ s: "ok", name, from, to: null, beta: false, betaNote: null, src: "CurseForge", sub: "", neededBy: [], checked: false });
  const rows = [
    { s: "dep", name: "MezzConfig", from: null, to: "0.7.1", icon: CDN + "2038/374/256/256/639246433191280078.png", beta: true,
      betaNote: "Única versión publicada; la requiere Just Enough Items (JEI)", src: "CurseForge", sub: "", neededBy: ["Just Enough Items (JEI)"], checked: true },
    // Mod INVENTADO para enseñar el estado "Descarga manual" (no atribuirlo a un mod real).
    { s: "manual", name: "Mod de ejemplo", nameEn: "Example Mod", from: "1.4.0", to: "1.5.2", icon: null, src: "CurseForge",
      sub: "", neededBy: [], checked: false, url: "https://example.com" },
    up("Balm", "21.0.56", "21.0.67", "1107/117/256/256/638657111836546584.png"),
    up("Accessories", "1.1.0-beta.52", "1.1.0-beta.54", "948/913/256/256/638436487112587498.png", "Versión beta: ya usas la beta de este mod"),
    up("Curios API", "9.5.1", "9.6.0", "195/772/256/256/636881112930494939.png"),
    ok("Just Enough Items (JEI)", "19.71.0.475"), ok("Sodium", "0.8.13"),
    // Fijado de ejemplo: hay versión nueva, pero no entra en "Actualizar todo".
    { s: "pin", name: "Create", from: "6.0.4", to: "6.0.10", icon: null, beta: false, betaNote: null, src: "CurseForge",
      sub: "El servidor va en 6.0.4", neededBy: [], checked: false, cl: true },
    { ...ok("JourneyMap", "6.0.0"), off: true },
  ].map((r, i) => ({ ...r, id: i, vers: r.s !== "dep", file: r.s === "dep" ? null : `${r.name.replace(/\W+/g, "")}.jar${r.off ? ".disabled" : ""}`, off: !!r.off }));

  const emit = (e, p) => window.onBackend(e, p);
  let diagSeen = false;
  let bs = null;
  const bsView = () => ({ ok: true, active: !bs.done, done: bs.done, round: bs.round, left: bs.done ? 0 : Math.max(1, Math.ceil(Math.log2(Math.max(bs.suspects.length, 1))) + (bs.proven ? 0 : 1)), suspects: bs.suspects.length,
    testing: bs.testing, result: bs.result, result_rows: bs.result.map(n => rows.find(r => r.name === n).id), problems: [] });
  const bsNext = () => {
    if (!bs.suspects.length) { bs.done = true; bs.result = []; return; }
    if (bs.suspects.length === 1 && bs.proven) { bs.done = true; bs.result = bs.suspects; bs.testing = []; return; }
    bs.testing = bs.suspects.length === 1 ? bs.suspects : bs.suspects.slice(0, Math.floor(bs.suspects.length / 2));
    bs.round++;
  };
  if (params.has("bspending")) { bs = { suspects: ["Balm", "Accessories", "Curios API"], testing: ["Balm"], round: 2, max: 4, proven: false, done: false, result: [] }; }
  window.pywebview = { api: {
    get_state: state,
    profile_switch: async id => { profs.forEach(p => p.active = p.id === id); return { ok: true, state: await state() }; },
    profile_rename: async (id, name) => { profs.find(p => p.id === id).name = name.trim() || "?"; return { ok: true, state: await state() }; },
    profile_remove: async id => { const was = profs.find(p => p.id === id).active; profs = profs.filter(p => p.id !== id);
      if (was) profs[0].active = true; return { ok: true, switched: was, state: await state() }; },
    profile_detect: async () => [{ launcher: "prism", name: "Fabric con amigos", mods_dir: "C:\\Users\\Ana\\AppData\\Roaming\\PrismLauncher\\instances\\Amigos\\minecraft\\mods",
      loader: "fabric", minecraft_version: "1.21.1", exists: true }],
    profile_add: async d => { const id = "nuevo" + profs.length; profs.push({ id, name: d.name || "Nuevo", mods_dir: d.mods_dir,
      minecraft_version: d.minecraft_version || "1.21.1", loader: d.loader || "neoforge", active: false, exists: true });
      return { ok: true, id, state: await state() }; },
    get_strings: async code => ({ lang: resolve(code), strings: await strings(code) }),
    mc_versions: async include => [...new Set(["26.3", "26.2", "26.1.2", "26.1.1", "26.1", "1.21.11", "1.21.10", "1.21.1", "1.21", "1.20.1", ...(include || [])])],
    peek: async () => (await state()).folder,
    choose_folder: async () => ({ path: "D:\\Juegos\\Minecraft\\mods", folder: { exists: true, jars: 42, minecraft_version: "1.20.1", loader: "forge" } }),
    test_key: async k => (k && k.length > 10 ? { ok: true, message: "Key válida. CurseForge responde." }
      : { ok: false, message: k ? "CurseForge no acepta esta key. Comprueba que la has copiado entera." : "Pega primero tu key de CurseForge." }),
    save_setup: async d => { Object.assign(settings, { mods_dir: d.mods_dir, minecraft_version: d.minecraft_version, loader: d.loader,
      use_curseforge: d.use_curseforge, allow_beta: d.allow_beta, backups_to_keep: d.backups_to_keep, language: d.language, setup_done: true });
      if (d.key) keySource = "keyring"; return { ok: true, state: await state() }; },
    forget_key: async () => { keySource = null; return state(); },
    start_scan: async () => {
      let i = 0; const n = 125;
      const tick = () => {
        i += 5;
        if (i <= n) { emit("progress", { phase: "read", label: `Leyendo mods ${i}/${n}`, done: i, total: n }); setTimeout(tick, 30); return; }
        emit("progress", { phase: "cf", label: "Consultando CurseForge" });
        setTimeout(() => emit("progress", { phase: "mr", label: "Consultando Modrinth" }), 300);
        setTimeout(() => emit("progress", { phase: "deps", label: "Comprobando dependencias" }), 600);
        // Los textos que en la app real genera Python salen aquí de las mismas traducciones.
        setTimeout(async () => {
          const S = await strings(settings.language);
          const fill = (key, p = {}) => S[key].replace(/\{(\w+)\}/g, (m, k) => p[k] ?? m);
          const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
          const data = JSON.parse(JSON.stringify(rows)).map(r => {
            if (r.s === "manual") { r.sub = cap(fill("note.no_api_download")); if (resolve(settings.language) === "en" && r.nameEn) r.name = r.nameEn; }
            if (r.s === "dep") r.betaNote = fill("beta.only_published", { names: r.neededBy.join(", ") });
            if (r.s === "up" && r.beta) r.betaNote = fill("beta.already");
            return r;
          });
          emit("results", { rows: data,
            details: [fill("deps.ignored", { parent: "Create: Escalated", dep: "Create Fabric" })],
            notices: keySource && settings.use_curseforge ? [] : [fill("notice.no_key")],
            env: { mods_dir: settings.mods_dir, minecraft_version: settings.minecraft_version, loader: "NeoForge", curseforge: !!keySource } });
        }, 900);
      };
      tick(); return true;
    },
    // Activar/desactivar: Curios API la necesita Accessories (para ver el aviso de librería).
    mods_set_enabled: async (ids, enabled, mode = "ask") => {
      if (bs && !bs.done) return { ok: false, reason: "bisect", message: "Hay una búsqueda por mitades en curso. Termínala o cancélala en Diagnóstico antes de cambiar mods." };
      if (params.has("mcopen")) return { ok: false, reason: "minecraft", message: "Minecraft está abierto con esta carpeta. Ciérralo y vuelve a pulsar el botón." };
      const S = await strings(settings.language);
      const fill = (key, p = {}) => S[key].replace(/\{(\w+)\}/g, (m, k) => p[k] ?? m);
      let targets = rows.filter(r => ids.includes(r.id) && r.file && r.off === enabled);
      const curios = targets.find(r => r.name === "Curios API"), acc = rows.find(r => r.name === "Accessories");
      if (!enabled && curios && !acc.off && !targets.includes(acc)) {
        if (mode === "ask") return { ok: false, reason: "dependents", names: [acc.name],
          message: fill("toggle.dependents_one", { name: curios.name, names: acc.name }) };
        if (mode === "with") targets = [...targets, acc];
      }
      for (const r of targets) r.off = !enabled;
      return { ok: true, rows: targets.map(r => ({ id: r.id, off: r.off })), also: [], failed: [] };
    },
    apply: async ids => {
      if (bs && !bs.done) return { ok: false, reason: "bisect", message: "Hay una búsqueda por mitades en curso. Termínala o cancélala en Diagnóstico antes de cambiar mods." };
      if (params.has("mcopen")) return { ok: false, reason: "minecraft", message: "Minecraft está abierto con esta carpeta. Ciérralo y vuelve a pulsar el botón." };
      const chosen = rows.filter(r => ids.includes(r.id));
      let done = 0;
      const step = params.has("slow") ? 4000 : 250;
      chosen.forEach((r, i) => {
        const fail = r.name === "Curios API" && params.has("fail");
        setTimeout(() => emit("apply_progress", { id: r.id, state: "downloading", done, total: chosen.length }), step * i + 50);
        if (!fail) setTimeout(() => emit("apply_progress", { id: r.id, state: "verified", done, total: chosen.length }), step * i + 150);
        setTimeout(() => { done++; emit("apply_progress", { id: r.id, state: fail ? "error" : r.s === "dep" ? "installed" : "done",
          message: fail ? "descarga fallida: HTTP 503 al descargar" : "", done, total: chosen.length }); }, step * i + 240);
      });
      setTimeout(() => {
        const failed = params.has("fail") ? chosen.filter(r => r.name === "Curios API").map(r => ({ name: r.name, message: "descarga fallida: HTTP 503 al descargar" })) : [];
        const okRows = chosen.filter(r => !failed.some(f => f.name === r.name));
        emit("apply_done", { updated: okRows.filter(r => r.s === "up").length, installed: okRows.filter(r => r.s === "dep").length, failed,
          backup: { path: "C:\\Users\\Ana\\AppData\\Roaming\\.minecraft\\mods_backup\\2026-11-20_1930", date: "2026-11-20T19:30:00", changes: okRows.length, undone: false, undoable: okRows.length > 0 }, pruned: 1 });
      }, step * chosen.length + 400);
      return { ok: true, total: chosen.length };
    },
    // ?update: simula que hay una versión nueva de la app
    app_update: async () => params.has("update") ? { version: "0.4.0", url: "https://github.com/racsoga/mod_updater_Minecraft/releases/tag/v0.4.0",
      notes_html: "<h2>Novedades</h2><ul><li>Ejemplo de novedad</li></ul>" } : null,
    // Sugerencias de ejemplo.
    suggest_answers: async () => ({}),
    suggest_run: async a => ({ ok: true, answers: a, total: 120, over_limit: 0,
      remove: [{ name: "JourneyMap", reason: "Tienes dos minimapas: Xaero's Minimap y JourneyMap. Basta con uno.", file: "journeymap.jar" },
        { name: "Mod de ejemplo", reason: "Sin versiones nuevas desde 2024: puede estar abandonado.", file: "ejemplo.jar" }],
      review: [{ name: "Cloth Config API", reason: "Librería que ningún mod pide: puede que algún mod la use de forma opcional (por ejemplo, pantallas de configuración).", file: "cloth.jar" }],
      unchanged: ["Balm", "Sodium", "Waystones"],
      keep: [{ name: "Create", reason: "Encaja con tu partida de tecnología y automatización." },
        { name: "Just Enough Items (JEI)", reason: "Útil en cualquier partida." }],
      add: [{ name: "Mekanism", reason: "Muy popular en partidas de tecnología y automatización.", source: "curseforge", id: "268560" },
        { name: "Terralith", reason: "Da mucho juego para explorar: estructuras, biomas y viajes.", note: "Solo afecta a mundos nuevos o zonas sin explorar.", source: "curseforge", id: "513688" }] }),
    suggest_plan: async sel => ({ ok: true, size: 9000000, overlaps: [], manual: [], unavailable: [], already: [], blocked: [],
      rows: [...sel.add.map((a, i) => ({ id: 100000 + i, s: "dep", name: a.name, to: "10.7", size: 9000000, neededBy: [] })),
        ...sel.remove.slice(sel.add.length ? 1 : 0).map((f, i) => ({ id: 100100 + i, s: "rm", name: f, from: "1.0", neededBy: [] }))],
      // Simula S3: con algo para añadir, el primero que se quita lo necesita lo nuevo y no se quita.
      kept: sel.add.length && sel.remove.length ? [`No se quita ${sel.remove[0]}: lo necesita ${sel.add[0].name}, que vas a añadir.`] : [] }),
    // Lista de mods (sin archivos reales).
    modlist_export: async kind => ({ ok: true, file: kind === "mrpack" ? "Principal.mrpack" : "Principal.modlist.json",
      excluded: kind === "mrpack" ? ["Mod de ejemplo"] : [], no_loader_version: false }),
    modlist_import: async () => ({ ok: true, file: "Servidor.modlist.json", mismatch: null,
      profile: { minecraft: "1.21.1", loader: "NeoForge" }, same: 118,
      add: [{ name: "Waystones", version: "21.1.47" }], update: [{ name: "Create", version: "6.0.8", have: "6.0.6" }],
      unavailable: [{ name: "Mod privado", version: "1.0" }], remove: [{ name: "Mod de ejemplo", version: "1.4.0" }] }),
    modlist_import_start: async remove => {
      setTimeout(() => emit("apply_done", { updated: 1, installed: 0, added: 1, removed: remove ? 1 : 0, failed: [], pruned: 0,
        backup: { path: "C:\\…\\mods_backup\\2026-11-21_1700", date: "2026-11-21T17:00:00", changes: 3, undone: false, undoable: true } }), 800);
      return { ok: true, manual: [], rows: [{ id: 200000, s: "dep", name: "Waystones", from: null, to: "21.1.47", neededBy: [] },
        { id: 200001, s: "up", name: "Create", from: "6.0.6", to: "6.0.8", neededBy: [] }] };
    },
    compare_profiles: async () => ({ ok: true, a: "Principal", b: "Servidor con Ana", only_a: ["Mod de ejemplo"],
      only_b: ["Waystones"], different: ["Create"], same: 118 }),
    copy_list: async () => ({ ok: true, count: 120 }),
    // Explorar de ejemplo (sin red). Los nombres son inventados salvo los de la colección de prueba.
    explore_search: async opts => {
      await new Promise(r => setTimeout(r, 250));
      const all = [
        ["curseforge", "1", "Ejemplo de mochilas", "almacenamiento", 12400000, false],
        ["modrinth", "a2", "Ejemplo de minimapa", "mapas", 8900000, false],
        ["curseforge", "3", "Balm", "librerias", 98000000, true],
        ["curseforge", "4", "Ejemplo de cocina", "comida", 3100000, false],
        ["modrinth", "b5", "Ejemplo de rendimiento", "rendimiento", 45000000, false],
      ].map(([source, id, name, cat, downloads, installed]) => ({ source, id, name, cat, cats: [cat], downloads, installed,
        author: "Autor", summary: `Descripción corta de ${name}.`, updated: "2026-10-12T00:00:00Z", icon: null,
        url: "https://example.org", manual: false, also_on: [] }));
      const q = (opts.query || "").toLowerCase();
      const cards = all.filter(c => (!q || c.name.toLowerCase().includes(q)) && (!opts.category || c.cat === opts.category)
        && !(opts.hide_installed && c.installed));
      return { ok: true, cards: opts.page ? [] : cards, page: opts.page, more: false, scanned: true,
               env: { minecraft_version: "1.21.1", loader: "NeoForge" } };
    },
    explore_detail: async () => ({ ok: true, html: "<p>Descripción larga de ejemplo.</p>", images: [],
      links: { page: "https://example.org" }, install: { version: "1.2.0", beta: false, manual: false, via: "CurseForge",
      deps: [{ name: "Balm", installed: true }] } }),
    install_plan: async items => ({ ok: true, manual: [], unavailable: [], already: [], blocked: [],
      rows: items.map((it, i) => ({ id: 100000 + i, s: "dep", name: it.name, icon: null, from: null, to: "1.2.0", beta: false, neededBy: [] })) }),
    install_start: async () => {
      setTimeout(() => emit("apply_done", { updated: 0, installed: 0, added: 1, failed: [], pruned: 0,
        backup: { path: "C:\\…\\mods_backup\\2026-11-21_1600", date: "2026-11-21T16:00:00", changes: 1, undone: false, undoable: true } }), 800);
      return { ok: true, total: 1 };
    },
    // Pasar a otra versión de ejemplo (sin red).
    migrate_check: async target => {
      await new Promise(r => setTimeout(r, 300));
      return { ok: true, target, loader: "NeoForge", current: "1.21.1", total: 5, ready_count: 3, installable: 4, no_curseforge: false,
        delta: target === "1.21.4" ? 2 : null, last_date: "2026-11-20T18:00",
        ready: [{ name: "Create" }, { name: "Just Enough Items (JEI)" }, { name: "Sodium" }],
        missing: [{ name: "Mod de ejemplo", date: "2025-03-10T00:00:00Z" }],
        alternative: [{ name: "Accessories", via: "Modrinth", instead: null }],
        libs: [{ name: "Balm", ok: true }, { name: "Curios API", ok: false }] };
    },
    migrate_create: async () => {
      setTimeout(() => emit("apply_progress", { id: 400000, state: "done", done: 1, total: 4 }), 300);
      setTimeout(() => emit("apply_done", { updated: 0, installed: 0, added: 4, failed: [], pruned: 0, backup: null }), 700);
      return { ok: true, profile: "Principal (1.21.4)", folder: "D:\\Juegos\\mc-1.21.4\\mods",
        rows: ["Create", "Just Enough Items (JEI)", "Sodium", "Accessories"].map((n, i) => ({ id: 400000 + i, s: "dep", name: n, to: "nueva", neededBy: [] })) };
    },
    // Búsqueda por mitades de ejemplo: el culpable es Accessories (?bspending: una búsqueda a medias).
    bisect_status: async () => (bs && !bs.done ? bsView() : null),
    bisect_start: async excluded => {
      const names = rows.filter(r => r.file && !r.off && !excluded.includes(r.id)).map(r => r.name);
      bs = { suspects: names, testing: [], round: 0, max: names.length > 1 ? Math.ceil(Math.log2(names.length)) + 1 : 1, proven: false, done: false, result: [] };
      bsNext(); return bsView();
    },
    bisect_answer: async fails => {
      const t = new Set(bs.testing);
      if (fails) bs.suspects = bs.suspects.filter(n => !t.has(n)); else { bs.suspects = bs.suspects.filter(n => t.has(n)); bs.proven = true; }
      bsNext(); return bsView();
    },
    bisect_cancel: async () => { bs = null; return { ok: true, problems: [] }; },
    // Diagnóstico de ejemplo (?nodiag: sin informes). Casos de dos crash reports reales (anonimizados).
    diag_new: async () => ({ new: !params.has("nodiag") && !diagSeen, date: "2026-11-24T12:08" }),
    diag_reports: async () => {
      diagSeen = true;
      return { ok: true, scanned: true, reports: params.has("nodiag") ? [] : [
        { id: 0, name: "crash-2026-11-24_12.08.00-client.txt", kind: "client", date: "2026-11-24T12:08" },
        { id: 1, name: "crash-2026-11-22_18.08.26-fml.txt", kind: "fml", date: "2026-11-22T18:08" },
        { id: 2, name: "latest.log", kind: "log", date: "2026-11-28T12:44" }] };
    },
    diag_run: async id => {
      await new Promise(r => setTimeout(r, 200));
      const S = await strings(settings.language);
      const fill = (key, p = {}) => S[key].replace(/\{(\w+)\}/g, (m, k) => p[k] ?? m);
      const one = (key, p) => fill(`${key}_${p.count === 1 ? "one" : "other"}`, p);
      if (id === 2) return { ok: true, head: fill("dg.h_none_found"), deck: fill("dg.d_none_found"), cards: [], scanned: true };
      if (id === 1) return { ok: true, head: one("dg.h_load", { count: 1 }), deck: fill("dg.d_load"), scanned: true, cards: [{
        kind: "missing", kicker: fill("dg.k_missing"), title: fill("dg.t_missing", { name: "Sodium" }),
        why: one("dg.w_missing", { count: 2, names: "Iris Flywheel Compat y Create Better FPS", dep: "Sodium", range: fill("dg.range_min", { version: "0.6.9" }) })
          + " " + fill("dg.w_incompat", { name: "Iris", other: "Embeddium" }),
        note: "", evidence: ["Mod irisflw requires sodium 0.6.9 or above", "Mod createbetterfps requires sodium 0.6.9 or above",
          "Currently, sodium is not installed", "Mod iris is incompatible with embeddium 0.0.1 or above",
          "The reason is: Iris and Embeddium cannot be used together. Please use Sodium 0.8 instead."],
        actions: [{ id: "a1", primary: true, type: "swap", label: fill("dg.act_swap", { old: "Embeddium", new: "Sodium" }) },
          { id: "a2", primary: false, type: "disable", label: fill("dg.act_disable", { names: "Iris Flywheel Compat y Create Better FPS" }) },
          { id: "a3", primary: false, type: "disable", label: fill("dg.act_disable", { names: "Iris" }) }] }] };
      return { ok: true, head: fill("dg.t_suspect", { name: "Iris Flywheel Compat" }), deck: fill("dg.d_game"), scanned: true, cards: [{
        kind: "mixin", kicker: fill("dg.k_likely"), title: fill("dg.t_mixin_other", { name: "Iris Flywheel Compat", other: "Create" }),
        why: fill("dg.w_mixin_other", { name: "Iris Flywheel Compat", other: "Create", cls: "AllSpecialTextures" }),
        note: fill("dg.no_newer", { name: "Iris Flywheel Compat" }),
        evidence: ["Caused by: org.spongepowered.asm.mixin.transformer.throwables.MixinPreProcessorException: Attach error for irisflw.mixins.create.json:MixinOutlineParams from mod irisflw",
          "Caused by: java.lang.ClassNotFoundException: com.simibubi.create.AllSpecialTextures"],
        actions: [{ id: "a4", primary: true, type: "versions", label: fill("dg.act_versions", { name: "Create" }) },
          { id: "a5", primary: false, type: "disable", label: fill("dg.act_disable", { names: "Iris Flywheel Compat" }) }] }] };
    },
    diag_copy: async () => ({ ok: true }),
    diag_open_folder: async () => true,
    diag_do: async aid => {
      if (aid === "a4") return { ok: true, open_versions: rows.find(r => r.name === "Create").id };
      if (aid === "a1") {
        setTimeout(() => emit("apply_progress", { id: 100000, state: "done", done: 1, total: 1 }), 400);
        setTimeout(() => emit("apply_done", { updated: 0, installed: 0, added: 1, failed: [], pruned: 0,
          backup: { path: "C:\\…\\mods_backup\\2026-11-28_1400", date: "2026-11-28T14:00:00", changes: 1, undone: false, undoable: true } }), 700);
        return { ok: true, total: 1, rows: [{ id: 100000, s: "dep", name: "Sodium", from: null, to: "0.8.13", neededBy: [] }] };
      }
      return { ok: true, rows: [], also: [], failed: [] };
    },
    // Versiones para fijar o volver atrás (?mcopen: Minecraft abierto).
    versions_for: async id => {
      await new Promise(r => setTimeout(r, 200));
      const r = rows.find(x => x.id === id) || rows[0];
      const cur = r.from || "1.0";
      return { ok: true, pinned: r.s === "pin", reason: r.s === "pin" ? r.sub : "", current: cur, versions: [
        { id: "v4", version: r.to || cur, date: "2026-11-10T10:00:00Z", channel: "release", current: !r.to, manual: false },
        { id: "v3", version: "versión-beta", date: "2026-10-20T10:00:00Z", channel: "beta", current: false, manual: false },
        { id: "v2", version: r.to ? cur : "versión-anterior", date: "2026-09-02T10:00:00Z", channel: "release", current: !!r.to, manual: false },
        { id: "v1", version: "anterior", date: "2026-07-15T10:00:00Z", channel: "release", current: false, manual: true },
      ].filter((v, i, all) => all.findIndex(x => x.version === v.version) === i) };
    },
    pin_set: async (id, on, reason) => {
      const r = rows.find(x => x.id === id);
      if (r) { r.s = on ? "pin" : (r.to ? "up" : "ok"); r.sub = on ? (reason || `Fijado en ${r.from}`) : ""; r.checked = !on && !!r.to; }
      return { ok: true };
    },
    rollback: async (id, vid) => {
      if (params.has("mcopen")) return { ok: false, reason: "minecraft", message: "Minecraft está abierto con esta carpeta. Ciérralo y vuelve a pulsar el botón." };
      const r = rows.find(x => x.id === id) || rows[0];
      setTimeout(() => emit("apply_progress", { id: 300000, state: "downloading", done: 0, total: 1 }), 100);
      setTimeout(() => emit("apply_progress", { id: 300000, state: "done", done: 1, total: 1 }), 600);
      setTimeout(() => emit("apply_done", { updated: 1, installed: 0, added: 0, failed: [], pruned: 0,
        backup: { path: "C:\\…\\mods_backup\\2026-11-28_1300", date: "2026-11-28T13:00:00", changes: 1, undone: false, undoable: true } }), 900);
      return { ok: true, rows: [{ id: 300000, s: "up", name: r.name, from: r.from, to: vid, neededBy: [] }] };
    },
    // Changelog de ejemplo (?clfail: error de red). El HTML real llega ya limpio desde Python.
    changelog: async id => {
      await new Promise(r => setTimeout(r, params.has("slow") ? 1500 : 300));
      if (params.has("clfail")) return { ok: false, message: t("cl.err_network") };
      const r = rows.find(x => x.id === id) || rows[0];
      return { ok: true, name: r.name, from: r.from, to: r.to, url: "https://example.org", more: 2, versions: [
        { version: r.to, date: "2026-11-10T10:00:00Z", channel: "release",
          html: '<h3>Nuevo</h3><ul><li>Soporte para la <a href="https://example.org" data-external rel="noopener">API nueva</a></li><li><mark class="cl-flag">Breaking</mark>: cambia el formato de configuración</li></ul>' },
        { version: "anterior-beta", date: "2026-10-28T10:00:00Z", channel: "beta", html: "" },
        { version: "anterior", date: "2026-10-02T10:00:00Z", channel: "release",
          html: '<p>Corregido un fallo al cargar el <mark class="cl-flag">world</mark> con muchos chunks.</p><pre><code>config.toml: maxChunks = 64</code></pre>' },
      ] };
    },
    // Análisis de ejemplo (?noanalysis: sin revisión todavía).
    analysis: async libs => {
      if (params.has("noanalysis")) return { ready: false };
      const cats = [["tecnologia", ["Create", "Mekanism", "Create: Steam 'n' Rails", "Applied Energistics 2", "Immersive Engineering", "Create Crafts & Additions"]],
        ["mobs", ["Alex's Mobs", "Mowzie's Mobs", "Born in Chaos", "Guard Villagers"]], ["calidad_vida", ["Jade", "Mouse Tweaks", "Waystones"]],
        ["comida", ["Farmer's Delight", "Croptopia"]], ["mapas", ["Xaero's Minimap", "Xaero's World Map"]], ["mundo", ["Terralith"]],
        ["almacenamiento", ["Sophisticated Backpacks"]], ["rendimiento", ["FerriteCore", "ModernFix"]], ["otras", ["Mod de ejemplo"]]];
      if (libs) cats.splice(1, 0, ["librerias", ["Balm", "Architectury API", "Kotlin for Forge", "Cloth Config API", "GeckoLib", "Curios API", "Puzzles Lib"]]);
      return { ready: true,
        by_category: cats.map(([cat, mods]) => ({ cat, count: mods.length, mods })),
        totals: { mods: 29, libraries: 7, size: 186400000, up_to_date: 25, updates: 4, sources: { curseforge: 24, modrinth: 4, none: 1 } },
        heaviest: [{ name: "Create", size: 19100000 }, { name: "Mekanism", size: 15800000 }, { name: "Alex's Mobs", size: 14300000 },
          { name: "Applied Energistics 2", size: 9900000 }, { name: "Immersive Engineering", size: 8700000 }],
        stale: { abandoned: [{ name: "Mod de ejemplo", date: "2024-10-15T00:00:00Z", url: "https://example.org" }],
                 no_version: [{ name: "Croptopia", date: "2025-02-03T00:00:00Z", url: "https://example.org" }] },
        game_version: "1.21.1",
        orphans: [{ name: "Cloth Config API", size: 1200000, optional_by: ["Sound Physics Remastered"], needed_by_orphans: [] }],
        sides: { client: 5, server: 1, both: 21, unknown: 2 } };
    },
    // ?interrupted: simula que la última actualización se cortó a medias
    interrupted: async () => params.has("interrupted")
      ? { path: "C:\\…\\mods_backup\\2026-11-20_1930", date: "2026-11-20T19:30:00", changes: 2, complete: false, undone: false, undoable: true }
      : null,
    restore_interrupted: async () => ({ ok: true, restored: 2, removed: 1, errors: [], message: t("undo.done", { count: 2, removed: 1 }) }),
    undo_last: async () => ({ ok: true, restored: 3, removed: 4, errors: [], message: "Hecho: 3 mods vuelven a su versión anterior (4 archivos nuevos apartados en la copia)." }),
    backups_info: async () => ({ count: 2, last: { path: "C:\\…\\mods_backup\\2026-11-20_1930", date: "2026-11-20T19:30:00", changes: 4, undone: false, undoable: true } }),
    clear_backups: async () => ({ ok: true, count: 2, message: "2 backups borrados." }),
    open_url: async () => true,
    open_mods_folder: async () => true,
  } };
})();

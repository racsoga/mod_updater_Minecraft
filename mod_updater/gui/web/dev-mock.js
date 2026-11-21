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
    ok("Just Enough Items (JEI)", "19.71.0.475"), ok("Create", "6.0.10"), ok("Sodium", "0.8.13"),
  ].map((r, i) => ({ ...r, id: i }));

  const emit = (e, p) => window.onBackend(e, p);
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
    apply: async ids => {
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
    // Sugerencias de ejemplo.
    suggest_answers: async () => ({}),
    suggest_run: async a => ({ ok: true, answers: a, total: 120, over_limit: 0,
      remove: [{ name: "JourneyMap", reason: "Tienes dos minimapas: Xaero's Minimap y JourneyMap. Basta con uno.", file: "journeymap.jar" },
        { name: "Mod de ejemplo", reason: "Sin versiones nuevas desde 2024: puede estar abandonado.", file: "ejemplo.jar" }],
      keep: [{ name: "Create", reason: "Imprescindible para una partida de tecnología y automatización." },
        { name: "Just Enough Items (JEI)", reason: "Útil en cualquier partida." }],
      add: [{ name: "Mekanism", reason: "Muy popular en partidas de tecnología y automatización.", source: "curseforge", id: "268560" }] }),
    suggest_plan: async sel => ({ ok: true, size: 9000000, overlaps: [], manual: [], unavailable: [], already: [], blocked: [],
      rows: [...sel.add.map((a, i) => ({ id: 100000 + i, s: "dep", name: a.name, to: "10.7", size: 9000000, neededBy: [] })),
        ...sel.remove.map((f, i) => ({ id: 100100 + i, s: "rm", name: f, from: "1.0", neededBy: [] }))] }),
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

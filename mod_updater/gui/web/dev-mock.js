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
  const state = async () => ({ settings: { ...settings }, default_mods_dir: settings.mods_dir,
    folder: { exists: true, jars: 125, minecraft_version: "1.21.1", loader: "neoforge" },
    has_key: !!keySource, key_hint: keySource === "keyring" ? "••••3f9a" : keySource === "env" ? "••••c0de" : null, key_source: keySource,
    loaders, languages, lang: resolve(settings.language), strings: await strings(settings.language) });

  const up = (name, from, to, icon, betaNote = null) => ({ s: "up", name, from, to, icon: icon && CDN + icon, beta: !!betaNote, betaNote, src: "CurseForge", sub: "", neededBy: [], checked: true });
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

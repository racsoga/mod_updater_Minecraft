/* Solo para desarrollo: simula window.pywebview.api para probar la interfaz en un navegador.
   Servir la carpeta mod_updater/ y abrir gui/web/index.html?mock (añadir &lang=en|ca|es, &done).
   No se incluye en el ejecutable. */
"use strict";
(() => {
  const params = new URLSearchParams(location.search);
  const CDN = "https://media.forgecdn.net/avatars/thumbnails/";
  const loaders = ["forge", "fabric", "quilt", "neoforge"].map(v => ({ value: v, label: { neoforge: "NeoForge", forge: "Forge", fabric: "Fabric", quilt: "Quilt" }[v] }));
  const languages = [{ value: "auto", label: null }, { value: "es", label: "Español" }, { value: "en", label: "English" }, { value: "ca", label: "Català" }];
  const settings = { mods_dir: "C:\\Users\\Ana\\AppData\\Roaming\\.minecraft\\mods", minecraft_version: "1.21.1", loader: "neoforge",
    allow_beta: false, backups_to_keep: 1, setup_done: params.has("done"), use_curseforge: true, language: params.get("lang") || "auto" };
  let keySource = params.get("key") || null;   // null | "env" | "keyring"
  const cache = {};
  const load = async code => (cache[code] ??= await (await fetch(`../../locales/${code}.json`)).json());
  const resolve = code => (["es", "en", "ca"].includes(code) ? code : "es");
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
    { s: "manual", name: "Sophisticated Backpacks", from: "3.26.22", to: "3.26.31", icon: CDN + "375/56/256/256/637549610342642859.png", src: "CurseForge",
      sub: "El autor no permite descargarlo automáticamente", neededBy: [], checked: false, url: "https://www.curseforge.com/minecraft/mc-mods/sophisticated-backpacks" },
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
        setTimeout(() => emit("results", { rows: JSON.parse(JSON.stringify(rows)),
          details: ["Create: Escalated menciona Create Fabric como necesaria, pero no hay ninguna versión de Create Fabric para tu Minecraft y cargador de mods. Suele ser la versión para otro cargador: no tienes que hacer nada."],
          notices: keySource && settings.use_curseforge ? [] : ["Sin key de CurseForge: solo se ha consultado Modrinth, así que algunos mods pueden salir como No encontrado."],
          env: { mods_dir: settings.mods_dir, minecraft_version: settings.minecraft_version, loader: "NeoForge", curseforge: !!keySource } }), 900);
      };
      tick(); return true;
    },
    apply: async () => ({ ok: false, message: "La actualización desde la ventana llega en la siguiente versión." }),
    open_url: async () => true,
    open_mods_folder: async () => true,
    quit: async () => {},
  } };
})();

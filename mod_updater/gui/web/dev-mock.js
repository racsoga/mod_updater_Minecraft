/* Solo para desarrollo: simula window.pywebview.api para probar la interfaz en un
   navegador (index.html?mock). No se incluye en el ejecutable. */
"use strict";
(() => {
  const CDN = "https://media.forgecdn.net/avatars/thumbnails/";
  const loaders = ["forge", "fabric", "quilt", "neoforge"].map(v => ({ value: v, label: { neoforge: "NeoForge", forge: "Forge", fabric: "Fabric", quilt: "Quilt" }[v] }));
  const settings = { mods_dir: "C:\\Users\\Ana\\AppData\\Roaming\\.minecraft\\mods", minecraft_version: "1.21.1", loader: "neoforge",
    allow_beta: false, backups_to_keep: 1, setup_done: location.search.includes("done"), use_curseforge: true };
  let hasKey = false;
  const state = () => ({ settings: { ...settings }, default_mods_dir: settings.mods_dir,
    folder: { exists: true, jars: 125, minecraft_version: "1.21.1", loader: "neoforge" },
    has_key: hasKey, key_hint: hasKey ? "••••3f9a" : null, key_source: hasKey ? "keyring" : null, loaders });

  const up = (name, from, to, icon, beta = false) => ({ s: "up", name, from, to, icon: icon && CDN + icon, beta, src: "CurseForge", sub: "", neededBy: [], checked: true });
  const ok = (name, from) => ({ s: "ok", name, from, to: null, beta: false, src: "CurseForge", sub: "", neededBy: [], checked: false });
  const rows = [
    { s: "dep", name: "MezzConfig", from: null, to: "0.7.1", icon: CDN + "2038/374/256/256/639246433191280078.png", beta: true, src: "CurseForge", sub: "", neededBy: ["Just Enough Items (JEI)"], checked: true, url: "https://www.curseforge.com/minecraft/mc-mods/mezzconfig" },
    { s: "manual", name: "Sophisticated Backpacks", from: "3.26.22", to: "3.26.31", icon: CDN + "375/56/256/256/637549610342642859.png", src: "CurseForge", sub: "El autor no permite descarga por API", neededBy: [], checked: false, url: "https://www.curseforge.com/minecraft/mc-mods/sophisticated-backpacks" },
    { s: "missing", name: "mapa-del-servidor-1.0.jar", from: "1.0", to: null, src: "", sub: "mapa-del-servidor-1.0.jar", neededBy: [], checked: false },
    up("Balm", "21.0.56", "21.0.67", "1107/117/256/256/638657111836546584.png"),
    up("Accessories", "1.1.0-beta.52", "1.1.0-beta.54", "948/913/256/256/638436487112587498.png", true),
    up("Curios API", "9.5.1", "9.6.0", "195/772/256/256/636881112930494939.png"),
    up("GeckoLib", "4.8.4", "4.9.3", "1081/393/256/256/638621132937140582.png"),
    up("Collective", "8.13", "8.87", "975/602/256/256/638479075930399380.png"),
    up("Kotlin for Forge", "5.11.0", "5.13.0"),
    ok("Just Enough Items (JEI)", "19.71.0.475"), ok("Create", "6.0.10"), ok("Sodium", "0.8.13"), ok("Waystones", "21.1.47"),
  ].map((r, i) => ({ ...r, id: i }));

  const emit = (e, p) => window.onBackend(e, p);
  window.pywebview = { api: {
    get_state: async () => state(),
    peek: async () => state().folder,
    choose_folder: async () => ({ path: "D:\\Juegos\\Minecraft\\mods", folder: { exists: true, jars: 42, minecraft_version: "1.20.1", loader: "forge" } }),
    test_key: async k => (k && k.length > 10 ? { ok: true, message: "Key válida. CurseForge responde." }
      : { ok: false, message: k ? "CurseForge no acepta esta key. Comprueba que la has copiado entera." : "Pega primero tu key de CurseForge." }),
    save_setup: async d => { Object.assign(settings, { mods_dir: d.mods_dir, minecraft_version: d.minecraft_version, loader: d.loader,
      use_curseforge: d.use_curseforge, allow_beta: d.allow_beta, backups_to_keep: d.backups_to_keep, setup_done: true });
      if (d.key) hasKey = true; return { ok: true, state: state() }; },
    forget_key: async () => { hasKey = false; return state(); },
    start_scan: async () => {
      let i = 0; const n = 125;
      const tick = () => {
        i += 5;
        if (i <= n) { emit("progress", { phase: "read", label: `Leyendo mods ${i}/${n}`, done: i, total: n }); setTimeout(tick, 30); return; }
        emit("progress", { phase: "cf", label: "Consultando CurseForge" });
        setTimeout(() => emit("progress", { phase: "mr", label: "Consultando Modrinth" }), 300);
        setTimeout(() => emit("progress", { phase: "deps", label: "Comprobando dependencias" }), 600);
        setTimeout(() => emit("results", { rows: JSON.parse(JSON.stringify(rows)), broken: [],
          ignored: ["Create: Escalated declara como requerida Create Fabric, que no tiene versión para este Minecraft/loader; se ignora"],
          notices: hasKey && settings.use_curseforge ? [] : ["Sin key de CurseForge: solo se ha consultado Modrinth, así que algunos mods pueden salir como No encontrado."],
          env: { mods_dir: settings.mods_dir, minecraft_version: settings.minecraft_version, loader: "NeoForge", curseforge: hasKey } }), 900);
      };
      tick(); return true;
    },
    apply: async () => ({ ok: false, message: "La actualización desde la ventana llega en la siguiente versión. Mientras tanto, usa actualizar.bat." }),
    open_url: async () => true,
    open_mods_folder: async () => true,
    quit: async () => {},
  } };
})();

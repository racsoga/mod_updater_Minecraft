<p align="center">
  <img src="docs/images/logo.png" width="96" height="96" alt="Mod Updater logo: an anvil with a refresh arrow">
</p>

<h1 align="center">Mod Updater</h1>

<p align="center">
  Update your Minecraft mods in one click, with a backup and an undo button.
</p>

<p align="center">
  <a href="https://github.com/racsoga/mod_updater_Minecraft/actions/workflows/tests.yml"><img src="https://github.com/racsoga/mod_updater_Minecraft/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-357a1f" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-1a1b1e" alt="Windows 10 and 11">
</p>

<p align="center"><a href="README.md">Español</a> · <b>English</b></p>

<p align="center">
  <img src="docs/images/results.png" width="820" alt="Results screen: 3 mods have a new version and 1 dependency is missing">
</p>

## What it does

Mod Updater checks your Minecraft `mods` folder, recognises each mod by its fingerprint on **CurseForge** and **Modrinth**, and tells you which ones have a new version. You choose what to update.

- **Recognises your mods even if you renamed the files**: it identifies them by their content, not their name.
- **Respects your game version and mod loader**: it only suggests versions for your Minecraft (e.g. 1.21.1) and your loader, which it works out from your own mods. Designed for NeoForge, Forge, Fabric and Quilt; tested with NeoForge 1.21.1.
- **Installs missing dependencies**: if a mod needs another one you don't have, it adds it and tells you why ("Just Enough Items needs MezzConfig").
- **Doesn't break your game**: if a dependency can't be downloaded, that mod isn't updated. If you have a mod's stable version, it won't suggest betas (unless you enable them).
- **There's always a way back**: a copy of your mods is saved before anything changes. When it finishes you can **Undo**.
- **Never touches anything while Minecraft is open.**
- In **English and Spanish** (it follows your Windows language).

<p align="center">
  <img src="docs/images/flujo.gif" width="720" alt="Animation (in Spanish): Update is pressed, each mod goes through downloading, verified and updated, and the final screen appears">
</p>

## Download

**Coming soon.** The first downloadable version (`ModUpdater.exe`) will be published under *Releases* once testing is finished. Meanwhile you can run it from source with Python (`pip install -r requirements.txt` and `python ModUpdater.pyw`).

Once it's out: download `ModUpdater.exe` and open it. Nothing to install.

> **Make a copy of your `mods` folder the first time.** The app keeps backups and lets you undo, but your own copy never hurts.

**Requirements:** 64-bit Windows 10 or 11, an internet connection and Microsoft's WebView2 component (included in Windows 11 and in up-to-date Windows 10).

## First run

1. **Mods folder.** The app suggests `%APPDATA%\.minecraft\mods`. If you use another launcher (CurseForge, Prism, Modrinth App…), press *Change folder* and pick your instance's `mods` folder.
2. **Version and mod loader.** They're detected from your mods; check they're right.
3. **CurseForge key** (optional, but recommended). Without it only Modrinth is checked and some mods may show as *Not found*. See [how to get one](#how-to-get-a-curseforge-key).
4. Press **Check my mods**, tick what you want and press **Update**.

## How to get a CurseForge key

CurseForge requires each person to use **their own key** (it can't be shared or bundled with the app).

1. Go to [console.curseforge.com](https://console.curseforge.com/) and sign in (or create an account).
2. If asked, create an organisation with any name.
3. Open the **API Keys** section and copy your key.
4. In Mod Updater, paste it into *CurseForge key* and press **Test**. If it says "Valid key", you're done.

## FAQ

<details>
<summary><b>Windows says "Windows protected your PC" (SmartScreen). Is it dangerous?</b></summary>

It appears because the executable isn't signed with a paid certificate, not because anything was detected. Press **More info → Run anyway**. If you'd rather check first, see *How do I check the .exe is the original?* below; the full source code is in this repository.
</details>

<details>
<summary><b>My antivirus says the <code>.exe</code> is suspicious</b></summary>

A minor antivirus may give a **false positive**. It happens to many programs built with PyInstaller, because from the outside they resemble others that really are malicious. For example, version 0.2.0 is clean on Microsoft Defender, Kaspersky, ESET, Bitdefender and SentinelOne, and only 2 of VirusTotal's 71 engines flag it (Bkav Pro and SecureAge).

- Each Release's notes link to the **VirusTotal scan** of the exact file, so you can see for yourself.
- Check your file is the original (see the next question).
- If your antivirus blocks it, download **`ModUpdater-…-carpeta.zip`** from the same Release. It's the same program as a folder: unzip it and open the `ModUpdater.exe` inside.
</details>

<details>
<summary><b>How do I check the <code>.exe</code> is the original?</b></summary>

Every Release includes the **SHA-256** of each file, in the notes and in `ModUpdater.exe.sha256`. It's a unique fingerprint: changing a single byte of the file would give a different one.

1. Open PowerShell in the folder where you downloaded the file.
2. Run:
   ```powershell
   Get-FileHash .\ModUpdater.exe -Algorithm SHA256
   ```
3. The `Hash` value must match the one in the Release (upper or lower case doesn't matter). If it doesn't match, don't open it and download it again from this repository's *Releases* page.
</details>

<details>
<summary><b>Where is my key stored? Is it safe?</b></summary>

- It's stored in **Windows Credential Manager**, not in a file.
- It's never shown in full: only the last 4 characters.
- It's only sent to CurseForge's servers (`api.curseforge.com` and its download CDN). No other site receives it, even if a download redirects elsewhere.
- It never appears in logs or error messages.
- You can delete it at any time from *Settings → Delete key*.
</details>

<details>
<summary><b>What if an update breaks something?</b></summary>

Press **Undo** on the final screen, or *Settings → Undo the last update*. The old files go back to the `mods` folder and the new ones are set aside (not deleted) in `.minecraft\mods_backup\<date>\undo`. Each backup has a `cambios.txt` that explains what changed.
</details>

<details>
<summary><b>A mod shows as "Up to date", but the website has a newer version.</b></summary>

If the newer version is a **beta** and you have the stable one, the app doesn't suggest it and tells you "A newer beta is available". To have betas suggested, enable them in *Settings*.
</details>

<details>
<summary><b>What does "Manual download" mean? And "Not found"?</b></summary>

- **Manual download:** there's a new version, but the author doesn't allow other apps to download it. Press *Open page* and download it from the website.
- **Not found:** the file isn't on CurseForge or Modrinth (your own mod, or downloaded elsewhere). It's left as is.
</details>

<details>
<summary><b>Does it work with Forge, Fabric or other Minecraft versions?</b></summary>

It's designed for NeoForge, Forge, Fabric and Quilt, and for any Minecraft version that has mods on CurseForge or Modrinth: choose the version and loader in *Settings*. But **it has only been tested with NeoForge 1.21.1**. Other combinations should work, but there may be bugs; if you find one, [let us know](https://github.com/racsoga/mod_updater_Minecraft/issues/new/choose).
</details>

## Privacy

- **No telemetry or analytics.** The app doesn't send usage data to anyone.
- To identify your mods it sends CurseForge and Modrinth the **fingerprint** (hash) of each `.jar` file, not the file or your data.
- It only connects to `api.curseforge.com`, `api.modrinth.com` and their download and image servers (`forgecdn.net`, `modrinth.com`).
- What it stores stays on your PC: settings in `%APPDATA%\mod_updater`, the key in Credential Manager and backups in `.minecraft\mods_backup`.

## Disclaimer

Mod Updater is an **unofficial** personal project. It is not affiliated with, sponsored or endorsed by Mojang Studios, Microsoft, CurseForge (Overwolf) or Modrinth. *Minecraft* is a trademark of Mojang Studios and Microsoft. Mods belong to their authors; the app only downloads them from the official sources.

## For developers

<details>
<summary>Run from source, command line, tests and build</summary>

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-dev.txt

.venv\Scripts\python -m mod_updater.gui        :: the app (or double-click ModUpdater.pyw)
.venv\Scripts\python -m mod_updater            :: CLI: checks without changing anything
.venv\Scripts\python -m mod_updater --apply    :: CLI: updates (asks for confirmation)
.venv\Scripts\python -m pytest                 :: tests
.venv\Scripts\python -m PyInstaller packaging\ModUpdater.spec --noconfirm --distpath build/dist --workpath build/work
```

During development the key can go in a `.env` file (`CF_API_KEY=…`, see `.env.example`); it's in `.gitignore`.

**Releasing a version:** update `CHANGELOG.md` and `mod_updater/__init__.py`, then create a `vX.Y.Z` tag. GitHub Actions runs the tests, builds `ModUpdater.exe` with the icon and creates the Release with the changelog notes.

Structure and technical decisions (in Spanish): [`docs/PLAN.md`](docs/PLAN.md) and [`docs/PLAN_v2.md`](docs/PLAN_v2.md).
</details>

## License

[MIT](LICENSE) © 2026 Oscar Gonzalez

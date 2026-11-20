"""Detecta si Minecraft está abierto usando la carpeta del juego que vamos a tocar."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

JAVA_NAMES = ("javaw.exe", "java.exe")

# PowerShell: "<pid>\t<línea de comandos>" por cada proceso java/javaw.
_PS_SCRIPT = (
    "Get-CimInstance Win32_Process -Filter \"Name='javaw.exe' OR Name='java.exe'\" | "
    "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"
)


def list_java_processes() -> list[tuple[int, str]]:
    """[(pid, línea de comandos)] de los procesos java/javaw. Vacío fuera de Windows o si falla."""
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    procs = []
    for line in out.splitlines():
        pid, _, cmd = line.partition("\t")
        if pid.strip().isdigit():
            procs.append((int(pid), cmd))
    return procs


def _norm(path: str) -> str:
    return path.replace("/", "\\").rstrip("\\").lower()


def minecraft_running(game_dir: Path, lister: Callable[[], list[tuple[int, str]]] = list_java_processes) -> list[int]:
    """PIDs de procesos java cuya línea de comandos menciona `game_dir`
    (la carpeta `.minecraft` que contiene `mods`)."""
    target = _norm(str(game_dir))
    return [pid for pid, cmd in lister() if target in _norm(cmd)]

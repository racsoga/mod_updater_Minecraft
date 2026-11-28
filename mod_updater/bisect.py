"""Búsqueda por mitades del mod que rompe la partida (hito 5 del plan v4).

Cada vuelta desactiva la mitad de los sospechosos (renombrándolos a `.jar.disabled`) y la persona
abre Minecraft y dice si sigue fallando:
- si sigue fallando, el culpable está entre los que siguen activos;
- si deja de fallar, está entre los desactivados.

Nunca deja un mod activo sin su librería: al desactivar algo se desactiva también todo lo que lo
necesita (según las dependencias que se calcularon al empezar). Si nunca se ha visto que el fallo
desaparezca, el último sospechoso se comprueba en una vuelta más (así se sabe si el problema no
está en ningún mod). El estado se guarda para poder retomar tras cerrar la app, y al terminar o
cancelar todo vuelve a estar como al principio.

Los nombres son los de los jars activos (`x.jar`), que es lo que se renombra en disco.
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

SUFFIX = ".disabled"


@dataclass
class Bisect:
    original: list[str]  # jars activos al empezar (lo que se restaura)
    needs: dict[str, list[str]]  # jar -> jars que necesita (entre los originales)
    suspects: list[str]
    testing: list[str] = field(default_factory=list)  # desactivados en esta vuelta
    round: int = 0
    max_rounds: int = 0
    proven: bool = False  # ya se vio que el fallo desaparece al desactivar algo
    done: bool = False
    result: list[str] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)  # jar -> nombre visible

    # ------------------------------------------------------------------ ciclo

    @classmethod
    def start(cls, active: list[str], needs: dict, *, excluded=(), names: dict | None = None) -> "Bisect":
        active = sorted(dict.fromkeys(active))
        suspects = [n for n in active if n not in set(excluded)]
        b = cls(original=active, needs={k: sorted(set(v) & set(active)) for k, v in needs.items() if k in active},
                suspects=suspects, names=dict(names or {}),
                max_rounds=math.ceil(math.log2(len(suspects))) + 1 if len(suspects) > 1 else 1)
        if not suspects:
            b.done = True
        else:
            b._next()
        return b

    def answer(self, fails: bool) -> None:
        """Respuesta de la vuelta actual: ¿sigue fallando con `testing` desactivados?"""
        if self.done:
            return
        tested = set(self.testing)
        if fails:
            self.suspects = [s for s in self.suspects if s not in tested]
        else:
            self.suspects = [s for s in self.suspects if s in tested]
            self.proven = True
        self._next()

    def _next(self) -> None:
        if not self.suspects:  # desactivando cualquier sospechoso sigue fallando: no es un mod
            self._finish([])
            return
        if len(self.suspects) == 1 and self.proven:
            self._finish(self.suspects)
            return
        if len(self.suspects) == 1:  # comprobar el último: ¿deja de fallar sin él?
            self._plan(self.suspects)
            return
        part = self._balanced_part()
        if part:
            self._plan(part)
        else:  # no se puede separar (dependencias en círculo): es el grupo entero
            self._finish(self.suspects) if self.proven else self._plan(self.suspects)

    def _balanced_part(self) -> list[str]:
        """La parte cuya prueba (ella y lo que la necesita) deja a los sospechosos lo más cerca
        posible de la mitad. Primero los que arrastran menos dependientes."""
        sus = set(self.suspects)
        order = sorted(self.suspects, key=lambda x: (len(self._closure([x]) & sus), x))
        best, part = None, []
        for x in order:
            part.append(x)
            size = len(self._closure(part) & sus)
            if size >= len(sus):
                break
            score = abs(size - len(sus) / 2)
            if best is None or score < best[0]:
                best = (score, list(part))
        return best[1] if best else []

    @property
    def rounds_left(self) -> int:
        """Vueltas que quedan, aproximadas (con dependencias las mitades no siempre son iguales)."""
        if self.done:
            return 0
        k = len(self.suspects)
        return (math.ceil(math.log2(k)) if k > 1 else 0) + (0 if self.proven else 1)

    def _plan(self, part: list[str]) -> None:
        self.testing = sorted(self._closure(part))
        self.round += 1

    def _finish(self, result: list[str]) -> None:
        self.done, self.result, self.testing = True, sorted(result), []

    def _closure(self, part) -> set[str]:
        """`part` y todo lo que lo necesita (directa o indirectamente)."""
        out = set(part)
        changed = True
        while changed:
            changed = False
            for jar, deps in self.needs.items():
                if jar not in out and out & set(deps):
                    out.add(jar)
                    changed = True
        return out

    # ------------------------------------------------------------------ datos

    def display(self, jar: str) -> str:
        return self.names.get(jar) or jar

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Bisect":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


# --------------------------------------------------------------------------- disco y estado

def state_file(cache_dir: Path, profile_id: str | None) -> Path:
    """Archivo con la búsqueda en curso de un perfil (en la caché de la app)."""
    pid = "".join(c if c.isalnum() or c in "-_" else f"~{ord(c):x}" for c in (profile_id or "principal").lower())
    return Path(cache_dir) / f"bisect-{pid}.json"


def active_for_folder(mods_dir: Path, settings_file: Path | None = None) -> bool:
    """¿Hay una búsqueda por mitades en curso en esa carpeta? (para que la CLI no toque nada)."""
    import json

    from .settings import app_dir, load_settings  # aquí para no crear un import circular

    s = load_settings(settings_file)
    norm = lambda p: os.path.normcase(os.path.normpath(str(p)))  # noqa: E731
    for p in s.profiles:
        f = state_file(app_dir() / "cache", p.get("id"))
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if norm(data.get("mods_dir", "")) == norm(mods_dir):
            return True
    return False

def _rename(src: Path, dst: Path) -> bool:
    if dst.exists():  # nunca se sobrescribe nada
        return False
    try:
        os.replace(src, dst)
    except OSError:
        return False
    return True


def apply_round(mods_dir: Path, b: Bisect) -> list[str]:
    """Deja activos los originales salvo `testing`. Devuelve los jars que no se pudieron cambiar."""
    problems = []
    off = set(b.testing)
    for jar in b.original:
        on_path, off_path = Path(mods_dir) / jar, Path(mods_dir) / f"{jar}{SUFFIX}"
        if jar in off and on_path.exists():
            if not _rename(on_path, off_path):
                problems.append(jar)
        elif jar not in off and off_path.exists() and not on_path.exists():
            if not _rename(off_path, on_path):
                problems.append(jar)
    return problems


def restore(mods_dir: Path, b: Bisect) -> list[str]:
    """Todo como al empezar: los originales activos otra vez. Devuelve los que no se pudieron."""
    problems = []
    for jar in b.original:
        on_path, off_path = Path(mods_dir) / jar, Path(mods_dir) / f"{jar}{SUFFIX}"
        if off_path.exists() and not _rename(off_path, on_path):
            problems.append(jar)
    return problems

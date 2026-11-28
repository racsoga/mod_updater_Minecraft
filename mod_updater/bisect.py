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
        half = len(self.suspects) // 2
        for part in (self.suspects[:half], self.suspects[half:]):
            test = self._closure(part)
            if not set(self.suspects) <= test:
                self._plan(part)
                return
        self._finish(self.suspects) if self.proven else self._plan(self.suspects)

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


# --------------------------------------------------------------------------- disco

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

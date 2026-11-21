"""Changelog de un mod entre la versión instalada y la nueva, limpio para mostrarlo.

- CurseForge da el changelog de cada archivo en HTML; Modrinth, en Markdown dentro de cada versión.
- Todo pasa por `sanitize_html`: lista blanca de etiquetas, sin scripts, estilos, iframes ni
  atributos de eventos; los enlaces se abren en el navegador del sistema (`data-external`) y las
  imágenes solo se cargan de los CDN de CurseForge y Modrinth.
- Se marcan las palabras que suelen anunciar cambios que rompen partidas.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from markdown_it import MarkdownIt

from .resolver import CF, MR, Resolution

MAX_VERSIONS = 15  # como mucho se piden y muestran tantas versiones (CurseForge: una petición por archivo)

ALLOWED = {"p", "br", "hr", "ul", "ol", "li", "strong", "b", "em", "i", "u", "s", "del", "code", "pre",
           "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "a", "img", "table", "thead", "tbody", "tr", "th", "td",
           "sub", "sup", "details", "summary"}
VOID = {"br", "hr", "img"}
DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math",
                     "form", "select", "textarea", "button", "head", "title", "frame", "frameset", "applet"}
IMG_HOSTS = {"media.forgecdn.net", "edge.forgecdn.net", "mediafilez.forgecdn.net", "cdn.modrinth.com"}
FLAG_WORDS = re.compile(r"\b(breaking|incompatible|requires|world)\b", re.IGNORECASE)


def _safe_url(url: str | None, *, image: bool = False) -> str | None:
    if not url:
        return None
    if any(c in url for c in ("\\", "@")) or any(c.isspace() for c in url.strip()):
        return None  # los navegadores tratan \ como / y "@" separa usuario y host: no fiarse
    parts = urlparse(url.strip())
    if image:
        return url.strip() if parts.scheme == "https" and (parts.hostname or "") in IMG_HOSTS else None
    return url.strip() if parts.scheme in ("http", "https") and parts.hostname else None


class _Sanitizer(HTMLParser):
    def __init__(self, flag: bool = True) -> None:
        super().__init__(convert_charrefs=True)
        self.flag = flag
        self.out: list[str] = []
        self.open: list[str] = []   # etiquetas permitidas abiertas
        self.skip: list[str] = []   # etiquetas cuyo contenido se descarta
        self.text = False           # ¿hay texto visible?

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in DROP_WITH_CONTENT:
                self.skip.append(tag)
            return
        if tag in DROP_WITH_CONTENT:
            self.skip.append(tag)
            return
        if tag not in ALLOWED:
            return  # se quita la etiqueta pero se conserva su contenido
        a = dict(attrs)
        if tag == "li" and self.open and self.open[-1] == "li":
            self._close("li")  # <li> sin cerrar antes del siguiente
        if tag == "a":
            href = _safe_url(a.get("href"))
            self.out.append(f'<a href="{html.escape(href)}" data-external rel="noopener">' if href else "<a>")
        elif tag == "img":
            src = _safe_url(a.get("src"), image=True)
            if src:
                alt = html.escape(a.get("alt") or "")
                self.out.append(f'<img src="{html.escape(src)}" alt="{alt}" loading="lazy">')
                self.text = True
            return
        else:
            self.out.append(f"<{tag}>")
        if tag not in VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        if tag in self.open:
            self._close(tag)

    def _close(self, tag):
        while self.open:
            t = self.open.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if self.skip:
            return
        if data.strip():
            self.text = True
        escaped = html.escape(data, quote=False)
        if not self.flag or "code" in self.open or "pre" in self.open:
            self.out.append(escaped)
        else:
            self.out.append(FLAG_WORDS.sub(lambda m: f'<mark class="cl-flag">{m.group(0)}</mark>', escaped))

    def result(self) -> str:
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out).strip() if self.text else ""


def sanitize_html(raw: str | None, flag: bool = True) -> str:
    """HTML seguro para insertar en la ventana (cadena vacía si no queda texto visible).
    `flag`: resaltar las palabras de aviso (solo en changelogs, no en descripciones)."""
    if not raw:
        return ""
    s = _Sanitizer(flag)
    s.feed(raw)
    s.close()
    return s.result()


_MD = MarkdownIt("commonmark", {"html": False})  # el HTML crudo del Markdown se muestra como texto


def markdown_to_html(text: str | None, flag: bool = True) -> str:
    return sanitize_html(_MD.render(text or ""), flag) if text else ""


def _between(items: list, date_of, current: str | None, new: str | None) -> list:
    """Versiones publicadas después de la instalada y hasta la nueva, de la más nueva a la más vieja."""
    out = [i for i in items if date_of(i) and (not current or date_of(i) > current) and (not new or date_of(i) <= new)]
    return sorted(out, key=date_of, reverse=True)


def changelog_for(res: Resolution, *, curseforge, modrinth, game_version: str, loader: str) -> dict:
    """{versions: [{version, date, channel, html}], more: cuántas versiones más viejas no se muestran}."""
    if res.source == CF and curseforge is not None:
        files = _between(curseforge.mod_files(int(res.project_id), game_version, loader),
                         lambda f: f.date_published, res.current_date, res.new_date)
        shown = files[:MAX_VERSIONS]
        versions = [{"version": f.display_name, "date": f.date_published, "channel": f.version_type,
                     "html": sanitize_html(curseforge.file_changelog(int(res.project_id), int(f.id)))} for f in shown]
    elif res.source == MR and modrinth is not None:
        found = _between(modrinth.project_versions(res.project_id, loader, game_version),
                         lambda v: v.date_published, res.current_date, res.new_date)
        shown = found[:MAX_VERSIONS]
        versions = [{"version": v.version_number, "date": v.date_published, "channel": v.version_type,
                     "html": markdown_to_html(v.changelog)} for v in shown]
        files = found
    else:
        return {"versions": [], "more": 0}
    return {"versions": versions, "more": len(files) - len(shown)}

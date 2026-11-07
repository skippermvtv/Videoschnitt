"""„Was ist neu“ nach einem Update: Versionen vergleichen und die passenden Abschnitte der CHANGELOG aufbereiten."""
from __future__ import annotations

import html
import re

MAX_SECTIONS = 4          # bei übersprungenen Versionen höchstens so viele Abschnitte zeigen


def parse_version(v) -> tuple[int, int, int] | None:
    m = re.fullmatch(r"\s*v?(\d+)\.(\d+)\.(\d+)\s*", v) if isinstance(v, str) else None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def sections(changelog: str) -> dict[tuple[int, int, int], str]:
    """{Version: Text des Abschnitts} aus Zeilen wie „## 1.4.3“."""
    out: dict[tuple[int, int, int], str] = {}
    parts = re.split(r"(?m)^##\s+", changelog or "")
    for part in parts[1:]:
        head, _, body = part.partition("\n")
        v = parse_version(head.strip())
        if v and v not in out:
            out[v] = body.strip()
    return out


def decide(last: str, current: str, settings_existed: bool, changelog: str) -> list[tuple[str, str]]:
    """Welche Abschnitte sollen gezeigt werden? Gibt [(Version, Text)] zurück, neueste zuerst; leer = nichts anzeigen.

    - gleiche oder ältere Version als beim letzten Start (z. B. Rückschritt): nichts
    - noch nie gestartet (keine Einstellungen): nichts, die Version wird nur gemerkt
    - kein gemerkter Stand, aber Einstellungen da (Update von einer Version vor 1.4.4): nur die aktuelle Version
    - sonst alle Abschnitte zwischen dem letzten Stand (ausschließlich) und jetzt (einschließlich)"""
    cur = parse_version(current)
    if cur is None:
        return []
    secs = sections(changelog)
    prev = parse_version(last)
    if prev is None:
        if not settings_existed:
            return []
        wanted = [cur] if cur in secs else []
    else:
        if prev >= cur:
            return []
        wanted = sorted((v for v in secs if prev < v <= cur), reverse=True)[:MAX_SECTIONS]
    return [(".".join(map(str, v)), secs[v]) for v in wanted]


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def to_html(items: list[tuple[str, str]]) -> str:
    """Einfaches Markdown (Aufzählung, **fett**, `Code`) → HTML für das Fenster."""
    out = []
    for ver, body in items:
        out.append(f"<h3>Version {html.escape(ver)}</h3>")
        in_list = False
        for line in body.splitlines():
            m = re.match(r"^\s*[-*]\s+(.*)$", line)
            if m:
                if not in_list:
                    out.append("<ul>")
                    in_list = True
                out.append(f"<li>{_inline(m.group(1))}</li>")
            elif line.strip():
                if in_list:
                    out.append("</ul>")
                    in_list = False
                out.append(f"<p>{_inline(line.strip())}</p>")
        if in_list:
            out.append("</ul>")
    return "\n".join(out)

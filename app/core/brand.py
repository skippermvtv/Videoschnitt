"""Marken-Vorlage: Intro, Outro und Logo einmal festlegen und in Projekte einsetzen. Ohne Qt.

Intro und Outro sind ganz normale Clips am Anfang und Ende der Timeline (Feld `Clip.brand`), damit sie sich wie jeder Clip anschauen und
bearbeiten lassen. Beim Einsetzen rücken alle Spuren (Ton, Bild-in-Bild, Effekte, Texte, Untertitel, Marker) mit; erneutes Einsetzen ersetzt die
Markenclips statt sie zu verdoppeln. Die Vorlage liegt in `brand.json` im Benutzerordner.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from ..paths import user_dir
from .project import IMAGE_MAX, Clip, Project, probe

CORNERS = ("tl", "tr", "bl", "br")
IMAGE_SECONDS = 4.0
MIN_IMAGE_SECONDS, MAX_IMAGE_SECONDS = 0.5, 30.0


@dataclass
class Kit:
    intro: str = ""                # Video oder Bild; leer = kein Intro
    outro: str = ""
    image_seconds: float = IMAGE_SECONDS     # so lange steht ein Bild als Intro/Outro
    logo: str = ""                 # Wasserzeichen über dem ganzen Video; leer = keins
    corner: str = "br"
    size: float = 14.0             # Breite in % der Bildbreite
    opacity: float = 80.0
    auto_new: bool = False         # beim Hinzufügen des ersten Clips zu einem leeren Projekt automatisch einsetzen

    def empty(self) -> bool:
        return not (self.intro or self.outro or self.logo)


def _file() -> Path:
    return user_dir() / "brand.json"


def clean(kit: Kit) -> Kit:
    kit.corner = kit.corner if kit.corner in CORNERS else "br"
    try:
        kit.image_seconds = min(MAX_IMAGE_SECONDS, max(MIN_IMAGE_SECONDS, float(kit.image_seconds)))
        kit.size = min(60.0, max(2.0, float(kit.size)))
        kit.opacity = min(100.0, max(0.0, float(kit.opacity)))
    except (TypeError, ValueError):
        kit.image_seconds, kit.size, kit.opacity = IMAGE_SECONDS, 14.0, 80.0
    for name in ("intro", "outro", "logo"):
        v = getattr(kit, name)
        setattr(kit, name, v if isinstance(v, str) else "")
    kit.auto_new = bool(kit.auto_new)
    return kit


def load() -> Kit:
    kit = Kit()
    try:
        raw = json.loads(_file().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for f in fields(Kit):
                if f.name in raw:
                    setattr(kit, f.name, raw[f.name])
    except (OSError, ValueError):
        pass
    return clean(kit)


def save(kit: Kit) -> bool:
    try:
        _file().write_text(json.dumps(asdict(clean(kit)), indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- Einsetzen
def _make_clip(path: str, role: str, seconds: float) -> Clip:
    info = probe(path)
    if info.is_image:
        c = Clip(path, IMAGE_MAX, out_pt=max(MIN_IMAGE_SECONDS, seconds), has_audio=False, width=info.width, height=info.height, is_image=True)
    else:
        c = Clip(path, info.duration, has_audio=info.has_audio, width=info.width, height=info.height)
    c.brand = role
    return c


def _shift_tracks(project: Project, dt: float) -> None:
    """Alles auf den Spuren über dem Hauptvideo um `dt` Sekunden verschieben (negativ = früher, nie vor 0)."""
    if abs(dt) < 1e-9:
        return

    def mv(t: float) -> float:
        return max(0.0, round(t + dt, 3))

    for a in project.audio_clips:
        if a.kind != "video":                      # getrennte Töne folgen ihrem Clip (sync_linked)
            a.start = mv(a.start)
    for o in project.overlays:
        o.start = mv(o.start)
    for t in project.texts:
        t.start, t.end = mv(t.start), mv(t.end)
    for e in project.effects:
        if "start" in e:
            e["start"] = mv(float(e["start"]))
        if "end" in e:
            e["end"] = mv(float(e["end"]))
    for cue in project.subtitles:
        cue.start, cue.end = mv(cue.start), mv(cue.end)
    for m in project.markers or []:
        if isinstance(m, dict) and "t" in m:
            m["t"] = mv(float(m["t"]))


def remove_clips(project: Project) -> int:
    """Nimmt Intro und Outro aus dem Projekt (Spuren rücken zurück). Gibt die Zahl der entfernten Clips zurück."""
    n = 0
    while project.clips and project.clips[0].brand == "intro":
        dt = project.clips[0].length
        del project.clips[0]
        project.sync_linked()
        _shift_tracks(project, -dt)
        n += 1
    keep = [c for c in project.clips if c.brand != "outro"]
    n += len(project.clips) - len(keep)
    project.clips[:] = keep
    project.sync_linked()
    return n


def apply(project: Project, kit: Kit) -> list[str]:
    """Setzt die Vorlage ein; gibt Hinweise zurück (z. B. fehlende Dateien). Ersetzt vorhandene Markenclips."""
    kit = clean(kit)
    notes: list[str] = []
    remove_clips(project)
    for role, path in (("intro", kit.intro), ("outro", kit.outro)):
        if not path:
            continue
        label = "Intro" if role == "intro" else "Outro"
        if not os.path.exists(path):
            notes.append(f"{label}: Datei nicht gefunden ({Path(path).name}) – ausgelassen.")
            continue
        try:
            c = _make_clip(path, role, kit.image_seconds)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{label}: {Path(path).name} lässt sich nicht lesen ({str(exc)[:100]}) – ausgelassen.")
            continue
        if role == "intro":
            project.clips.insert(0, c)
            project.sync_linked()
            _shift_tracks(project, c.length)
        else:
            project.clips.append(c)
    project.sync_linked()
    if kit.logo:
        if os.path.exists(kit.logo):
            project.watermark, project.wm_corner, project.wm_size, project.wm_opacity = kit.logo, kit.corner, kit.size, kit.opacity
        else:
            notes.append(f"Logo: Datei nicht gefunden ({Path(kit.logo).name}) – ausgelassen.")
    return notes


def remove(project: Project, kit: Kit | None = None) -> int:
    """Nimmt Intro/Outro heraus und das Logo, wenn es das der Vorlage ist. Gibt die Zahl der entfernten Clips zurück."""
    n = remove_clips(project)
    if kit is not None and kit.logo and project.watermark == kit.logo:
        project.watermark = ""
    return n


def insert_position(project: Project) -> int:
    """Stelle für neue Clips: vor einem Outro der Vorlage, sonst am Ende."""
    n = len(project.clips)
    while n > 0 and project.clips[n - 1].brand == "outro":
        n -= 1
    return n

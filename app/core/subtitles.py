"""Untertitel: SRT lesen/schreiben, automatisch erzeugen (whisper.cpp), in Textebenen umwandeln."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from .. import paths
from ..paths import find_binary
from .project import Project, SubtitleCue, SubtitleStyle, TextLayer

_NOWINDOW = 0x08000000


# ----------------------------------------------------------------------------- SRT
def _ts(t: float) -> str:
    t = max(0.0, t)
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _parse_ts(s: str) -> float:
    m = re.match(r"\s*(?:(\d+):)?(\d+):(\d+)[,.](\d{1,3})", s)
    if not m:
        raise ValueError(s)
    h, mi, se, ms = int(m.group(1) or 0), int(m.group(2)), int(m.group(3)), m.group(4).ljust(3, "0")
    return h * 3600 + mi * 60 + se + int(ms) / 1000.0


def to_srt(cues: list[SubtitleCue]) -> str:
    out = []
    for i, c in enumerate(sorted(cues, key=lambda c: c.start), 1):
        out.append(f"{i}\n{_ts(c.start)} --> {_ts(c.end)}\n{c.text.strip()}\n")
    return "\n".join(out)


def parse_srt(text: str) -> list[SubtitleCue]:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[SubtitleCue] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        for k, ln in enumerate(lines[:3]):
            if "-->" in ln:
                a, b = ln.split("-->", 1)
                try:
                    start, end = _parse_ts(a), _parse_ts(b.split()[0] if b.split() else b)
                except ValueError:
                    break
                body = re.sub(r"</?[a-zA-Z][^>]*>", "", "\n".join(lines[k + 1:])).strip()
                if body:
                    cues.append(SubtitleCue(start, max(end, start + 0.1), body))
                break
    return cues


def read_srt(path: str) -> list[SubtitleCue]:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return parse_srt(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    return parse_srt(raw.decode("latin-1"))


def write_srt(path: str, cues: list[SubtitleCue]) -> None:
    Path(path).write_text(to_srt(cues), encoding="utf-8")


# ------------------------------------------------------------------ Textebenen
def split_long(cues: list[SubtitleCue], max_chars: int = 38) -> list[SubtitleCue]:
    """Teilt zu lange Einträge an Wortgrenzen in mehrere kurze, zeitlich anteilig."""
    out: list[SubtitleCue] = []
    for c in cues:
        flat = " ".join(c.text.split())
        if len(flat) <= max_chars * 2:
            out.append(c)
            continue
        words, parts, cur = flat.split(" "), [], ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_chars * 2:
                parts.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            parts.append(cur)
        total = sum(len(x) for x in parts) or 1
        t = c.start
        for x in parts:
            d = (c.end - c.start) * len(x) / total
            out.append(SubtitleCue(t, t + d, x))
            t += d
    return out


def cue_layers(cues: list[SubtitleCue], st: SubtitleStyle, limit: float | None = None) -> list[TextLayer]:
    layers = []
    for c in sorted(cues, key=lambda c: c.start):
        if not c.text.strip() or (limit is not None and c.start >= limit):
            continue
        layers.append(TextLayer(text=c.text.strip(), start=c.start, end=c.end, position=st.position,
                                size_pct=st.size_pct, color=st.color, border_color=st.border_color, font=st.font,
                                anim=st.anim, anim_dur=st.anim_dur, box=st.box,
                                karaoke=(st.karaoke_color if st.karaoke else ""), karaoke_mode=st.karaoke_mode))
    return layers


# ------------------------------------------------------------ automatische Erkennung
def whisper_dir() -> Path:
    d = paths.user_dir() / "whisper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_whisper_program() -> str | None:
    d = whisper_dir()
    for name in ("whisper-cli.exe", "whisper-cli", "main.exe", "main"):
        for cand in [d / name, *d.rglob(name)]:
            if cand.is_file():
                return str(cand)
    return None


def find_whisper_model() -> str | None:
    """Bevorzugt base/small; sonst das größte vorhandene Modell."""
    models = sorted(whisper_dir().rglob("ggml-*.bin"), key=lambda p: p.stat().st_size)
    if not models:
        return None
    pref = [m for m in models if "base" in m.name or "small" in m.name]
    return str((pref or models)[-1])


def find_whisper() -> tuple[str, str] | None:
    """(Programm, Modell) aus %APPDATA%\\FATE VIDEOSCHNITT\\whisper – oder None. Erwartet whisper.cpp."""
    exe, model = find_whisper_program(), find_whisper_model()
    return (exe, model) if exe and model else None


def transcribe(wav: str, language: str = "auto", on_done=None) -> list[SubtitleCue]:
    """Erzeugt Untertitel aus einer 16-kHz-WAV mit whisper.cpp. Wirft RuntimeError bei Problemen."""
    found = find_whisper()
    if not found:
        raise RuntimeError("whisper.cpp wurde nicht gefunden.")
    exe, model = found
    out_prefix = str(Path(tempfile.mkdtemp(prefix="clipforge_whisper_")) / "out")
    cmd = [exe, "-m", model, "-f", wav, "-osrt", "-of", out_prefix, "-l", language, "-ml", "42", "-sow"]
    flags = _NOWINDOW if os.name == "nt" else 0
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=flags)
    srt = out_prefix + ".srt"
    if r.returncode != 0 or not os.path.exists(srt):
        raise RuntimeError("Spracherkennung fehlgeschlagen:\n" + (r.stderr or r.stdout)[-600:])
    return read_srt(srt)


def extract_wav(video: str, out_wav: str) -> None:
    cmd = [find_binary("ffmpeg"), "-v", "error", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", out_wav]
    flags = _NOWINDOW if os.name == "nt" else 0
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=flags)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-400:])


def transcribe_project(project: Project, language: str = "auto", draft_runner=None) -> list[SubtitleCue]:
    """Rendert den Ton des Projekts (schneller Entwurf), erkennt Sprache und gibt Untertitel zurück."""
    from . import exporter
    tmp = Path(tempfile.mkdtemp(prefix="clipforge_asr_"))
    mp4 = str(tmp / "draft.mp4")
    saved_t, saved_s, saved_o = project.texts, project.subtitles, project.overlays
    try:
        project.texts, project.subtitles, project.overlays = [], [], []
        cmd, total, _ = exporter.build_command(project, mp4, draft=True)
    finally:
        project.texts, project.subtitles, project.overlays = saved_t, saved_s, saved_o
    (draft_runner or exporter.run)(cmd, total)
    wav = str(tmp / "a.wav")
    extract_wav(mp4, wav)
    return transcribe(wav, language)

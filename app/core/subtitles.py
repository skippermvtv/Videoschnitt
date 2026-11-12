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
def _split_with_words(c: SubtitleCue, parts: list[str], n_words: int) -> list[SubtitleCue] | None:
    """Teilt einen Eintrag mit echten Wortzeiten in die Teile `parts`; None, wenn die Wortzeiten nicht zum Text passen."""
    real = c.words
    if not isinstance(real, list) or len(real) != n_words:
        return None
    out: list[SubtitleCue] = []
    k = 0
    try:
        for pi, x in enumerate(parts):
            n = len(x.split(" "))
            chunk = real[k:k + n]
            k += n
            t0 = c.start + float(chunk[0][1]) if pi else c.start
            nxt = c.start + float(real[k][1]) if k < len(real) else c.end
            t1 = max(t0 + 0.05, min(nxt, c.end))
            shift = t0 - c.start
            out.append(SubtitleCue(t0, t1, x, [[w[0], round(max(0.0, float(w[1]) - shift), 3), round(max(0.0, float(w[2]) - shift), 3)]
                                               for w in chunk]))
    except (TypeError, ValueError, IndexError):
        return None
    return out


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
        pieces = _split_with_words(c, parts, len(words))
        if pieces is not None:                            # echte Wortzeiten: Schnitte an den Wortgrenzen, Zeiten bleiben genau
            out.extend(pieces)
            continue
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
                                karaoke=(st.karaoke_color if st.karaoke else ""), karaoke_mode=st.karaoke_mode,
                                words=list(c.words or [])))
    return layers


# ------------------------------------------------------------ SRT-Datei beim Export
def srt_path_for(video: str) -> str:
    """Die SRT-Datei liegt neben dem Video und heißt genauso (Mein Film.mp4 → Mein Film.srt)."""
    return str(Path(video).with_suffix(".srt"))


def export_cues(project: Project) -> list[SubtitleCue]:
    """Die Einträge so, wie sie zum Video passen: ohne leere, nach Zeit sortiert, auf die Länge des Videos begrenzt."""
    total = max(0.0, project.duration)
    out: list[SubtitleCue] = []
    for c in sorted(project.subtitles, key=lambda c: c.start):
        text = "\n".join(ln.strip() for ln in c.text.splitlines() if ln.strip())     # leere Zeilen würden die SRT zerreißen
        if not text or c.start >= total or c.end <= c.start:
            continue
        out.append(SubtitleCue(max(0.0, c.start), min(c.end, total), text))
    return out


def write_export_srt(project: Project, video: str) -> str | None:
    """Schreibt die SRT neben das Video; gibt den Pfad zurück oder None, wenn es keine Untertitel gibt."""
    cues = export_cues(project)
    if not cues:
        return None
    path = srt_path_for(video)
    write_srt(path, cues)
    return path


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


def parse_whisper_json(path: str) -> list[SubtitleCue]:
    """Liest die „volle“ JSON-Ausgabe von whisper.cpp (-ojf): Einträge mit Wortzeiten (Sekunden ab Beginn des Eintrags).
    Ein Wort besteht aus Teilstücken (Tokens); ein Teilstück mit führendem Leerzeichen beginnt ein neues Wort, Satzzeichen kleben am Wort."""
    import json
    data = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    cues: list[SubtitleCue] = []
    for seg in data.get("transcription", []):
        off = seg.get("offsets") or {}
        s0, s1 = float(off.get("from", 0)) / 1000.0, float(off.get("to", 0)) / 1000.0
        text = " ".join(str(seg.get("text", "")).split())
        if not text or s1 <= s0:
            continue
        words: list[list] = []
        for tok in seg.get("tokens", []):
            t = str(tok.get("text", ""))
            if (t.strip().startswith("[_") and t.strip().endswith("]")) or not t.strip():
                continue                                   # Steuerzeichen wie [_BEG_] und leere Teilstücke
            to = tok.get("offsets") or {}
            a, b = float(to.get("from", 0)) / 1000.0 - s0, float(to.get("to", 0)) / 1000.0 - s0
            if words and not t[:1].isspace():
                words[-1][0] += t.strip()
                words[-1][2] = max(words[-1][2], round(b, 3))
            else:
                words.append([t.strip(), round(max(0.0, a), 3), round(max(0.0, b), 3)])
        cues.append(SubtitleCue(s0, s1, text, words if " ".join(w[0] for w in words) == text else []))
    return cues


def attach_words(srt_cues: list[SubtitleCue], json_cues: list[SubtitleCue]) -> list[SubtitleCue]:
    """Überträgt die Wortzeiten auf die Einträge der SRT (gleiche Reihenfolge und Zeiten; sonst unverändert)."""
    if len(srt_cues) != len(json_cues):
        return srt_cues
    out = []
    for a, b in zip(srt_cues, json_cues):
        ok = abs(a.start - b.start) < 0.06 and abs(a.end - b.end) < 0.06 and a.text.split() == b.text.split()
        out.append(SubtitleCue(a.start, a.end, a.text, list(b.words) if ok else []))
    return out


def transcribe(wav: str, language: str = "auto", on_done=None) -> list[SubtitleCue]:
    """Erzeugt Untertitel aus einer 16-kHz-WAV mit whisper.cpp. Wirft RuntimeError bei Problemen."""
    found = find_whisper()
    if not found:
        raise RuntimeError("whisper.cpp wurde nicht gefunden.")
    exe, model = found
    out_prefix = str(Path(tempfile.mkdtemp(prefix="clipforge_whisper_")) / "out")
    cmd = [exe, "-m", model, "-f", wav, "-osrt", "-ojf", "-of", out_prefix, "-l", language, "-ml", "42", "-sow"]
    flags = _NOWINDOW if os.name == "nt" else 0
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=flags)
    srt = out_prefix + ".srt"
    if r.returncode != 0 or not os.path.exists(srt):
        raise RuntimeError("Spracherkennung fehlgeschlagen:\n" + (r.stderr or r.stdout)[-600:])
    cues = read_srt(srt)
    js = out_prefix + ".json"
    if os.path.exists(js):                       # echte Wortzeiten dazu (Karaoke); fehlt die Datei oder passt sie nicht, bleibt es bei der SRT
        try:
            cues = attach_words(cues, parse_whisper_json(js))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return cues


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

"""Mischt Ton-Spuren (Video-Ton, A1 Ton, A2 Musik, A3 frei) zu einer Tonspur.

Eingabe ist das Label des Video-Tons ("[ac]"); Ergebnis ist ein neues Label.
Alle Zeiten sind absolute Sekunden auf der Timeline.
"""
from __future__ import annotations

from . import audiofix
from pathlib import Path

from .project import AudioClip, Project, probe


def _atempo_chain(speed: float) -> str:
    parts = []
    s = speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


LUFS_CHOICES = (-14.0, -16.0, -23.0)


def lufs_goal(project: Project) -> float:
    """Ziel-Lautheit; Unsinniges (kaputte Projektdatei) fällt auf −14 zurück."""
    try:
        v = float(project.lufs_target)
    except (TypeError, ValueError):
        return -14.0
    return v if -40.0 <= v <= -5.0 else -14.0


def duck_ratio(amount: float) -> float:
    """Kompressionsverhältnis des Duckings: quadratisch, damit niedrige Stärken wirklich nur leicht absenken."""
    a = max(0.0, min(1.0, float(amount)))
    return 1.0 + a * a * 19.0


_audio_cache: dict[tuple, bool] = {}


def has_audio_stream(path: str) -> bool:
    """Hat die Datei eine Tonspur? (zwischengespeichert; bei Fehlern „nein“, damit der Export nicht daran scheitert)"""
    try:
        st = Path(path).stat()
        key = (path, st.st_size, st.st_mtime_ns)
    except OSError:
        return False
    if key not in _audio_cache:
        try:
            _audio_cache[key] = bool(probe(path).has_audio)
        except Exception:  # noqa: BLE001
            _audio_cache[key] = False
    return _audio_cache[key]


def overlay_sound_on(o) -> bool:
    return bool(getattr(o, "sound", False)) and not o.is_image and float(getattr(o, "volume", 100.0)) > 0.0


def effective_volume(project: Project, a: AudioClip) -> float:
    if a.mute or project.track_mute.get(str(a.track)):
        return 0.0
    return max(0.0, a.volume) * max(0.0, float(project.track_volume.get(str(a.track), 1.0)))


def _mix(labels: list[str], out: str) -> str:
    if len(labels) == 1:
        return f"[{labels[0]}]anull[{out}]"
    ins = "".join(f"[{l}]" for l in labels)
    return f"{ins}amix=inputs={len(labels)}:duration=longest:normalize=0[{out}]"


def build_audio(project: Project, total: float, first_input: int, bed: str = "ac",
                out: str = "aout") -> tuple[list[str], list[str]]:
    """Gibt (zusätzliche ffmpeg-Eingaben, Filterzeilen) zurück. Das Ergebnis liegt in [out]."""
    cmd: list[str] = []
    g: list[str] = []
    track_labels: dict[int, list[str]] = {1: [], 2: [], 3: []}
    k = first_input

    for j, a in enumerate(project.audio_clips):
        vol = effective_volume(project, a)
        if vol <= 0 or a.start >= total - 0.01:
            continue
        sp = max(0.1, min(a.speed, 20.0))
        seg = max(0.05, a.out_pt - a.in_pt)
        seg_len = seg / sp
        cmd += ["-ss", f"{a.in_pt:.3f}", "-t", f"{seg:.3f}", "-i", a.path]
        chain = f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo"
        fix = audiofix.chain(a.denoise, a.voice, audiofix.noise_floor(a.path, a.in_pt, a.out_pt) if a.denoise > 0 else None)
        if fix:
            chain += "," + fix
        if a.reverse:
            chain += ",areverse"
        if abs(sp - 1.0) > 1e-3:
            chain += "," + _atempo_chain(sp)
        length = seg_len
        if a.loop:
            length = max(seg_len, total - a.start)
            chain += f",aloop=loop=-1:size={int(seg_len * 48000) + 1},atrim=duration={length:.3f}"
        chain += ",asetpts=PTS-STARTPTS"
        if abs(vol - 1.0) > 1e-3:
            chain += f",volume={vol:.4f}"
        if a.fade_in > 0:
            chain += f",afade=t=in:st=0:d={min(a.fade_in, length):.3f}"
        if a.fade_out > 0:
            fo = min(a.fade_out, length)
            chain += f",afade=t=out:st={max(0.0, length - fo):.3f}:d={fo:.3f}"
        ms = int(round(max(0.0, a.start) * 1000))
        if ms > 0:
            chain += f",adelay={ms}|{ms}"
        label = f"x{j}"
        g.append(f"{chain}[{label}]")
        track_labels.setdefault(a.track if a.track in (1, 2, 3) else 3, []).append(label)
        k += 1

    # Ton von Bild-in-Bild-Blöcken (Schalter am Block): gehört zur Sprach-Gruppe
    for j, o in enumerate(project.overlays):
        if not overlay_sound_on(o) or o.start >= total - 0.05 or not has_audio_stream(o.path):
            continue
        osp = max(0.1, min(o.speed, 20.0))
        oseg = max(0.05, o.out_pt - o.in_pt)
        olen = oseg / osp
        cmd += ["-ss", f"{o.in_pt:.3f}", "-t", f"{oseg:.3f}", "-i", o.path]
        chain = f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo"
        if getattr(o, "reverse", False):
            chain += ",areverse"
        if abs(osp - 1.0) > 1e-3:
            chain += "," + _atempo_chain(osp)
        chain += f",atrim=duration={olen:.3f},asetpts=PTS-STARTPTS"
        vol = max(0.0, float(o.volume)) / 100.0
        if abs(vol - 1.0) > 1e-3:
            chain += f",volume={vol:.4f}"
        if o.fade_in > 0:
            chain += f",afade=t=in:st=0:d={min(o.fade_in, olen):.3f}"
        if o.fade_out > 0:
            fo = min(o.fade_out, olen)
            chain += f",afade=t=out:st={max(0.0, olen - fo):.3f}:d={fo:.3f}"
        ms = int(round(max(0.0, o.start) * 1000))
        if ms > 0:
            chain += f",adelay={ms}|{ms}"
        g.append(f"{chain}[ox{j}]")
        track_labels[1].append(f"ox{j}")
        k += 1

    speech = [bed] + track_labels[1]
    music = track_labels[2] + track_labels[3]

    if not music and not track_labels[1]:
        g.append(f"[{bed}]anull[mx]")
    else:
        g.append(_mix(speech, "sp") if len(speech) > 1 else f"[{bed}]anull[sp]")
        if music:
            g.append(_mix(music, "mu"))
            if project.ducking:
                ratio = duck_ratio(project.ducking_amount)
                g.append("[sp]asplit=2[spa][spb]")
                g.append(f"[mu][spb]sidechaincompress=threshold=0.03:ratio={ratio:.2f}:"
                         f"attack=20:release=300:makeup=1[mud]")
                g.append("[spa][mud]amix=inputs=2:duration=longest:normalize=0[mx]")
            else:
                g.append("[sp][mu]amix=inputs=2:duration=longest:normalize=0[mx]")
        else:
            g.append("[sp]anull[mx]")

    tail = f"[mx]aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=duration={total:.3f},apad=whole_dur={total:.3f}"
    if project.fade_in > 0:
        tail += f",afade=t=in:st=0:d={project.fade_in:.2f}"
    if project.fade_out > 0:
        tail += f",afade=t=out:st={max(0.0, total - project.fade_out):.2f}:d={project.fade_out:.2f}"
    if project.normalize:
        tail += f",loudnorm=I={lufs_goal(project):g}:TP=-1.5:LRA=11,aresample=48000,alimiter=limit=0.89"
        tail += f",atrim=duration={total:.3f},apad=whole_dur={total:.3f}"
    g.append(f"{tail}[{out}]")
    return cmd, g

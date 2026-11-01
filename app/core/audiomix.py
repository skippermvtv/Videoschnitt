"""Mischt Ton-Spuren (Video-Ton, A1 Ton, A2 Musik, A3 frei) zu einer Tonspur.

Eingabe ist das Label des Video-Tons ("[ac]"); Ergebnis ist ein neues Label.
Alle Zeiten sind absolute Sekunden auf der Timeline.
"""
from __future__ import annotations

from .project import AudioClip, Project


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

    speech = [bed] + track_labels[1]
    music = track_labels[2] + track_labels[3]

    if not music and not track_labels[1]:
        g.append(f"[{bed}]anull[mx]")
    else:
        g.append(_mix(speech, "sp") if len(speech) > 1 else f"[{bed}]anull[sp]")
        if music:
            g.append(_mix(music, "mu"))
            if project.ducking:
                ratio = 1.0 + max(0.0, min(1.0, project.ducking_amount)) * 19.0
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
        tail += ",loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,alimiter=limit=0.89"
        tail += f",atrim=duration={total:.3f},apad=whole_dur={total:.3f}"
    g.append(f"{tail}[{out}]")
    return cmd, g

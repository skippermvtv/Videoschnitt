"""Baut aus einem Projekt den FFmpeg-Aufruf und führt ihn mit Fortschrittsanzeige aus."""
from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Callable

from ..paths import find_binary
from . import presets
from .effects import Ctx, build_graph
from .project import Clip, Project, TextLayer

_NOWINDOW = 0x08000000


class ExportError(Exception):
    pass


def default_font() -> str:
    """Lesbare Systemschrift als Rückfall, wenn keine eigene Schrift gewählt ist."""
    for cand in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(cand):
            return cand
    return ""


def _esc_path(p: str) -> str:
    """Pfad für FFmpeg-Filteroptionen (Windows: C:\\x → C\\:/x)."""
    return p.replace("\\", "/").replace(":", "\\:").replace("'", r"\'")


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


def _layout_chain(i: int, W: int, H: int, mode: str) -> str:
    src, dst = f"c{i}s", f"v{i}"
    if mode == "fill":
        return (f"[{src}]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},setsar=1[{dst}]")
    if mode == "blur":
        bg, fg, bgb, fgs = f"c{i}bg", f"c{i}fg", f"c{i}bb", f"c{i}fs"
        return (
            f"[{src}]split[{bg}][{fg}];"
            f"[{bg}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"gblur=sigma=40:steps=2[{bgb}];"
            f"[{fg}]scale={W}:{H}:force_original_aspect_ratio=decrease[{fgs}];"
            f"[{bgb}][{fgs}]overlay=(W-w)/2:(H-h)/2,setsar=1[{dst}]"
        )
    # fit
    return (f"[{src}]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[{dst}]")


def _drawtext(layer: TextLayer, idx: int, W: int, H: int, tmpdir: Path) -> str:
    size = max(12, int(H * layer.size_pct / 100.0))
    max_chars = max(6, int(W * 0.88 / (size * 0.52)))
    wrapped = "\n".join(textwrap.fill(line, max_chars) for line in layer.text.splitlines() or [""])
    tf = tmpdir / f"text{idx}.txt"
    tf.write_text(wrapped, encoding="utf-8")
    vertical = H > W
    ypos = {"top": "h*0.14", "center": "(h-text_h)/2",
            "bottom": "h*0.68" if vertical else "h*0.80"}.get(layer.position, "h*0.8")
    font = layer.font or default_font()
    fontopt = f"fontfile='{_esc_path(font)}':" if font else ""
    border = max(2, size // 14)
    return (
        f"drawtext={fontopt}textfile='{_esc_path(str(tf))}':fontsize={size}:"
        f"fontcolor={layer.color}:borderw={border}:bordercolor={layer.border_color}:"
        f"x=(w-text_w)/2:y={ypos}:line_spacing={size // 6}:"
        f"enable='between(t,{layer.start},{layer.end})'"
    )


def build_command(project: Project, out_path: str, *, draft: bool = False,
                  max_seconds: float | None = None) -> tuple[list[str], float, Path]:
    """Gibt (Kommando, Gesamtdauer, temp-Ordner) zurück."""
    if not project.clips:
        raise ExportError("Das Projekt enthält keine Clips.")
    fmt = presets.get("formats", project.format_id)
    exp = presets.get("exports", "fast_draft" if draft else project.export_id)
    if not fmt or not exp:
        raise ExportError("Format- oder Export-Preset nicht gefunden.")

    W, H, fps = int(fmt["width"]), int(fmt["height"]), int(fmt.get("fps", 30))
    if draft:
        W, H = max(2, round(W / 2 / 2) * 2), max(2, round(H / 2 / 2) * 2)
    layout = project.layout or fmt.get("layout", "fit")
    ctx = Ctx(W, H, fps)

    tmp = Path(tempfile.mkdtemp(prefix="clipforge_"))
    cmd = [find_binary("ffmpeg"), "-hide_banner", "-y", "-progress", "pipe:1", "-nostats"]
    graph: list[str] = []
    concat_in = []

    for i, c in enumerate(project.clips):
        span = max(0.05, c.out_pt - c.in_pt)
        cmd += ["-ss", f"{c.in_pt:.3f}", "-t", f"{span:.3f}", "-i", c.path]
        sp = max(0.1, min(c.speed, 20.0))
        v = f"[{i}:v]"
        if c.reverse:
            v += "reverse,"
        v += f"setpts=(PTS-STARTPTS)/{sp:.4f},fps={fps}[c{i}s]"
        graph.append(v)
        graph.append(_layout_chain(i, W, H, layout))

        out_len = span / sp
        if c.has_audio and not c.mute:
            a = f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo"
            if c.reverse:
                a += ",areverse"
            if abs(sp - 1.0) > 1e-3:
                a += "," + _atempo_chain(sp)
            if abs(c.volume - 1.0) > 1e-3:
                a += f",volume={c.volume:.3f}"
            a += f",asetpts=PTS-STARTPTS[a{i}]"
        else:
            a = (f"anullsrc=r=48000:cl=stereo,atrim=duration={out_len:.3f},"
                 f"asetpts=PTS-STARTPTS[a{i}]")
        graph.append(a)
        concat_in.append(f"[v{i}][a{i}]")

    total = sum(max(0.05, c.out_pt - c.in_pt) / max(0.1, min(c.speed, 20.0)) for c in project.clips)
    graph.append(f"{''.join(concat_in)}concat=n={len(project.clips)}:v=1:a=1[vc][ac]")

    graph += build_graph(project.effects, "vc", "vfx", ctx)

    cur = "vfx"
    for ti, t in enumerate(project.texts):
        if not t.text.strip():
            continue
        nxt = f"vt{ti}"
        graph.append(f"[{cur}]{_drawtext(t, ti, W, H, tmp)}[{nxt}]")
        cur = nxt

    tail = []
    if project.fade_in > 0:
        tail.append(f"fade=t=in:st=0:d={project.fade_in:.2f}")
    if project.fade_out > 0:
        tail.append(f"fade=t=out:st={max(0.0, total - project.fade_out):.2f}:d={project.fade_out:.2f}")
    tail.append("format=yuv420p")
    graph.append(f"[{cur}]{','.join(tail)}[vout]")

    af = []
    if project.fade_in > 0:
        af.append(f"afade=t=in:st=0:d={project.fade_in:.2f}")
    if project.fade_out > 0:
        af.append(f"afade=t=out:st={max(0.0, total - project.fade_out):.2f}:d={project.fade_out:.2f}")
    graph.append(f"[ac]{','.join(af) if af else 'anull'}[aout]")

    cmd += ["-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "ultrafast" if draft else exp.get("x264_preset", "medium"),
            "-crf", str(exp.get("crf", 20)), "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:a", "aac", "-b:a", f"{exp.get('audio_kbps', 192)}k",
            "-movflags", "+faststart"]
    if max_seconds:
        cmd += ["-t", f"{max_seconds:.2f}"]
        total = min(total, max_seconds)
    cmd.append(out_path)
    return cmd, total, tmp


def run(cmd: list[str], total: float, on_progress: Callable[[float], None] | None = None,
        should_cancel: Callable[[], bool] | None = None) -> None:
    flags = _NOWINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", creationflags=flags)
    stderr_lines: list[str] = []

    import threading

    def _drain():
        for line in proc.stderr:  # type: ignore[union-attr]
            stderr_lines.append(line)
            del stderr_lines[:-60]

    th = threading.Thread(target=_drain, daemon=True)
    th.start()
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if should_cancel and should_cancel():
                proc.kill()
                raise ExportError("Abgebrochen.")
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    us = int(line.split("=", 1)[1])
                    if on_progress and total > 0:
                        on_progress(max(0.0, min(1.0, us / 1_000_000 / total)))
                except ValueError:
                    pass
        proc.wait()
    finally:
        th.join(timeout=2)
    if proc.returncode != 0:
        raise ExportError("FFmpeg-Fehler:\n" + "".join(stderr_lines[-15:]))
    if on_progress:
        on_progress(1.0)

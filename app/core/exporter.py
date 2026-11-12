"""Baut aus einem Projekt den FFmpeg-Aufruf und führt ihn mit Fortschrittsanzeige aus."""
from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Callable

from ..paths import find_binary, resolve_font
from . import audiofix, audiomix, grade, overlaykeys, presets, split
from .effects import Ctx, build_graph
from .project import Clip, Project, TextLayer, overlap

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


_HW_CACHE: dict[str, str | None] = {}


def hw_encoder() -> str | None:
    """Findet einen Grafikkarten-Encoder (NVIDIA, Intel, AMD), der wirklich funktioniert – sonst None."""
    if "enc" in _HW_CACHE:
        return _HW_CACHE["enc"]
    found = None
    flags = _NOWINDOW if os.name == "nt" else 0
    for enc in ("h264_nvenc", "h264_qsv", "h264_amf"):
        try:
            r = subprocess.run([find_binary("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.3",
                                "-c:v", enc, "-f", "null", "-"], capture_output=True, text=True, timeout=25,
                               creationflags=flags)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0:
            found = enc
            break
    _HW_CACHE["enc"] = found
    return found


def video_codec_args(exp: dict, draft: bool, use_hw: bool) -> tuple[list[str], str]:
    """(ffmpeg-Argumente, Name des Encoders). Fällt ohne Grafikkarte auf libx264 zurück."""
    crf = str(exp.get("crf", 20))
    enc = hw_encoder() if (use_hw and not draft) else None
    if enc == "h264_nvenc":
        return ["-c:v", enc, "-preset", "p5", "-rc", "vbr", "-cq", crf, "-b:v", "0"], enc
    if enc == "h264_qsv":
        return ["-c:v", enc, "-global_quality", crf, "-preset", "medium"], enc
    if enc == "h264_amf":
        return ["-c:v", enc, "-quality", "quality", "-rc", "cqp", "-qp_i", crf, "-qp_p", crf], enc
    return ["-c:v", "libx264", "-preset", "ultrafast" if draft else exp.get("x264_preset", "medium"), "-crf", crf], "libx264"


def format_eta(elapsed: float, progress: float) -> str:
    """Restzeit als Text, z. B. 'noch ca. 1:25 min'. Leer, wenn noch nicht schätzbar."""
    if progress < 0.03 or elapsed < 2.0:
        return ""
    left = int(elapsed / progress * (1.0 - progress))
    return f"noch ca. {left // 60}:{left % 60:02d} min" if left >= 5 else "gleich fertig"


MAX_REVERSE_SECONDS = 90.0


def chromakey_filters(o) -> str:
    """Chroma-Key für ein Bild-in-Bild: leer, wenn aus oder die Farbe ungültig ist (siehe OverlayClip.key_*)."""
    import re
    col = (getattr(o, "key_color", "") or "").strip()
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", col)
    if not m:
        return ""
    hexv = m.group(1).lower()
    sim = 0.02 + 0.48 * min(100.0, max(0.0, float(o.key_similarity))) / 100.0
    blend = 0.5 * min(100.0, max(0.0, float(o.key_blend))) / 100.0
    out = f"chromakey=color=0x{hexv}:similarity={sim:.3f}:blend={blend:.3f}"
    if o.key_spill:
        r, g, b = (int(hexv[i:i + 2], 16) for i in (0, 2, 4))
        if g >= r and g >= b:
            out += ",despill=type=green"
        elif b >= r and b >= g:
            out += ",despill=type=blue"
    return out


def _key_graph(c: Clip, i: int, W: int, H: int, fps, key: str) -> list[str]:
    """Hauptvideo mit Chroma-Key über seinen Hintergrund legen: [v{i}g] (Bild nach Korrektur) → [v{i}].
    Der Hintergrund kommt per movie-Filter aus der Datei (Video läuft in Schleife, Bild wird gehalten) oder ist schwarz."""
    from .project import is_image_path
    bg = (c.key_bg or "").strip()
    if bg and Path(bg).is_file():
        if is_image_path(bg):
            src = f"movie='{_esc_path(bg)}',loop=loop=-1:size=1,setpts=N/({fps}*TB)"
        else:
            src = f"movie='{_esc_path(bg)}':loop=0,setpts=N/(FRAME_RATE*TB)"      # PTS-STARTPTS würde bei der Schleife hängen
        back = f"{src},fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,format=rgba[kb{i}]"
    else:
        back = f"color=c=black:s={W}x{H}:r={fps},format=rgba[kb{i}]"
    return [back,
            f"[v{i}g]format=rgba,{key},format=rgba[kf{i}]",
            f"[kb{i}][kf{i}]overlay=shortest=1:format=auto,format=yuv420p[v{i}]"]


GRAPH_INLINE_MAX = 8000     # längere Filtergraphen kommen in eine Datei (Windows erlaubt nur ~32 000 Zeichen je Befehl)
_script_flag_cache: list[str | None] = []


def _script_flag() -> str | None:
    """Wie liest dieses FFmpeg einen Filtergraphen aus einer Datei? Neuere Versionen: „-/filter_complex“; ältere (bis 6.x):
    „-filter_complex_script“ (in neuesten Builds entfernt). Das wird einmal mit einem winzigen Graphen ausprobiert."""
    if _script_flag_cache:
        return _script_flag_cache[0]
    found = None
    d = Path(tempfile.mkdtemp(prefix="clipforge_probe_"))
    try:
        g = d / "g.txt"
        g.write_text("[0:v]null[o]", encoding="utf-8")
        for flag in ("-/filter_complex", "-filter_complex_script"):
            try:
                r = subprocess.run([find_binary("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=d=0.1:s=16x16", flag, str(g),
                                    "-map", "[o]", "-f", "null", "-"], capture_output=True, timeout=30,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.SubprocessError):
                continue
            if r.returncode == 0:
                found = flag
                break
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
    _script_flag_cache.append(found)
    return found


def _filter_args(graph: str, tmp: Path) -> list[str]:
    """Filtergraph für den Befehl: kurz direkt, lang (z. B. Tempokurve mit vielen Abschnitten) über eine Datei."""
    if len(graph) > GRAPH_INLINE_MAX:
        flag = _script_flag()
        if flag:
            f = tmp / "filtergraph.txt"
            f.write_text(graph, encoding="utf-8")
            return [flag, str(f)]
    return ["-filter_complex", graph]


def _esc_path(p: str) -> str:
    """Pfad für FFmpeg-Filteroptionen (Windows: C:\\x → C\\:/x)."""
    return p.replace("\\", "/").replace(":", "\\:").replace("'", r"\'")


JOIN_FADE = 0.004        # Sekunden Ein-/Ausblendung an Tempowechsel-Schnitten (Tempokurve)
AUDIO_MARGIN = 0.15      # Sekunden Ton-Zugabe hinter dem Clip, wenn atempo benutzt wird (siehe unten)


def _tempo_join(a, b) -> bool:
    """Läuft b direkt hinter a in derselben Aufnahme weiter und wird mindestens eines der beiden mit atempo gedehnt? (Tempokurve)
    Auch bei gleichem Tempo: atempo beginnt in jedem Stück neu, die Schwingungen schließen nicht aneinander an."""
    return (a.path == b.path and not a.is_image and not b.is_image and not a.reverse and not b.reverse
            and abs(a.out_pt - b.in_pt) < 0.002
            and (abs(a.speed - 1.0) > 1e-3 or abs(b.speed - 1.0) > 1e-3))


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


def _transform_chain(c: Clip) -> str:
    """Zuschneiden, Spiegeln, Drehen (um 90°) – vor dem Einpassen ins Format."""
    parts = []
    l, r = max(0.0, min(c.crop_l, 90.0)), max(0.0, min(c.crop_r, 90.0))
    t, b = max(0.0, min(c.crop_t, 90.0)), max(0.0, min(c.crop_b, 90.0))
    if l + r > 90.0:
        r = 90.0 - l
    if t + b > 90.0:
        b = 90.0 - t
    if l or r or t or b:
        parts.append(f"crop=w='trunc(iw*(1-{(l + r) / 100:.4f})/2)*2':h='trunc(ih*(1-{(t + b) / 100:.4f})/2)*2':"
                     f"x='trunc(iw*{l / 100:.4f}/2)*2':y='trunc(ih*{t / 100:.4f}/2)*2'")
    if c.flip_h:
        parts.append("hflip")
    if c.flip_v:
        parts.append("vflip")
    rot = c.rotate % 360
    if rot == 90:
        parts.append("transpose=1")
    elif rot == 180:
        parts.append("hflip,vflip")
    elif rot == 270:
        parts.append("transpose=2")
    return ",".join(parts)


def _interp(keys: list[dict], field_name: str, L: float, ease: bool, tvar: str = "t") -> str:
    """Stückweise lineare (oder sanfte) Kurve über die Zeit t des Clips als FFmpeg-Ausdruck."""
    pts = sorted(((max(0.0, min(1.0, float(k.get("t", 0)))), float(k.get(field_name, 0))) for k in keys))
    fixed = []
    for tt, v in pts:                       # gleiche Zeiten leicht auseinanderziehen
        if fixed and tt <= fixed[-1][0]:
            tt = min(1.0, fixed[-1][0] + 0.001)
        fixed.append((tt, v))
    if len(fixed) == 1 or len({v for _, v in fixed}) == 1:
        return f"{fixed[0][1]:.4f}"
    tn = f"({tvar}/{max(L, 0.05):.4f})"
    expr = f"{fixed[-1][1]:.4f}"
    for (t0, v0), (t1, v1) in reversed(list(zip(fixed[:-1], fixed[1:]))):
        u = f"min(1,max(0,({tn}-{t0:.4f})/{max(t1 - t0, 0.001):.4f}))"
        if ease:
            u = f"({u}*{u}*(3-2*{u}))"
        seg = f"({v0:.4f}+({v1 - v0:.4f})*{u})"
        expr = f"if(lt({tn},{t1:.4f}),{seg},{expr})"
    expr = f"if(lt({tn},{fixed[0][0]:.4f}),{fixed[0][1]:.4f},{expr})"
    return expr


def _motion_chain(c: Clip, W: int, H: int) -> str:
    """Zoom, Schwenk und Drehung über die Zeit (Keyframes) auf dem fertigen Bild W×H."""
    keys = [k for k in (c.keyframes or []) if isinstance(k, dict)]
    if not keys:
        return ""
    L = c.length
    zoom = _interp([dict(k, zoom=max(100.0, min(float(k.get("zoom", 100)), 400.0))) for k in keys], "zoom", L, c.motion_ease)
    px = _interp(keys, "x", L, c.motion_ease)
    py = _interp(keys, "y", L, c.motion_ease)
    rot = _interp(keys, "rot", L, c.motion_ease)
    parts = []
    if rot not in ("0.0000", "-0.0000"):
        parts.append(f"rotate=a='({rot})*PI/180':ow=iw:oh=ih:c=black")
    still_zoom = zoom.replace(".", "", 1).isdigit() and abs(float(zoom) - 100.0) < 1e-6
    still_pan = px.replace("-", "").replace(".", "", 1).isdigit() and py.replace("-", "").replace(".", "", 1).isdigit()
    if not (still_zoom and still_pan):
        sw = f"trunc({W}*({zoom})/100/2)*2"      # Breite/Höhe nach dem Zoom (crop kennt die wechselnde Größe nicht)
        sh = f"trunc({H}*({zoom})/100/2)*2"
        parts.append(f"scale=w='{sw}':h='{sh}':eval=frame:flags=bilinear")
        parts.append(f"crop={W}:{H}:x='({sw}-{W})/2*(1+({px})/100)':y='({sh}-{H})/2*(1+({py})/100)'")
        parts.append("setsar=1")                  # scale rechnet das Seitenverhältnis pro Bild neu: concat verträgt kein wechselndes SAR
    return ",".join(parts)


def _is_const(expr: str) -> bool:
    try:
        float(expr)
        return True
    except ValueError:
        return False


def _free_overlay_chain(o, k: int, fps, W: int, ow: int, osp: float, olen: float) -> tuple[str, str]:
    """Filterkette (ohne Zeitversatz) und Position eines freien Bild-in-Bild-Blocks, ggf. mit Keyframes."""
    rev = "reverse," if getattr(o, "reverse", False) and not o.is_image else ""
    head = f"[{k}:v]{rev}setpts=(PTS-STARTPTS)/{osp:.4f},fps={fps}"
    if not overlaykeys.active(o):
        ch = f"{head},scale={ow}:-2,format=rgba"
        key = chromakey_filters(o)
        if key:
            ch += "," + key + ",format=rgba"
        if o.border:
            b = max(2, ow // 80)
            ch += f",pad=iw+{2 * b}:ih+{2 * b}:{b}:{b}:white"
        rot = max(-720.0, min(720.0, float(getattr(o, "rot", 0.0) or 0.0)))
        if abs(rot) > 0.01:                    # feste Drehung: das Bild wird größer, damit nichts abgeschnitten wird
            ch += f",rotate=a={rot:.3f}*PI/180:ow=rotw({rot:.3f}*PI/180):oh=roth({rot:.3f}*PI/180):c=black@0"
        if o.opacity < 99.5:
            ch += f",colorchannelmixer=aa={max(0.0, o.opacity) / 100.0:.3f}"
        if o.fade_in > 0:
            ch += f",fade=t=in:st=0:d={min(o.fade_in, olen):.3f}:alpha=1"
        if o.fade_out > 0:
            fo = min(o.fade_out, olen)
            ch += f",fade=t=out:st={max(0.0, olen - fo):.3f}:d={fo:.3f}:alpha=1"
        return ch, f"x='W*{o.x_pct:.2f}/100-w/2':y='H*{o.y_pct:.2f}/100-h/2'"

    keys = overlaykeys.clean(o.keys, o)
    ease = bool(getattr(o, "anim_ease", True))
    ex = _interp(keys, "x", olen, ease, f"(t-{o.start:.3f})")
    ey = _interp(keys, "y", olen, ease, f"(t-{o.start:.3f})")
    esz = _interp(keys, "size", olen, ease, "t")
    eop = _interp(keys, "opacity", olen, ease, "T")
    erot = _interp(keys, "rot", olen, ease, "t")
    rotating = not (_is_const(erot) and abs(float(erot)) < 0.01)
    big = max(k_["size"] for k_ in keys)
    ow_max = max(16, int(W * big / 100.0) // 2 * 2)
    ch = f"{head},scale={ow_max}:-2,format=rgba"
    key = chromakey_filters(o)
    if key:
        ch += "," + key + ",format=rgba"
    ref_w = ow_max
    if o.border:
        b = max(2, ow_max // 80)
        ch += f",pad=iw+{2 * b}:ih+{2 * b}:{b}:{b}:white"
        ref_w = ow_max + 2 * b
    if rotating:                               # Drehen auf einer festen Fläche (Diagonale), damit die Größe gleich bleibt
        ang = f"({erot})*PI/180" if not _is_const(erot) else f"{float(erot):.4f}*PI/180"
        ch += f",rotate=a='{ang}':ow='hypot(iw,ih)':oh='hypot(iw,ih)':c=black@0"
    if _is_const(eop):
        if float(eop) < 99.5:
            ch += f",colorchannelmixer=aa={max(0.0, float(eop)) / 100.0:.3f}"
    else:
        ch += f",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*({eop})/100'"
    if o.fade_in > 0:
        ch += f",fade=t=in:st=0:d={min(o.fade_in, olen):.3f}:alpha=1"
    if o.fade_out > 0:
        fo = min(o.fade_out, olen)
        ch += f",fade=t=out:st={max(0.0, olen - fo):.3f}:d={fo:.3f}:alpha=1"
    if rotating:                               # Fläche im gleichen Verhältnis verkleinern/vergrößern wie das Bild
        fac = f"({W}*({esz})/100/{ref_w})" if not _is_const(esz) else f"({max(16, int(W * float(esz) / 100.0) // 2 * 2)}/{ref_w})"
        ch += f",scale=w='trunc(iw*{fac}/2)*2':h='trunc(ih*{fac}/2)*2':eval=frame:flags=bilinear"
    elif _is_const(esz):
        want = max(16, int(W * float(esz) / 100.0) // 2 * 2)
        if abs(want - ow_max) > 1:
            ch += f",scale={want}:-2"
    else:
        sw = f"trunc({W}*({esz})/100/2)*2"
        ch += f",scale=w='{sw}':h='trunc(ow*ih/iw/2)*2':eval=frame:flags=bilinear"
    return ch, f"x='W*({ex})/100-w/2':y='H*({ey})/100-h/2'"


WM_CORNERS = {"tl": "Oben links", "tr": "Oben rechts", "bl": "Unten links", "br": "Unten rechts"}


def _watermark(project: Project, graph: list[str], cur: str, W: int, fps) -> str:
    """Logo über das fertige Bild legen (nach Overlays und Text). Gibt den neuen Ausgangsnamen zurück."""
    from .project import is_image_path
    path = (getattr(project, "watermark", "") or "").strip()
    if not path:
        return cur
    if not Path(path).is_file():
        raise ExportError(f"Wasserzeichen: Die Datei wurde nicht gefunden:\n{path}\nIm Reiter „Format“ eine andere wählen oder entfernen.")
    if not is_image_path(path):
        raise ExportError("Wasserzeichen: Bitte eine Bilddatei wählen (PNG mit Transparenz ist am besten).")
    ow = max(16, int(W * max(2.0, min(float(project.wm_size), 80.0)) / 100.0) // 2 * 2)
    m = max(4, int(W * 0.025))
    pos = {"tl": f"x={m}:y={m}", "tr": f"x=W-w-{m}:y={m}", "bl": f"x={m}:y=H-h-{m}",
           "br": f"x=W-w-{m}:y=H-h-{m}"}.get(project.wm_corner, f"x=W-w-{m}:y=H-h-{m}")
    op = max(0.0, min(float(project.wm_opacity), 100.0)) / 100.0
    chain = f"movie='{_esc_path(path)}',loop=loop=-1:size=1,setpts=N/({fps}*TB),fps={fps},scale={ow}:-2,format=rgba"
    if op < 0.995:
        chain += f",colorchannelmixer=aa={op:.3f}"
    graph.append(chain + "[wm]")
    graph.append(f"[{cur}][wm]overlay={pos}:shortest=1:format=auto[vwm]")
    return "vwm"


def _layout_chain(i: int, W: int, H: int, mode: str) -> str:
    src, dst = f"c{i}s", f"l{i}"
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


def _text_width(font: str, text: str, size: int) -> float:
    """Breite der längsten Zeile (ohne Kerning) – für die feste Position der Schreibmaschine."""
    try:
        from fontTools.ttLib import TTFont
        f = TTFont(font, lazy=True)
        cmap, hmtx, upm = f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm
        best = 0.0
        for line in text.split("\n"):
            w = sum(hmtx[cmap[ord(ch)]][0] if ord(ch) in cmap else upm * 0.5 for ch in line)
            best = max(best, w * size / upm)
        return best
    except Exception:  # noqa: BLE001
        return max((len(l) for l in text.split("\n")), default=1) * size * 0.52


def _karaoke_drawtext(layer: TextLayer, idx: int, W: int, H: int, tmpdir: Path, size: int, max_chars: int,
                      font: str, fontopt: str, border: int) -> list[str]:
    """Jedes Wort einzeln an fester Stelle: in der Grundfarbe bis zu seinem Beginn, danach in der Hervorhebungsfarbe.
    Gibt [] zurück, wenn der Eintrag nicht als Karaoke gezeichnet werden kann (dann zeichnet der Aufrufer normal)."""
    from . import karaoke
    S, E = float(layer.start), float(layer.end)
    words = karaoke.word_times(layer.text, S, E, getattr(layer, "words", None))
    if not words or len(words) > karaoke.MAX_WORDS:
        return []
    measure = (lambda t: _text_width(font, t, size)) if font else (lambda t: len(t) * size * 0.52)
    rows = karaoke.layout(layer.text, measure, W, max_chars)
    if not rows:
        return []
    pitch = int(size * 1.25) + size // 6
    block_h = len(rows) * pitch - size // 6
    vertical = H > W
    y0 = {"top": H * 0.14, "center": (H - block_h) / 2.0,
          "bottom": H * (0.68 if vertical else 0.80)}.get(layer.position, H * 0.8)
    y0 = max(0.0, min(y0, H * 0.96 - block_h))          # mehrere Zeilen sollen nicht unten aus dem Bild ragen
    hi = layer.karaoke
    only_active = layer.karaoke_mode == "active"
    common = f"fontsize={size}:fontcolor=%s:borderw={border}:bordercolor={layer.border_color}"
    out: list[str] = []
    k = 0

    def one(text: str, color: str, x: float, y: float, cond: str) -> str:
        nonlocal k
        tf = tmpdir / f"text{idx}_k{k}.txt"
        k += 1
        tf.write_text(text, encoding="utf-8")
        return (f"drawtext={fontopt}textfile='{_esc_path(str(tf))}':{common % color}:x={x:.1f}:y={y:.1f}:"
                f"enable='{cond}'")

    if layer.box:                                        # Kasten: unsichtbarer Text im natürlichen Satz dahinter
        tf = tmpdir / f"text{idx}_kbox.txt"
        tf.write_text("\n".join(" ".join(w for w, _x in row) for row in rows), encoding="utf-8")
        out.append(f"drawtext={fontopt}textfile='{_esc_path(str(tf))}':fontsize={size}:fontcolor=black@0:borderw=0:"
                   f"x=(w-text_w)/2:y={y0:.1f}:line_spacing={size // 6}:box=1:boxcolor=black@0.55:"
                   f"boxborderw={max(6, size // 4)}:enable='between(t,{S:.3f},{E:.3f})'")
    wi = 0
    for li, row in enumerate(rows):
        y = y0 + li * pitch
        for w, x in row:
            _w, t0, t1 = words[wi]
            wi += 1
            if only_active:
                base = f"between(t,{S:.3f},{E:.3f})*not(between(t,{t0:.3f},{t1:.3f}))"
                lit = f"between(t,{t0:.3f},{t1:.3f})"
            else:
                base = f"between(t,{S:.3f},{t0:.3f})"
                lit = f"between(t,{t0:.3f},{E:.3f})"
            out.append(one(w, layer.color, x, y, base))
            out.append(one(w, hi, x, y, lit))
    return out


def _drawtext(layer: TextLayer, idx: int, W: int, H: int, tmpdir: Path) -> list[str]:
    """Gibt eine oder mehrere drawtext-Filter zurück (Schreibmaschine = mehrere Schritte)."""
    size = max(12, int(H * layer.size_pct / 100.0))
    max_chars = max(6, int(W * 0.88 / (size * 0.52)))
    wrapped = "\n".join(textwrap.fill(line, max_chars) for line in layer.text.splitlines() or [""])
    vertical = H > W
    ybase = {"top": "h*0.14", "center": "(h-text_h)/2",
             "bottom": "h*0.68" if vertical else "h*0.80"}.get(layer.position, "h*0.8")
    font = resolve_font(layer.font) or default_font()
    fontopt = f"fontfile='{_esc_path(font)}':" if font else ""
    border = max(2, size // 14)
    S, E = float(layer.start), float(layer.end)
    if getattr(layer, "karaoke", ""):
        kar = _karaoke_drawtext(layer, idx, W, H, tmpdir, size, max_chars, font, fontopt, border)
        if kar:
            return kar
    D = max(0.05, min(float(layer.anim_dur), (E - S) / 2.0 if E > S else 0.5))
    anim = layer.anim if layer.anim in ("none", "fade", "slide_up", "slide_left", "bounce", "typewriter",
                                        "shake", "blink") else "none"
    x = "(w-text_w)/2"
    y = ybase
    alpha = "1"
    p_in = f"min(1,max(0,(t-{S:.3f})/{D:.3f}))"
    if anim == "fade":
        alpha = f"if(lt(t,{S + D:.3f}),(t-{S:.3f})/{D:.3f},if(gt(t,{E - D:.3f}),({E:.3f}-t)/{D:.3f},1))"
    elif anim == "slide_up":
        y = f"({ybase})+(1-{p_in})*h*0.10"
        alpha = p_in
    elif anim == "slide_left":
        x = f"(w-text_w)/2+(1-{p_in})*w*0.45"
    elif anim == "bounce":
        y = f"({ybase})-h*0.05*abs(sin((t-{S:.3f})*9))*max(0,1-(t-{S:.3f})/1.2)"
    elif anim == "shake":
        x = "(w-text_w)/2+w*0.006*sin(t*55)"
        y = f"({ybase})+h*0.004*cos(t*47)"
    elif anim == "blink":
        alpha = "if(lt(mod(t,0.8),0.5),1,0.15)"
    box = ""
    if layer.box:
        box = f":box=1:boxcolor=black@0.55:boxborderw={max(6, size // 4)}"
    common = (f"fontsize={size}:fontcolor={layer.color}:borderw={border}:bordercolor={layer.border_color}"
              f"{box}:line_spacing={size // 6}")
    alpha_opt = "" if alpha == "1" else f":alpha='{alpha}'"

    def one(text: str, k: int, t0: float, t1: float, xx: str) -> str:
        tf = tmpdir / f"text{idx}_{k}.txt"
        tf.write_text(text, encoding="utf-8")
        return (f"drawtext={fontopt}textfile='{_esc_path(str(tf))}':{common}:x='{xx}':y='{y}'{alpha_opt}:"
                f"enable='between(t,{t0:.3f},{t1:.3f})'")

    if anim != "typewriter" or len(wrapped.strip()) < 2:
        return [one(wrapped, 0, S, E, x)]
    # Schreibmaschine: Text bleibt an fester Stelle, Buchstaben erscheinen nacheinander
    n = len(wrapped)
    steps = min(n, 40)
    dur = min(max(0.3, float(layer.anim_dur) * n / 8.0), max(0.3, (E - S) * 0.7))
    full_w = _text_width(font, wrapped, size) if font else n * size * 0.52
    fx = f"{max(0.0, (W - full_w) / 2):.1f}"
    out = []
    for k in range(1, steps + 1):
        cut = max(1, round(n * k / steps))
        t0 = S + dur * (k - 1) / steps
        t1 = S + dur * k / steps if k < steps else E
        out.append(one(wrapped[:cut], k, t0, t1, fx))
    return out


def _stabilize_filter(c) -> str:
    if not getattr(c, "stabilize", 0) or c.is_image:
        return ""
    from . import stabilize                              # erst hier laden (stabilize importiert den Exporter)
    return stabilize.filter_for(c)


def build_command(project: Project, out_path: str, *, draft: bool = False,
                  max_seconds: float | None = None, start: float = 0.0, preview_height: int | None = None,
                  use_hw: bool = False) -> tuple[list[str], float, Path]:
    """Gibt (Kommando, Dauer des Ergebnisses, temp-Ordner) zurück.

    start/max_seconds: nur diesen Ausschnitt rendern (Vorschau ab Abspielkopf).
    preview_height: Entwurf mit dieser Bildhöhe statt halber Auflösung.
    use_hw: Grafikkarten-Encoder nutzen, falls vorhanden (nur beim echten Export).
    """
    if not project.clips:
        raise ExportError("Das Projekt enthält keine Clips.")
    fmt = presets.get("formats", project.format_id)
    exp = presets.get("exports", "fast_draft" if draft else project.export_id)
    if not fmt or not exp:
        raise ExportError("Format- oder Export-Preset nicht gefunden.")

    W, H, fps = int(fmt["width"]), int(fmt["height"]), int(fmt.get("fps", 30))
    if draft and preview_height:
        f = min(1.0, preview_height / H)
        W, H = max(2, round(W * f / 2) * 2), max(2, round(H * f / 2) * 2)
    elif draft:
        W, H = max(2, round(W / 2 / 2) * 2), max(2, round(H / 2 / 2) * 2)
    layout = project.layout or fmt.get("layout", "fit")
    ctx = Ctx(W, H, fps)

    tmp = Path(tempfile.mkdtemp(prefix="clipforge_"))
    cmd = [find_binary("ffmpeg"), "-hide_banner", "-y", "-progress", "pipe:1", "-nostats"]
    graph: list[str] = []
    concat_in = []

    # Bildanzahl je Clip: laufend gerundet, damit Bild und Ton auch bei vielen Schnitten (z. B. Tempo-Kurve) im Gleichklang bleiben.
    # Sonst rundet jeder Clip auf ganze Quellbilder auf und das Video wird mit jedem Schnitt etwas länger als der Ton.
    frame_n: list[int] = []
    _acc, _prev = 0.0, 0
    for c in project.clips:
        _acc += max(0.05, c.out_pt - c.in_pt) / max(0.1, min(c.speed, 20.0))
        _cur = max(_prev + 1, round(_acc * fps))
        frame_n.append(_cur - _prev)
        _prev = _cur

    for i, c in enumerate(project.clips):
        span = max(0.05, c.out_pt - c.in_pt)
        if c.reverse and not c.is_image and span > MAX_REVERSE_SECONDS:
            raise ExportError(f"„{c.name}“: Rückwärts abspielen geht nur für Clips bis {int(MAX_REVERSE_SECONDS)} Sekunden "
                              "(der ganze Clip müsste im Speicher liegen). Kürze den Clip oder schalte „Rückwärts“ aus.")
        sp = max(0.1, min(c.speed, 20.0))
        tempo_audio = False
        if c.is_image:                      # Standbild: als Endlosschleife einlesen
            cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{span:.3f}", "-i", c.path]
        else:
            tempo_audio = (c.has_audio and not c.mute and not c.audio_detached and not c.reverse
                           and abs(sp - 1.0) > 1e-3)
            cmd += ["-ss", f"{c.in_pt:.3f}", "-t", f"{span + (AUDIO_MARGIN if tempo_audio else 0.0):.3f}", "-i", c.path]
        v = f"[{i}:v]"
        stab = _stabilize_filter(c)                      # vor „rückwärts“, damit die Bildfolge zur Analyse passt
        if stab:
            v += stab + ","
        if c.reverse and not c.is_image:
            v += "reverse,"
        v += f"setpts=(PTS-STARTPTS)/{sp:.4f},fps={fps},tpad=stop_mode=clone:stop=3,trim=end_frame={frame_n[i]}[c{i}r]"
        graph.append(v)
        graph.append(f"[c{i}r]{_transform_chain(c) or 'null'}[c{i}s]")
        graph.append(_layout_chain(i, W, H, layout))
        motion = _motion_chain(c, W, H)
        src = f"l{i}"
        if motion:
            graph.append(f"[l{i}]{motion}[l{i}m]")
            src = f"l{i}m"
        key = chromakey_filters(c)
        if key:                                                   # Greenscreen auf dem Hauptvideo: Hintergrund scheint durch
            graph.append(grade.apply_label(src, f"v{i}g", c.grade))
            graph += _key_graph(c, i, W, H, fps, key)
        else:
            graph.append(grade.apply_label(src, f"v{i}", c.grade))   # Licht/Kontrast/Farbe pro Clip

        out_len = span / sp
        if c.has_audio and not c.mute and not c.audio_detached and not c.is_image:
            a = f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo"
            fix = audiofix.chain(c.denoise, c.voice, audiofix.noise_floor(c.path, c.in_pt, c.out_pt) if c.denoise > 0 else None)
            if fix:
                a += "," + fix
            if c.reverse:
                a += ",areverse"
            if abs(sp - 1.0) > 1e-3:
                a += "," + _atempo_chain(sp)
            if abs(c.volume - 1.0) > 1e-3:
                a += f",volume={c.volume:.3f}"
            if tempo_audio:
                # atempo liefert bei langsamem Tempo bis zu ~50 ms zu wenig Ton (Aussetzer an den Schnitten, z. B. in der
                # Tempokurve). Deshalb wird etwas mehr Ton eingelesen und exakt auf die Clip-Länge gekürzt; reicht die
                # Aufnahme nicht weiter, füllt apad den Rest.
                # Länge = Bildanzahl/fps: ist der Ton kürzer als das Bild, füllt concat die Lücke mit Stille (hörbarer Aussetzer).
                seg = frame_n[i] / fps
                a += f",atrim=duration={seg:.5f},apad=whole_dur={seg:.5f}"
            # Bei Tempowechsel passen die Schwingungen an der Schnittstelle nicht aneinander (Knacken): ein paar Millisekunden
            # aus- bzw. einblenden. Vorher wird die Länge auf die Bildlänge gebracht, damit die Blende am Ende sitzt.
            _fin = i > 0 and _tempo_join(project.clips[i - 1], c)
            _fout = i + 1 < len(project.clips) and _tempo_join(c, project.clips[i + 1])
            if _fin or _fout:
                seg_a = frame_n[i] / fps
                if not tempo_audio:
                    a += f",atrim=duration={seg_a:.5f},apad=whole_dur={seg_a:.5f}"
                if _fin:
                    a += f",afade=t=in:st=0:d={JOIN_FADE}"
                if _fout:
                    a += f",afade=t=out:st={max(0.0, seg_a - JOIN_FADE):.5f}:d={JOIN_FADE}"
            a += f",asetpts=PTS-STARTPTS[a{i}]"
        else:
            a = (f"anullsrc=r=48000:cl=stereo,atrim=duration={out_len:.3f},"
                 f"asetpts=PTS-STARTPTS[a{i}]")
        graph.append(a)
        concat_in.append(f"[v{i}][a{i}]")

    lens = [max(0.05, c.out_pt - c.in_pt) / max(0.1, min(c.speed, 20.0)) for c in project.clips]
    n = len(project.clips)
    ovl = [overlap(project.clips[i], lens[i], lens[i + 1] if i + 1 < n else None) for i in range(n)]
    trans = {t["id"]: t for t in presets.load("transitions")}
    if n == 1:
        graph.append("[v0]null[vc]")
        graph.append("[a0]anull[ac]")
        total = lens[0]
    elif not any(o > 0.001 for o in ovl):
        graph.append(f"{''.join(concat_in)}concat=n={n}:v=1:a=1[vc][ac]")
        total = sum(lens)
    else:
        for i in range(n):                      # gleiches Format/Zeitbasis für xfade
            graph.append(f"[v{i}]format=yuv420p,settb=AVTB,fps={fps},setsar=1[w{i}]")
        cur_v, cur_a, curlen = "w0", "a0", lens[0]
        for i in range(1, n):
            d = ovl[i - 1]
            last = i == n - 1
            nv, na = ("vc", "ac") if last else (f"cv{i}", f"ca{i}")
            if d > 0.001:
                name = trans.get(project.clips[i - 1].transition, {}).get("xfade", "fade")
                graph.append(f"[{cur_v}][w{i}]xfade=transition={name}:duration={d:.3f}:"
                             f"offset={max(0.0, curlen - d):.3f}[{nv}]")
                graph.append(f"[{cur_a}][a{i}]acrossfade=d={d:.3f}[{na}]")
                curlen += lens[i] - d
            else:
                # concat liefert die Zeitbasis 1/1000000; ein folgender xfade verlangt dieselbe wie [w{i}] (1/fps)
                graph.append(f"[{cur_v}][{cur_a}][w{i}][a{i}]concat=n=2:v=1:a=1[{nv}c][{na}]")
                graph.append(f"[{nv}c]fps={fps}[{nv}]")
                curlen += lens[i]
            cur_v, cur_a = nv, na
        total = curlen

    graph += build_graph(project.effects, "vc", "vfx", ctx)

    cur = "vfx"
    n_ov = 0
    mc = split.main_cell_px(project, total, W, H)
    if mc:      # Split Screen: Hauptvideo füllt ein Feld, solange das Split läuft (sonst wieder das ganze Bild)
        mx, my, mw, mh, mt0, mt1 = mc
        graph += [f"[{cur}]split=2[mA][mB]",
                  f"[mB]scale={mw}:{mh}:force_original_aspect_ratio=increase,crop={mw}:{mh},setsar=1,format=rgba[mC]",
                  f"color=c=black:s={W}x{H}:r={fps}:d={total + 1:.3f},format=rgba[mD]",
                  f"[mD][mC]overlay=x={mx}:y={my}:eof_action=repeat[mE]",
                  f"[mA][mE]overlay=eof_action=repeat:enable='between(t,{mt0:.3f},{mt1:.3f})'[mF]"]
        cur = "mF"
        for o in project.overlays:                         # Linie um das Hauptfeld (einmal, aus den Angaben des ersten Blocks)
            if split.is_split(o) and split.line_px(o, W) and split.valid_cell(o.main_cell):
                th = min(split.line_px(o, W), mw // 2, mh // 2)
                graph.append(f"[{cur}]drawbox=x={mx}:y={my}:w={mw}:h={mh}:color={split.line_color(o)}:t={th}:"
                             f"enable='between(t,{mt0:.3f},{mt1:.3f})'[mG]")
                cur = "mG"
                break
    for oj, o in enumerate(project.overlays):
        if o.start >= total - 0.05:
            continue
        osp = max(0.1, min(o.speed, 20.0))
        oseg = max(0.05, o.out_pt - o.in_pt)
        olen = oseg / osp
        k = n + n_ov
        if o.is_image:
            cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{oseg:.3f}", "-i", o.path]
        else:
            cmd += ["-ss", f"{o.in_pt:.3f}", "-t", f"{oseg:.3f}", "-i", o.path]
        if getattr(o, "reverse", False) and not o.is_image and oseg > MAX_REVERSE_SECONDS:
            raise ExportError(f"Bild-in-Bild „{o.name}“: Rückwärts abspielen geht nur für Blöcke bis {int(MAX_REVERSE_SECONDS)} Sekunden "
                              "(Teile den Block oder kürze ihn).")
        cell = split.cell_px(o, W, H)
        ow = max(16, int(W * max(1.0, min(o.size_pct, 100.0)) / 100.0) // 2 * 2)
        if cell:                         # Split Screen: Bild füllt das Feld aus (überstehende Ränder werden abgeschnitten)
            sw, sh, dx, dy = split.crop_params(o, cell[2], cell[3])
            rev = "reverse," if getattr(o, "reverse", False) and not o.is_image else ""
            ch = (f"[{k}:v]{rev}setpts=(PTS-STARTPTS)/{osp:.4f},fps={fps},scale={sw}:{sh}:force_original_aspect_ratio=increase,"
                  f"crop={cell[2]}:{cell[3]}:x='(iw-{cell[2]})*(0.5+{dx / 200.0:.5f})':y='(ih-{cell[3]})*(0.5+{dy / 200.0:.5f})',"
                  "setsar=1,format=rgba")
        else:
            ch, pos = _free_overlay_chain(o, k, fps, W, ow, osp, olen)
        if cell:
            pos = f"x={cell[0]}:y={cell[1]}"
            key = chromakey_filters(o)
            if key:
                ch += "," + key + ",format=rgba"
            if o.opacity < 99.5:
                ch += f",colorchannelmixer=aa={max(0.0, o.opacity) / 100.0:.3f}"
            if o.fade_in > 0:
                ch += f",fade=t=in:st=0:d={min(o.fade_in, olen):.3f}:alpha=1"
            if o.fade_out > 0:
                fo = min(o.fade_out, olen)
                ch += f",fade=t=out:st={max(0.0, olen - fo):.3f}:d={fo:.3f}:alpha=1"
        ch += f",setpts=PTS+{o.start:.3f}/TB[ov{oj}]"
        nxt = f"vo{oj}"
        graph.append(ch)
        graph.append(f"[{cur}][ov{oj}]overlay={pos}:"
                     f"eof_action=pass:enable='between(t,{o.start:.3f},{o.start + olen:.3f})'[{nxt}]")
        cur = nxt
        if cell and split.line_px(o, W):               # Split: Trennlinie als Rahmen um das Feld
            th = min(split.line_px(o, W), cell[2] // 2, cell[3] // 2)
            graph.append(f"[{cur}]drawbox=x={cell[0]}:y={cell[1]}:w={cell[2]}:h={cell[3]}:color={split.line_color(o)}:t={th}:"
                         f"enable='between(t,{o.start:.3f},{o.start + olen:.3f})'[vl{oj}]")
            cur = f"vl{oj}"
        n_ov += 1
    from . import subtitles as _subs
    layers = list(project.texts) + (_subs.cue_layers(project.subtitles, project.sub_style, limit=total) if project.sub_burn else [])
    k = 0
    for ti, t in enumerate(layers):
        if not t.text.strip():
            continue
        for f in _drawtext(t, ti, W, H, tmp):
            nxt = f"vt{k}"
            graph.append(f"[{cur}]{f}[{nxt}]")
            cur = nxt
            k += 1

    cur = _watermark(project, graph, cur, W, fps)

    tail = []
    if project.fade_in > 0:
        tail.append(f"fade=t=in:st=0:d={project.fade_in:.2f}")
    if project.fade_out > 0:
        tail.append(f"fade=t=out:st={max(0.0, total - project.fade_out):.2f}:d={project.fade_out:.2f}")
    tail.append("format=yuv420p")
    graph.append(f"[{cur}]{','.join(tail)}[vout]")

    extra_cmd, audio_graph = audiomix.build_audio(project, total, len(project.clips) + n_ov, "ac", "aout")
    cmd += extra_cmd
    graph += audio_graph

    cmd += [*_filter_args(";".join(graph), tmp), "-map", "[vout]", "-map", "[aout]",
            *video_codec_args(exp, draft, use_hw)[0], "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:a", "aac", "-b:a", f"{exp.get('audio_kbps', 192)}k",
            "-movflags", "+faststart"]
    if start > 0.001:
        start = min(start, max(0.0, total - 0.5))
        cmd += ["-ss", f"{start:.3f}"]
        total = max(0.5, total - start)
    if max_seconds:
        cmd += ["-t", f"{max_seconds:.2f}"]
        total = min(total, max_seconds)
    elif n_ov:
        cmd += ["-t", f"{total:.3f}"]       # ein längeres Overlay darf das Video nicht verlängern
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

"""Effekt-Bibliothek. Jeder Effekt erzeugt ein Stück FFmpeg-Filtergraph.

Neue Effekte hinzufügen: eine Funktion schreiben und mit @effect(...) registrieren.
Eine Funktion bekommt (i, o, k, ctx):
    i, o  – Name des Eingangs-/Ausgangs-Labels (ohne eckige Klammern)
    k     – Intensität 0.0 … 1.0
    ctx   – Ctx(width, height, fps) des Projekts
und liefert einen Filtergraph-String der Form "[i]…[o]".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

REGISTRY: dict[str, "Effect"] = {}


@dataclass
class Ctx:
    width: int
    height: int
    fps: int = 30


@dataclass
class Effect:
    id: str
    name: str
    category: str
    build: Callable[..., str]
    default: int = 60
    params: bool = False      # Effekt bekommt zusätzlich die Block-Einstellungen (Masken: Form, Ort, Tracking)


def effect(id: str, name: str, category: str, default: int = 60, params: bool = False):
    def deco(fn):
        REGISTRY[id] = Effect(id, name, category, fn, default, params)
        return fn
    return deco


def n(x: float, digits: int = 3) -> str:
    return f"{x:.{digits}f}"


def even(x: float) -> int:
    return max(2, int(round(x / 2.0)) * 2)


def chain(i: str, o: str, filters: str) -> str:
    return f"[{i}]{filters}[{o}]"


# --------------------------------------------------------------------- Farbe
@effect("bw", "Schwarz-Weiß", "Farbe", 100)
def _bw(i, o, k, c):
    return chain(i, o, f"hue=s={n(1 - k)}")


@effect("contrast", "Kontrast", "Farbe", 50)
def _contrast(i, o, k, c):
    return chain(i, o, f"eq=contrast={n(1 + 0.8 * k)}:brightness={n(-0.03 * k)}")


@effect("brightness", "Helligkeit", "Farbe", 40)
def _brightness(i, o, k, c):
    return chain(i, o, f"eq=brightness={n(0.25 * k)}")


@effect("saturation", "Sättigung", "Farbe", 60)
def _saturation(i, o, k, c):
    return chain(i, o, f"eq=saturation={n(1 + 1.2 * k)}")


@effect("sepia", "Sepia / Vintage", "Farbe", 80)
def _sepia(i, o, k, c):
    sepia = [.393, .769, .189, .349, .686, .168, .272, .534, .131]
    ident = [1, 0, 0, 0, 1, 0, 0, 0, 1]
    m = [k * s + (1 - k) * d for s, d in zip(sepia, ident)]
    names = ["rr", "rg", "rb", "gr", "gg", "gb", "br", "bg", "bb"]
    args = ":".join(f"{nm}={n(v)}" for nm, v in zip(names, m))
    return chain(i, o, f"colorchannelmixer={args}")


@effect("cinematic", "Cinematic (Teal & Orange)", "Farbe", 60)
def _cinematic(i, o, k, c):
    return chain(
        i, o,
        f"colorbalance=rs={n(-0.12 * k)}:gs={n(-0.02 * k)}:bs={n(0.12 * k)}"
        f":rh={n(0.14 * k)}:bh={n(-0.12 * k)},"
        f"eq=contrast={n(1 + 0.18 * k)}:saturation={n(1 + 0.12 * k)}",
    )


@effect("neon", "Neon-Glow", "Farbe", 70)
def _neon(i, o, k, c):
    a, b, g = f"{o}_a", f"{o}_b", f"{o}_g"
    return (
        f"[{i}]eq=saturation={n(1 + 1.4 * k)}:contrast={n(1 + 0.2 * k)},"
        f"colorbalance=bs={n(0.18 * k)}:rm={n(-0.08 * k)}:bh={n(0.1 * k)},split[{a}][{b}];"
        f"[{b}]gblur=sigma={n(14 + 20 * k, 1)}[{g}];"
        f"[{a}][{g}]blend=all_mode=screen:all_opacity={n(0.2 + 0.55 * k)}[{o}]"
    )


@effect("vignette", "Vignette (dunkle Ränder)", "Farbe", 50)
def _vignette(i, o, k, c):
    return chain(i, o, f"vignette=angle={n(1.45 - 1.1 * k)}:mode=forward")


@effect("bars", "Kino-Balken", "Farbe", 50)
def _bars(i, o, k, c):
    h = even(c.height * (0.04 + 0.10 * k))
    return chain(
        i, o,
        f"drawbox=x=0:y=0:w=iw:h={h}:color=black:t=fill,"
        f"drawbox=x=0:y=ih-{h}:w=iw:h={h}:color=black:t=fill",
    )


# ------------------------------------------------------------ Schärfe / Blur
@effect("blur", "Weichzeichner", "Schärfe", 40)
def _blur(i, o, k, c):
    return chain(i, o, f"gblur=sigma={n(1 + 19 * k, 1)}")


@effect("sharpen", "Schärfen", "Schärfe", 50)
def _sharpen(i, o, k, c):
    return chain(i, o, f"unsharp=5:5:{n(0.3 + 1.7 * k)}:5:5:0")


@effect("grain", "Filmkorn", "Schärfe", 40)
def _grain(i, o, k, c):
    return chain(i, o, f"noise=alls={int(5 + 35 * k)}:allf=t")


# ------------------------------------------------------------------ Bewegung
@effect("zoom_pulse", "Zoom-Puls (im Beat)", "Bewegung", 50)
def _zoom_pulse(i, o, k, c):
    z = n(0.14 * k)
    expr_w = f"trunc({c.width}*(1+{z}*pow(sin(t*3.2),2))/2)*2"
    expr_h = f"trunc({c.height}*(1+{z}*pow(sin(t*3.2),2))/2)*2"
    return chain(i, o, f"scale=w='{expr_w}':h='{expr_h}':eval=frame,crop={c.width}:{c.height}")


@effect("shake", "Wackeln", "Bewegung", 40)
def _shake(i, o, k, c):
    m = even(c.width * 0.02 * k + 2)
    return chain(
        i, o,
        f"crop=iw-{2 * m}:ih-{2 * m}:x='{m}+{m}*sin(t*37)':y='{m}+{m}*cos(t*43)',"
        f"scale={c.width}:{c.height}",
    )


@effect("mirror", "Spiegeln (Kaleidoskop)", "Bewegung", 100)
def _mirror(i, o, k, c):
    a, b, m = f"{o}_a", f"{o}_b", f"{o}_m"
    return (
        f"[{i}]crop=iw/2:ih:0:0,split[{a}][{b}];[{b}]hflip[{m}];"
        f"[{a}][{m}]hstack,scale={c.width}:{c.height}[{o}]"
    )


# ----------------------------------------------------------- Glitch & Retro
@effect("rgb_split", "RGB-Versatz (Chromatic Aberration)", "Glitch", 50)
def _rgb_split(i, o, k, c):
    d = int(2 + 14 * k)
    return chain(i, o, f"rgbashift=rh={-d}:bh={d}:gv={d // 3}")


@effect("glitch", "Glitch (Streifen, RGB, Rauschen)", "Glitch", 70)
def _glitch(i, o, k, c):
    duty = n(0.18 + 0.5 * k)
    gate = f"lt(mod(t,1.3),{duty})"
    cur = i
    parts = []
    # zwei horizontale Streifen, die springen und seitlich verschoben werden
    for idx, (hfrac, speed, amp, phase) in enumerate([(0.12, 9, 12, 0.0), (0.05, 13, 8, 0.31)]):
        base, tmp, band, nxt = f"{o}_b{idx}", f"{o}_t{idx}", f"{o}_s{idx}", f"{o}_o{idx}"
        pos = f"mod(floor(t*{speed})*0.6180339+{phase},1)"
        shift = f"({amp}/100)*main_w*sin(floor(t*{speed})*5.3)*{n(0.4 + k)}"
        parts.append(f"[{cur}]split[{base}][{tmp}]")
        parts.append(
            f"[{tmp}]crop=iw:ih*{hfrac}:0:'(ih-out_h)*{pos}'[{band}]"
        )
        parts.append(
            f"[{base}][{band}]overlay=x='{shift}':"
            f"y='(main_h-overlay_h)*{pos}':enable='{gate}'[{nxt}]"
        )
        cur = nxt
    d = int(4 + 14 * k)
    parts.append(
        f"[{cur}]rgbashift=rh={-d}:bh={d}:gv={d // 3}:enable='{gate}',"
        f"noise=alls={int(15 + 40 * k)}:allf=t:enable='{gate}'[{o}]"
    )
    return ";".join(parts)


@effect("vhs", "VHS-Look", "Glitch", 70)
def _vhs(i, o, k, c):
    d = int(2 + 5 * k)
    return chain(
        i, o,
        f"eq=saturation={n(1 - 0.25 * k)}:contrast={n(1 + 0.1 * k)},"
        f"rgbashift=rh={-d}:bh={d},"
        f"noise=alls={int(10 + 30 * k)}:allf=t,"
        f"drawgrid=w=0:h=4:t=1:c=black@{n(0.12 + 0.3 * k)},"
        f"gblur=sigma={n(0.6 + 1.2 * k)}:steps=1",
    )


@effect("scanlines", "Scanlines (Röhrenmonitor)", "Glitch", 50)
def _scanlines(i, o, k, c):
    return chain(i, o, f"drawgrid=w=0:h=4:t=1:c=black@{n(0.15 + 0.5 * k)}")


@effect("pixelate", "Pixel-Mosaik", "Glitch", 40)
def _pixelate(i, o, k, c):
    f = 2 + 14 * k
    return chain(
        i, o,
        f"scale=trunc(iw/{n(f, 2)}/2)*2:trunc(ih/{n(f, 2)}/2)*2:flags=neighbor,"
        f"scale={c.width}:{c.height}:flags=neighbor",
    )


@effect("flicker", "Flackern", "Glitch", 50)
def _flicker(i, o, k, c):
    return chain(i, o, f"eq=brightness='{n(0.3 * k)}*gt(mod(t*13,1),0.8)':eval=frame")


@effect("invert_flash", "Invertier-Blitz", "Glitch", 50)
def _invert_flash(i, o, k, c):
    return chain(i, o, f"negate=enable='lt(mod(t,1.7),{n(0.06 + 0.2 * k)})'")


# -------------------------------------------------------------------- Aufbau
def categories() -> dict[str, list[Effect]]:
    out: dict[str, list[Effect]] = {}
    for e in REGISTRY.values():
        out.setdefault(e.category, []).append(e)
    return out


# ------------------------------------------------------------ neu in 0.8
@effect("posterize", "Posterisieren (Comic-Farben)", "Farbe", 50)
def _posterize(i, o, k, c):
    step = int(10 + 70 * k)
    expr = f"trunc(val/{step})*{step}"
    return chain(i, o, f"lutrgb=r='{expr}':g='{expr}':b='{expr}'")


@effect("duotone", "Duotone (Orange / Blau)", "Farbe", 60)
def _duotone(i, o, k, c):
    return chain(i, o, f"hue=s={n(1 - 0.9 * k)},colorbalance=rs={n(-0.5 * k)}:bs={n(0.55 * k)}:"
                       f"rm={n(0.1 * k)}:bm={n(0.1 * k)}:rh={n(0.6 * k)}:bh={n(-0.5 * k)}")


@effect("night_vision", "Nachtsicht (grün)", "Farbe", 80)
def _night(i, o, k, c):
    return chain(i, o, f"format=gray,format=rgb24,eq=brightness={n(0.08 * k)}:contrast={n(1 + 0.5 * k)},"
                       f"colorchannelmixer=rr=0.15:gg=1.0:bb=0.2,noise=alls={int(10 + 30 * k)}:allf=t,"
                       f"vignette=angle={n(1.2 - 0.5 * k)}:mode=forward")


@effect("hue_cycle", "Regenbogen-Farbwechsel", "Farbe", 50)
def _hue_cycle(i, o, k, c):
    return chain(i, o, f"hue=h='t*{int(30 + 150 * k)}'")


@effect("comic", "Comic-Kontur", "Farbe", 60)
def _comic(i, o, k, c):
    return chain(i, o, f"edgedetect=mode=colormix:low={n(0.12 - 0.08 * k)}:high={n(0.30 - 0.1 * k)},"
                       f"eq=saturation={n(1.2 + 0.8 * k)}:contrast={n(1.05 + 0.2 * k)}")


@effect("dream_glow", "Traum-Glühen", "Farbe", 50)
def _glow(i, o, k, c):
    a, b, g = f"{o}_a", f"{o}_b", f"{o}_g"
    return (f"[{i}]split[{a}][{b}];[{b}]gblur=sigma={n(6 + 24 * k, 1)}[{g}];"
            f"[{a}][{g}]blend=all_mode=screen:all_opacity={n(0.25 + 0.5 * k)}[{o}]")


@effect("echo_trail", "Nachzieh-Spur (Echo)", "Bewegung", 50)
def _echo(i, o, k, c):
    frames = int(2 + round(6 * k))
    return chain(i, o, f"tmix=frames={frames}")


@effect("fisheye", "Fischauge", "Bewegung", 50)
def _fisheye(i, o, k, c):
    return chain(i, o, f"lenscorrection=k1={n(-0.35 * k)}:k2={n(-0.12 * k)}")


@effect("dutch_tilt", "Schiefe Kamera (Pendeln)", "Bewegung", 50)
def _dutch(i, o, k, c):
    deg = 2 + 8 * k
    z = 1.0 + 0.04 + 0.012 * deg
    w, h = even(c.width), even(c.height)
    return chain(i, o, f"rotate=a='{n(deg)}*PI/180*sin(t*1.2)':ow=iw:oh=ih:c=black,"
                       f"scale=w={even(c.width * z)}:h={even(c.height * z)},crop={w}:{h}")


# ------------------------------------------------------------ neu in 1.4.8
@effect("tilt_shift", "Tilt-Shift (Miniatur-Look)", "Farbe", 60)
def _tilt_shift(i, o, k, c):
    a, b, g = f"{o}_a", f"{o}_b", f"{o}_g"
    return (f"[{i}]split[{a}][{b}];[{b}]gblur=sigma={n(4 + 14 * k, 1)}[{g}];"
            f"[{a}][{g}]blend=all_expr='A+(B-A)*clip((abs(Y/H-0.5)-0.12)/0.22,0,1)',"
            f"eq=saturation={n(1 + 0.35 * k)}:contrast={n(1 + 0.08 * k)}[{o}]")


@effect("zoom_blur", "Zoom-Unschärfe (Speed-Blur)", "Bewegung", 50)
def _zoom_blur(i, o, k, c):
    a, b, d, b2, d2, ab = f"{o}_a", f"{o}_b", f"{o}_c", f"{o}_b2", f"{o}_c2", f"{o}_ab"
    w, h = even(c.width), even(c.height)
    z1, z2 = 1 + 0.025 * (0.4 + k), 1 + 0.06 * (0.4 + k)
    return (f"[{i}]split=3[{a}][{b}][{d}];"
            f"[{b}]scale={even(w * z1)}:{even(h * z1)},crop={w}:{h}[{b2}];"
            f"[{d}]scale={even(w * z2)}:{even(h * z2)},crop={w}:{h}[{d2}];"
            f"[{a}][{b2}]blend=all_mode=average[{ab}];"
            f"[{ab}][{d2}]blend=all_expr='A*0.66+B*0.34'[{o}]")


@effect("stop_motion", "Stop-Motion (Ruckeln)", "Bewegung", 60)
def _stop_motion(i, o, k, c):
    low = max(3, int(round(c.fps * (0.6 - 0.45 * k))))
    return chain(i, o, f"fps={low},fps={c.fps}")


@effect("light_leak", "Lichtleck (warmer Schein)", "Farbe", 60)
def _light_leak(i, o, k, c):
    a, b, g = f"{o}_a", f"{o}_b", f"{o}_g"
    sw, sh = max(8, even(c.width / 8)), max(8, even(c.height / 8))
    v = "exp(-pow((X/W-(0.5+0.45*sin(T*0.6)))*2.4,2))*(1-0.35*Y/H)"
    return (f"[{i}]split[{a}][{b}];"
            f"[{b}]scale={sw}:{sh},format=rgb24,geq=r='255*{v}':g='120*{v}':b='20*{v}',"
            f"scale={even(c.width)}:{even(c.height)}:flags=bilinear,format=rgb24[{g}];"
            f"[{a}]format=rgb24[{a}f];[{a}f][{g}]blend=all_mode=screen:all_opacity={n(0.35 + 0.6 * k)},format=gbrp,format=yuv420p[{o}]")


@effect("pencil", "Bleistiftskizze", "Farbe", 60)
def _pencil(i, o, k, c):
    a, b, g = f"{o}_a", f"{o}_b", f"{o}_g"
    return (f"[{i}]format=gray,split[{a}][{b}];[{b}]negate,gblur=sigma={n(2 + 14 * k, 1)}[{g}];"
            f"[{a}][{g}]blend=all_mode=dodge,format=yuv420p[{o}]")


@effect("thermal", "Wärmebild", "Farbe", 80)
def _thermal(i, o, k, c):
    a, b, t = f"{o}_a", f"{o}_b", f"{o}_t"
    return (f"[{i}]split[{a}][{b}];[{b}]pseudocolor=preset=inferno[{t}];"
            f"[{a}][{t}]blend=all_expr='A+(B-A)*{n(0.3 + 0.7 * k)}',format=yuv420p[{o}]")


def _keep_color(i, o, k, rgb: str):
    return chain(i, o, f"colorhold=color=0x{rgb}:similarity={n(0.5 - 0.38 * k)}:blend=0.1")


@effect("keep_red", "Nur Rot behalten", "Farbe", 60)
def _keep_red(i, o, k, c):
    return _keep_color(i, o, k, "ff0000")


@effect("keep_green", "Nur Grün behalten", "Farbe", 60)
def _keep_green(i, o, k, c):
    return _keep_color(i, o, k, "00ff00")


@effect("keep_blue", "Nur Blau behalten", "Farbe", 60)
def _keep_blue(i, o, k, c):
    return _keep_color(i, o, k, "0000ff")


@effect("strobe", "Strobe (Blitzlicht)", "Glitch", 50)
def _strobe(i, o, k, c):
    return chain(i, o, f"drawbox=x=0:y=0:w=iw:h=ih:color=black@1:t=fill:"
                       f"enable='lt(mod(t*{n(2 + 6 * k, 2)},1),0.4)'")


@effect("double_exposure", "Doppelbelichtung", "Farbe", 55)
def _double_exposure(i, o, k, c):
    a, b, m = f"{o}_a", f"{o}_b", f"{o}_m"
    return (f"[{i}]split[{a}][{b}];[{b}]hflip,eq=brightness=-0.05[{m}];"
            f"[{a}][{m}]blend=all_mode=screen:all_opacity={n(0.3 + 0.55 * k)}[{o}]")


@effect("xray", "Röntgen", "Farbe", 70)
def _xray(i, o, k, c):
    return chain(i, o, f"format=gray,negate,eq=contrast={n(1.1 + 0.9 * k)}:brightness={n(-0.05 * k)},"
                       f"format=rgb24,colorchannelmixer=rr={n(1 - 0.5 * k)}:gg={n(1 - 0.15 * k)}:bb=1.0,format=yuv420p")


# ------------------------------------------------------------ Masken (ab 1.3.1)
# Ein Masken-Effekt wirkt nur in einem Bereich (Ellipse oder Rechteck), der mit einem Objekt mitwandern kann.
# Block-Einstellung "mask": {"shape": "ellipse"|"rect", "x", "y", "w", "h" (Mitte und Größe in % des Bildes),
#                            "feather" 0…100, "invert": bool, "track": [[t, x, y], …]}  (t = Sekunden ab Blockanfang)
MASK_DEFAULTS: dict = {"shape": "ellipse", "x": 50.0, "y": 50.0, "w": 30.0, "h": 30.0, "feather": 25.0,
                       "invert": False, "track": []}
MASK_TRACK_MAX = 60


def mask_params(m: dict | None) -> dict:
    """Ergänzt Standardwerte und begrenzt alles auf sinnvolle Bereiche."""
    out = dict(MASK_DEFAULTS)
    src = m if isinstance(m, dict) else {}

    def num(key, lo, hi):
        try:
            out[key] = min(hi, max(lo, float(src.get(key, out[key]))))
        except (TypeError, ValueError):
            pass
    num("x", 0.0, 100.0)
    num("y", 0.0, 100.0)
    num("w", 1.0, 200.0)
    num("h", 1.0, 200.0)
    num("feather", 0.0, 100.0)
    out["shape"] = "rect" if src.get("shape") == "rect" else "ellipse"
    out["invert"] = bool(src.get("invert", False))
    pts = []
    for q in src.get("track") or []:
        try:
            pts.append([max(0.0, float(q[0])), min(100.0, max(0.0, float(q[1]))), min(100.0, max(0.0, float(q[2])))])
        except (TypeError, ValueError, IndexError):
            continue
    pts.sort(key=lambda q: q[0])
    if len(pts) > MASK_TRACK_MAX:                        # gleichmäßig ausdünnen
        step = (len(pts) - 1) / (MASK_TRACK_MAX - 1)
        pts = [pts[round(i * step)] for i in range(MASK_TRACK_MAX)]
    out["track"] = pts
    return out


def _num(x: float) -> str:
    return f"{x:.5f}".rstrip("0").rstrip(".") or "0"


def _piecewise(points: list[list[float]], col: int, start: float, const: float) -> str:
    """Stückweise lineare FFmpeg-Formel in T (Sekunden); Werte in % → Anteil 0…1."""
    if not points:
        return _num(const / 100.0)
    tt = f"(T-{_num(start)})"
    expr = _num(points[-1][col] / 100.0)
    for a, b in zip(points[-2::-1], points[::-1]):
        dt = b[0] - a[0]
        if dt < 1e-4:
            continue
        slope = (b[col] - a[col]) / 100.0 / dt
        expr = f"if(lt({tt},{_num(b[0])}),{_num(a[col] / 100.0)}+({tt}-{_num(a[0])})*{_num(slope)},{expr})"
    return f"if(lt({tt},{_num(points[0][0])}),{_num(points[0][col] / 100.0)},{expr})"


def mask_expression(m: dict | None, start: float = 0.0, invert: bool = False) -> str:
    """geq-Formel: 255 innerhalb der Form (mit weicher Kante), 0 außerhalb. T ist die Zeit im Video."""
    p = mask_params(m)
    cx = _piecewise(p["track"], 1, start, p["x"])
    cy = _piecewise(p["track"], 2, start, p["y"])
    rx, ry = _num(p["w"] / 200.0), _num(p["h"] / 200.0)
    dx, dy = f"((X+0.5)/W-{cx})/{rx}", f"((Y+0.5)/H-{cy})/{ry}"
    d = f"hypot({dx},{dy})" if p["shape"] == "ellipse" else f"max(abs({dx}),abs({dy}))"
    fe = _num(0.03 + 0.95 * p["feather"] / 100.0)
    m01 = f"clip((1+{fe}/2-{d})/{fe},0,1)"
    if bool(p["invert"]) != bool(invert):
        m01 = f"(1-{m01})"
    return f"255*{m01}"


def _mask_effect(kind: str, i: str, o: str, k: float, c: Ctx, m: dict | None, start: float, invert: bool = False) -> str:
    W, H = even(c.width), even(c.height)
    s = H / 1080.0
    if kind == "blur":
        sig = max(1.0, (4 + 36 * k) * s) / 4.0
        fx = f"scale={max(2, W // 4)}:{max(2, H // 4)}:flags=bilinear,gblur=sigma={n(sig, 2)}:steps=2,scale={W}:{H}:flags=bilinear"
    elif kind == "mosaic":
        size = max(4, int(round((6 + 54 * k) * s)))
        fx = f"pixelize=w={size}:h={size}"
    elif kind == "dim":
        fx = f"eq=brightness={n(-(0.25 + 0.65 * k))}:saturation={n(1 - 0.6 * k)}"
    else:                                              # black
        fx = "lutyuv=y=16:u=128:v=128"
    mw, mh = min(W, 480) // 2 * 2, max(2, int(round(min(W, 480) * H / W / 2)) * 2)
    expr = mask_expression(m, start, invert)
    b, t, e = f"{o}_b", f"{o}_t", f"{o}_e"
    return (f"[{i}]split=3[{b}][{t}][{e}];"
            f"[{t}]scale={mw}:{mh}:flags=bilinear,format=gray,geq=lum='{expr}',scale={W}:{H}:flags=bilinear[{o}_m];"
            f"[{e}]{fx},format=yuva420p[{o}_f];[{o}_f][{o}_m]alphamerge[{o}_a];"
            f"[{b}][{o}_a]overlay[{o}]")


@effect("mask_blur", "Bereich weichzeichnen (Maske)", "Maske", 60, params=True)
def _mask_blur(i, o, k, c, m=None, start=0.0):
    return _mask_effect("blur", i, o, k, c, m, start)


@effect("mask_mosaic", "Bereich verpixeln (Maske)", "Maske", 40, params=True)
def _mask_mosaic(i, o, k, c, m=None, start=0.0):
    return _mask_effect("mosaic", i, o, k, c, m, start)


@effect("mask_dim", "Bereich hervorheben, Rest abdunkeln (Maske)", "Maske", 70, params=True)
def _mask_dim(i, o, k, c, m=None, start=0.0):
    return _mask_effect("dim", i, o, k, c, m, start, invert=True)


@effect("mask_black", "Bereich schwärzen (Maske)", "Maske", 100, params=True)
def _mask_black(i, o, k, c, m=None, start=0.0):
    return _mask_effect("black", i, o, k, c, m, start)


def build_graph(effects: list[dict], in_label: str, out_label: str, ctx: Ctx, prefix: str = "fx") -> list[str]:
    """effects: [{"id": "glitch", "intensity": 70, "start": 0, "end": 3}, …]

    Liefert eine Liste von Filtergraph-Teilen (ohne führendes/abschließendes ';'),
    deren Kette von in_label nach out_label führt. Ohne Effekte: ein einfaches 'null'.
    """
    active = [e for e in effects if e.get("id") in REGISTRY]
    if not active:
        return [f"[{in_label}]null[{out_label}]"]

    parts: list[str] = []
    cur = in_label
    for idx, item in enumerate(active):
        eff = REGISTRY[item["id"]]
        k = max(0.0, min(1.0, float(item.get("intensity", eff.default)) / 100.0))
        nxt = out_label if idx == len(active) - 1 else f"{prefix}{idx}"
        start, end = item.get("start"), item.get("end")
        extra = (item.get("mask"), 0.0 if start is None else float(start)) if eff.params else None
        if start is None and end is None:
            parts.append(eff.build(cur, nxt, k, ctx, *extra) if extra else eff.build(cur, nxt, k, ctx))
        else:
            s = 0.0 if start is None else float(start)
            e_ = 1e9 if end is None else float(end)
            keep, work, done = f"{prefix}{idx}_k", f"{prefix}{idx}_w", f"{prefix}{idx}_d"
            parts.append(f"[{cur}]split[{keep}][{work}]")
            parts.append(eff.build(work, done, k, ctx, *extra) if extra else eff.build(work, done, k, ctx))
            parts.append(f"[{keep}][{done}]overlay=enable='between(t,{s},{e_})'[{nxt}]")
        cur = nxt
    return parts


def chain_for_test(effect_id: str, intensity: int, ctx: Ctx) -> str:
    return ";".join(build_graph([{"id": effect_id, "intensity": intensity}], "in", "out", ctx))

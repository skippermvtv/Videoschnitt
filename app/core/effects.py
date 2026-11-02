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
    build: Callable[[str, str, float, Ctx], str]
    default: int = 60


def effect(id: str, name: str, category: str, default: int = 60):
    def deco(fn):
        REGISTRY[id] = Effect(id, name, category, fn, default)
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
        if start is None and end is None:
            parts.append(eff.build(cur, nxt, k, ctx))
        else:
            s = 0.0 if start is None else float(start)
            e_ = 1e9 if end is None else float(end)
            keep, work, done = f"{prefix}{idx}_k", f"{prefix}{idx}_w", f"{prefix}{idx}_d"
            parts.append(f"[{cur}]split[{keep}][{work}]")
            parts.append(eff.build(work, done, k, ctx))
            parts.append(f"[{keep}][{done}]overlay=enable='between(t,{s},{e_})'[{nxt}]")
        cur = nxt
    return parts


def chain_for_test(effect_id: str, intensity: int, ctx: Ctx) -> str:
    return ";".join(build_graph([{"id": effect_id, "intensity": intensity}], "in", "out", ctx))

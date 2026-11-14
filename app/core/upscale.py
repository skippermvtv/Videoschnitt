"""KI-Hochskalieren (Real-ESRGAN, ncnn/Vulkan): einen Clip mit neuem Bildinhalt auf 1440p oder 2160p vergrößern. Ohne Qt.

Hinweise, die in der Oberfläche auch so stehen: Das ist keine verlustfreie Vergrößerung (neue Details werden vom Modell
erfunden, was bei Gesichtern und Schrift manchmal künstlich wirkt) und es ist langsam: jedes Bild geht einzeln durch die
Grafikkarte. Gearbeitet wird in Stücken, damit der Plattenplatz begrenzt bleibt (je Stück nur einige Hundert Bilder).

Ablauf je Stück: Bilder aus dem Video lesen (PNG) → Programm vergrößert den Ordner → Bilder zu einem Video-Stück verpacken.
Am Ende werden die Stücke verbunden und der Ton des Ausschnitts dazugelegt. Das Ergebnis ist eine neue Datei; der Clip zeigt danach darauf.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from .. import paths
from ..paths import find_binary
from . import whisper_setup
from .whisper_setup import Cancelled

_NOWINDOW = 0x08000000 if os.name == "nt" else 0

RELEASE_APIS = ("https://api.github.com/repos/xinntao/Real-ESRGAN/releases/tags/v0.2.5.0",
                "https://api.github.com/repos/xinntao/Real-ESRGAN-ncnn-vulkan/releases/latest")
ASSET_RE = re.compile(r"realesrgan-ncnn-vulkan-.*windows.*\.zip", re.IGNORECASE)
EXE_NAME = "realesrgan-ncnn-vulkan.exe" if os.name == "nt" else "realesrgan-ncnn-vulkan"

# Schlüssel: (Modellname im Programm, mögliche Vergrößerungsfaktoren, Beschreibung)
MODELS = {
    "video": ("realesr-animevideov3", (2, 3, 4), "Schnell, für Videos geeignet (empfohlen)"),
    "photo": ("realesrgan-x4plus", (4,), "Höchste Qualität für Fotos/echte Aufnahmen, deutlich langsamer"),
}
TARGETS = {1440: "2K (1440p)", 2160: "4K (2160p)"}
CHUNK_FRAMES = 150            # Bilder je Stück (bestimmt den Plattenbedarf)
MIN_FREE_GB = 4.0             # so viel Platz muss mindestens frei sein
CRF = 14                      # Qualität des neuen Videos (sehr hoch)


class UpscaleError(Exception):
    pass


# ------------------------------------------------------------------ Programm einrichten
def program_dir() -> Path:
    return paths.user_dir() / "realesrgan"


def find_program() -> Path | None:
    """Pfad zu realesrgan-ncnn-vulkan(.exe) im Ordner des Programms (auch eine Ebene tiefer, wenn das Archiv einen Ordner enthält)."""
    d = program_dir()
    if not d.is_dir():
        return None
    for p in [d / EXE_NAME] + sorted(d.glob(f"*/{EXE_NAME}")):
        if p.is_file():
            return p
    return None


def models_ok(exe: Path, model: str) -> bool:
    m = exe.parent / "models"
    return (m / f"{model}.param").is_file() or any(m.glob(f"{model}-x*.param"))


def pick_asset(release_json: dict) -> tuple[str, str] | None:
    """(Download-Adresse, Dateiname) des Windows-Pakets aus den Dateien eines GitHub-Releases."""
    for a in release_json.get("assets", []):
        n = str(a.get("name", ""))
        if ASSET_RE.fullmatch(n) and a.get("browser_download_url"):
            return a["browser_download_url"], n
    return None


def find_asset(apis: tuple[str, ...] = RELEASE_APIS) -> tuple[str, str]:
    last = ""
    for api in apis:
        try:
            with whisper_setup._open(api) as r:  # noqa: SLF001
                found = pick_asset(json.loads(r.read().decode("utf-8")))
            if found:
                return found
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
    raise UpscaleError("Das Real-ESRGAN-Paket für Windows wurde bei GitHub nicht gefunden"
                       + (f" ({last})" if last else "") + ". Du kannst es selbst von https://github.com/xinntao/Real-ESRGAN/releases "
                       f"laden (realesrgan-ncnn-vulkan-…-windows.zip) und in den Ordner {program_dir()} entpacken.")


def install(url: str | None = None, progress: Callable[[float], None] | None = None,
            cancelled: Callable[[], bool] | None = None, min_bytes: int = 5_000_000) -> Path:
    """Lädt das Paket (Programm plus Modelle) und entpackt es nach program_dir()."""
    if url is None:
        url, _ = find_asset()
    tmp = Path(tempfile.mkdtemp(prefix="fate_resrgan_")) / "pkg.zip"
    try:
        whisper_setup.download_file(url, tmp, progress, cancelled, min_bytes)
        whisper_setup.safe_extract(tmp, program_dir())
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    exe = find_program()
    if exe is None:
        raise UpscaleError("Nach dem Entpacken wurde kein realesrgan-ncnn-vulkan gefunden.")
    return exe


# ------------------------------------------------------------------ Planung
def plan(src_height: int, target_height: int, model_key: str = "video") -> tuple[int, int]:
    """(Vergrößerungsfaktor für das Modell, Zielhöhe). Das Modell vergrößert ganzzahlig (kleinster passender Faktor),
    danach wird auf die Zielhöhe verkleinert (Lanczos)."""
    if model_key not in MODELS:
        raise UpscaleError(f"Unbekanntes Modell: {model_key}")
    if src_height <= 0:
        raise UpscaleError("Die Höhe des Videos ist unbekannt.")
    if target_height <= src_height:
        raise UpscaleError(f"Das Video ist mit {src_height} Pixeln Höhe schon mindestens so groß wie das Ziel ({target_height}).")
    ratio = target_height / src_height
    scales = MODELS[model_key][1]
    scale = next((s for s in scales if s >= ratio - 1e-6), scales[-1])
    if scale * src_height < target_height:
        raise UpscaleError(f"Mit diesem Modell ist höchstens {scale}-fach möglich ({src_height} → {scale * src_height} Pixel).")
    return scale, target_height


def estimate(duration: float, fps: float, frames_per_second_gpu: float) -> float:
    """Geschätzte Rechenzeit in Sekunden bei einer gemessenen Geschwindigkeit (Bilder je Sekunde)."""
    return duration * fps / max(0.01, frames_per_second_gpu)


def free_space_ok(path: Path, need_gb: float = MIN_FREE_GB) -> tuple[bool, float]:
    try:
        free = shutil.disk_usage(path).free / 1e9
    except OSError:
        return True, 0.0
    return free >= need_gb, free


# ------------------------------------------------------------------ Arbeit
def _ffprobe_fps(path: str) -> float:
    r = subprocess.run([find_binary("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate,r_frame_rate",
                        "-of", "json", path], capture_output=True, text=True, creationflags=_NOWINDOW)
    try:
        s = json.loads(r.stdout or "{}")["streams"][0]
    except (ValueError, KeyError, IndexError):
        return 0.0
    for key in ("avg_frame_rate", "r_frame_rate"):
        a, _, b = str(s.get(key, "0/1")).partition("/")
        try:
            v = float(a) / float(b or 1)
        except (ValueError, ZeroDivisionError):
            continue
        if 1.0 <= v <= 240.0:
            return v
    return 0.0


def _mean_luma(png: Path) -> float:
    """Mittlere Helligkeit 0…255 eines Bildes (zum Erkennen schwarzer Ausgaben)."""
    r = subprocess.run([find_binary("ffmpeg"), "-v", "error", "-i", str(png), "-vf", "scale=32:32,format=gray", "-f", "rawvideo", "-"],
                       capture_output=True, creationflags=_NOWINDOW)
    return sum(r.stdout) / len(r.stdout) if r.stdout else -1.0


def _run_tool(cmd: list[str], total: int, out_dir: Path, cancelled: Callable[[], bool] | None,
              on_count: Callable[[int], None] | None, cwd: Path | None) -> None:
    """Startet das Vergrößerungsprogramm und beobachtet den Ausgabeordner (Fortschritt = fertige Bilder)."""
    log = Path(tempfile.mkdtemp(prefix="fate_resrgan_log_")) / "out.txt"
    try:
        with open(log, "w", encoding="utf-8", errors="replace") as lf:
            proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=str(cwd) if cwd else None, creationflags=_NOWINDOW)
            while proc.poll() is None:
                if cancelled and cancelled():
                    proc.kill()
                    proc.wait()
                    raise Cancelled()
                if on_count:
                    on_count(sum(1 for _ in out_dir.glob("*.png")))
                time.sleep(0.4)
        done = sum(1 for _ in out_dir.glob("*.png"))
        if proc.returncode != 0 or done < total:
            tail = ""
            try:
                tail = " ".join(log.read_text(encoding="utf-8", errors="replace").split())[-300:]
            except OSError:
                pass
            raise UpscaleError(f"Das Vergrößerungsprogramm hat nur {done} von {total} Bildern geschafft (Code {proc.returncode}). "
                               "Meist hilft ein aktueller Grafikkartentreiber (Vulkan nötig)." + (f" Meldung: {tail}" if tail else ""))
    finally:
        shutil.rmtree(log.parent, ignore_errors=True)


def output_path(src: str, in_pt: float, out_pt: float, target_height: int, model_key: str) -> Path:
    """Zieldatei im Ordner „upscaled“; der Name hängt von Quelle, Ausschnitt, Ziel und Modell ab."""
    try:
        st = Path(src).stat()
        sig = f"{src}|{st.st_size}|{st.st_mtime_ns}|{in_pt:.3f}|{out_pt:.3f}|{target_height}|{model_key}"
    except OSError:
        sig = f"{src}|{in_pt:.3f}|{out_pt:.3f}|{target_height}|{model_key}"
    d = paths.user_dir() / "upscaled"
    d.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w\-]+", "_", Path(src).stem)[:40]
    return d / f"{stem}_{target_height}p_{hashlib.sha1(sig.encode('utf-8')).hexdigest()[:8]}.mp4"


def upscale_range(src: str, in_pt: float, out_pt: float, target_height: int, out_file: str | Path, model_key: str = "video",
                  program: list[str] | None = None, models_dir: Path | None = None,
                  progress: Callable[[float, str], None] | None = None, cancelled: Callable[[], bool] | None = None,
                  chunk_frames: int = CHUNK_FRAMES, work_root: Path | None = None, crf: int = CRF) -> Path:
    """Vergrößert den Ausschnitt [in_pt, out_pt] der Datei `src` und schreibt `out_file` (mp4, H.264, mit Ton).

    `program` = Aufruf des Vergrößerungsprogramms (Standard: das eingerichtete realesrgan-ncnn-vulkan; Tests setzen einen Ersatz).
    progress(Anteil 0…1, Text) · cancelled() → True bricht ab (Cancelled)."""
    from .project import probe
    prog = progress or (lambda f, t: None)
    info = probe(src)
    if info.is_image:
        raise UpscaleError("Bei einem Standbild geht das nicht.")
    fps = _ffprobe_fps(src)
    if fps <= 0:
        raise UpscaleError("Die Bildrate des Videos ließ sich nicht lesen.")
    out_pt = out_pt if out_pt > in_pt else info.duration
    seg = out_pt - in_pt
    if seg < 0.2:
        raise UpscaleError("Der Ausschnitt ist zu kurz.")
    scale, final_h = plan(info.height, target_height, model_key)
    cwd: Path | None = None
    if program is None:
        exe = find_program()
        if exe is None:
            raise UpscaleError("Real-ESRGAN ist noch nicht eingerichtet.")
        if not models_ok(exe, MODELS[model_key][0]):
            raise UpscaleError(f"Im Paket fehlt das Modell {MODELS[model_key][0]}.")
        program, cwd, models_dir = [str(exe)], exe.parent, exe.parent / "models"
    root = Path(work_root) if work_root else Path(tempfile.gettempdir())
    ok, free = free_space_ok(root)
    if not ok:
        raise UpscaleError(f"Zu wenig freier Platz: {free:.1f} GB frei, gebraucht werden mindestens {MIN_FREE_GB:.0f} GB.")
    total_frames = max(1, int(round(seg * fps)))
    chunks = [(k, min(chunk_frames, total_frames - k)) for k in range(0, total_frames, chunk_frames)]
    work = Path(tempfile.mkdtemp(prefix="fate_upscale_", dir=str(root)))
    out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    part = out_file.with_name(out_file.stem + ".part.mp4")
    ff = find_binary("ffmpeg")
    t_start = time.time()
    done_frames = 0
    try:
        parts: list[Path] = []
        for ci, (first, n) in enumerate(chunks):
            if cancelled and cancelled():
                raise Cancelled()
            din, dout = work / f"in{ci}", work / f"out{ci}"
            din.mkdir()
            dout.mkdir()
            t0 = in_pt + first / fps
            prog(done_frames / total_frames, f"Stück {ci + 1} von {len(chunks)}: Bilder lesen …")
            r = subprocess.run([ff, "-v", "error", "-y", "-ss", f"{t0:.4f}", "-i", src, "-an", "-vf", f"fps={fps:.6f}", "-frames:v", str(n),
                                "-start_number", "1", "-compression_level", "1", str(din / "%06d.png")],
                               capture_output=True, text=True, creationflags=_NOWINDOW)
            got = sorted(din.glob("*.png"))
            if r.returncode != 0 or not got:
                raise UpscaleError("Die Bilder konnten nicht aus dem Video gelesen werden. " + (r.stderr or "")[-200:])
            cmd = list(program) + ["-i", str(din), "-o", str(dout), "-n", MODELS[model_key][0], "-s", str(scale), "-f", "png"]
            if models_dir is not None:
                cmd += ["-m", str(models_dir)]

            def on_count(c: int, base=done_frames, ci=ci, n=len(got)) -> None:
                elapsed = max(0.1, time.time() - t_start)
                rate = (base + c) / elapsed
                left = (total_frames - base - c) / max(0.01, rate)
                prog((base + c) / total_frames, f"Stück {ci + 1} von {len(chunks)}: Bild {c} von {n} – noch etwa {left / 60:.0f} min "
                                                f"({rate:.1f} Bilder/s)")

            _run_tool(cmd, len(got), dout, cancelled, on_count, cwd)
            if ci == 0:                                                  # bekanntes Problem mancher PCs: schwarze Ausgabe
                a, b = _mean_luma(sorted(din.glob("*.png"))[len(got) // 2]), _mean_luma(sorted(dout.glob("*.png"))[len(got) // 2])
                if a > 20 and 0 <= b < 3:
                    raise UpscaleError("Das Vergrößerungsprogramm liefert schwarze Bilder (bekanntes Problem mancher Grafikkarten/Treiber). "
                                       "Bitte den Grafikkartentreiber aktualisieren oder ein anderes Modell wählen.")
            vf = f"scale=-2:{final_h}:flags=lanczos,format=yuv420p"
            pf = work / f"part{ci:04d}.mkv"
            r = subprocess.run([ff, "-v", "error", "-y", "-framerate", f"{fps:.6f}", "-start_number", "1", "-i", str(dout / "%06d.png"),
                                "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-r", f"{fps:.6f}", str(pf)],
                               capture_output=True, text=True, creationflags=_NOWINDOW)
            if r.returncode != 0 or not pf.is_file():
                raise UpscaleError("Das vergrößerte Stück konnte nicht gespeichert werden. " + (r.stderr or "")[-200:])
            parts.append(pf)
            done_frames += len(got)
            shutil.rmtree(din, ignore_errors=True)                       # Platz sofort wieder freigeben
            shutil.rmtree(dout, ignore_errors=True)
        prog(0.98, "Stücke werden verbunden, Ton wird hinzugefügt …")
        lst = work / "list.txt"
        lst.write_text("".join("file '" + p.as_posix().replace("'", "'\\''") + "'\n" for p in parts), encoding="utf-8")
        cmd = [ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
        if info.has_audio:
            cmd += ["-ss", f"{in_pt:.4f}", "-t", f"{seg:.4f}", "-i", src, "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"]
        cmd += ["-c:v", "copy", "-movflags", "+faststart", "-shortest", str(part)]
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NOWINDOW)
        if r.returncode != 0 or not part.is_file() or part.stat().st_size == 0:
            raise UpscaleError("Die Stücke konnten nicht verbunden werden. " + (r.stderr or "")[-200:])
        os.replace(part, out_file)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    prog(1.0, "Fertig")
    return out_file


def apply_to_clip(project, idx: int, new_path: str) -> None:
    """Lässt den Clip auf die vergrößerte Datei zeigen (sie enthält nur den Ausschnitt: Start 0, Ende = Länge)."""
    from .project import probe
    c = project.clips[idx]
    info = probe(new_path)
    c.path = new_path
    c.in_pt, c.out_pt = 0.0, info.duration
    c.duration = info.duration
    c.width, c.height = info.width, info.height
    c.has_audio = info.has_audio and c.has_audio

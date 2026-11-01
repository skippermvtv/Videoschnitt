"""Fehlerprotokoll, Diagnosebericht und Whisper-Einrichtung (mit lokalem Testserver, ohne Internet)."""
import http.server
import io
import json
import os
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp_appdata = tempfile.mkdtemp()
os.environ["APPDATA"] = tmp_appdata   # alles landet in einem Testordner

from app.core import diagnostics, subtitles, whisper_setup as ws  # noqa: E402

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print("FEHLER", msg)


# ---- Protokoll und Hook
f = diagnostics.setup_logging()
diagnostics.setup_logging()  # zweimal ist harmlos
diagnostics.log("Testeintrag %s", 1)
got = []
diagnostics.install_exception_hooks(got.append)
try:
    raise ValueError("Testfehler")
except ValueError:
    sys.excepthook(*sys.exc_info())
check(got and "ValueError: Testfehler" in got[0], "Hook meldet den Fehler nicht")
t = threading.Thread(target=lambda: 1 / 0)
t.start()
t.join()
check(len(got) == 2 and "ZeroDivisionError" in got[1], "Thread-Fehler wird nicht gemeldet")
for h in diagnostics._LOG.handlers:
    h.flush()
txt = f.read_text(encoding="utf-8")
check("Testeintrag 1" in txt and "ValueError: Testfehler" in txt and "gestartet" in txt, "Protokoll unvollständig")
check(txt.count("gestartet (Python") == 1, "Logging doppelt eingerichtet")
print("OK  Protokoll und Hook")

# ---- Diagnosebericht
enc = diagnostics.test_encoders()
check(enc.get("libx264", (False,))[0], "libx264 sollte im Test funktionieren")
rep = diagnostics.build_report()
for w in ("ClipForge", "FFmpeg:", "Encoder-Test:", "libx264: OK", "Spracherkennung: nicht eingerichtet", "Protokoll (Ende)", "Testeintrag"):
    check(w in rep, f"Bericht ohne '{w}'")
check(len(diagnostics.build_report(False, False)) < len(rep), "Kurzbericht sollte kürzer sein")
print("OK  Diagnosebericht")

# ---- Whisper-Einrichtung gegen lokalen Server
srv_dir = Path(tempfile.mkdtemp())
zbuf = io.BytesIO()
with zipfile.ZipFile(zbuf, "w") as z:
    z.writestr("Release/whisper-cli.exe", b"#!/bin/sh\necho fake\n")
    z.writestr("Release/whisper.dll", b"x" * 50)
(srv_dir / "whisper-bin-x64.zip").write_bytes(zbuf.getvalue())
(srv_dir / "ggml-base.bin").write_bytes(b"M" * 5000)
evil = io.BytesIO()
with zipfile.ZipFile(evil, "w") as z:
    z.writestr("../evil.txt", b"boese")
(srv_dir / "evil.zip").write_bytes(evil.getvalue())


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(srv_dir), **k)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/api":
            body = json.dumps({"assets": [
                {"name": "whisper-cublas-12.4.0-bin-x64.zip", "browser_download_url": base + "/nope.zip"},
                {"name": "whisper-bin-x64.zip", "browser_download_url": base + "/whisper-bin-x64.zip"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
base = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()

url, name = ws.find_program_asset(base + "/api")
check(name == "whisper-bin-x64.zip" and url.endswith("whisper-bin-x64.zip"), f"falsches Programm gewählt: {name}")

check(subtitles.find_whisper() is None, "vor dem Download darf nichts gefunden werden")
prog = []
ws.setup_all("base", lambda t, fr: prog.append((t, fr)), None, program_url=base + "/whisper-bin-x64.zip",
             model_url=base + "/ggml-base.bin", min_bytes=1, model_min_bytes=1)
check(subtitles.find_whisper() is not None, "nach dem Download sollte whisper gefunden werden")
check(prog and prog[-1] == ("Fertig", 1.0) and any("Sprachmodell" in t for t, _ in prog) and any("Programm" in t for t, _ in prog),
      f"Fortschritt unvollständig: {prog[-3:]}")
check(all(a[1] <= b[1] + 1e-9 for a, b in zip(prog, prog[1:])), "Fortschritt springt zurück")
check(not list(subtitles.whisper_dir().rglob("*.part")), ".part-Dateien bleiben liegen")

# zu kleine Datei (Fehlerseite statt Modell) wird abgelehnt und nicht abgelegt
(srv_dir / "ggml-tiny.bin").write_bytes(b"<html>404</html>")
try:
    ws.download_model("tiny", base + "/ggml-tiny.bin")
    check(False, "Zu kleines Modell wurde akzeptiert")
except RuntimeError as e:
    check("zu klein" in str(e), f"andere Meldung: {e}")
check(not (subtitles.whisper_dir() / "ggml-tiny.bin").exists() and not list(subtitles.whisper_dir().rglob("*.part")),
      "Fehlerdatei liegt noch im Ordner")

# Abbrechen
try:
    ws.download_file(base + "/ggml-base.bin", Path(tempfile.mkdtemp()) / "x.bin", None, lambda: True)
    check(False, "Abbrechen hat nicht gewirkt")
except ws.Cancelled:
    pass

# bösartiges Archiv
try:
    ws.safe_extract(srv_dir / "evil.zip", Path(tempfile.mkdtemp()) / "ziel")
    check(False, "Pfad-Trick im Archiv wurde nicht erkannt")
except RuntimeError as e:
    check("Unsicherer Pfad" in str(e), str(e))

# nicht erreichbar -> verständlicher Fehler statt Absturz
try:
    ws.download_file("http://127.0.0.1:9/gibtsnicht", Path(tempfile.mkdtemp()) / "y.bin")
    check(False, "Verbindungsfehler wurde nicht gemeldet")
except Exception:  # noqa: BLE001
    pass
srv.shutdown()
print("OK  Whisper-Einrichtung")

print("ALLES OK" if not fails else f"{len(fails)} FEHLER")
sys.exit(1 if fails else 0)

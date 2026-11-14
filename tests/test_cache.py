"""Zwischenspeicher-Verwaltung: Übersicht, Leeren, Obergrenze (älteste zuerst), geschützte Ordner, Einstellungen."""
import os
import sys
import tempfile
import time
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata_cache")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import paths  # noqa: E402
from app.core import cache, proxy, settings  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


check(cache.human(0) == "0 Bytes" and cache.human(1536) == "1,5 KB" and cache.human(5 * 1024 ** 2) == "5,0 MB" and cache.human(3 * 1024 ** 3) == "3,0 GB", [cache.human(x) for x in (0, 1536, 5 * 1024 ** 2)])
keys = [r["key"] for r in cache.overview()]
check(keys == ["proxies", "preview", "stab", "wave", "thumbs"], keys)

pd = proxy.proxy_dir()
now = time.time()
for i, age in enumerate((300, 200, 100)):          # a ist am ältesten
    f = pd / f"{'abc'[i]}.mp4"
    f.write_bytes(b"x" * 1000)
    os.utime(f, (now - age, now - age))
(pd / "d.part.mp4").write_bytes(b"x" * 5000)        # angefangene Datei
(pd / "notiz.txt").write_text("bleibt")             # fremde Datei bleibt unberührt
ov = {r["key"]: r for r in cache.overview()}
check(ov["proxies"]["files"] == 4 and ov["proxies"]["bytes"] == 8000, ov["proxies"])

# Obergrenze: älteste zuerst, angefangene Dateien bleiben
freed = cache.enforce_limit("proxies", 2500)
check(freed == 1000 and not (pd / "a.mp4").exists() and (pd / "b.mp4").exists() and (pd / "d.part.mp4").exists(), freed)
freed = cache.enforce_limit("proxies", 0)
check(not (pd / "b.mp4").exists() and not (pd / "c.mp4").exists() and (pd / "d.part.mp4").exists(), "bis 0 geleert, .part bleibt")
check(cache.enforce_limit("unbekannt", 0) == 0 and cache.enforce_limit("proxies", -1) == 0, "unbekannte Stelle / negative Grenze")
print("OK  Übersicht und Obergrenze")

# touch ändert die Reihenfolge
for n, age in (("p.mp4", 500), ("q.mp4", 400)):
    (pd / n).write_bytes(b"y" * 1000)
    os.utime(pd / n, (now - age, now - age))
cache.touch(str(pd / "p.mp4"))                      # p wurde benutzt → q ist jetzt der älteste
cache.enforce_limit("proxies", 1000)
check((pd / "p.mp4").exists() and not (pd / "q.mp4").exists(), "zuletzt benutzte bleiben")
print("OK  Benutzung merken")

# Leeren: nur gewählte Stellen; Standbilder, Whisper, Schriften bleiben
still = paths.user_dir() / "standbilder"
still.mkdir(parents=True, exist_ok=True)
(still / "s.png").write_bytes(b"png")
wh = paths.user_dir() / "whisper"
wh.mkdir(parents=True, exist_ok=True)
(wh / "modell.bin").write_bytes(b"m")
th = paths.user_dir() / "thumbs"
th.mkdir(parents=True, exist_ok=True)
(th / "t.png").write_bytes(b"t")
freed = cache.clear(["thumbs"])
check(freed >= 1 and not (th / "t.png").exists() and (pd / "p.mp4").exists(), "nur Vorschaubilder geleert")
cache.clear(["proxies", "preview", "stab", "wave", "thumbs"])
check(not (pd / "p.mp4").exists() and (pd / "notiz.txt").exists(), "Proxys weg, fremde Datei bleibt")
check((still / "s.png").exists() and (wh / "modell.bin").exists(), "Standbilder und Spracherkennung bleiben unangetastet")
check(cache.clear([]) == 0 and cache.clear(["gibt_es_nicht"]) == 0, "leere/unbekannte Auswahl")
print("OK  Leeren schützt Fremdes")

# Einstellungen
d = settings.load()
check(d["proxy_auto"] is True and d["proxy_use"] is True and d["proxy_limit_gb"] == 20.0, d)
settings.save({"proxy_auto": False, "proxy_limit_gb": 5.0, "unbekannt": 1})
d = settings.load()
check(d["proxy_auto"] is False and d["proxy_limit_gb"] == 5.0 and "unbekannt" not in d, d)
print("OK  Einstellungen")
print("ALLES OK")

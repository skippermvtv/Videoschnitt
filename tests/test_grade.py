"""Bildkorrektur: jeder Regler (Extremwerte), Voreinstellungen, Vorher/Nachher-Bild, Export pro Clip."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import exporter, grade  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def run_chain(ff, chain, src):
    cmd = [ff, "-v", "error", "-y", "-i", src, "-vf", chain or "null", "-frames:v", "3", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0 and not r.stderr.strip(), r.stderr.strip()[:300]


def main() -> int:
    ff = find_binary("ffmpeg")
    tmp = Path(tempfile.mkdtemp())
    src = str(tmp / "src.mp4")
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2",
                    "-f", "lavfi", "-i", "sine=duration=2", "-shortest", "-c:v", "libx264", "-c:a", "aac", src], check=True)
    failed = []

    assert grade.is_neutral({}) and grade.is_neutral({"brightness": 0}) and grade.filter_chain({}) == ""
    # jeder Regler an beiden Enden
    for p in grade.PARAMS:
        for val in (p.min, p.max):
            ok, err = run_chain(ff, grade.filter_chain({p.key: val}), src)
            print(("OK  " if ok else "FEHLER ") + f"{p.key} = {val}")
            if not ok:
                failed.append((p.key, val, err))
    ok, err = run_chain(ff, grade.filter_chain({"auto": 1}), src)
    print(("OK  " if ok else "FEHLER ") + "auto")
    if not ok:
        failed.append(("auto", 1, err))
    # alles auf einmal
    allg = {p.key: p.max for p in grade.PARAMS}; allg["auto"] = 1
    ok, err = run_chain(ff, grade.filter_chain(allg), src)
    print(("OK  " if ok else "FEHLER ") + "alle Regler gleichzeitig")
    if not ok:
        failed.append(("alle", 0, err))

    # Voreinstellungen
    presets = json.loads((ROOT / "presets" / "grades.json").read_text(encoding="utf-8"))
    assert len(presets) >= 8
    for pr in presets:
        assert set(pr["values"]) <= grade.KEYS, pr["id"]
        ok, err = run_chain(ff, grade.filter_chain(pr["values"]), src)
        print(("OK  " if ok else "FEHLER ") + "Voreinstellung " + pr["id"])
        if not ok:
            failed.append((pr["id"], 0, err))

    # Vorher/Nachher-Standbild
    png = grade.render_preview(src, 1.0, {"brightness": 40, "saturation": -100})
    assert Path(png).stat().st_size > 2000
    print("OK  Vorher/Nachher-Bild:", png)

    # Export mit unterschiedlicher Korrektur je Clip
    i = probe(src)
    c1 = Clip(src, i.duration, has_audio=True, width=i.width, height=i.height, grade={"saturation": -100, "contrast": 30})
    c2 = Clip(src, i.duration, has_audio=True, width=i.width, height=i.height)
    proj = Project(format_id="shorts", export_id="fast_draft", clips=[c1, c2])
    out = str(tmp / "o.mp4")
    cmd, total, _ = exporter.build_command(proj, out, draft=True)
    exporter.run(cmd, total)
    assert abs(probe(out).duration - total) < 0.3
    print("OK  Export mit Bildkorrektur pro Clip")

    # Rückwärtskompatibel: Projekt ohne grade-Feld laden
    d = {"format_id": "shorts", "clips": [{"path": src, "duration": 2.0}]}
    (tmp / "alt.cforge").write_text(json.dumps(d), encoding="utf-8")
    assert Project.load(str(tmp / "alt.cforge")).clips[0].grade == {}
    print("OK  altes Projektformat lädt")
    for f in failed:
        print("FEHLER:", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

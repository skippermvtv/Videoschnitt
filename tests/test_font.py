"""Prüft die mitgelieferte Schrift: Abdeckung der Buchstaben, Umlaute und Darstellung per FFmpeg-drawtext."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.fontcheck import missing_chars  # noqa: E402
from app.paths import find_binary  # noqa: E402

FONT = Path(__file__).resolve().parent.parent / "fonts" / "FateMetal.ttf"


def main() -> int:
    assert FONT.exists(), "fonts/FateMetal.ttf fehlt"
    need = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzÄÖÜäöü. 0123456789!?,:;-'\"+/()%"
    miss = missing_chars(str(FONT), need)
    assert not miss, f"Zeichen fehlen in der Schrift: {miss}"
    assert missing_chars(str(FONT), "Test 2026! @€") == "@€", "Warnfunktion erkennt fehlende Zeichen nicht"
    print("OK  Zeichenabdeckung (A–Z, a–z, ÄÖÜäöü, Ziffern, Satzzeichen) und Warnfunktion")

    tmp = Path(tempfile.mkdtemp())
    txt = tmp / "t.txt"
    txt.write_text("JAMES Lilly Yeti 2026! äöü", encoding="utf-8")
    font = str(FONT).replace("\\", "/").replace(":", "\\:")
    out = tmp / "f.png"
    r = subprocess.run([find_binary("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "color=white:s=900x200",
                        "-vf", f"drawtext=fontfile='{font}':textfile='{str(txt).replace(chr(92), '/').replace(':', chr(92) + ':')}':"
                               "fontsize=110:fontcolor=black:x=20:y=30", "-frames:v", "1", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and not r.stderr.strip(), r.stderr
    assert out.stat().st_size > 5000
    print("OK  Darstellung mit FFmpeg-drawtext")
    return 0


if __name__ == "__main__":
    sys.exit(main())

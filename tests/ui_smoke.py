"""Echter Start-Test mit PySide6 (läuft ohne Bildschirm: QT_QPA_PLATFORM=offscreen).

Startet das Hauptfenster, prüft die Presets, wählt einen Look, legt einen Text an und
speichert einen Screenshot. Läuft automatisch im GitHub-Workflow vor dem Bauen.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CLIPFORGE_NO_PROMPTS"] = "1"   # keine Dialoge (Wiederherstellen/Speichern-Nachfrage)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui import main_window as mw  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.paths import find_binary  # noqa: E402
from app.ui.theme import STYLE  # noqa: E402


SLOT_ERRORS: list = []


def _collect(exc_type, exc, tb):
    import traceback
    SLOT_ERRORS.append("".join(traceback.format_exception(exc_type, exc, tb)))
    traceback.print_exception(exc_type, exc, tb)


def no_slot_errors(where: str) -> None:
    """Fehler in Qt-Slots werden von Qt nur ausgegeben, nicht geworfen – hier machen wir sie zu Testfehlern."""
    assert not SLOT_ERRORS, f"Fehler in einem Qt-Slot ({where}):\n" + SLOT_ERRORS[0]


FAILS: list[str] = []


class section:  # noqa: N801
    """Ein Abschnitt des Tests: ein Fehler wird gesammelt, die übrigen Abschnitte laufen trotzdem weiter
    (so zeigt ein Durchlauf auf dem Build-Server alle Fehler statt nur den ersten)."""

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is None:
            print("OK  ", self.name)
            return False
        import traceback
        FAILS.append(f"[{self.name}]\n" + "".join(traceback.format_exception(et, ev, tb)[-4:]))
        print("FEHLER in", self.name, "-", et.__name__, ev)
        return isinstance(ev, Exception)        # Abbruch durch Strg+C o. Ä. nicht verschlucken


def main() -> int:
    sys.excepthook = _collect
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.resize(1480, 880)
    win.show()
    app.processEvents()
    no_slot_errors("Fenster aufbauen")

    assert win.cmb_format.count() >= 7, "Format-Presets fehlen"
    assert win.cmb_export.count() >= 4, "Export-Presets fehlen"
    assert win.cmb_look.count() >= 8, "Looks fehlen"
    assert win.fx_tree.topLevelItemCount() >= 4, "Effekt-Kategorien fehlen"

    win.cmb_look.setCurrentIndex(win.cmb_look.findData("glitch_intro"))
    win._on_look_chosen(0)
    assert any(e["id"] == "glitch" for e in win.project.effects), "Look wurde nicht angewendet"

    win.cmb_format.setCurrentIndex(win.cmb_format.findData("tiktok"))
    assert win.project.format_id == "tiktok"

    win.tabs.setCurrentIndex(mw.TAB_TEXT)
    win.add_text()
    assert len(win.project.texts) == 1

    # Bildkorrektur (Tab "Bild") mit einem echten Testvideo
    assert win.tabs.count() == 13 and [win.tabs.tabText(i) for i in range(13)] == ["Medien", "Format", "Bild", "Effekte", "Titel", "Übergänge", "Text", "Clip", "Ton", "Bild-in-Bild", "Split", "Untertitel", "Bewegung"]
    vid = str(Path(tempfile.mkdtemp()) / "t.mp4")
    subprocess.run([find_binary("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=3", "-c:v", "libx264", "-c:a", "aac", "-shortest", vid], check=True)
    win.import_files([vid])
    assert len(win.project.clips) == 1 and win.sel == 0
    win._grade_timer.stop()
    assert win.grade_body.isEnabled()
    win.cmb_grade.setCurrentIndex(win.cmb_grade.findData("warm"))
    win._on_grade_preset(0)
    assert win.project.clips[0].grade.get("temperature") == 40, win.project.clips[0].grade
    win._grade_sliders["brightness"].setValue(25)
    assert win.project.clips[0].grade.get("brightness") == 25
    win.tabs.setCurrentIndex(mw.TAB_GRADE)
    win._grade_timer.stop()
    win._update_grade_preview()
    for _ in range(120):
        app.processEvents()
        time.sleep(0.05)
        if win._grade_worker is None:
            break
    assert win._grade_worker is None and not win.grade_preview.pixmap().isNull(), "Vorher/Nachher-Bild fehlt"
    win.apply_grade_to_all()
    win.reset_grade()
    assert win.project.clips[0].grade == {}
    win._grade_sliders["contrast"].setValue(30)
    win._grade_timer.stop()
    app.processEvents()

    # 1.3: Farbräder, Kurven-Editor und LUT mit echten Mausereignissen
    from PySide6.QtCore import QPoint, Qt as _Qt
    from PySide6.QtTest import QTest
    g = win.project.clips[0].grade
    wheel = win.wheels["gain"]
    wheel.resize(120, 120)
    app.processEvents()
    QTest.mouseClick(wheel, _Qt.MouseButton.LeftButton, _Qt.KeyboardModifier.NoModifier, QPoint(100, 60))   # rechts von der Mitte = rot
    assert g.get("gain_r", 0) > 20 and g.get("gain_g", 0) < 0, g
    assert wheel.rgb()[0] == g["gain_r"]
    QTest.mouseDClick(wheel, _Qt.MouseButton.LeftButton, _Qt.KeyboardModifier.NoModifier, QPoint(100, 60))
    assert "gain_r" not in g and wheel.rgb() == (0, 0, 0), (g, wheel.rgb())
    assert not wheel.grab().isNull()
    ed = win.curve_editor
    ed.resize(220, 220)
    app.processEvents()
    assert ed.curves() == {}
    QTest.mouseClick(ed, _Qt.MouseButton.LeftButton, _Qt.KeyboardModifier.NoModifier, QPoint(110, 60))     # Punkt oben in der Mitte
    cur = g.get("curves", {}).get("m")
    assert cur and len(cur) == 3 and cur[1][1] > 0.6, g
    QTest.mouseClick(ed, _Qt.MouseButton.RightButton, _Qt.KeyboardModifier.NoModifier, QPoint(110, 60))   # wieder löschen
    assert "curves" not in g, g
    win.cmb_curve.setCurrentIndex(win.cmb_curve.findData("r"))
    assert ed.channel() == "r"
    QTest.mouseClick(ed, _Qt.MouseButton.LeftButton, _Qt.KeyboardModifier.NoModifier, QPoint(110, 60))
    assert "r" in g.get("curves", {}) and "m" not in g["curves"], g
    assert not ed.grab().isNull()
    win.reset_curve()
    assert "curves" not in g, g
    os.environ["APPDATA"] = tempfile.mkdtemp()
    cube = str(Path(tempfile.mkdtemp()) / "t.cube")
    Path(cube).write_text("LUT_3D_SIZE 2\n" + "\n".join(f"{r} {gg} {b}" for b in (0, 1) for gg in (0, 1) for r in (0, 1)) + "\n", encoding="utf-8")
    assert win.set_lut(cube) and g["lut"].endswith(".cube") and win.btn_lut_clear.isEnabled()
    win.lut_mix.setValue(40)
    assert g.get("lut_mix") == 40.0
    win._update_grade_preview()                  # Vorher/Nachher mit LUT-Mischung
    for _ in range(120):
        app.processEvents()
        time.sleep(0.05)
        if win._grade_worker is None:
            break
    assert win._grade_worker is None and not win.grade_preview.pixmap().isNull()
    win.clear_lut()
    assert "lut" not in g and not win.btn_lut_clear.isEnabled()
    win.cmb_grade.setCurrentIndex(win.cmb_grade.findData("s_curve"))
    win._on_grade_preset(0)
    g = win.project.clips[0].grade                 # das Preset ersetzt das Dict
    assert "curves" in g and win.curve_editor.curves() == g["curves"], g
    win.cmb_grade.setCurrentIndex(win.cmb_grade.findData("teal_orange"))
    win._on_grade_preset(0)
    g = win.project.clips[0].grade
    assert g.get("lift_b", 0) > 0 and win.wheels["lift"].rgb()[2] == g["lift_b"], g
    win.reset_grade()
    win._grade_timer.stop()

    # Übergang (Clip 2 anlegen, Übergang von Clip 1 setzen)
    win._add_to_timeline(vid)
    win._select_clip(0)
    win.clip_trans.setCurrentIndex(win.clip_trans.findData("fadeblack"))
    win.clip_trans_dur.setValue(1.0)
    assert win.project.clips[0].transition == "fadeblack" and abs(win.project.duration - 5.0) < 0.05, win.project.duration
    win.apply_transition_to_all()
    win._select_clip(1)
    assert not win.clip_trans.isEnabled()
    win._select_clip(0)

    # Ton: trennen, Musik hinzufügen, Felder, Mischpult, Wellenform
    wav = str(Path(tempfile.mkdtemp()) / "m.wav")
    subprocess.run([find_binary("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=500:duration=2", wav], check=True)
    win.sel = 0
    win.detach_selected_audio()
    assert win.project.clips[0].audio_detached and win.asel == 0 and win.aud_group.isEnabled()
    win.add_audio_files([wav], track=2)
    assert len(win.project.audio_clips) == 2 and win.tabs.currentIndex() == mw.AUDIO_TAB
    win.aud_vol.setValue(50)
    win.aud_loop.setChecked(True)
    win.aud_fin.setValue(0.5)
    a = win.project.audio_clips[1]
    assert abs(a.volume - 0.5) < 1e-6 and a.loop and abs(a.fade_in - 0.5) < 1e-6
    win.mix_duck.setChecked(True)
    win._mix_mutes[3].setChecked(True)
    win.mix_norm.setChecked(True)
    assert win.project.ducking and win.project.track_mute.get("3") and win.project.normalize
    for _ in range(100):
        app.processEvents()
        time.sleep(0.05)
        if wav in win._waves:
            break
    assert wav in win._waves, "Wellenform fehlt"
    win.tabs.setCurrentIndex(mw.AUDIO_TAB)
    app.processEvents()
    win.timeline.update()
    app.processEvents()

    # Standbild und Bild-in-Bild
    png = str(Path(tempfile.mkdtemp()) / "s.png")
    subprocess.run([find_binary("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=320x180", "-frames:v", "1", png], check=True)
    win.import_files([png])
    assert win.media[png].is_image
    win.add_overlay_files([png])
    assert len(win.project.overlays) == 1 and win.osel == 0 and win.tabs.currentIndex() == mw.OVERLAY_TAB and win.ov_group.isEnabled()
    win.ov_size.setValue(40.0)
    win.ov_corner.setCurrentIndex(win.ov_corner.findData("bl"))
    o = win.project.overlays[0]
    assert abs(o.size_pct - 40.0) < 1e-6 and (o.x_pct, o.y_pct) == (22.0, 78.0), (o.x_pct, o.y_pct)
    win.timeline.update()
    app.processEvents()
    # 1.3: Chroma-Key (Greenscreen) mit echten Feldern
    win.ov_key_on.setChecked(True)
    assert o.key_color == "#00ff00" and win.ov_key_on.isChecked()
    win.ov_key_blue.click()
    assert o.key_color == "#0000ff"
    win.ov_key_sim.setValue(55.0)
    win.ov_key_blend.setValue(10.0)
    win.ov_key_spill.setChecked(False)
    assert (o.key_similarity, o.key_blend, o.key_spill) == (55.0, 10.0, False), (o.key_similarity, o.key_blend, o.key_spill)
    win.ov_key_full.click()
    assert (o.x_pct, o.y_pct, o.size_pct) == (50.0, 50.0, 100.0)
    win._select_overlay(0)                       # Felder neu laden: Werte bleiben stehen
    assert win.ov_key_on.isChecked() and win.ov_key_sim.value() == 55.0 and not win.ov_key_spill.isChecked()
    win.ov_key_on.setChecked(False)
    assert o.key_color == "" and not win.ov_key_on.isChecked()
    win.remove_overlay()
    assert not win.project.overlays

    # Untertitel und Textanimation
    srt = str(Path(tempfile.mkdtemp()) / "u.srt")
    Path(srt).write_text("1\n00:00:00,200 --> 00:00:01,500\nHallo Welt\n\n2\n00:00:01,800 --> 00:00:2,900\nZweite Zeile\n", encoding="utf-8")
    assert win.load_srt(srt) == 2 and win.sub_list.count() == 2 and win.sub_edit_box.isEnabled()
    win.sub_text.setPlainText("Geändert")
    assert win.project.subtitles[0].text == "Geändert"
    win.sub_anim.setCurrentIndex(win.sub_anim.findData("fade"))
    win.sub_box.setChecked(True)
    assert win.project.sub_style.anim == "fade" and win.project.sub_style.box
    win.tabs.setCurrentIndex(mw.SUBTITLE_TAB)
    win.tabs.setCurrentIndex(mw.TAB_TEXT)
    win.text_list.setCurrentRow(0)
    win.text_anim.setCurrentIndex(win.text_anim.findData("typewriter"))
    assert win.project.texts[0].anim == "typewriter"
    cmd, total, _ = __import__("app.core.exporter", fromlist=["x"]).build_command(win.project, str(Path(tempfile.mkdtemp()) / "o.mp4"), draft=True)
    assert "drawtext" in " ".join(cmd)
    win.clear_subtitles()

    # Bewegung und Transform
    win._select_clip(0)
    win.tabs.setCurrentIndex(mw.MOTION_TAB)
    assert win.motion_body.isEnabled()
    win.cmb_motion.setCurrentIndex(win.cmb_motion.findData("zoom_in"))
    c0 = win.project.clips[0]
    assert len(c0.keyframes) == 2 and win.kf_list.count() == 2
    win.kf_list.setCurrentRow(1)
    win.kf_fields["zoom"].setValue(150.0)
    assert abs(c0.keyframes[1]["zoom"] - 150.0) < 1e-6
    win._rotate_clip(90)
    win.tf_flip_h.setChecked(True)
    win.tf_crop["l"].setValue(10.0)
    assert c0.rotate == 90 and c0.flip_h and abs(c0.crop_l - 10.0) < 1e-6
    win.timeline.update()
    app.processEvents()
    win.reset_transform()
    win.clear_motion()

    # Vorschau ab Abspielkopf (ohne Dialog: Auftrag direkt ausführen)
    from app.core import exporter as _ex
    jobs = []
    def direct(cmd, total, title, on_done):
        jobs.append(title); _ex.run(cmd, total); on_done("")
    win._run_job = direct
    win.cmb_prev_q.setCurrentIndex(win.cmb_prev_q.findData(240))
    win.cmb_prev_len.setCurrentIndex(win.cmb_prev_len.findData(8.0))
    win.timeline.set_playhead(0.5)
    win.render_preview()
    assert len(jobs) == 1 and win._preview_path, "Vorschau wurde nicht erzeugt"
    win.render_preview()
    assert len(jobs) == 1, "zweite Vorschau muss aus dem Zwischenspeicher kommen"
    app.processEvents()

    # Hilfe, Lizenzen, Symbol
    dlg = win._text_dialog("Kurzanleitung", html=__import__("app.core.helptext", fromlist=["x"]).help_html())
    assert "Importieren" in dlg._browser.toPlainText()
    lic = win._text_dialog("Lizenzen", plain=(Path(__file__).resolve().parent.parent / "THIRD_PARTY.txt").read_text(encoding="utf-8"))
    assert "FFmpeg" in lic._browser.toPlainText()
    assert not win.windowIcon().isNull(), "Fenstersymbol fehlt"
    dlg.close(); lic.close()

    # Rückgängig/Wiederholen, Zoom, Sicherung, Abspielkopf
    n = len(win.project.clips)
    win._history.reset(win.project.to_json())
    win.delete_clip()
    win._history.observe(win.project.to_json(), 1000.0)
    win._history.observe(win.project.to_json(), 1001.0)
    assert len(win.project.clips) == n - 1
    win.undo()
    assert len(win.project.clips) == n, "Rückgängig fehlgeschlagen"
    win.redo()
    assert len(win.project.clips) == n - 1
    win.undo()
    win.timeline.zoom_by(3.0)
    assert win.timeline.zoom > 2.9
    win.timeline.zoom_fit()
    win._seek_project(0.5)
    win.timeline.set_playhead(0.5)
    win.timeline.update()
    app.processEvents()
    assert win.autosave_now() and win._autosave_path().exists()
    assert win.restore_autosave() and len(win.project.clips) == n
    assert not win._autosave_path().exists()

    # 1.2: Effekt-Spur (FX): Blöcke anlegen, auswählen, ändern, ablegen, löschen; Timeline wirklich zeichnen
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QDropEvent
    assert win.tabs.tabText(mw.FX_TAB) == "Effekte"
    n0 = len(win.project.effects)
    win.add_effect_block("vhs", 0.5)
    assert len(win.project.effects) == n0 + 1 and win.fsel == n0 and win.fx_box.isEnabled() and win.btn_fx_del.isEnabled()
    win.fx_int.setValue(35)
    win.fx_start.setValue(1.0)
    win.fx_end.setValue(2.0)
    e = win.project.effects[n0]
    assert e["intensity"] == 35 and win.project.fx_span(n0) == (1.0, 2.0), (e, win.project.fx_span(n0))
    win.timeline.set_project(win.project, win.sel, win.asel, win.osel, win.fsel)
    win.timeline.grab()                                   # zeichnet die Timeline inkl. FX-Spur (Painter-Fehler fallen hier auf)
    it = next(win.fx_tree.topLevelItem(0).child(j) for j in range(win.fx_tree.topLevelItem(0).childCount()))
    md = win.fx_tree.mimeData([it])
    assert md.text().startswith("fate-effect:") and md.text().split(":", 1)[1] == it.data(0, Qt.ItemDataRole.UserRole)
    x_in = win.timeline._x(1.5)
    assert win.timeline.effect_drop(it.data(0, Qt.ItemDataRole.UserRole), x_in) is not None
    assert win.timeline.effect_drop(it.data(0, Qt.ItemDataRole.UserRole), 2.0) is None
    try:
        ev = QDropEvent(QPointF(x_in, win.timeline._lane_y(5) + 8), Qt.DropAction.CopyAction, md, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    except TypeError as exc:
        print("(Drop-Ereignis konnte nicht erzeugt werden:", exc, "- Ablegen wird über das Signal geprüft)")
        win.timeline.effect_dropped.emit(it.data(0, Qt.ItemDataRole.UserRole), 1.5)
    else:
        win.timeline.dropEvent(ev)
    assert len(win.project.effects) == n0 + 2, "Ablegen aus der Effektliste hat keinen Block angelegt"
    win.timeline.grab()
    win.remove_effect_block()
    assert len(win.project.effects) == n0 + 1
    win.undo()
    win.redo()
    win.add_effect_block("glitch", 0.0)                   # bleibt für den Screenshot stehen
    win.timeline.grab()
    no_slot_errors("Effekt-Spur")

    # 1.1: Menüeinträge, Diagnose-Fenster, Fehlerdialog, Protokoll
    from PySide6.QtWidgets import QMenu
    from app.ui.workers import DiagnoseWorker
    from app.core import diagnostics
    titles = [a.text() for m in win.menuBar().findChildren(QMenu) for a in m.actions()]
    for t in ("Diagnose und Fehlerbericht …", "Spracherkennung einrichten …", "Protokoll-Ordner öffnen", "Kurzanleitung"):
        assert t in titles, f"Menüeintrag fehlt: {t}"
    d = win._report_dialog("Test", "Hallo")
    assert d._edit.toPlainText() == "Hallo"
    got = []
    w = DiagnoseWorker()
    w.done.connect(got.append)
    w.start()
    for _ in range(300):
        app.processEvents()
        time.sleep(0.05)
        if got:
            break
    w.wait()
    assert got and "Encoder-Test:" in got[0] and "libx264" in got[0], got
    win.show_crash("Traceback (test)")      # ohne Dialoge (NO_PROMPTS): darf nichts tun und nicht abstürzen
    diagnostics.setup_logging()
    diagnostics.log("ui_smoke 1.1 ok")
    assert diagnostics.log_file().exists()


    # 1.4: Maske im Effekt-Kasten
    win.tabs.setCurrentIndex(mw.FX_TAB)
    win.add_effect_block("mask_mosaic", 0.0)
    assert win.fx_mask_box.isVisibleTo(win), "Maskenfelder fehlen bei Masken-Effekt"
    win.mask_w.setValue(44.0)
    win.mask_shape.setCurrentIndex(win.mask_shape.findData("rect"))
    mk = win.project.effects[win.fsel]["mask"]
    assert mk["w"] == 44.0 and mk["shape"] == "rect", mk
    win._on_mask_canvas({"x": 30.0, "y": 40.0, "w": 20.0, "h": 25.0})
    mk = win.project.effects[win.fsel]["mask"]
    assert (mk["x"], mk["y"], mk["w"], mk["h"]) == (30.0, 40.0, 20.0, 25.0), mk
    # Rahmen im Vorschaubild: Bild laden, mit der Maus verschieben
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    win.show()
    win.btn_mask_edit.setChecked(True)
    assert win.view_stack.currentIndex() == 1
    for _ in range(200):
        app.processEvents()
        time.sleep(0.05)
        if win.mask_canvas.has_frame():
            break
    assert win.mask_canvas.has_frame(), "Maskenbild wurde nicht geladen"
    cv = win.mask_canvas
    r = cv._img_rect()
    c0 = QPoint(int(r.x() + 0.30 * r.width()), int(r.y() + 0.40 * r.height()))
    QTest.mousePress(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c0)
    QTest.mouseMove(cv, c0 + QPoint(int(0.10 * r.width()), 0))
    QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c0 + QPoint(int(0.10 * r.width()), 0))
    mk = win.project.effects[win.fsel]["mask"]
    assert abs(mk["x"] - 40.0) < 3.0 and abs(mk["y"] - 40.0) < 1.0, mk
    assert abs(win.mask_x.value() - mk["x"]) < 1e-6
    win.btn_mask_edit.setChecked(False)
    assert win.view_stack.currentIndex() == 0
    # Tracking mit echtem Video: läuft im Hintergrund, Ergebnis landet im Block
    win.project.fx_set_span(win.fsel, 0.0, 2.5)
    win._track_start()
    for _ in range(400):
        app.processEvents()
        time.sleep(0.05)
        if win._track_worker is None:
            break
    assert win._track_worker is None, "Tracking läuft zu lange"
    mk = win.project.effects[win.fsel]["mask"]
    assert len(mk["track"]) >= 2, ("Tracking ohne Ergebnis", mk, win.statusBar().currentMessage())
    win._track_clear()
    assert win.project.effects[win.fsel]["mask"]["track"] == []
    win.add_effect_block("vhs", 0.0)
    assert not win.fx_mask_box.isVisibleTo(win), "Maskenfelder bei normalem Effekt sichtbar"

    # 1.4.1: Stabilisieren-Regler im Reiter „Clip“ + Analyse im Hintergrund
    from app.core import stabilize as _stab
    win._select_clip(0)
    win.clip_stab.setValue(40)
    assert win.project.clips[0].stabilize == 40 and win.clip_stab_label.text() == "40 %"
    if _stab.available():
        win._stab_wait(None)
        for _ in range(400):
            app.processEvents()
            time.sleep(0.05)
            if win._stab_worker is None:
                break
        assert win._stab_worker is None and not _stab.missing(win.project), "Stabilisierungs-Analyse hängt"
    win.clip_stab.setValue(0)
    assert win.project.clips[0].stabilize == 0 and win.clip_stab_label.text() == "aus"

    # 1.4.1: Medien aus dem Raster auf die Timeline ziehen, Stumm-Schalter im Spurkopf, Vollbild-Knopf vorhanden
    from PySide6.QtCore import QPointF as _QPF
    from PySide6.QtGui import QDropEvent as _QDE
    from app.ui.timeline import MEDIA_MIME
    win.tabs.setCurrentIndex(mw.TAB_MEDIA)
    item = win.media_list.item(0)
    md = win.media_list.mimeData([item])
    assert md.text().startswith(MEDIA_MIME) and md.text().split(":", 1)[1] == item.data(Qt.ItemDataRole.UserRole)
    n_clips = len(win.project.clips)
    ev = _QDE(_QPF(win.timeline._x(0.2), win.timeline._lane_y(0) + 10), Qt.DropAction.CopyAction, md,
              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    win.timeline.dropEvent(ev)
    assert len(win.project.clips) == n_clips + 1 and win.sel == 0, (len(win.project.clips), win.sel)
    mr = win.timeline._header_buttons(3)["mute"]
    was = win._mix_mutes[3].isChecked()
    QTest.mouseClick(win.timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(int(mr.left() + 3), int(mr.top() + 3)))
    assert win._mix_mutes[3].isChecked() != was, "Stumm-Schalter im Spurkopf wirkt nicht"
    assert win.project.track_mute.get("3", False) == (not was)
    lr = win.timeline._header_buttons(1)["lock"]
    QTest.mouseClick(win.timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(int(lr.left() + 3), int(lr.top() + 3)))
    assert win.timeline.is_locked(1)
    win.timeline._locked.clear()
    win.timeline.grab()
    assert win.video.toggle_requested is not None

    # 1.4: neue Oberfläche – Medienraster mit Vorschaubildern, Suche, Suchleiste über die Projektzeit, Zoom, Zeitcode
    from PySide6.QtWidgets import QToolButton
    win.tabs.setCurrentIndex(mw.TAB_MEDIA)
    assert win.media_list.count() >= 2 and not win.media_hint.isVisibleTo(win)
    for _ in range(120):                                   # Vorschaubilder entstehen im Hintergrund
        app.processEvents()
        time.sleep(0.05)
        if all(not win.media_list.item(i).icon().isNull() for i in range(win.media_list.count())):
            break
    assert all(not win.media_list.item(i).icon().isNull() for i in range(win.media_list.count())), "Vorschaubilder fehlen"
    win.media_search.setText("zzz-gibt-es-nicht")
    assert all(win.media_list.item(i).isHidden() for i in range(win.media_list.count()))
    win.media_search.setText("")
    assert not any(win.media_list.item(i).isHidden() for i in range(win.media_list.count()))
    win._update_duration()
    assert win.seek.maximum() == int(win.project.duration * 1000) and win.project.duration > 0
    win._show_time(1.25)
    assert win.time_label.text() == "0:01.2" or win.time_label.text() == "0:01.3", win.time_label.text()
    assert win.seek.value() == 1250 and abs(win.timeline.playhead - 1.25) < 1e-6
    win.zoom_slider.setValue(50)
    app.processEvents()
    assert win.timeline.zoom > 1.5, win.timeline.zoom
    win.timeline.zoom_fit()
    win._sync_zoom_slider()
    assert win.zoom_slider.value() == 0
    assert win.btn_export.objectName() == "primary" and win.btn_export.isVisibleTo(win)
    assert len([b for b in win.findChildren(QToolButton) if b.toolTip()]) >= 10
    win.resize(1100, 700)
    app.processEvents()
    win.grab()                                             # zeichnet die ganze neue Oberfläche (Reiterleiste, Raster, Leisten)

    with section("Titel und Übergänge"):
        # 1.4.2: Titel-Reiter, Übergänge-Reiter (Vorschaubilder, Ablegen), Split, Ton verbessern, Oberfläche merken
        from app.ui.timeline import TITLE_MIME, TRANS_MIME
        win.tabs.setCurrentIndex(mw.TAB_TITLES)
        assert win.title_list.count() >= 10, "Titel-Vorlagen fehlen"
        n_tx = len(win.project.texts)
        win.add_title("lower_third", 1.0)
        assert len(win.project.texts) == n_tx + 1 and win.tabs.currentIndex() == mw.TAB_TEXT
        md = win.title_list.mimeData([win.title_list.item(0)])
        assert md.text().startswith(TITLE_MIME), md.text()
        ev = _QDE(_QPF(win.timeline._x(0.5), win.timeline._lane_y(0) + 10), Qt.DropAction.CopyAction, md,
                  Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        win.timeline.dropEvent(ev)
        assert len(win.project.texts) == n_tx + 2, "Titel ablegen"
        win.tabs.setCurrentIndex(mw.TAB_TRANS)
        assert win.trans_list.count() >= 10, "Übergänge fehlen"
        win._start_trans_thumbs()
        for _ in range(400):                                   # Vorschaubilder der Übergänge entstehen im Hintergrund
            app.processEvents()
            time.sleep(0.05)
            if all(not win.trans_list.item(i).icon().isNull() for i in range(win.trans_list.count())):
                break
        assert any(not win.trans_list.item(i).icon().isNull() for i in range(win.trans_list.count())), "Übergangs-Vorschaubilder fehlen"
        while len(win.project.clips) < 3:
            win._add_to_timeline(win.media_list.item(0).data(Qt.ItemDataRole.UserRole))
        win.apply_transition("fade", 0)
        assert win.project.clips[0].transition == "fade"
        win.apply_transition("", 0)
        assert win.project.clips[0].transition == ""
        md = win.trans_list.mimeData([win.trans_list.item(1)])
        assert md.text().startswith(TRANS_MIME), md.text()
        gap = win.project.clip_start(1)
        ev = _QDE(_QPF(win.timeline._x(gap), win.timeline._lane_y(0) + 10), Qt.DropAction.CopyAction, md,
                  Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        win.timeline.dropEvent(ev)
        assert win.project.clips[0].transition == win.trans_list.item(1).data(Qt.ItemDataRole.UserRole), "Übergang ablegen"
        win.apply_transition("", all_clips=True)
    with section("Split: zwei markierte Medien einfügen"):
        # Split: zwei markierte Medien einfügen
        win.tabs.setCurrentIndex(mw.TAB_SPLIT)
        win.media_list.selectAll()
        n_ov = len(win.project.overlays)
        used = win.split_from_media("2h")
        assert len(used) == 2 and len(win.project.overlays) == n_ov + 2 and all(win.project.overlays[i].cell for i in used), used
        assert not win.ov_x.isEnabled() and not win.ov_split_note.isHidden(), "Split-Block: Position sperren"
        win.grab()
        win.clear_split()
        assert not any(o.cell for o in win.project.overlays) and win.ov_x.isEnabled()
    with section("Ton verbessern"):
        # Ton verbessern
        win._select_clip(0)
        win.clip_dn.setValue(30)
        win.clip_vc.setValue(20)
        assert win.project.clips[0].denoise == 30 and win.project.clips[0].voice == 20 and win.clip_dn_label.text() == "30 %"
        win.clip_dn.setValue(0)
        win.clip_vc.setValue(0)
        assert win.clip_dn_label.text() == "aus"
    with section("Export-Thread misst die Lautheit"):
        from app.ui.workers import ExportWorker
        _outp = str(Path(tempfile.mkdtemp()) / "m.mp4")
        _cmd, _tot, _tmpd = mw.exporter.build_command(win.project, _outp, draft=True, preview_height=180, max_seconds=2.0)
        _errs: list = []
        _wk = ExportWorker(_cmd, _tot, None, measure_path=_outp)
        _wk.done.connect(_errs.append)
        _wk.start()
        assert _wk.wait(180000), "Export-Thread wurde nicht fertig"
        app.processEvents()
        assert _errs == [""], _errs
        assert Path(_outp).exists() and Path(_outp).stat().st_size > 0
        assert _wk.loudness is None or -70.0 < _wk.loudness < 5.0, _wk.loudness
    with section("Pipette (Dialog mit Standbild, Klick in die Mitte)"):
        # Pipette (Dialog mit Standbild, Klick in die Mitte)
        from PySide6.QtTest import QTest
        from app.core import frames as _frames
        from app.ui.pickdialog import PickDialog
        _png = str(Path(tempfile.mkdtemp()) / "pick.png")
        _frames.extract_frame(win.project.clips[0].path, _png, 0.5)
        dlg = PickDialog(_png)
        dlg.show()
        app.processEvents()
        assert not dlg.buttons.button(dlg.buttons.StandardButton.Ok).isEnabled(), "OK erst nach einer Wahl"
        QTest.mouseClick(dlg.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, dlg.canvas.rect().center())
        app.processEvents()
        assert dlg.color.startswith("#") and len(dlg.color) == 7, dlg.color
        assert dlg.buttons.button(dlg.buttons.StandardButton.Ok).isEnabled()
        dlg.close()
        assert win.ov_key_eye.text() == "Pipette …"
    with section("Mehrfach-Export: Menüeintrag vorhanden"):
        # Mehrfach-Export: Menüeintrag vorhanden
        assert "Mehrere Formate" in win.act_export_multi.text()
    with section("Geschwindigkeitskurve"):
        # Geschwindigkeitskurve
        win._select_clip(0)
        n_c = len(win.project.clips)
        win.ramp_preset.setCurrentIndex(win.ramp_preset.findData("slow_mid"))
        assert win.ramp_text.text().startswith("0:1") and "Länge" in win.ramp_info.text(), (win.ramp_text.text(), win.ramp_info.text())
        used = win.apply_speed_ramp()
        assert len(used) >= 5 and len(win.project.clips) == n_c - 1 + len(used), (len(used), len(win.project.clips))
        win.ramp_text.setText("0:1, 999:1")
        assert win.apply_speed_ramp() == [] and "999" in win.ramp_info.text()
        # nachträglich ändern: Abschnitt wählen → Kurve erscheint, „ersetzen“ berechnet neu, „entfernen“ stellt den Clip wieder her
        win._select_clip(used[3])
        assert win.btn_ramp_off.isEnabled() and "ersetzen" in win.btn_ramp.text(), win.btn_ramp.text()
        assert win.ramp_group_note.text().startswith("Dieser Clip gehört zu einer Kurve"), win.ramp_group_note.text()
        win.ramp_preset.setCurrentIndex(win.ramp_preset.findData("hero"))
        used2 = win.apply_speed_ramp()
        assert used2 and win.project.clips[used2[0]].ramp_id and win.btn_ramp_off.isEnabled(), used2
        win._select_clip(used2[1])
        assert win.ramp_text.text().startswith("0:2, 35:2, 50:0.2"), win.ramp_text.text()
        assert win.remove_speed_ramp() is True and len(win.project.clips) == n_c, (len(win.project.clips), n_c)
        assert not win.btn_ramp_off.isEnabled() and "anwenden" in win.btn_ramp.text()
    with section("Kurven-Editor: Vorlage erscheint in der Zeichenfläche, Ziehen/Doppelkl"):
        # Kurven-Editor: Vorlage erscheint in der Zeichenfläche, Ziehen/Doppelklick/Rechtsklick ändern das Textfeld
        from PySide6.QtCore import QPoint as _QP, Qt as _Qt
        from PySide6.QtTest import QTest as _QT
        from app.core import rampgraph as _rg
        cur = win.ramp_curve
        cur.resize(400, 160)
        CW, CH = cur.width(), cur.height()          # tatsächliche Größe (das Layout kann sie ändern)
        assert CW > 50 and CH > 50, (CW, CH)
        win.ramp_text.setText("0:1, 50:0.25, 100:1")
        assert len(cur.points()) == 3, cur.points()
        mx, my = _rg.to_px(cur.points()[1], CW, CH)
        _QT.mousePress(cur, _Qt.MouseButton.LeftButton, _Qt.KeyboardModifier.NoModifier, _QP(int(mx), int(my)))
        ux, uy = _rg.to_px([70, 2.0], CW, CH)
        _QT.mouseMove(cur, _QP(int(ux), int(uy)))
        _QT.mouseRelease(cur, _Qt.MouseButton.LeftButton, _Qt.KeyboardModifier.NoModifier, _QP(int(ux), int(uy)))
        pts_now = _rg.rounded(cur.points())
        assert 66 < pts_now[1][0] < 74 and 1.7 < pts_now[1][1] < 2.4, pts_now
        assert win.ramp_text.text().startswith("0:1, ") and len(win.ramp_text.text().split(",")) == 3, win.ramp_text.text()
        ax, ay = _rg.to_px([20, 0.5], CW, CH)
        _QT.mouseDClick(cur, _Qt.MouseButton.LeftButton, _Qt.KeyboardModifier.NoModifier, _QP(int(ax), int(ay)))
        assert len(cur.points()) == 4 and len(win.ramp_text.text().split(",")) == 4, (cur.points(), win.ramp_text.text())
        ax, ay = _rg.to_px(cur.points()[1], CW, CH)
        _QT.mouseClick(cur, _Qt.MouseButton.RightButton, _Qt.KeyboardModifier.NoModifier, _QP(int(ax), int(ay)))
        assert len(cur.points()) == 3 and len(win.ramp_text.text().split(",")) == 3, (cur.points(), win.ramp_text.text())
        cur.grab()                                  # Zeichnen darf nicht abstürzen
    with section("eigene Tempokurven speichern, auswählen, löschen"):
        # eigene Tempokurven speichern, auswählen, löschen
        from app.core import settings as _stq
        _stq.save({"my_ramps": []})
        win.ramp_text.setText("0:1, 40:0.3, 100:1.5")
        assert win.save_my_ramp("Rauschtest") is True
        assert win.ramp_preset.currentData() == "my:Rauschtest" and win.ramp_del.isEnabled(), win.ramp_preset.currentData()
        win.ramp_text.setText("0:1, 100:1")
        win.ramp_preset.setCurrentIndex(0)
        assert not win.ramp_del.isEnabled()
        win.ramp_preset.setCurrentIndex(win.ramp_preset.findData("my:Rauschtest"))
        assert win.ramp_text.text() == "0:1, 40:0.3, 100:1.5", win.ramp_text.text()
        assert win.delete_my_ramp() is True and win.ramp_preset.findData("my:Rauschtest") == -1 and _stq.load()["my_ramps"] == []
    with section("Chroma-Key auf dem Hauptvideo"):
        # Chroma-Key auf dem Hauptvideo
        win._select_clip(0)
        win.ck_on.setChecked(True)
        assert win.project.clips[win.sel].key_color == "#00ff00", win.project.clips[win.sel].key_color
        win.ck_sim.setValue(55.0)
        assert win.project.clips[win.sel].key_similarity == 55.0
        win.ck_blue.click()
        assert win.project.clips[win.sel].key_color == "#0000ff" and win.ck_on.isChecked()
        win.ck_on.setChecked(False)
        assert win.project.clips[win.sel].key_color == "" and "schwarz" in win.ck_bg_label.text()
    with section("Was ist neu: nach Versionswechsel erscheint das Fenster einmal, danach"):
        # Was ist neu: nach Versionswechsel erscheint das Fenster einmal, danach nicht mehr
        from app.core import settings as _st0
        from app.ui import whatsnewdialog as _wnd
        _shown = []
        _wnd.WhatsNewDialog.exec = lambda self: _shown.append(self.browser.toPlainText()) or 0
        _st0.save({"last_version": "1.0.0", "whatsnew_off": False})
        assert win._check_whats_new() is True and f"Version {mw.VERSION}" in _shown[0], _shown
        assert _st0.load()["last_version"] == mw.VERSION
        assert win._check_whats_new() is False and len(_shown) == 1
        _st0.save({"last_version": "1.0.0", "whatsnew_off": True})
        assert win._check_whats_new() is False and len(_shown) == 1
        _st0.save({"whatsnew_off": False})
    with section("Oberfläche merken: Werte in die Einstellungen schreiben, wiederherstel"):
        # Oberfläche merken: Werte in die Einstellungen schreiben, wiederherstellen, zurücksetzen
        from app.core import settings as _st
        win.timeline.set_locked([2])
        win.tabs.setCurrentIndex(mw.TAB_SPLIT)
        win._save_ui()
        saved = _st.load()
        assert saved["ui_locked"] == [2] and saved["ui_tab"] == mw.TAB_SPLIT and len(saved["ui_hsplit"]) == 2, saved
        win.timeline.set_locked([])
        win.tabs.setCurrentIndex(mw.TAB_MEDIA)
        win._restore_ui()
        assert win.timeline.locked_lanes() == [2] and win.tabs.currentIndex() == mw.TAB_SPLIT
        win.timeline.set_locked([])
        _st.save({"ui_locked": [], "ui_tab": 0, "ui_zoom": 1.0, "ui_hsplit": [], "ui_vsplit": []})
        win.tabs.setCurrentIndex(mw.TAB_MEDIA)
    try:
        no_slot_errors("1.4.2")
    except AssertionError as exc:
        FAILS.append(f"[Slot-Fehler]\n{exc}")

    if FAILS:
        print("\n===== %d Abschnitt(e) fehlgeschlagen =====" % len(FAILS))
        print("\n".join(FAILS))
        return 1
    no_slot_errors("Ende des Tests")
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "ui_smoke.png")
    win.grab().save(str(out))
    print("UI-Start-Test OK, Screenshot:", out)
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

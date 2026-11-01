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

from app.ui.main_window import MainWindow  # noqa: E402
from app.paths import find_binary  # noqa: E402
from app.ui.theme import STYLE  # noqa: E402


def main() -> int:
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.resize(1480, 880)
    win.show()
    app.processEvents()

    assert win.cmb_format.count() >= 7, "Format-Presets fehlen"
    assert win.cmb_export.count() >= 4, "Export-Presets fehlen"
    assert win.cmb_look.count() >= 8, "Looks fehlen"
    assert win.fx_tree.topLevelItemCount() >= 4, "Effekt-Kategorien fehlen"

    win.cmb_look.setCurrentIndex(win.cmb_look.findData("glitch_intro"))
    win._on_look_chosen(0)
    assert any(e["id"] == "glitch" for e in win.project.effects), "Look wurde nicht angewendet"

    win.cmb_format.setCurrentIndex(win.cmb_format.findData("tiktok"))
    assert win.project.format_id == "tiktok"

    win.tabs.setCurrentIndex(3)
    win.add_text()
    assert len(win.project.texts) == 1

    # Bildkorrektur (Tab "Bild") mit einem echten Testvideo
    assert win.tabs.count() == 9 and win.tabs.tabText(1) == "Bild" and win.tabs.tabText(5) == "Ton" and win.tabs.tabText(6) == "Bild-in-Bild" and win.tabs.tabText(7) == "Untertitel" and win.tabs.tabText(8) == "Bewegung"
    vid = str(Path(tempfile.mkdtemp()) / "t.mp4")
    subprocess.run([find_binary("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=3",
                    "-c:v", "libx264", vid], check=True)
    win.import_files([vid])
    assert len(win.project.clips) == 1 and win.sel == 0
    win._grade_timer.stop()
    assert win.grade_body.isEnabled()
    win.cmb_grade.setCurrentIndex(win.cmb_grade.findData("warm"))
    win._on_grade_preset(0)
    assert win.project.clips[0].grade.get("temperature") == 40, win.project.clips[0].grade
    win._grade_sliders["brightness"].setValue(25)
    assert win.project.clips[0].grade.get("brightness") == 25
    win.tabs.setCurrentIndex(1)
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
    assert len(win.project.audio_clips) == 2 and win.tabs.currentIndex() == 5
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
    win.tabs.setCurrentIndex(5)
    app.processEvents()
    win.timeline.update()
    app.processEvents()

    # Standbild und Bild-in-Bild
    png = str(Path(tempfile.mkdtemp()) / "s.png")
    subprocess.run([find_binary("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=320x180", "-frames:v", "1", png], check=True)
    win.import_files([png])
    assert win.media[png].is_image
    win.add_overlay_files([png])
    assert len(win.project.overlays) == 1 and win.osel == 0 and win.tabs.currentIndex() == 6 and win.ov_group.isEnabled()
    win.ov_size.setValue(40.0)
    win.ov_corner.setCurrentIndex(win.ov_corner.findData("bl"))
    o = win.project.overlays[0]
    assert abs(o.size_pct - 40.0) < 1e-6 and (o.x_pct, o.y_pct) == (22.0, 78.0), (o.x_pct, o.y_pct)
    win.timeline.update()
    app.processEvents()
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
    win.tabs.setCurrentIndex(7)
    win.tabs.setCurrentIndex(3)
    win.text_list.setCurrentRow(0)
    win.text_anim.setCurrentIndex(win.text_anim.findData("typewriter"))
    assert win.project.texts[0].anim == "typewriter"
    cmd, total, _ = __import__("app.core.exporter", fromlist=["x"]).build_command(win.project, str(Path(tempfile.mkdtemp()) / "o.mp4"), draft=True)
    assert "drawtext" in " ".join(cmd)
    win.clear_subtitles()

    # Bewegung und Transform
    win._select_clip(0)
    win.tabs.setCurrentIndex(8)
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

    out = Path(sys.argv[1] if len(sys.argv) > 1 else "ui_smoke.png")
    win.grab().save(str(out))
    print("UI-Start-Test OK, Screenshot:", out)
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

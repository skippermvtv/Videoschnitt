"""Timeline mit Spuren: FX (Effekte), V2 (Bild-in-Bild), V1 (Video) und A1 Ton, A2 Musik, A3 frei.

Maus:
- Effekte: aus der Effektliste auf die FX-Spur ziehen; Block verschieben = Zeitpunkt ändern, Rand ziehen = Länge ändern.
- Klick wählt aus; Klick auf das Zeitlineal setzt den Abspielkopf.
- Videoclips: Rand ziehen = kürzen, in der Mitte ziehen = Reihenfolge ändern.
- Audioblöcke: ziehen = verschieben (auch auf andere Spur), Rand ziehen = kürzen; rasten an Clipgrenzen ein.
- Strg + Mausrad = Zoom, Mausrad (bei Zoom) = seitlich scrollen.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..core import effects as fxlib
from ..core.audiomix import effective_volume
from .theme import ACCENT, MUTED, PANEL

_COLORS = ["#3d5a80", "#5b7f5b", "#80603d", "#6b3d80", "#3d8080", "#80453d"]
_AUDIO_COLORS = {1: "#2f7d6b", 2: "#7d5ba6", 3: "#a6823d"}
LANE_LABELS = ["V1", "A1 Ton", "A2 Musik", "A3 frei", "V2 Bild-in-Bild", "FX Effekte"]
LANE_ORDER = [5, 4, 0, 1, 2, 3]    # von oben nach unten
FX_LANE = 5
FX_COLOR = "#a63d6b"
FX_ROW_H = 18.0
FX_MAX_ROWS = 3
FX_MIME = "fate-effect:"
OV_COLOR = "#b8672f"
LABEL_W = 66.0
RULER_H = 28.0
V_H = 44.0
V2_H = 34.0
A_H = 34.0
GAP = 4.0
EDGE = 7.0
SNAP_PX = 8.0
DRAG_START_PX = 5.0
MAX_ZOOM = 40.0


class Timeline(QWidget):
    clip_selected = Signal(int)
    clip_edited = Signal(int)              # Videoclip wurde mit der Maus gekürzt
    clip_reordered = Signal(int, int)      # (von, nach)
    audio_selected = Signal(int)
    overlay_selected = Signal(int)
    overlay_edited = Signal(int)
    audio_edited = Signal(int)             # während/nach dem Ziehen
    fx_selected = Signal(int)
    fx_edited = Signal(int)                # Effekt-Block wurde verschoben oder in der Länge geändert
    effect_dropped = Signal(str, float)    # (Effekt-ID, Projektzeit) – aus der Effektliste abgelegt
    seek_requested = Signal(float)         # Projektzeit in Sekunden

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(int(RULER_H + FX_ROW_H * FX_MAX_ROWS + 6 + V2_H + V_H + 3 * A_H + 7 * GAP + 6))
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self._project = None
        self._sel = -1
        self._asel = -1
        self._osel = -1
        self._fsel = -1
        self._frects: list[tuple[int, QRectF]] = []
        self._fx_rows: list[int] = []
        self._orects: list[tuple[int, QRectF]] = []
        self._waves: dict = {}
        self._vrects: list[QRectF] = []
        self._arects: list[tuple[int, QRectF]] = []
        self._drag: dict | None = None
        self._zoom = 1.0
        self._view0 = 0.0
        self._playhead = -1.0
        self._drop_t = -1.0

    # ------------------------------------------------------------ Daten
    def set_project(self, project, selected: int, audio_selected: int = -1, overlay_selected: int = -1,
                    fx_selected: int = -1) -> None:
        self._project = project
        self._sel = selected
        self._asel = audio_selected
        self._osel = overlay_selected
        self._fsel = fx_selected
        self._fx_rows = project.fx_rows(FX_MAX_ROWS) if project is not None else []
        self._clamp_view()
        self.update()

    def set_waveforms(self, waves: dict) -> None:
        self._waves = waves
        self.update()

    @property
    def playhead(self) -> float:
        return self._playhead

    def set_playhead(self, t: float) -> None:
        self._playhead = t
        self.update()

    # ------------------------------------------------------------ Zoom
    def _total(self) -> float:
        return max(1.0, self._project.duration) if self._project else 1.0

    def _span(self) -> float:
        return self._total() / self._zoom

    def _clamp_view(self) -> None:
        self._view0 = max(0.0, min(self._view0, self._total() - self._span()))

    def zoom_by(self, factor: float, anchor_t: float | None = None) -> None:
        if anchor_t is None:
            anchor_t = self._view0 + self._span() / 2
        frac = (anchor_t - self._view0) / self._span()
        self._zoom = max(1.0, min(MAX_ZOOM, self._zoom * factor))
        self._view0 = anchor_t - frac * self._span()
        self._clamp_view()
        self.update()

    def zoom_fit(self) -> None:
        self._zoom = 1.0
        self._view0 = 0.0
        self.update()

    @property
    def zoom(self) -> float:
        return self._zoom

    # ------------------------------------------------------------ Geometrie
    def _avail(self) -> float:
        return max(50.0, self.width() - LABEL_W - 24.0)

    def _x(self, t: float) -> float:
        return 12.0 + LABEL_W + (t - self._view0) / self._span() * self._avail()

    def _t_at(self, x: float) -> float:
        return self._view0 + (x - 12.0 - LABEL_W) / self._avail() * self._span()

    def _in_content(self, x: float) -> bool:
        return 12.0 + LABEL_W <= x <= 12.0 + LABEL_W + self._avail()

    def _fx_row_count(self) -> int:
        return (max(self._fx_rows) + 1) if self._fx_rows else 1

    def _lane_h(self, lane: int) -> float:
        if lane == FX_LANE:
            return FX_ROW_H * self._fx_row_count() + 6.0
        return V_H if lane == 0 else V2_H if lane == 4 else A_H

    def _lane_y(self, lane: int) -> float:
        """lane 0 = V1, 1..3 = A1..A3, 4 = V2, 5 = FX (ganz oben)"""
        y = RULER_H
        for ln in LANE_ORDER:
            if ln == lane:
                return y
            y += self._lane_h(ln) + GAP
        return y

    def _lane_at(self, y: float) -> int:
        for lane in (1, 2, 3):
            top = self._lane_y(lane)
            if top - GAP / 2 <= y <= top + A_H + GAP / 2:
                return lane
        return -1

    def _audio_len(self, a) -> float:
        if a.loop:
            return max(a.length, self._total() - a.start)
        return a.length

    # ------------------------------------------------------------ Zeichnen
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(PANEL))
        self._vrects = []
        self._arects = []
        self._orects = []
        self._frects = []
        proj = self._project
        if proj is None or (not proj.clips and not proj.audio_clips and not proj.overlays):
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Noch keine Clips – im Reiter „Medien“ importieren (oder Dateien ins Fenster ziehen) und zur Timeline hinzufügen")
            return
        span = self._span()
        avail = self._avail()
        left = 12.0 + LABEL_W
        small = QFont(self.font())
        small.setPointSize(8)
        p.setFont(small)

        # Spurnamen (außerhalb des Zeichenbereichs)
        for lane, label in enumerate(LANE_LABELS):
            y = self._lane_y(lane)
            h = self._lane_h(lane)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(12, y, LABEL_W - 6, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)

        p.setClipRect(QRectF(left, 0, avail, self.height()))
        for lane in range(6):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#161920"))
            p.drawRoundedRect(QRectF(left, self._lane_y(lane), avail, self._lane_h(lane)), 4, 4)

        # Zeitlineal
        step = 0.5 if span <= 8 else 1 if span <= 20 else 5 if span <= 100 else 15 if span <= 600 else 60
        p.setPen(QColor(MUTED))
        t = int(self._view0 / step) * step
        while t <= self._view0 + span + 1e-6:
            x = self._x(t)
            p.drawLine(int(x), 18, int(x), 26)
            p.drawText(int(x) + 3, 14, f"{int(t // 60)}:{t % 60:04.1f}" if step < 1 else f"{int(t // 60)}:{int(t % 60):02d}")
            t += step

        # Videoclips (V1)
        y = self._lane_y(0)
        for i, c in enumerate(proj.clips):
            t0 = proj.clip_start(i)
            r = QRectF(self._x(t0) + 1, y, max(6.0, c.length / span * avail - 2), V_H)
            self._vrects.append(r)
            p.setBrush(QColor(_COLORS[i % len(_COLORS)]))
            p.setPen(QPen(QColor(ACCENT), 3) if i == self._sel and self._asel < 0 and self._osel < 0 and self._fsel < 0 else Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 5, 5)
            p.setPen(QColor("white"))
            label = c.name + f"  {c.length:.1f} s"
            if abs(c.speed - 1) > 1e-3:
                label += f"  ×{c.speed:g}"
            if any(abs(float(v)) > 0 for v in getattr(c, "grade", {}).values()):
                label += "  ◐ Bild"
            if getattr(c, "audio_detached", False):
                label += "  ♪ getrennt"
            if getattr(c, "keyframes", None):
                label += "  ⤢ Bewegung"
            if getattr(c, "has_transform", False):
                label += "  ⟲ Transform"
            if getattr(c, "transition", "") and i < len(proj.clips) - 1:
                label += "  ⇄"
            p.drawText(r.adjusted(5, 3, -5, -3), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, label)

        # Effekte (FX): jeder Block ist ein Effekt mit Zeitfenster
        fy = self._lane_y(FX_LANE)
        for fi, e in enumerate(proj.effects):
            f0, f1 = proj.fx_span(fi)
            x0, x1 = self._x(f0), self._x(f1)
            if x1 <= x0:
                continue
            row = self._fx_rows[fi] if fi < len(self._fx_rows) else 0
            r = QRectF(x0, fy + 3.0 + row * FX_ROW_H, max(6.0, x1 - x0), FX_ROW_H - 2.0)
            self._frects.append((fi, r))
            p.setBrush(QColor(FX_COLOR))
            p.setPen(QPen(QColor(ACCENT), 3) if fi == self._fsel else Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor("white"))
            eff = fxlib.REGISTRY.get(e.get("id"))
            name = eff.name if eff else str(e.get("id"))
            p.drawText(r.adjusted(5, 0, -4, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"{name}  {int(e.get('intensity', 0))} %")

        # Bild-in-Bild (V2)
        oy = self._lane_y(4)
        for oi, o in enumerate(proj.overlays):
            x0 = self._x(o.start)
            x1 = self._x(o.start + o.length)
            if x1 <= x0:
                continue
            r = QRectF(x0, oy, max(6.0, x1 - x0), V2_H)
            self._orects.append((oi, r))
            p.setBrush(QColor(OV_COLOR))
            p.setPen(QPen(QColor(ACCENT), 3) if oi == self._osel else Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 5, 5)
            p.setPen(QColor("white"))
            p.drawText(r.adjusted(5, 2, -5, -2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       o.name + ("  (Bild)" if o.is_image else ""))

        # Audioblöcke
        for idx, a in enumerate(proj.audio_clips):
            lane = a.track if a.track in (1, 2, 3) else 3
            ay = self._lane_y(lane)
            x0 = self._x(a.start)
            x1 = self._x(a.start + self._audio_len(a))
            if x1 <= x0:
                continue
            r = QRectF(x0, ay, max(6.0, x1 - x0), A_H)
            self._arects.append((idx, r))
            muted = effective_volume(proj, a) <= 0
            col = QColor(_AUDIO_COLORS[lane])
            if muted:
                col.setAlpha(110)
            p.setBrush(col)
            p.setPen(QPen(QColor(ACCENT), 3) if idx == self._asel else Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 5, 5)
            pm = self._waves.get(a.path)
            if pm is not None and not pm.isNull() and a.duration > 0:
                self._draw_wave(p, pm, a, r, span, avail)
            p.setPen(QColor("white"))
            label = a.name + ("  (stumm)" if muted else "") + ("  ↻" if a.loop else "")
            p.drawText(r.adjusted(5, 2, -5, -2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, label)

        # Einfüge-Markierung beim Umsortieren
        if self._drop_t >= 0:
            p.setPen(QPen(QColor("#ffd24a"), 3))
            x = self._x(self._drop_t)
            p.drawLine(int(x), int(RULER_H), int(x), int(RULER_H + V_H))

        # Abspielkopf
        if self._playhead >= 0:
            x = self._x(self._playhead)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawLine(int(x), 16, int(x), self.height() - 4)

    def _draw_wave(self, p, pm, a, r: QRectF, span: float, avail: float) -> None:
        pw, ph = float(pm.width()), float(pm.height())
        seg_w = a.length / span * avail
        if seg_w < 1:
            return
        sx0 = max(0.0, a.in_pt / a.duration) * pw
        sx1 = min(1.0, a.out_pt / a.duration) * pw
        if sx1 - sx0 < 1:
            return
        x = r.left()
        inner_top, inner_h = r.top() + 12.0, r.height() - 14.0
        right = min(r.right(), 12.0 + LABEL_W + avail + seg_w)   # nur bis knapp hinter den sichtbaren Rand
        while x < right - 0.5:
            w = min(seg_w, r.right() - x)
            if w <= 0:
                break
            src_w = (sx1 - sx0) * (w / seg_w)
            p.drawPixmap(QRectF(x, inner_top, w, inner_h), pm, QRectF(sx0, 0.0, src_w, ph))
            if not a.loop:
                break
            x += seg_w

    # ------------------------------------------------------------ Treffer
    def _hit_audio(self, pos):
        for idx, r in reversed(self._arects):
            if r.contains(pos):
                mode = "move"
                a = self._project.audio_clips[idx]
                if pos.x() - r.left() <= EDGE:
                    mode = "trim_l"
                elif r.right() - pos.x() <= EDGE and not a.loop:
                    mode = "trim_r"
                return idx, mode
        return -1, ""

    def _hit_fx(self, pos):
        for idx, r in reversed(self._frects):
            if r.contains(pos):
                mode = "move"
                if pos.x() - r.left() <= EDGE:
                    mode = "trim_l"
                elif r.right() - pos.x() <= EDGE:
                    mode = "trim_r"
                return idx, mode
        return -1, ""

    def _hit_overlay(self, pos):
        for idx, r in reversed(self._orects):
            if r.contains(pos):
                mode = "move"
                if pos.x() - r.left() <= EDGE:
                    mode = "trim_l"
                elif r.right() - pos.x() <= EDGE:
                    mode = "trim_r"
                return idx, mode
        return -1, ""

    def _hit_video(self, pos):
        for i, r in enumerate(self._vrects):
            if r.contains(pos):
                mode = "move"
                if pos.x() - r.left() <= EDGE:
                    mode = "trim_l"
                elif r.right() - pos.x() <= EDGE:
                    mode = "trim_r"
                return i, mode
        return -1, ""

    # ------------------------------------------------------------ Maus
    def mousePressEvent(self, event):
        if self._project is None:
            return
        pos = event.position()
        if pos.y() < RULER_H and self._in_content(pos.x()):
            self._drag = {"kind": "scrub"}
            self.seek_requested.emit(max(0.0, min(self._project.duration, self._t_at(pos.x()))))
            return
        if not self._in_content(pos.x()):
            return
        fi, fmode = self._hit_fx(pos)
        if fi >= 0:
            s0, t0 = self._project.fx_span(fi)
            self._fsel, self._osel, self._asel = fi, -1, -1
            self._drag = {"kind": "f", "idx": fi, "mode": fmode, "x": pos.x(), "start": s0, "end": t0}
            self.fx_selected.emit(fi)
            self.update()
            return
        oi, omode = self._hit_overlay(pos)
        if oi >= 0:
            o = self._project.overlays[oi]
            self._osel, self._asel, self._fsel = oi, -1, -1
            self._drag = {"kind": "o", "idx": oi, "mode": omode, "x": pos.x(), "start": o.start, "in": o.in_pt,
                          "out": o.out_pt}
            self.overlay_selected.emit(oi)
            self.update()
            return
        idx, mode = self._hit_audio(pos)
        if idx >= 0:
            a = self._project.audio_clips[idx]
            self._asel = idx
            self._osel = -1
            self._fsel = -1
            self._drag = {"kind": "a", "idx": idx, "mode": mode, "x": pos.x(), "start": a.start, "in": a.in_pt,
                          "out": a.out_pt, "track": a.track}
            self.audio_selected.emit(idx)
            self.update()
            return
        i, mode = self._hit_video(pos)
        if i >= 0:
            c = self._project.clips[i]
            self._sel = i
            self._asel = -1
            self._osel = -1
            self._fsel = -1
            self._drag = {"kind": "v", "idx": i, "mode": mode, "x": pos.x(), "in": c.in_pt, "out": c.out_pt,
                          "started": False}
            self.clip_selected.emit(i)
            self.update()

    def _snap_points(self, skip: int, skip_fx: int = -1) -> list[float]:
        pts = [0.0, self._total()]
        for k in range(len(self._project.effects)):
            if k != skip_fx:
                pts += list(self._project.fx_span(k))
        for i, c in enumerate(self._project.clips):
            t = self._project.clip_start(i)
            pts += [t, t + c.length]
        for j, o in enumerate(self._project.audio_clips):
            if j != skip:
                pts += [o.start, o.start + o.length]
        return pts

    def _snap(self, value: float, pts: list[float]) -> float:
        tol = SNAP_PX / self._avail() * self._span()
        best = value
        dist = tol
        for q in pts:
            if abs(q - value) < dist:
                best, dist = q, abs(q - value)
        return best

    def mouseMoveEvent(self, event):
        if self._project is None:
            return
        pos = event.position()
        if self._drag is None:
            _, fm = self._hit_fx(pos)
            _, om = self._hit_overlay(pos) if not fm else (-1, "")
            _, am = self._hit_audio(pos) if not (om or fm) else (-1, "")
            _, vm = self._hit_video(pos) if not (am or om or fm) else (-1, "")
            mode = fm or om or am or vm
            self.setCursor(Qt.CursorShape.SizeHorCursor if mode in ("trim_l", "trim_r")
                           else Qt.CursorShape.OpenHandCursor if mode == "move" else Qt.CursorShape.ArrowCursor)
            return
        d = self._drag
        kind = d["kind"]
        if kind == "scrub":
            self.seek_requested.emit(max(0.0, min(self._project.duration, self._t_at(pos.x()))))
        elif kind == "v":
            self._move_video(d, pos)
        elif kind == "a":
            self._move_audio(d, pos)
        elif kind == "o":
            self._move_overlay(d, pos)
        elif kind == "f":
            self._move_fx(d, pos)

    def _move_fx(self, d: dict, pos) -> None:
        """Effekt-Block verschieben (rastet an Clipgrenzen und anderen Blöcken ein) oder an einem Rand kürzen/verlängern."""
        proj = self._project
        dt = (pos.x() - d["x"]) / self._avail() * self._span()
        pts = self._snap_points(-1, d["idx"])
        s0, t0 = d["start"], d["end"]
        if d["mode"] == "move":
            start = max(0.0, s0 + dt)
            s1 = self._snap(start, pts)
            s2 = self._snap(start + (t0 - s0), pts) - (t0 - s0)
            d1, d2 = abs(s1 - start), abs(s2 - start)
            if d1 > 1e-9 and (d2 < 1e-9 or d1 <= d2):
                start = s1
            elif d2 > 1e-9:
                start = s2
            start = max(0.0, start)
            total = proj.duration
            if total > 0:
                start = min(start, max(0.0, total - (t0 - s0)))
            proj.fx_set_span(d["idx"], start, start + (t0 - s0))
        elif d["mode"] == "trim_l":
            start = self._snap(max(0.0, min(s0 + dt, t0 - proj.FX_MIN)), pts)
            proj.fx_set_span(d["idx"], min(start, t0 - proj.FX_MIN), t0)
        else:
            end = self._snap(max(s0 + proj.FX_MIN, t0 + dt), pts)
            proj.fx_set_span(d["idx"], s0, max(end, s0 + proj.FX_MIN))
        self._fx_rows = proj.fx_rows(FX_MAX_ROWS)
        self.fx_edited.emit(d["idx"])
        self.update()

    def _move_video(self, d: dict, pos) -> None:
        c = self._project.clips[d["idx"]]
        dx = pos.x() - d["x"]
        dt = dx / self._avail() * self._span()
        sp = max(0.1, c.speed)
        if d["mode"] == "trim_l":
            c.in_pt = min(max(0.0, d["in"] + dt * sp), d["out"] - 0.05)
            self.clip_edited.emit(d["idx"])
        elif d["mode"] == "trim_r":
            c.out_pt = min(max(d["in"] + 0.05, d["out"] + dt * sp), c.duration)
            self.clip_edited.emit(d["idx"])
        else:
            if not d["started"] and abs(dx) < DRAG_START_PX:
                return
            d["started"] = True
            t = self._t_at(pos.x())
            drop = 0
            others = [i for i in range(len(self._project.clips)) if i != d["idx"]]
            for i in others:
                if self._project.clip_start(i) + self._project.clips[i].length / 2 < t:
                    drop += 1
            d["drop"] = drop
            if not others:
                self._drop_t = -1.0
            elif drop < len(others):
                self._drop_t = self._project.clip_start(others[drop])
            else:
                j = others[-1]
                self._drop_t = self._project.clip_start(j) + self._project.clips[j].length
        self.update()

    def _move_overlay(self, d: dict, pos) -> None:
        o = self._project.overlays[d["idx"]]
        dt = (pos.x() - d["x"]) / self._avail() * self._span()
        sp = max(0.1, o.speed)
        pts = self._snap_points(-1)
        if d["mode"] == "move":
            start = max(0.0, d["start"] + dt)
            s1 = self._snap(start, pts)
            s2 = self._snap(start + o.length, pts) - o.length
            d1, d2 = abs(s1 - start), abs(s2 - start)
            if d1 > 1e-9 and (d2 < 1e-9 or d1 <= d2):
                start = s1
            elif d2 > 1e-9:
                start = s2
            o.start = max(0.0, start)
        elif d["mode"] == "trim_l":
            new_in = min(max(0.0, d["in"] + dt * sp), d["out"] - 0.05)
            o.in_pt = new_in
            o.start = max(0.0, d["start"] + (new_in - d["in"]) / sp)
        elif d["mode"] == "trim_r":
            end = self._snap(d["start"] + (d["out"] - d["in"]) / sp + dt, pts)
            o.out_pt = min(max(d["in"] + 0.05, d["in"] + (end - d["start"]) * sp), o.duration)
        self.overlay_edited.emit(d["idx"])
        self.update()

    def _move_audio(self, d: dict, pos) -> None:
        a = self._project.audio_clips[d["idx"]]
        dt = (pos.x() - d["x"]) / self._avail() * self._span()
        sp = max(0.1, a.speed)
        pts = self._snap_points(d["idx"])
        if d["mode"] == "move":
            start = max(0.0, d["start"] + dt)
            s1 = self._snap(start, pts)                       # Anfang rastet ein
            s2 = self._snap(start + a.length, pts) - a.length  # Ende rastet ein
            d1, d2 = abs(s1 - start), abs(s2 - start)
            if d1 > 1e-9 and (d2 < 1e-9 or d1 <= d2):
                start = s1
            elif d2 > 1e-9:
                start = s2
            a.start = max(0.0, start)
            lane = self._lane_at(pos.y())
            if lane in (1, 2, 3):
                a.track = lane
        elif d["mode"] == "trim_l":
            new_in = min(max(0.0, d["in"] + dt * sp), d["out"] - 0.05)
            a.in_pt = new_in
            a.start = max(0.0, d["start"] + (new_in - d["in"]) / sp)
        elif d["mode"] == "trim_r":
            end = d["start"] + (d["out"] - d["in"]) / sp + dt
            end = self._snap(end, pts)
            a.out_pt = min(max(d["in"] + 0.05, d["in"] + (end - d["start"]) * sp), a.duration)
        if a.kind == "video":
            i = self._project.clip_index(a.link)
            if i >= 0:
                a.link_offset = a.start - self._project.clip_start(i)
        self.audio_edited.emit(d["idx"])
        self.update()

    def mouseReleaseEvent(self, _event):
        d = self._drag
        self._drag = None
        self._drop_t = -1.0
        if d is None:
            return
        if d["kind"] == "a":
            self.audio_edited.emit(d["idx"])
        elif d["kind"] == "f":
            self.fx_edited.emit(d["idx"])
        elif d["kind"] == "o":
            self.overlay_edited.emit(d["idx"])
        elif d["kind"] == "v":
            if d["mode"] == "move" and d.get("started") and d.get("drop", d["idx"]) != d["idx"]:
                self.clip_reordered.emit(d["idx"], d["drop"])
            elif d["mode"] != "move":
                self.clip_edited.emit(d["idx"])
        self.update()

    # ------------------------------------------------------------ Ablegen aus der Effektliste
    @staticmethod
    def _mime_effect(mime) -> str:
        try:
            text = mime.text() if mime.hasText() else ""
        except Exception:  # noqa: BLE001
            return ""
        return text[len(FX_MIME):] if text.startswith(FX_MIME) else ""

    def effect_drop(self, effect_id: str, x: float) -> float | None:
        """Wird ein Effekt an der Stelle x abgelegt? Gibt die Projektzeit zurück oder None (außerhalb der Zeitleiste)."""
        if self._project is None or effect_id not in fxlib.REGISTRY or not self._in_content(x):
            return None
        return max(0.0, self._t_at(x))

    def _forward_to_window(self, name: str, event) -> None:
        """Dateien, die auf die Timeline gezogen werden, behandelt wie bisher das Hauptfenster (Import)."""
        w = self.window()
        if w is not None and w is not self and hasattr(w, name):
            getattr(w, name)(event)
        else:
            event.ignore()

    def dragEnterEvent(self, event):
        if self._mime_effect(event.mimeData()):
            event.acceptProposedAction()
        else:
            self._forward_to_window("dragEnterEvent", event)

    def dragMoveEvent(self, event):
        eid = self._mime_effect(event.mimeData())
        if not eid:
            event.acceptProposedAction() if event.mimeData().hasUrls() else event.ignore()
            return
        t = self.effect_drop(eid, event.position().x())
        self._drop_t = -1.0 if t is None else t
        self.update()
        if t is None:
            event.ignore()
        else:
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._drop_t = -1.0
        self.update()

    def dropEvent(self, event):
        eid = self._mime_effect(event.mimeData())
        if not eid:
            self._forward_to_window("dropEvent", event)
            return
        t = self.effect_drop(eid, event.position().x())
        self._drop_t = -1.0
        self.update()
        if t is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.effect_dropped.emit(eid, t)

    def wheelEvent(self, event):
        if self._project is None:
            return
        dy = event.angleDelta().y()
        if dy == 0:
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(1.25 if dy > 0 else 0.8, self._t_at(event.position().x()))
        elif self._zoom > 1.0:
            self._view0 -= dy / 120.0 * self._span() * 0.15
            self._clamp_view()
            self.update()

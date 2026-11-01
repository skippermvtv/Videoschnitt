"""Rückgängig/Wiederholen über Zustands-Schnappschüsse des Projekts (als JSON-Text).

Die Oberfläche ruft regelmäßig observe() mit dem aktuellen Zustand auf. Änderungen, die kurz
nacheinander passieren (z. B. ein Regler wird gezogen), werden zu EINEM Schritt zusammengefasst.
"""
from __future__ import annotations


class History:
    def __init__(self, state: str = "", limit: int = 100, settle: float = 0.6):
        self.limit = limit
        self.settle = settle
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._cur = state
        self._base: str | None = None      # Zustand vor der laufenden Änderungsserie
        self._last_change = 0.0

    @property
    def current(self) -> str:
        return self._cur

    def reset(self, state: str) -> None:
        self._undo.clear()
        self._redo.clear()
        self._cur = state
        self._base = None

    def rebase(self, state: str) -> None:
        """Setzt den aktuellen Zustand, ohne Schritte zu erzeugen (nach Rückgängig/Laden)."""
        self._cur = state
        self._base = None

    def observe(self, state: str, now: float) -> None:
        if state != self._cur:
            if self._base is None:
                self._base = self._cur
            self._cur = state
            self._last_change = now
        elif self._base is not None and now - self._last_change >= self.settle:
            self._commit()

    def _commit(self) -> None:
        if self._base is not None and self._base != self._cur:
            self._undo.append(self._base)
            del self._undo[:-self.limit]
            self._redo.clear()
        self._base = None

    def can_undo(self) -> bool:
        return bool(self._undo) or (self._base is not None and self._base != self._cur)

    def can_redo(self) -> bool:
        return bool(self._redo) and self._base is None

    def undo(self, state: str | None = None) -> str | None:
        """Gibt den vorherigen Zustand zurück (oder None). `state` = aktueller Zustand der Oberfläche."""
        if state is not None and state != self._cur:
            if self._base is None:
                self._base = self._cur
            self._cur = state
        self._commit()
        if not self._undo:
            return None
        self._redo.append(self._cur)
        self._cur = self._undo.pop()
        return self._cur

    def redo(self) -> str | None:
        self._commit()
        if not self._redo:
            return None
        self._undo.append(self._cur)
        self._cur = self._redo.pop()
        return self._cur

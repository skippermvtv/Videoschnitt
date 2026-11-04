ACCENT = "#2fc4b2"          # Türkis wie im Vorbild; Markenrot (FATE) bleibt beim Namenszug
BRAND = "#d4382c"
BG = "#1a1c21"
PANEL = "#22252b"
PANEL_2 = "#2b2f37"
LINE = "#343842"
TEXT = "#dfe2e8"
MUTED = "#8d929d"

STYLE = f"""
* {{ font-size: 13px; }}
QMainWindow, QDialog, QWidget {{ background: {BG}; color: {TEXT}; }}
QLabel {{ background: transparent; }}
QMenuBar {{ background: {BG}; color: {TEXT}; padding: 2px 6px; }}
QMenuBar::item {{ background: transparent; padding: 5px 10px; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {PANEL_2}; }}
QMenu {{ background: {PANEL}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT}; color: #07201c; }}
QToolBar {{ background: {PANEL}; border: 0; padding: 4px; spacing: 4px; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 5px 8px; color: {TEXT}; }}
QToolButton:hover {{ background: {PANEL_2}; border-color: {LINE}; }}
QToolButton:checked {{ background: {PANEL_2}; color: {ACCENT}; }}
QToolButton:disabled {{ color: #565b66; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {LINE}; border-radius: 5px; padding: 5px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:checked {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:disabled {{ color: #565b66; }}
QPushButton#primary {{ background: #1f6f66; border-color: #2a8f84; color: #eafffb; font-weight: 700; letter-spacing: 1px; padding: 6px 22px; }}
QPushButton#primary:hover {{ background: #27877c; }}
QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: 5px; background: {PANEL}; top: -1px; }}
QTabBar::tab {{ background: {BG}; padding: 8px 14px; border: 1px solid transparent; color: {MUTED}; }}
QTabBar::tab:selected {{ background: {PANEL}; color: {TEXT}; border: 1px solid {LINE}; border-bottom-color: {PANEL}; border-top-left-radius: 5px; border-top-right-radius: 5px; }}
QListWidget, QTreeWidget, QPlainTextEdit, QLineEdit, QTextEdit {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 5px; padding: 4px; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: transparent; color: {ACCENT}; }}
QListWidget#medialist {{ background: {BG}; border: 0; }}
QListWidget#medialist::item {{ color: {TEXT}; border: 2px solid transparent; border-radius: 4px; padding: 2px; }}
QListWidget#medialist::item:selected {{ border-color: {ACCENT}; color: {ACCENT}; }}
QListWidget#medialist::item:hover {{ background: {PANEL}; }}
QComboBox, QSpinBox, QDoubleSpinBox {{ background: {PANEL_2}; border: 1px solid {LINE}; border-radius: 5px; padding: 4px 8px; min-height: 22px; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; selection-background-color: {ACCENT}; selection-color: #07201c; }}
QSlider::groove:horizontal {{ height: 3px; background: #3a3f4a; border-radius: 1px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 12px; margin: -5px 0; border-radius: 6px; }}
QSlider::handle:horizontal:hover {{ background: {ACCENT}; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 1px; }}
QProgressBar {{ background: {PANEL_2}; border: 1px solid {LINE}; border-radius: 5px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QStatusBar {{ background: {PANEL}; color: {MUTED}; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: 5px; margin-top: 12px; padding-top: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; color: {MUTED}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; }}
QScrollBar:vertical {{ background: {BG}; width: 10px; }}
QScrollBar::handle:vertical {{ background: #3a3f4a; border-radius: 5px; min-height: 24px; }}
QScrollBar:horizontal {{ background: {BG}; height: 10px; }}
QScrollBar::handle:horizontal {{ background: #3a3f4a; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QSplitter::handle {{ background: {BG}; }}
QLabel#timecode {{ background: #101216; border: 1px solid {LINE}; border-radius: 3px; padding: 3px 10px; font-family: Consolas, "Courier New", monospace; font-size: 15px; }}
QLabel#livebadge {{ color: {MUTED}; }}
"""

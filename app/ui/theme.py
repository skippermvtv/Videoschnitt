ACCENT = "#d4382c"
BG = "#121317"
PANEL = "#1b1e25"
PANEL_2 = "#232731"
TEXT = "#e8e9ed"
MUTED = "#8b90a0"

STYLE = f"""
* {{ font-size: 13px; }}
QMainWindow, QDialog, QWidget {{ background: {BG}; color: {TEXT}; }}
QLabel {{ background: transparent; }}
QToolBar {{ background: {PANEL}; border: 0; padding: 6px; spacing: 6px; }}
QToolButton {{ background: {PANEL_2}; border: 1px solid #2c313d; border-radius: 6px; padding: 6px 12px; color: {TEXT}; }}
QToolButton:hover {{ border-color: {ACCENT}; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid #2c313d; border-radius: 6px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #5a5f6e; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: #e5473a; }}
QTabWidget::pane {{ border: 1px solid #2c313d; border-radius: 6px; background: {PANEL}; top: -1px; }}
QTabBar::tab {{ background: {BG}; padding: 8px 14px; border: 1px solid transparent; color: {MUTED}; }}
QTabBar::tab:selected {{ background: {PANEL}; color: {TEXT}; border: 1px solid #2c313d; border-bottom-color: {PANEL}; border-top-left-radius: 6px; border-top-right-radius: 6px; }}
QListWidget, QTreeWidget, QPlainTextEdit, QLineEdit, QTextEdit {{ background: {PANEL}; border: 1px solid #2c313d; border-radius: 6px; padding: 4px; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {ACCENT}; color: white; }}
QComboBox, QSpinBox, QDoubleSpinBox {{ background: {PANEL_2}; border: 1px solid #2c313d; border-radius: 6px; padding: 4px 8px; min-height: 22px; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; selection-background-color: {ACCENT}; }}
QSlider::groove:horizontal {{ height: 4px; background: #2c313d; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QProgressBar {{ background: {PANEL_2}; border: 1px solid #2c313d; border-radius: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QStatusBar {{ background: {PANEL}; color: {MUTED}; }}
QGroupBox {{ border: 1px solid #2c313d; border-radius: 6px; margin-top: 12px; padding-top: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; color: {MUTED}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; }}
"""

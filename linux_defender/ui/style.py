"""Theme tokens and Qt stylesheet (dark and light)."""

THEMES = {
    "dark": {
        "bg": "#14171c", "side": "#0e1014", "card": "#1c2027", "card2": "#232832", "line": "#2b313b",
        "text": "#e6eaef", "muted": "#8d97a3", "accent": "#2fd38a", "accent_text": "#062016",
        "blue": "#4c9dff", "warn": "#ffc24b", "risk": "#ff6a6a", "hover": "#262c36", "sel": "#1f3a2e",
        "input": "#11141a",
    },
    "light": {
        "bg": "#f3f5f8", "side": "#ffffff", "card": "#ffffff", "card2": "#f6f8fb", "line": "#e1e6ec",
        "text": "#16202b", "muted": "#5f6b78", "accent": "#16a56b", "accent_text": "#ffffff",
        "blue": "#1f6fe0", "warn": "#c77a00", "risk": "#d42e37", "hover": "#eef2f6", "sel": "#dff4ea",
        "input": "#ffffff",
    },
}


def _check_svg(color: str) -> str:
    """Write a small tick-mark SVG (used by checkboxes in lists) and return its path."""
    import os
    import tempfile
    d = os.path.join(tempfile.gettempdir(), f"linux-defender-{os.getuid()}")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"check-{color.strip('#')}.svg")
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" '
                    f'fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    return p


def _arrow_svg(direction: str, color: str) -> str:
    """Small chevron for the up/down buttons of number and time fields."""
    import os
    import tempfile
    d = os.path.join(tempfile.gettempdir(), f"linux-defender-{os.getuid()}")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"arrow-{direction}-{color.strip('#')}.svg")
    if not os.path.exists(p):
        path = "M3 10l5-5 5 5" if direction == "up" else "M3 6l5 5 5-5"
        with open(p, "w", encoding="utf-8") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
                    f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" '
                    'stroke-linejoin="round"/></svg>')
    return p


# width reserved on the right of number/time fields for the up/down buttons (also used by fit_field)
SPIN_BUTTON_W = 22


def stylesheet(name: str) -> str:
    t = THEMES.get(name, THEMES["dark"])
    tick = _check_svg(t["accent_text"])
    up, down = _arrow_svg("up", t["muted"]), _arrow_svg("down", t["muted"])
    up_h, down_h = _arrow_svg("up", t["text"]), _arrow_svg("down", t["text"])
    bw = SPIN_BUTTON_W
    return f"""
QTreeView::indicator, QListView::indicator {{ width: 15px; height: 15px; border: 1.5px solid {t['muted']};
    border-radius: 4px; background: {t['input']}; }}
QTreeView::indicator:hover, QListView::indicator:hover {{ border-color: {t['accent']}; }}
QTreeView::indicator:checked, QListView::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']};
    image: url({tick}); }}
* {{ font-family: "Inter", "Ubuntu", "Noto Sans", sans-serif; font-size: 10pt; color: {t['text']}; }}
QMainWindow, QDialog, #Content {{ background: {t['bg']}; }}
QWidget#Sidebar {{ background: {t['side']}; border-right: 1px solid {t['line']}; }}
QLabel#Brand {{ font-size: 15pt; font-weight: 700; letter-spacing: .5px; }}
QLabel#BrandSub {{ color: {t['muted']}; font-size: 8pt; }}
QPushButton#Nav {{ text-align: left; padding: 10px 14px; border: none; border-radius: 8px;
    background: transparent; color: {t['muted']}; font-weight: 600; }}
QPushButton#Nav:hover {{ background: {t['hover']}; color: {t['text']}; }}
QPushButton#Nav:checked {{ background: {t['sel']}; color: {t['text']}; }}
QLabel#Badge {{ background: {t['risk']}; color: white; border-radius: 8px; padding: 0 5px;
    font-size: 8pt; font-weight: 700; min-width: 8px; }}
QLabel#PageTitle {{ font-size: 18pt; font-weight: 700; }}
QLabel#H2 {{ font-size: 12.5pt; font-weight: 700; }}
QLabel#Muted, QLabel[muted="true"] {{ color: {t['muted']}; }}
QLabel#Hero {{ font-size: 20pt; font-weight: 800; }}
QFrame#Card {{ background: {t['card']}; border: 1px solid {t['line']}; border-radius: 12px; }}
QFrame#Card2 {{ background: {t['card2']}; border: 1px solid {t['line']}; border-radius: 10px; }}
QFrame#Tile {{ background: {t['card']}; border: 1px solid {t['line']}; border-radius: 12px; }}
QFrame#Tile:hover {{ border-color: {t['accent']}; }}
QFrame#Sep {{ background: {t['line']}; max-height: 1px; min-height: 1px; }}
QPushButton {{ background: {t['card2']}; border: 1px solid {t['line']}; border-radius: 8px;
    padding: 7px 14px; font-weight: 600; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:disabled {{ color: {t['muted']}; }}
QPushButton#Primary {{ background: {t['accent']}; color: {t['accent_text']}; border: none; }}
QPushButton#Primary:hover {{ background: {t['accent']}; border: 1px solid {t['text']}; }}
QPushButton#Danger {{ background: transparent; color: {t['risk']}; border: 1px solid {t['risk']}; }}
QPushButton#Link {{ background: transparent; border: none; color: {t['blue']}; padding: 2px 0; text-align: left; }}
QPushButton#Link:hover {{ text-decoration: underline; }}
QLineEdit, QSpinBox, QComboBox, QTimeEdit, QPlainTextEdit {{ background: {t['input']}; border: 1px solid {t['line']};
    border-radius: 7px; padding: 5px 8px; selection-background-color: {t['accent']}; }}
QSpinBox::up-button, QTimeEdit::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: {bw}px;
    border: none; border-left: 1px solid {t['line']}; border-top-right-radius: 7px; background: transparent; }}
QSpinBox::down-button, QTimeEdit::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
    width: {bw}px; border: none; border-left: 1px solid {t['line']}; border-bottom-right-radius: 7px;
    background: transparent; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover, QTimeEdit::up-button:hover, QTimeEdit::down-button:hover {{
    background: {t['card2']}; }}
QSpinBox::up-arrow, QTimeEdit::up-arrow {{ image: url({up}); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QTimeEdit::down-arrow {{ image: url({down}); width: 10px; height: 10px; }}
QSpinBox::up-arrow:hover, QTimeEdit::up-arrow:hover {{ image: url({up_h}); }}
QSpinBox::down-arrow:hover, QTimeEdit::down-arrow:hover {{ image: url({down_h}); }}
QSpinBox::up-arrow:off, QSpinBox::down-arrow:off, QTimeEdit::up-arrow:off, QTimeEdit::down-arrow:off,
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled {{ image: none; }}
QComboBox {{ padding-right: {bw + 6}px; }}
QComboBox::drop-down {{ subcontrol-origin: border; subcontrol-position: center right; width: {bw}px; border: none;
    border-left: 1px solid {t['line']}; border-top-right-radius: 7px; border-bottom-right-radius: 7px;
    background: transparent; }}
QComboBox::drop-down:hover {{ background: {t['card2']}; }}
QComboBox::down-arrow {{ image: url({down}); width: 10px; height: 10px; }}
QComboBox::down-arrow:hover, QComboBox::down-arrow:on {{ image: url({down_h}); }}
QComboBox::down-arrow:disabled {{ image: url({down}); }}
QComboBox QAbstractItemView {{ background: {t['card']}; border: 1px solid {t['line']}; selection-background-color: {t['sel']}; }}
QCheckBox {{ spacing: 8px; }}
QProgressBar {{ background: {t['card2']}; border: none; border-radius: 5px; height: 10px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 5px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {t['muted']}; padding: 9px 16px; border: none;
    border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {t['text']}; border-bottom: 2px solid {t['accent']}; }}
QTabBar::tab:hover {{ color: {t['text']}; }}
QTreeWidget, QListWidget, QTableWidget {{ background: {t['card']}; border: 1px solid {t['line']}; border-radius: 10px;
    alternate-background-color: {t['card2']}; outline: 0; }}
QTreeWidget::item, QListWidget::item {{ padding: 6px 4px; }}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {{ background: {t['sel']}; color: {t['text']}; }}
QHeaderView::section {{ background: {t['card2']}; color: {t['muted']}; border: none; border-bottom: 1px solid {t['line']};
    padding: 6px; font-weight: 600; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['line']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {t['card']}; color: {t['text']}; border: 1px solid {t['line']}; padding: 6px; }}
QMenu {{ background: {t['card']}; border: 1px solid {t['line']}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 5px; }}
QMenu::item:selected {{ background: {t['sel']}; }}
"""


def color(theme: str, key: str) -> str:
    return THEMES.get(theme, THEMES["dark"])[key]

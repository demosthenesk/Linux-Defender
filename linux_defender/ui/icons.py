"""Original line icons (drawn for Linux Defender — no third-party artwork)."""
from PySide6.QtCore import QByteArray, Qt, QSize
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_S = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{b}</svg>'

PATHS = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    "protection": '<path d="M12 2.8 19.5 5.6V11c0 4.9-3.2 8.6-7.5 10.2C7.7 19.6 4.5 15.9 4.5 11V5.6Z"/><path d="m8.8 11.8 2.2 2.2 4.3-4.6"/>',
    "bell": '<path d="M6 16.5V11a6 6 0 1 1 12 0v5.5l1.5 2H4.5Z"/><path d="M10 20.5a2.2 2.2 0 0 0 4 0"/>',
    "settings": '<circle cx="12" cy="12" r="3.1"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7"/>',
    "support": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.6"/><path d="M12 17h.01"/>',
    "quick": '<path d="M13 2.5 5 13.5h6.2L10.5 21.5 19 10.2h-6.4Z"/>',
    "system": '<rect x="3" y="4" width="18" height="12.5" rx="1.8"/><path d="M8.5 20.5h7M12 16.5v4"/><path d="m9 10.3 2 2 4-4"/>',
    "custom": '<path d="M3.5 6.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z"/><circle cx="11.5" cy="12.8" r="2.6"/><path d="m13.4 14.7 2.1 2.1"/>',
    "update": '<path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v4.3h-4.3"/>',
    "quarantine": '<rect x="4" y="9.5" width="16" height="11" rx="2"/><path d="M8 9.5V7a4 4 0 0 1 8 0v2.5"/><path d="M12 14v2.5"/>',
    "exceptions": '<circle cx="12" cy="12" r="8.6"/><path d="m6 6 12 12"/>',
    "schedule": '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 9.5h17M8 3v4M16 3v4"/><path d="M12 12.5v3l2 1.2"/>',
    "shield_check": '<path d="M12 2.8 19.5 5.6V11c0 4.9-3.2 8.6-7.5 10.2C7.7 19.6 4.5 15.9 4.5 11V5.6Z"/><path d="m8.8 11.8 2.2 2.2 4.3-4.6"/>',
    "shield_alert": '<path d="M12 2.8 19.5 5.6V11c0 4.9-3.2 8.6-7.5 10.2C7.7 19.6 4.5 15.9 4.5 11V5.6Z"/><path d="M12 8v4.5M12 15.8h.01"/>',
    "log": '<path d="M7 3.5h7l4 4V20a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z"/><path d="M14 3.5V8h4M9 12h6M9 15.5h6"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "folder": '<path d="M3.5 6.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z"/>',
    "file": '<path d="M7 3.5h7l4 4V20a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z"/><path d="M14 3.5V8h4"/>',
    "trash": '<path d="M4.5 6.5h15M9.5 6.5V4h5v2.5M6.5 6.5l1 14h9l1-14"/>',
    "restore": '<path d="M4 12a8 8 0 1 0 2.4-5.7"/><path d="M4 4v4.3h4.3"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "pause": '<path d="M9 5v14M15 5v14"/>',
    "play": '<path d="M7 4.5 19 12 7 19.5Z"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.8h.01"/>',
    "warning": '<path d="M12 3.5 21.5 20h-19Z"/><path d="M12 10v4.5M12 17.3h.01"/>',
    "critical": '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.6 3.8 5.6 3.8 9s-1.2 6.4-3.8 9c-2.6-2.6-3.8-5.6-3.8-9S9.4 5.6 12 3Z"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="m11 12 8.5-8.5M16.5 6.5l2.5 2.5M14.5 8.5l2 2"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
}


def svg_icon(name: str, color: str = "#c9d1d9", size: int = 24) -> QIcon:
    return QIcon(svg_pixmap(name, color, size))


def svg_pixmap(name: str, color: str = "#c9d1d9", size: int = 24, scale: float = 2.0) -> QPixmap:
    data = _S.format(c=color, b=PATHS.get(name, PATHS["info"]))
    r = QSvgRenderer(QByteArray(data.encode()))
    px = QPixmap(QSize(int(size * scale), int(size * scale)))
    px.fill(Qt.transparent)
    p = QPainter(px)
    r.render(p)
    p.end()
    px.setDevicePixelRatio(scale)
    return px


APP_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient></defs>
<path d="M128 14 222 48v70c0 62-40 104-94 124C74 222 34 180 34 118V48Z" fill="url(#g)"/>
<path d="M76 98h20V76h17v22h30V76h17v22h20v22c0 36-24 63-52 76-28-13-52-40-52-76Z" fill="#ffffff" fill-opacity=".96"/>
<path d="M112 178v-28a16 16 0 0 1 32 0v28c-6 4-11 7-16 9-5-2-10-5-16-9Z" fill="{b}"/>
</svg>"""

STATUS_COLORS = {"safe": ("#2fd38a", "#118a58"), "warn": ("#ffc24b", "#d1810b"),
                 "risk": ("#ff6a6a", "#c3232c"), "idle": ("#9aa7b4", "#5b6773")}


def app_icon_svg(status="safe") -> str:
    a, b = STATUS_COLORS.get(status, STATUS_COLORS["safe"])
    return APP_ICON_SVG.format(a=a, b=b)


def app_icon(status="safe") -> QIcon:
    ic = QIcon()
    data = app_icon_svg(status).encode()
    for s in (16, 22, 24, 32, 48, 64, 128, 256):
        r = QSvgRenderer(QByteArray(data))
        px = QPixmap(s, s)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p)
        p.end()
        ic.addPixmap(px)
    return ic


def app_pixmap(status="safe", size=96) -> QPixmap:
    r = QSvgRenderer(QByteArray(app_icon_svg(status).encode()))
    px = QPixmap(size * 2, size * 2)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p)
    p.end()
    px.setDevicePixelRatio(2)
    return px

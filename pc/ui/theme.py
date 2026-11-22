"""Colors, fonts and the application style sheet."""
from gt.config import ASSETS

_ASSETS = ASSETS.as_posix()

BG = "#0E1116"
SIDEBAR = "#12161C"
CARD = "#181D25"
CARD_HI = "#1F2630"
BORDER = "#28303C"
TEXT = "#E8ECF1"
MUTED = "#8B97A7"
ACCENT = "#4C8DFF"
ACCENT_HI = "#6AA1FF"
GREEN = "#34D399"
YELLOW = "#FBBF24"
RED = "#F87171"

FONT = "Segoe UI Variable Text"
ICON_FONT = "Segoe Fluent Icons"


class Icon:
    HOME = ""
    VIDEO = ""
    CROP = ""
    FILTER = ""
    GLOBE = ""
    TV = ""
    PALETTE = ""
    SETTINGS = ""
    PLAY = ""
    STOP = ""
    REFRESH = ""
    SYNC = ""
    ADD = ""
    DELETE = ""
    OPEN = ""
    INFO = ""
    WARNING = ""
    CHECK = ""
    GAME = ""
    LIBRARY = ""
    LINK = ""
    HELP = ""
    USB = ""
    LOCK = ""


QSS = f"""
* {{ color: {TEXT}; }}
QMainWindow, #content {{ background: {BG}; }}
QToolTip {{ background: {CARD_HI}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; }}

#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
#appTitle {{ font-size: 15pt; font-weight: 600; }}
#appSubtitle {{ color: {MUTED}; font-size: 9pt; }}
#navSection {{ color: #5B6573; font-size: 8pt; font-weight: 600; letter-spacing: 1px; padding: 0 14px; }}
#navButton {{
    text-align: left; padding: 10px 14px; border: none; border-radius: 8px;
    background: transparent; color: {MUTED}; font-size: 10.5pt;
}}
#navButton:hover {{ background: {CARD}; color: {TEXT}; }}
#navButton:checked {{ background: {CARD_HI}; color: {TEXT}; }}

#header {{ background: {BG}; }}
#pageTitle {{ font-size: 18pt; font-weight: 600; }}
#pageHint {{ color: {MUTED}; }}

#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
#cardTitle {{ font-size: 11.5pt; font-weight: 600; }}
#cardHint, #muted {{ color: {MUTED}; }}
#rowTitle {{ font-weight: 600; }}
#stepIcon {{ font-size: 13pt; }}
#stepTitle {{ font-weight: 600; }}
#guideStep {{ text-align: left; padding: 9px 12px; border: none; border-radius: 8px; background: transparent; color: {MUTED}; }}
#guideStep:checked {{ background: {CARD_HI}; color: {TEXT}; }}
#guideStep:hover {{ background: {CARD}; color: {TEXT}; }}
#segButton {{ padding: 7px 14px; border: 1px solid {BORDER}; border-radius: 8px; background: {CARD_HI}; color: {MUTED}; }}
#segButton:hover {{ color: {TEXT}; }}
#segButton:checked {{ background: #1C2A44; border: 1px solid {ACCENT}; color: {TEXT}; }}
#guideTitle {{ font-size: 15pt; font-weight: 600; }}

#banner {{ background: #2A2112; border: 1px solid #5C4517; border-radius: 10px; }}
#banner QLabel {{ color: {YELLOW}; }}
#bannerError {{ background: #2A1517; border: 1px solid #5C2329; border-radius: 10px; }}
#bannerError QLabel {{ color: {RED}; }}

#pill {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 13px; padding: 4px 12px; }}

#statValue {{ font-size: 20pt; font-weight: 600; }}
#statLabel {{ color: {MUTED}; font-size: 9pt; }}

#nowSpeaker {{ color: {ACCENT_HI}; font-size: 12pt; font-weight: 600; }}
#nowTurkish {{ font-size: 20pt; font-weight: 600; }}
#nowEnglish {{ color: {MUTED}; font-size: 11pt; }}

QPushButton {{
    background: {CARD_HI}; border: 1px solid {BORDER}; border-radius: 8px; padding: 8px 14px;
}}
QPushButton:hover {{ background: #283141; }}
QPushButton:pressed {{ background: #1B222C; }}
QPushButton:disabled {{ color: #5B6573; }}
QPushButton#primary {{ background: {ACCENT}; border: none; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_HI}; }}
QPushButton#danger {{ background: #3A1D22; border: 1px solid #6B2A33; color: {RED}; font-weight: 600; }}
QPushButton#danger:hover {{ background: #4A2229; }}
QPushButton#startButton {{
    background: {ACCENT}; border: none; color: white; font-size: 11pt; font-weight: 600;
    padding: 10px 22px; border-radius: 10px;
}}
QPushButton#startButton:hover {{ background: {ACCENT_HI}; }}
QPushButton#startButton[running="true"] {{ background: #3A1D22; border: 1px solid #6B2A33; color: {RED}; }}

#optionCard {{ background: {CARD_HI}; border: 1px solid {BORDER}; border-radius: 10px; }}
#optionCard[selected="true"] {{ border: 2px solid {ACCENT}; background: #1C2A44; }}
#optionTitle {{ font-weight: 600; font-size: 11pt; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{
    background: {BG}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QComboBox {{ padding-right: 28px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({_ASSETS}/chevron-down.svg); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {CARD_HI}; border: 1px solid {BORDER}; selection-background-color: {ACCENT}; }}
QSpinBox {{ padding-right: 24px; min-width: 70px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 22px; border: none; background: transparent; }}
QSpinBox::up-arrow {{ image: url({_ASSETS}/chevron-up.svg); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url({_ASSETS}/chevron-down.svg); width: 10px; height: 10px; }}

QSlider::groove:horizontal {{ height: 6px; background: {BORDER}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: white; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px;
}}

QListWidget, QTableWidget {{
    background: {BG}; border: 1px solid {BORDER}; border-radius: 8px; gridline-color: {BORDER};
    alternate-background-color: #12161C;
}}
QListWidget::item {{ padding: 6px 8px; }}
QListWidget::item:selected, QTableWidget::item:selected {{ background: #1C2A44; color: {TEXT}; }}
QHeaderView::section {{
    background: {CARD_HI}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER}; padding: 6px 8px;
}}
QTableCornerButton::section {{ background: {CARD_HI}; border: none; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3A4452; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 4px; min-width: 30px; }}

QMenu {{ background: {CARD_HI}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT}; }}

/* Question / warning boxes and other dialogs: with Windows in light mode they kept a white background under the
   light text of this style (white on white, unreadable). */
QDialog, QMessageBox, QColorDialog, QInputDialog {{ background: {CARD}; }}
QMessageBox QLabel, QDialog QLabel {{ color: {TEXT}; background: transparent; }}
"""

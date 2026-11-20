"""Oyun Çeviri — desktop app entry point."""
import ctypes
import os
import sys
import tempfile

from PySide6.QtCore import QCoreApplication, QLockFile, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gt import config  # noqa: E402
from ui import theme  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


def _crash_log():
    """pythonw has no console: write crashes to logs/crash.log so they can be diagnosed."""
    import faulthandler
    import traceback
    log_dir = config.ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    stream = open(log_dir / "crash.log", "a", encoding="utf-8")
    faulthandler.enable(stream)

    def hook(kind, value, tb):
        stream.write(f"\n--- {__import__('time').strftime('%Y-%m-%d %H:%M:%S')}\n")
        traceback.print_exception(kind, value, tb, file=stream)
        stream.flush()

    sys.excepthook = hook
    __import__("threading").excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)


def main():
    _crash_log()
    if "--selftest" in sys.argv:            # check every part, write logs/selftest.txt, no window
        from gt import selftest
        return selftest.run()
    # Own taskbar icon instead of Python's.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GameTranslate.OyunCeviri")
    # The PSN sign-in window (Qt WebEngine) needs this before the application object exists.
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("Oyun Çeviri")
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont(theme.FONT, 10))
    try:
        # The app is dark: native parts (dialogs, menus, scroll bars) must not follow a light Windows theme.
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    except AttributeError:      # Qt older than 6.8
        pass
    app.setStyleSheet(theme.QSS)
    from ui.widgets import WheelGuard
    wheel_guard = WheelGuard(app)
    app.installEventFilter(wheel_guard)
    icon = QIcon(str(config.ASSETS / "icon.ico"))
    app.setWindowIcon(icon)

    lock = QLockFile(os.path.join(tempfile.gettempdir(), "oyun-ceviri.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "Oyun Çeviri", "Oyun Çeviri zaten açık (saatin yanındaki simgeye bak).")
        return 0

    win = MainWindow(icon)
    win.show()
    if "--start" in sys.argv:
        win.toggle_engine()
    return app.exec()


if __name__ == "__main__":
    # Installed app: the Remote Play child process starts this same exe; let it run its part only.
    __import__("multiprocessing").freeze_support()
    sys.exit(main())

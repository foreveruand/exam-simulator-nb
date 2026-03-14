from aqt import mw
from aqt.qt import QAction


def _open_exam_simulator():
    from .launcher import LauncherDialog
    dlg = LauncherDialog(mw)
    dlg.exec()


action = QAction("Exam Simulator - NB", mw)
action.triggered.connect(_open_exam_simulator)
mw.form.menuTools.addAction(action)

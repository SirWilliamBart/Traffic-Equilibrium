# run.py
# Entry point. Launches the GUI application.

import sys
from PySide6.QtWidgets import QApplication
from gui.main_window_logic import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

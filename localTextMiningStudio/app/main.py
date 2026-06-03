"""Application entry point.

Run with:
    python -m app.main
"""

from __future__ import annotations

import sys


def main() -> int:
    """Start the desktop application."""
    from PySide6.QtWidgets import QApplication

    from app.utils.logging import setup_logging
    from app.ui.main_window import MainWindow

    logger = setup_logging()
    logger.info("Application starting")

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

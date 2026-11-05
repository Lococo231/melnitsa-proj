"""Главная точка входа в приложение PySide6 (PyCharm: Run main.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'project'))
from qt_app import main

if __name__ == '__main__':
    sys.exit(main())

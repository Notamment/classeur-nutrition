"""Point d'entrée installé, sans déplacement des scripts et skills historiques."""
from pathlib import Path
import sys


def main():
    installed = Path(__file__).resolve().parent / "engine/scripts"
    source = Path(__file__).resolve().parent.parent / "skills/meal-binder/scripts"
    scripts = installed if installed.is_dir() else source
    sys.path.insert(0, str(scripts))
    from core import utf8_stdio
    from binder import main as binder_main
    utf8_stdio()
    return binder_main()

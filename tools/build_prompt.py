#!/usr/bin/env python3
"""Assemble dist/prompt.md (version monolithique pour les chats sans exécution de code).

Une seule source de vérité : les règles vivent dans skills/meal-binder/references/.
Ce script les concatène ; ne jamais éditer dist/prompt.md à la main.
"""
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills/meal-binder/scripts"))
from core import DEFAULT_PROFILE
from profiles import NEUTRAL_PROFILE, list_presets
from catalogs import load_catalogs
from schemas import SELECTION_CRITERIA
REFS = ROOT / "skills" / "meal-binder" / "references"
PARTS = [
    ROOT / "tools" / "prompt_header.md",
    REFS / "rules.md",
    REFS / "authenticity.md",
    ROOT / "tools" / "prompt_output_format.md",
]

# Passages propres au mode « skills + scripts », retirés ou reformulés dans la version monolithique.
SCRIPT_ONLY = (
    "Le script classe tout seul",
    "Le script signale",
    "check-plan",
)
REPLACE = {
    "valeur lue dans `profile.yaml`, contrôlée par `binder.py`": "valeur lue dans `profile.yaml`, à contrôler par le modèle",
    "non vérifiable par script ; appliquée": "appliquée",
    "`config`, contrôle script": "`config`",
    "`modèle` + script": "`modèle`",
    " : note ajoutée automatiquement si `nutrition.note_tanins` est vrai": " : le noter si `nutrition.note_tanins` est vrai",
    "`authenticite` :": "Authenticité :",
    "`references.culinaire` :": "Référence culinaire :",
}


def demote(md: str) -> str:
    """Décale les titres d'un niveau pour imbriquer chaque partie sous le titre principal."""
    out = []
    for line in md.splitlines():
        if line.startswith("#"):
            line = "#" + line
        out.append(line)
    return "\n".join(out)


def strip_script_lines(md: str) -> str:
    for old, new in REPLACE.items():
        md = md.replace(old, new)
    return "\n".join(l for l in md.splitlines() if not any(s in l for s in SCRIPT_ONLY))


def main() -> None:
    chunks = []
    for i, path in enumerate(PARTS):
        text = path.read_text(encoding="utf-8").strip()
        if i:
            text = demote(strip_script_lines(text))
        chunks.append(text)
        if i == 0:
            config = {"defauts_v1": DEFAULT_PROFILE, "defauts_v2": NEUTRAL_PROFILE,
                      "prereglages_disponibles": list_presets(),
                      "options_adaptation": load_catalogs().as_dict() | {"criteres_selection": list(SELECTION_CRITERIA)}}
            chunks.append("## Configuration embarquée\n\nValeurs de référence, à surcharger par mon profil.\n\n```yaml\n"
                          + yaml.safe_dump(config, allow_unicode=True, sort_keys=False) + "```")
    out = ROOT / "dist" / "prompt.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n\n".join(chunks) + "\n", encoding="utf-8")
    words = sum(len(c.split()) for c in chunks)
    print(f"Écrit : {out} (~{words} mots)")


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # Windows : sortie redirigée en UTF-8, pas en cp1252
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    main()

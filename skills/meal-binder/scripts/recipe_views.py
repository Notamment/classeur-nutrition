"""Common calculated recipe views for review and delivery."""
from dataclasses import dataclass, field
import re

TOKEN = re.compile(r"\{\{([^{}]*)\}\}")
REFERENCE = re.compile(r"qte:([a-z][a-z0-9_-]*)")


def resolve_steps(recipe, *, version=2):
    """Substitute quantities only; no execution or rewriting of free text."""
    from core import DataError, Issue, fmt_qty
    def fail(message):
        raise DataError([Issue("erreur", "etapes_reference", recipe.get("id", "?"), message)])
    lines = recipe.get("ingredients", [])
    identifiers = [line["id_ligne"] for line in lines if "id_ligne" in line]
    if len(set(identifiers)) != len(identifiers):
        fail("id_ligne dupliqué dans les ingrédients")
    def substitute(match):
        if version != 2:
            fail("les références de quantités nécessitent un profil version 2")
        reference = REFERENCE.fullmatch(match.group(1))
        if reference is None:
            fail("référence attendue : {{qte:identifiant}}")
        key = reference.group(1)
        matches = [line for line in lines if key in {line["food"], line.get("id_ligne")}]
        if len(matches) != 1:
            fail(f"référence {key} absente ou ambiguë ; utiliser un id_ligne unique")
        return fmt_qty(matches[0]["qte"], matches[0]["unite"])
    out = []
    for step in recipe.get("etapes", []):
        leftover = TOKEN.sub("", step)
        if "{{" in leftover or "}}" in leftover:
            fail("délimiteurs de référence incomplets ou imbriqués")
        out.append(TOKEN.sub(substitute, step))
    return out


def step_issues(recipe, version):
    from core import DataError
    try:
        resolve_steps(recipe, version=version)
    except DataError as exc:
        return exc.issues
    return []


def check_scalable_steps(recipe, ratio):
    """Do not silently retain explicit doses when scaling free-text instructions."""
    from core import DataError, Issue
    resolve_steps(recipe)
    dose = re.compile(r"[\d¼½¾]\s*(?:[.,/]\s*\d+)?\s*(?:kilogrammes?|milligrammes?|grammes?|millilitres?|centilitres?|d[eé]cilitres?|litres?|kg|mg|g|ml|cl|dl|l|pi[eè]ces?|[oœ]e?ufs?|cuill[eè]res?|c\.?\s*[àa]\s*(?:caf[eé]|soupe))\b", re.I)
    if ratio != 1 and any(dose.search(TOKEN.sub("", step)) for step in recipe.get("etapes", []) if isinstance(step, str)):
        raise DataError([Issue("erreur", "etapes_quantifiees", recipe.get("id", "?"),
                               "changement d'échelle refusé : quantités explicites dans les étapes ; fournir une recette aux portions cibles avec étapes et ingrédients cohérents")])


@dataclass
class RecipeView:
    identifier: str
    recipe: dict
    calc: object
    alternatives: list = field(default_factory=list)
    origin: str = ""
    preparation: str = ""
    service: str = ""


def recipe_views(ctx, *, include_sources=False):
    sources = [RecipeView(rid, recipe, ctx.calcs[rid], ctx.alts.get(rid, []))
               for rid, recipe in sorted(ctx.recipes.items()) if rid in ctx.calcs]
    if ctx.schedule is None:
        return sources
    return (sources if include_sources else []) + list(ctx.served_recipes)


def used_foods(ctx, *, include_sources=False):
    return {line.food.id for view in recipe_views(ctx, include_sources=include_sources) for line in view.calc.lines}

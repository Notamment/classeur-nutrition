"""Common calculated recipe views for review and delivery."""
from dataclasses import dataclass, field
import re


def check_scalable_steps(recipe, ratio):
    """Do not silently retain explicit doses when scaling free-text instructions."""
    from core import DataError, Issue
    dose = re.compile(r"[\d¼½¾]\s*(?:[.,/]\s*\d+)?\s*(?:kilogrammes?|milligrammes?|grammes?|millilitres?|centilitres?|d[eé]cilitres?|litres?|kg|mg|g|ml|cl|dl|l|pi[eè]ces?|[oœ]e?ufs?|cuill[eè]res?|c\.?\s*[àa]\s*(?:caf[eé]|soupe))\b", re.I)
    if ratio != 1 and any(dose.search(step) for step in recipe.get("etapes", []) if isinstance(step, str)):
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

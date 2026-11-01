"""Common calculated recipe views for review and delivery."""
from dataclasses import dataclass, field


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

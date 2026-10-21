"""Exports locaux séparant recettes client et informations de production."""
from __future__ import annotations

import argparse
import csv
import html
import io
from pathlib import Path

from checks import analyse
from core import BinderError
from manifest import encode, make_manifest
from storage import atomic_batch, safe_destination
from workflow import locked, review_status

MARKER = "meal-binder:export:v1"


def cell(value):
    """Texte CSV : empêcher son interprétation comme formule de tableur."""
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def table_csv(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerows([[cell(v) for v in row] for row in rows])
    return stream.getvalue().encode("utf-8-sig")


def export(directory, *, audience="client", formats=("html",), draft=False):
    if audience not in ("client", "production") or not formats or set(formats) - {"html", "csv", "pdf"}:
        raise BinderError("public ou formats d'export invalides")
    directory = safe_destination(directory)
    with locked(directory):
        ctx = analyse(directory, complete=True)
        status = review_status(directory)
        if not draft and (not status["revue_actuelle"] or status.get("decision") != "revu"):
            raise BinderError("livraison refusée : rendu et revue humaine actuels requis ; --draft pour un brouillon explicite")
        manifest = make_manifest(ctx)
        e = lambda value: html.escape(str(value), quote=True)
        title = "Recettes" if audience == "client" else "Dossier de production"
        state = "BROUILLON — NON VALIDÉ" if draft else "Version relue — limites et données manquantes conservées"
        body = [f"<h1>{title}</h1><p class='etat'>{e(state)}</p>",
                "<p>Les valeurs et durées sont des estimations. La revue humaine ne certifie ni les données ni les allergènes.</p>"]
        rows = [["recette", "plat", "aliment", "quantite", "unite", "etat"]]
        for rid, r in sorted(ctx.recipes.items()):
            c = ctx.calcs[rid]
            body.append(f"<section><h2>{e(rid)} — {e(r['nom'])}</h2><p>{c.portions} portions ; durée déclarée : {e(r['temps_total_min'])} min.</p><ul>")
            for line in c.lines:
                body.append(f"<li>{e(line.qty)} {e(line.unit)} {e(line.food.nom)} ({e(line.etat)})</li>")
                rows.append([rid, r["nom"], line.food.nom, line.qty, line.unit, line.etat])
            body.append("</ul><ol>")
            body.extend(f"<li>{e(step)}</li>" for step in r["etapes"])
            body.append("</ol>")
            for key in ("gamelle", "conservation", "adaptation"):
                if r.get(key):
                    body.append(f"<p>{e(key)} : {e(r[key])}</p>")
            if ctx.profile["nutrition"]["mode"] != "desactive":
                show = lambda n: "inconnues" if n is None else f"{n:.1f}"
                body.append(f"<p>Par portion : protéines {show(c.prot_pp)} g ; énergie {show(c.kcal_pp)} kcal. Valeurs estimées ; consulter les sources.</p>")
            body.append("</section>")
        # Les sources attachées aux aliments utilisés sont publiques ; aucun profil,
        # identifiant professionnel, commentaire de revue, tarif ou stock côté client.
        from sources import load_sources
        registry = load_sources(directory)
        used = {line.food.id for calc in ctx.calcs.values() for line in calc.lines}
        sources = sorted({(v["source"], v["edition"], v["licence"]) for fid, v in registry.items() if fid in used})
        body.append("<h2>Sources et limites</h2>")
        body.extend(f"<p>{e(source)} — édition {e(edition)} — {e(licence)}</p>" for source, edition, licence in sources)
        unknown = sum(i.kind == "unknown" for i in ctx.issues)
        body.append(f"<p>{unknown} information(s) non vérifiée(s). Les données provisoires restent des estimations.</p><ul>")
        for issue in ctx.issues:
            body.append(f"<li>{e(issue.where)} : {e(issue.code)} — {e(issue.level)} / {e(issue.kind)} / {e(issue.requirement)}</li>")
            rows.append(["controle", issue.where, issue.code, issue.level, issue.kind, issue.requirement])
        body.append("</ul>")
        for source, edition, licence in sources:
            rows.append(["source", source, edition, licence, "", ""])
        if audience == "production":
            body.append("<h2>Courses et budget</h2><table><tr><th>Semaine</th><th>Aliment</th><th>Besoin</th><th>Stock mobilisé</th><th>Achat emballé</th><th>Unité d'achat</th></tr>")
            rows.append(["semaine", "aliment", "besoin", "stock_mobilise", "achat", "unite_achat"])
            for shop in ctx.shops:
                for line in shop.lines:
                    data = [shop.semaine, line.food.nom, line.besoin, line.mobilise, line.achat, line.food.unite_achat]
                    rows.append(data)
                    body.append("<tr>" + "".join(f"<td>{e(v)}</td>" for v in data) + "</tr>")
                body.append(f"<tr><td colspan='6'>Caisse : {shop.montant_caisse:.2f} EUR ; budget {'estimé complet' if shop.budget_verifiable else 'NON VÉRIFIÉ — sous-total connu uniquement'}.</td></tr>")
            body.append("</table><h2>Contrôles</h2><ul>")
            body.extend(f"<li>{e(i.level)} / {e(i.kind)} / {e(i.requirement)} : {e(i.where)} — {e(i.code)} : {e(i.msg)}</li>" for i in ctx.issues)
            body.append("</ul>")
        if ctx.schedule:
            body.append("<h2>Calendrier des services</h2><p>Les fiches donnent les quantités pour leurs portions sources. Le calendrier indique les portions de chaque service ; consulter la production pour les achats recalculés.</p><ul>")
            for job in ctx.schedule["services"]:
                body.append(f"<li>{e(job['service'])} — {e(job['plat'])} : {job['portions']} portions.</li>")
                if audience == "production":
                    body.append(f"<li>Préparation : {e(job['preparation'])}. Achats : {e(encode(job['achats']))}. Lots mobilisés : {e(encode(job['lots_mobilises']))}.</li>")
            body.append("</ul>")
        document = (f"<!doctype html><!-- {MARKER} --><html lang='fr'><meta charset='utf-8'><title>{title}</title>"
                    "<style>body{font:16px sans-serif;max-width:70rem;margin:2rem auto;padding:1rem}"
                    "td,th{border:1px solid #aaa;padding:.4rem}table{border-collapse:collapse}.etat{font-weight:bold}"
                    "@media print{section{break-inside:avoid}body{font-size:11pt;margin:0}}</style><body>"
                    + "\n".join(body) + "</body></html>")
        target = safe_destination(directory / "out/exports" / audience)
        marker = target / "GENERATED"
        if target.exists() and (not marker.is_file() or marker.read_text(encoding="utf-8").strip() != MARKER):
            raise BinderError("sortie d'export existante non reconnue : protégée")
        contents = {target / "GENERATED": (MARKER + "\n").encode("utf-8")}
        if "html" in formats:
            contents[target / "classeur.html"] = document.encode("utf-8")
        if "csv" in formats:
            contents[target / "ingredients.csv"] = table_csv(rows)
        if "pdf" in formats:
            try:
                from weasyprint import HTML
            except ImportError as exc:
                raise BinderError("PDF nécessite l'option d'installation [exports] et les bibliothèques système WeasyPrint ; le HTML est imprimable en PDF") from exc
            def no_fetch(url, *args, **kwargs):
                raise ValueError("aucune ressource externe autorisée dans l'export")
            contents[target / "classeur.pdf"] = HTML(string=document, url_fetcher=no_fetch).write_pdf()
        from manifest import digest
        # Manifeste livrable minimal : pas de profil résolu, notes privées ou noms de fichiers d'entrées.
        contents[target / "manifest.json"] = encode({"version": 1, "moteur": manifest["moteur"],
            "date_generation": manifest["date_generation"], "public": audience, "brouillon": draft,
            "analyse_sha256": manifest["analyse_sha256"],
            "fichiers": {p.name: digest(data) for p, data in contents.items() if p.name != "GENERATED"}}).encode("utf-8")
        # Un ancien PDF ou CSV pourrait sinon passer pour le nouvel export.
        existing = {p.name for p in target.iterdir()} if target.exists() else set()
        expected = {p.name for p in contents}
        if existing - expected:
            raise BinderError("formats précédents présents : conserver les mêmes formats ou archiver l'ancien export avant remplacement")
        atomic_batch(contents)
        return {"version": 1, "public": audience, "brouillon": draft,
                "fichiers": sorted(p.name for p in contents if p.name != "GENERATED")}


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["export"])
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--audience", choices=["client", "production"], default="client")
    parser.add_argument("--format", choices=["html", "csv", "pdf"], action="append", dest="formats")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = export(args.dir, audience=args.audience, formats=args.formats or ["html"], draft=args.draft)
        print(encode(result), end="")
        return 0
    except (BinderError, OSError, ValueError) as exc:
        print(encode({"version": 1, "erreur": str(exc)}), end="")
        return 2

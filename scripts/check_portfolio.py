#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "research-portfolio.json"
SCHEMA = ROOT / "research-portfolio.schema.json"
JSONLD = ROOT / "research-portfolio.jsonld"
USER_AGENT = "Mozilla/5.0 (compatible; SEGPortfolioCheck/1.1; +https://selguetagodoy.github.io/)"

REQUIRED_INTERFACES = {
    "research_overview",
    "open_data_catalog",
    "public_dataset_json",
    "methodology",
    "research_status",
    "research_jsonld",
}

REQUIRED_PROJECT_FIELDS = {
    "id",
    "title",
    "type",
    "scope",
    "description",
    "keywords",
    "landing",
    "repository",
    "concept_doi",
    "version_doi",
    "latest_git_release",
    "latest_citable_version",
    "latest_git_release_url",
    "latest_citable_release_url",
    "citation",
    "data_package",
    "citable_release_date",
}


def check(url: str) -> tuple[str, str]:
    req = Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
    try:
        with urlopen(req, timeout=20) as response:
            return "OK", str(response.status)
    except HTTPError as exc:
        if exc.code == 405 or exc.code >= 500:
            try:
                req = Request(url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-1023"}, method="GET")
                with urlopen(req, timeout=20) as response:
                    return "OK", str(response.status)
            except HTTPError as fallback:
                exc = fallback
            except URLError as fallback:
                return "DEAD", f"network: {fallback.reason}"
        if 400 <= exc.code < 500:
            return "WARN", f"HTTP {exc.code}"
        return "DEAD", f"HTTP {exc.code}"
    except URLError as exc:
        return "DEAD", f"network: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return "DEAD", str(exc)


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []
    checked = 0

    for path in (PORTFOLIO, SCHEMA, JSONLD):
        if not path.exists():
            failures.append(f"missing required file: {path.name}")

    if failures:
        for failure in failures:
            print("ERROR:", failure)
        return 2

    payload = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonld = json.loads(JSONLD.read_text(encoding="utf-8"))

    interfaces = payload.get("interfaces", {})
    missing_interfaces = REQUIRED_INTERFACES - set(interfaces)
    if missing_interfaces:
        failures.append(f"portfolio interfaces missing: {sorted(missing_interfaces)}")
    for key in sorted(REQUIRED_INTERFACES & set(interfaces)):
        label, detail = check(interfaces[key])
        checked += 1
        print(f"{label} interface {key} — {detail} — {interfaces[key]}")
        if label == "DEAD":
            failures.append(f"interface {key}: {detail}")
        elif label == "WARN":
            warnings.append(f"interface {key}: {detail}")

    projects = payload.get("projects", [])
    if len(projects) != 6:
        failures.append(f"expected 6 portfolio projects, found {len(projects)}")

    expected_schema = "https://selguetagodoy.github.io/research-portfolio.schema.json"
    if payload.get("$schema") != expected_schema:
        failures.append("portfolio $schema does not point to the canonical schema")

    schema_required = set(
        schema.get("properties", {})
        .get("projects", {})
        .get("items", {})
        .get("required", [])
    )
    missing_schema_fields = REQUIRED_PROJECT_FIELDS - schema_required
    if missing_schema_fields:
        failures.append(f"schema does not require fields: {sorted(missing_schema_fields)}")

    ids: set[str] = set()
    landings: set[str] = set()
    titles: set[str] = set()

    for project in projects:
        pid = project.get("id", "unknown")
        missing = REQUIRED_PROJECT_FIELDS - set(project)
        if missing:
            failures.append(f"{pid}: missing {sorted(missing)}")
            continue

        if pid in ids:
            failures.append(f"duplicate project id: {pid}")
        ids.add(pid)

        if project["landing"] in landings:
            failures.append(f"duplicate landing URL: {project['landing']}")
        landings.add(project["landing"])

        if project["title"] in titles:
            failures.append(f"duplicate project title: {project['title']}")
        titles.add(project["title"])

        if project["type"] != "dataset":
            failures.append(f"{pid}: unsupported project type {project['type']!r}")
        if len(project["description"].strip()) < 20:
            failures.append(f"{pid}: description too short")
        if len(project["keywords"]) < 4:
            failures.append(f"{pid}: at least four keywords required")

        citation = project.get("citation", {})
        for field in ("cff", "bibtex", "codemeta"):
            if field not in citation:
                failures.append(f"{pid}: citation.{field} missing")

        urls = {
            "landing": project["landing"],
            "repository": project["repository"],
            "concept_doi": project["concept_doi"],
            "version_doi": project["version_doi"],
            "latest_git_release_url": project["latest_git_release_url"],
            "latest_citable_release_url": project["latest_citable_release_url"],
            "citation.cff": citation.get("cff", ""),
            "citation.bibtex": citation.get("bibtex", ""),
            "citation.codemeta": citation.get("codemeta", ""),
            "data_package": project["data_package"],
        }

        for field, url in urls.items():
            if not url:
                continue
            label, detail = check(url)
            checked += 1
            print(f"{label} {pid} {field} — {detail} — {url}")
            if label == "DEAD":
                failures.append(f"{pid} {field}: {detail}")
            elif label == "WARN":
                warnings.append(f"{pid} {field}: {detail}")

    graph = jsonld.get("@graph", [])
    catalog_nodes = [node for node in graph if node.get("@type") == "DataCatalog"]
    if len(catalog_nodes) != 1:
        failures.append(f"JSON-LD DataCatalog count {len(catalog_nodes)} != 1")
    else:
        catalog = catalog_nodes[0]
        if catalog.get("url") != interfaces.get("open_data_catalog"):
            failures.append("JSON-LD DataCatalog URL mismatch")
        catalog_ids = {
            item.get("@id")
            for item in catalog.get("dataset", [])
            if isinstance(item, dict)
        }
        expected_catalog_ids = {
            (
                f"{project['landing']}#atlas"
                if project["id"] == "atlas-desconexion-digital-chile"
                else f"{project['landing']}#dataset"
            )
            for project in projects
        }
        if catalog_ids != expected_catalog_ids:
            failures.append("JSON-LD DataCatalog dataset membership mismatch")

    dataset_nodes = [node for node in graph if node.get("@type") == "Dataset"]
    if len(dataset_nodes) != len(projects):
        failures.append(
            f"JSON-LD dataset count {len(dataset_nodes)} != portfolio project count {len(projects)}"
        )

    by_name = {node.get("name"): node for node in dataset_nodes}
    for project in projects:
        node = by_name.get(project["title"])
        if not node:
            failures.append(f"{project['id']}: missing from research-portfolio.jsonld")
            continue
        if node.get("url") != project["landing"]:
            failures.append(f"{project['id']}: JSON-LD landing mismatch")
        if node.get("version") != project["latest_citable_version"]:
            failures.append(f"{project['id']}: JSON-LD citable version mismatch")
        if node.get("datePublished") != project["citable_release_date"]:
            failures.append(f"{project['id']}: JSON-LD citable release date mismatch")
        identifiers = set(node.get("identifier", []))
        expected_identifiers = {project["concept_doi"], project["version_doi"]}
        if not expected_identifiers.issubset(identifiers):
            failures.append(f"{project['id']}: JSON-LD DOI identifiers incomplete")

    print(
        f"\nPortfolio check: {len(projects)} projects · {checked} URLs · "
        f"{len(warnings)} WARN · {len(failures)} failures"
    )
    for warning in warnings:
        print("WARN:", warning)
    if failures:
        for failure in failures:
            print("ERROR:", failure)
        return 1
    print("OK: JSON, schema, JSON-LD and public identifiers are aligned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

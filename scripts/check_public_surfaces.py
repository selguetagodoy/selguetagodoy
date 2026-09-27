#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "research-portfolio.json"
UA = "Mozilla/5.0 (compatible; SEGSurfaceCheck/1.0; +https://selguetagodoy.github.io/)"

SURFACES = {
    "llms.txt": "https://selguetagodoy.github.io/llms.txt",
    "research.md": "https://selguetagodoy.github.io/research.md",
    "profile.md": "https://selguetagodoy.github.io/profile.md",
    "publications.md": "https://selguetagodoy.github.io/publications.md",
    "datos-abiertos.html": "https://selguetagodoy.github.io/datos-abiertos.html",
    "datasets.json": "https://selguetagodoy.github.io/datasets.json",
    "research.jsonld": "https://selguetagodoy.github.io/research.jsonld",
    "investigacion.html": "https://selguetagodoy.github.io/investigacion.html",
    "publicaciones.html": "https://selguetagodoy.github.io/publicaciones.html",
}


def get(url: str, attempts: int = 4) -> str:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = Request(url, headers={"User-Agent": UA})
        try:
            with urlopen(req, timeout=25) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            last_error = exc
            retryable = exc.code in {404, 500, 502, 503, 504}
            if not retryable or attempt == attempts:
                raise
        except URLError as exc:
            last_error = exc
            if attempt == attempts:
                raise
        time.sleep(attempt * 3)
    assert last_error is not None
    raise last_error


def main() -> int:
    portfolio = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    failures: list[str] = []
    downloaded: dict[str, str] = {}

    for name, url in SURFACES.items():
        try:
            downloaded[name] = get(url)
            print(f"OK surface {name} — {url}")
        except (HTTPError, URLError) as exc:
            failures.append(f"{name}: cannot fetch {url}: {exc}")

    if failures:
        for failure in failures:
            print("ERROR:", failure)
        return 1

    interfaces = portfolio.get("interfaces", {})
    required_interface_surfaces = {
        "research_overview": ("llms.txt", "profile.md"),
        "open_data_catalog": ("llms.txt", "profile.md", "research.md"),
        "public_dataset_json": ("llms.txt", "profile.md", "research.md"),
        "research_jsonld": ("llms.txt", "profile.md", "research.md"),
        "methodology": ("llms.txt", "profile.md", "research.md"),
        "research_status": ("llms.txt", "profile.md", "research.md"),
    }
    for key, surfaces in required_interface_surfaces.items():
        url = interfaces.get(key)
        if not url:
            failures.append(f"portfolio interface missing: {key}")
            continue
        for surface_name in surfaces:
            if url not in downloaded[surface_name]:
                failures.append(
                    f"interface {key} missing from {surface_name}: {url}"
                )

    for project in portfolio["projects"]:
        pid = project["id"]
        landing = project["landing"]
        version_doi = project["version_doi"]
        title = project["title"]

        for surface in ("llms.txt", "research.md", "profile.md", "publications.md", "datos-abiertos.html", "datasets.json", "investigacion.html"):
            text = downloaded[surface]
            if landing not in text and landing.removeprefix("https://selguetagodoy.github.io/") not in text:
                failures.append(f"{pid}: canonical landing missing from {surface}")

        if version_doi not in downloaded["research.md"]:
            failures.append(f"{pid}: version DOI missing from research.md")
        if version_doi not in downloaded["profile.md"]:
            failures.append(f"{pid}: version DOI missing from profile.md")
        if version_doi not in downloaded["publications.md"]:
            failures.append(f"{pid}: version DOI missing from publications.md")
        if version_doi not in downloaded["datasets.json"]:
            failures.append(f"{pid}: version DOI missing from datasets.json")
        if version_doi not in downloaded["research.jsonld"]:
            failures.append(f"{pid}: version DOI missing from research.jsonld")
        if title not in downloaded["llms.txt"]:
            failures.append(f"{pid}: project title missing from llms.txt")
        if title not in downloaded["research.jsonld"]:
            failures.append(f"{pid}: project title missing from research.jsonld")

    # Publications HTML intentionally treats datasets as research outputs,
    # not as journalistic articles; all six should still be discoverable there.
    for project in portfolio["projects"]:
        path = project["landing"].removeprefix("https://selguetagodoy.github.io/")
        if path not in downloaded["publicaciones.html"]:
            failures.append(f"{project['id']}: dataset landing missing from publicaciones.html")

    print(
        f"Public surface consistency: {len(SURFACES)} surfaces · "
        f"{len(portfolio['projects'])} projects · {len(failures)} failures"
    )
    if failures:
        for failure in failures:
            print("ERROR:", failure)
        return 1
    print("OK: canonical research products are aligned across public surfaces.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

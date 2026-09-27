#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "research-portfolio.json"
USER_AGENT = "Mozilla/5.0 (compatible; SEGPortfolioCheck/1.0; +https://selguetagodoy.github.io/)"

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
    except Exception as exc:
        return "DEAD", str(exc)

def main() -> int:
    payload = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    projects = payload.get("projects", [])
    if len(projects) != 6:
        print(f"ERROR: expected 6 portfolio projects, found {len(projects)}")
        return 2

    required = {"id","title","landing","repository","concept_doi","version_doi"}
    failures = []
    warnings = []
    checked = 0

    for project in projects:
        missing = required - set(project)
        if missing:
            failures.append(f"{project.get('id','unknown')}: missing {sorted(missing)}")
            continue
        for field in ("landing","repository","concept_doi","version_doi"):
            url = project[field]
            label, detail = check(url)
            checked += 1
            print(f"{label} {project['id']} {field} — {detail} — {url}")
            if label == "DEAD":
                failures.append(f"{project['id']} {field}: {detail}")
            elif label == "WARN":
                warnings.append(f"{project['id']} {field}: {detail}")

    print(f"\nPortfolio check: {len(projects)} projects · {checked} URLs · {len(warnings)} WARN · {len(failures)} DEAD/schema errors")
    if failures:
        for failure in failures:
            print("ERROR:", failure)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())

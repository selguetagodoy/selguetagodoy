#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "research-portfolio.json"
UA = "Mozilla/5.0 (compatible; SEGMetadataCheck/1.0; +https://selguetagodoy.github.io/)"

def get(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=25) as response:
        return response.read().decode("utf-8")

def github_raw(repository: str, path: str) -> str:
    owner_repo = repository.removeprefix("https://github.com/").rstrip("/")
    return f"https://raw.githubusercontent.com/{owner_repo}/main/{path}"

def main() -> int:
    payload = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    failures: list[str] = []
    checks = 0

    required_artifacts = (
        "SOURCE_OF_TRUTH.md",
        "CITATION.cff",
        "CITATION.bib",
        "codemeta.json",
        "NOTICE.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        ".github/ISSUE_TEMPLATE/evidence-correction.yml",
        ".github/pull_request_template.md",
    )

    for project in payload["projects"]:
        pid = project["id"]
        repo = project["repository"]
        landing = project["landing"]
        version_doi = project["version_doi"]
        expected_latest = project.get("latest_git_release")

        if expected_latest:
            owner_repo = repo.removeprefix("https://github.com/").rstrip("/")
            api_url = f"https://api.github.com/repos/{owner_repo}/releases/latest"
            try:
                latest_release = json.loads(get(api_url))
                checks += 1
                actual_latest = latest_release.get("tag_name")
                if actual_latest != expected_latest:
                    failures.append(
                        f"{pid}: latest GitHub release {actual_latest!r} != portfolio {expected_latest!r}"
                    )
            except (HTTPError, URLError, json.JSONDecodeError) as exc:
                failures.append(f"{pid}: cannot verify latest GitHub release: {exc}")

        for filename in required_artifacts:
            url = github_raw(repo, filename)
            try:
                content = get(url)
                checks += 1
            except (HTTPError, URLError, UnicodeDecodeError) as exc:
                failures.append(f"{pid}: cannot read {filename}: {exc}")
                continue

            if filename in {"SOURCE_OF_TRUTH.md", "NOTICE.md", "CHANGELOG.md"}:
                continue

            if filename == "CITATION.cff":
                url_match = re.search(r'^url:\s*"([^"]+)"', content, re.M)
                doi_match = re.search(r'^doi:\s*"([^"]+)"', content, re.M)
                if not url_match or url_match.group(1) != landing:
                    failures.append(f"{pid}: CITATION.cff canonical URL mismatch")
                expected = version_doi.removeprefix("https://doi.org/")
                if not doi_match or doi_match.group(1) != expected:
                    failures.append(f"{pid}: CITATION.cff version DOI mismatch")

            elif filename == "codemeta.json":
                try:
                    meta = json.loads(content)
                except json.JSONDecodeError as exc:
                    failures.append(f"{pid}: invalid codemeta.json: {exc}")
                    continue
                if meta.get("url") != landing:
                    failures.append(f"{pid}: CodeMeta canonical URL mismatch")
                if meta.get("codeRepository") != repo:
                    failures.append(f"{pid}: CodeMeta repository mismatch")
                if meta.get("identifier") != version_doi:
                    failures.append(f"{pid}: CodeMeta version DOI mismatch")

            elif filename == "CITATION.bib":
                if landing not in content:
                    failures.append(f"{pid}: CITATION.bib missing canonical landing")
                doi = version_doi.removeprefix("https://doi.org/")
                if doi not in content:
                    failures.append(f"{pid}: CITATION.bib missing version DOI")

    print(f"Research metadata consistency: {len(payload['projects'])} projects · {checks} metadata files checked.")
    if failures:
        for failure in failures:
            print("ERROR:", failure)
        return 1
    print("OK: CFF, BibTeX and CodeMeta align with the canonical portfolio.")
    return 0

if __name__ == "__main__":
    sys.exit(main())

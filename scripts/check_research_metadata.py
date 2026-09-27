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
CANONICAL_PORTFOLIO_RAW = "https://raw.githubusercontent.com/selguetagodoy/selguetagodoy.github.io/main/research-portfolio.json"
CANONICAL_SCHEMA_RAW = "https://raw.githubusercontent.com/selguetagodoy/selguetagodoy.github.io/main/research-portfolio.schema.json"

def get(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=25) as response:
        return response.read().decode("utf-8")

def exists(url: str) -> bool:
    req = Request(url, headers={"User-Agent": UA}, method="HEAD")
    try:
        with urlopen(req, timeout=20) as response:
            return 200 <= response.status < 400
    except HTTPError as exc:
        if exc.code in {405, 501}:
            req = Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"}, method="GET")
            try:
                with urlopen(req, timeout=20) as response:
                    return 200 <= response.status < 400
            except (HTTPError, URLError):
                return False
        return False
    except URLError:
        return False

def github_raw(repository: str, path: str) -> str:
    owner_repo = repository.removeprefix("https://github.com/").rstrip("/")
    return f"https://raw.githubusercontent.com/{owner_repo}/main/{path}"

def main() -> int:
    payload = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    failures: list[str] = []
    checks = 0

    try:
        public_payload = json.loads(get(CANONICAL_PORTFOLIO_RAW))
        checks += 1
        if public_payload != payload:
            failures.append("canonical-domain research-portfolio.json differs from source portfolio")
    except (HTTPError, URLError, json.JSONDecodeError) as exc:
        failures.append(f"cannot validate canonical-domain research portfolio: {exc}")

    try:
        public_schema = json.loads(get(CANONICAL_SCHEMA_RAW))
        checks += 1
        if public_schema.get("$id") != "https://selguetagodoy.github.io/research-portfolio.schema.json":
            failures.append("canonical research portfolio schema has unexpected $id")
        if payload.get("$schema") != public_schema.get("$id"):
            failures.append("source portfolio $schema does not match canonical schema $id")
    except (HTTPError, URLError, json.JSONDecodeError) as exc:
        failures.append(f"cannot validate canonical-domain research schema: {exc}")

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
        "datapackage.json",
        "ro-crate-metadata.json",
        "RELEASE_POLICY.md",
        "PUBLIC_RESOURCES.md",
        "README.md",
    )

    for project in payload["projects"]:
        pid = project["id"]
        repo = project["repository"]
        landing = project["landing"]
        version_doi = project["version_doi"]
        expected_latest = project.get("latest_git_release")
        expected_citable_date = project.get("citable_release_date")
        package_resource_paths: set[str] = set()

        owner_repo = repo.removeprefix("https://github.com/").rstrip("/")
        tree_items: dict[str, dict] = {}
        try:
            tree_url = f"https://api.github.com/repos/{owner_repo}/git/trees/main?recursive=1"
            tree_payload = json.loads(get(tree_url))
            tree_items = {
                item["path"]: item
                for item in tree_payload.get("tree", [])
                if item.get("type") == "blob" and item.get("path")
            }
            checks += 1
        except (HTTPError, URLError, json.JSONDecodeError) as exc:
            failures.append(f"{pid}: cannot read repository tree: {exc}")

        if expected_latest:
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

            if filename in {"SOURCE_OF_TRUTH.md", "NOTICE.md", "CHANGELOG.md", "CONTRIBUTING.md", "RELEASE_POLICY.md", "PUBLIC_RESOURCES.md", ".github/ISSUE_TEMPLATE/evidence-correction.yml", ".github/pull_request_template.md"}:
                continue

            if filename == "CITATION.cff":
                url_match = re.search(r'^url:\s*"([^"]+)"', content, re.M)
                doi_match = re.search(r'^doi:\s*"([^"]+)"', content, re.M)
                if not url_match or url_match.group(1) != landing:
                    failures.append(f"{pid}: CITATION.cff canonical URL mismatch")
                expected = version_doi.removeprefix("https://doi.org/")
                if not doi_match or doi_match.group(1) != expected:
                    failures.append(f"{pid}: CITATION.cff version DOI mismatch")
                date_match = re.search(r'^date-released:\s*"?([^"\n]+)"?', content, re.M)
                if expected_citable_date and (
                    not date_match or date_match.group(1).strip() != expected_citable_date
                ):
                    failures.append(f"{pid}: CITATION.cff release date mismatch")

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
                if expected_citable_date and meta.get("datePublished") != expected_citable_date:
                    failures.append(f"{pid}: CodeMeta datePublished mismatch")
                related_links = set(meta.get("relatedLink", []))
                if project.get("concept_doi") not in related_links:
                    failures.append(f"{pid}: CodeMeta missing concept DOI in relatedLink")

            elif filename == "CITATION.bib":
                if landing not in content:
                    failures.append(f"{pid}: CITATION.bib missing canonical landing")
                doi = version_doi.removeprefix("https://doi.org/")
                if doi not in content:
                    failures.append(f"{pid}: CITATION.bib missing version DOI")

            elif filename == "README.md":
                if expected_citable_date and expected_citable_date not in content:
                    failures.append(f"{pid}: README missing citable release date")
                doi = version_doi.removeprefix("https://doi.org/")
                if doi not in content:
                    failures.append(f"{pid}: README missing version DOI")

            elif filename == "datapackage.json":
                try:
                    package = json.loads(content)
                except json.JSONDecodeError as exc:
                    failures.append(f"{pid}: invalid datapackage.json: {exc}")
                    continue

                if package.get("profile") != "data-package":
                    failures.append(f"{pid}: datapackage profile must be data-package")
                if package.get("homepage") != landing:
                    failures.append(f"{pid}: datapackage homepage mismatch")

                expected_version = expected_latest.removeprefix("v") if expected_latest else None
                if expected_version and package.get("version") != expected_version:
                    failures.append(
                        f"{pid}: datapackage version {package.get('version')!r} != latest GitHub release {expected_version!r}"
                    )

                resources = package.get("resources", [])
                if not resources:
                    failures.append(f"{pid}: datapackage has no resources")
                    continue
                package_resource_paths = {
                    resource.get("path")
                    for resource in resources
                    if resource.get("path")
                }

                seen_names: set[str] = set()
                for resource in resources:
                    name = resource.get("name")
                    path = resource.get("path")
                    if not name or not path:
                        failures.append(f"{pid}: datapackage resource missing name/path")
                        continue
                    if name in seen_names:
                        failures.append(f"{pid}: duplicate datapackage resource name {name!r}")
                    seen_names.add(name)

                    resource_url = github_raw(repo, path)
                    checks += 1
                    if not exists(resource_url):
                        failures.append(f"{pid}: datapackage resource not found — {path}")
                        continue

                    tree_item = tree_items.get(path)
                    if not tree_item:
                        failures.append(f"{pid}: resource missing from Git tree — {path}")
                        continue

                    declared_size = resource.get("bytes")
                    declared_sha = resource.get("git_blob_sha")
                    actual_size = tree_item.get("size")
                    actual_sha = tree_item.get("sha")

                    if declared_size is None:
                        failures.append(f"{pid}: datapackage resource missing bytes — {path}")
                    elif declared_size != actual_size:
                        failures.append(
                            f"{pid}: resource size drift for {path}: "
                            f"{declared_size} != {actual_size}"
                        )

                    if not declared_sha:
                        failures.append(f"{pid}: datapackage resource missing git_blob_sha — {path}")
                    elif declared_sha != actual_sha:
                        failures.append(
                            f"{pid}: resource blob drift for {path}: "
                            f"{declared_sha} != {actual_sha}"
                        )

            elif filename == "ro-crate-metadata.json":
                try:
                    crate = json.loads(content)
                except json.JSONDecodeError as exc:
                    failures.append(f"{pid}: invalid ro-crate-metadata.json: {exc}")
                    continue

                if crate.get("@context") != "https://w3id.org/ro/crate/1.2/context":
                    failures.append(f"{pid}: RO-Crate context is not 1.2")

                graph = crate.get("@graph", [])
                descriptor = next(
                    (node for node in graph if node.get("@id") == "ro-crate-metadata.json"),
                    None,
                )
                root = next((node for node in graph if node.get("@id") == "./"), None)

                if not descriptor:
                    failures.append(f"{pid}: RO-Crate metadata descriptor missing")
                else:
                    if descriptor.get("@type") != "CreativeWork":
                        failures.append(f"{pid}: RO-Crate descriptor type mismatch")
                    if (descriptor.get("about") or {}).get("@id") != "./":
                        failures.append(f"{pid}: RO-Crate descriptor about mismatch")
                    if (descriptor.get("conformsTo") or {}).get("@id") != "https://w3id.org/ro/crate/1.2":
                        failures.append(f"{pid}: RO-Crate conformsTo mismatch")

                if not root:
                    failures.append(f"{pid}: RO-Crate root Dataset missing")
                else:
                    if root.get("@type") != "Dataset":
                        failures.append(f"{pid}: RO-Crate root type mismatch")
                    if root.get("name") != project.get("title"):
                        failures.append(f"{pid}: RO-Crate title mismatch")
                    if root.get("url") != landing:
                        failures.append(f"{pid}: RO-Crate landing mismatch")
                    if root.get("identifier") != version_doi:
                        failures.append(f"{pid}: RO-Crate version DOI mismatch")
                    expected_version = project.get("latest_citable_version", "").removeprefix("v")
                    if root.get("version") != expected_version:
                        failures.append(f"{pid}: RO-Crate citable version mismatch")
                    if expected_citable_date and root.get("datePublished") != expected_citable_date:
                        failures.append(f"{pid}: RO-Crate datePublished mismatch")
                    creator_id = (root.get("creator") or {}).get("@id")
                    if creator_id != "https://selguetagodoy.github.io/#person":
                        failures.append(f"{pid}: RO-Crate creator mismatch")
                    has_part = {
                        item.get("@id")
                        for item in root.get("hasPart", [])
                        if isinstance(item, dict) and item.get("@id")
                    }
                    missing_payload = package_resource_paths - has_part
                    if missing_payload:
                        failures.append(
                            f"{pid}: RO-Crate missing Data Package resources {sorted(missing_payload)}"
                        )

    print(f"Research metadata consistency: {len(payload['projects'])} projects · {checks} metadata/resource checks.")
    if failures:
        for failure in failures:
            print("ERROR:", failure)
        return 1
    print("OK: citation metadata, research package and declared public resources align with the canonical portfolio.")
    return 0

if __name__ == "__main__":
    sys.exit(main())

"""Validate the small, portal-ready SafeSort submission bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md",
    "portal-description.txt",
    "presentation.pdf",
    "demonstration.mp4",
    "report.pdf",
    "defense-script.md",
    "recovery-script.md",
    "submission-checklist.md",
    "checksums.sha256",
    "web/index.html",
    "web/styles.css",
    "web/app.js",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_checksums(bundle: Path) -> list[str]:
    failures: list[str] = []
    checksum_path = bundle / "checksums.sha256"
    if not checksum_path.is_file():
        return ["checksums.sha256"]
    for line in checksum_path.read_text(encoding="ascii").splitlines():
        expected, relative = line.split("  ", 1)
        path = bundle / relative
        if not path.is_file() or sha256(path) != expected:
            failures.append(relative)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    args = parser.parse_args()
    bundle = (ROOT / args.bundle).resolve()
    if not bundle.is_relative_to(ROOT):
        raise SystemExit("bundle must stay inside the repository")
    missing = [relative for relative in REQUIRED if not (bundle / relative).is_file()]
    description_path = bundle / "portal-description.txt"
    description = description_path.read_text(encoding="utf-8") if description_path.is_file() else ""
    urls = re.findall(r"https://[^\s]+", description)
    checksum_failures = check_checksums(bundle)
    result = {
        "bundle": bundle.relative_to(ROOT).as_posix(),
        "checksum_failures": checksum_failures,
        "description_characters": len(description),
        "links": len(urls),
        "missing": missing,
        "result": "pass" if not missing and not checksum_failures and len(description) <= 1500 and len(urls) >= 2 else "fail",
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

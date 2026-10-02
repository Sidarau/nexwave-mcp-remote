#!/usr/bin/env python3
"""Validate portable schemas and documented OpenAI submission constraints.

Run from any directory. --build creates an allowlisted ZIP only after validation.
This checks the upload package, not dashboard approval or conversational behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
FILES = ("plugin.json", "mcp.json", "assets/tdc-icon.svg")
ENDPOINT = "https://trydayclub-mcp.fly.dev/mcp"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def text_limit(value: object, maximum: int, name: str, single_line: bool = True) -> None:
    require(isinstance(value, str) and bool(value.strip()), f"{name}: nonempty text required")
    require(len(value) <= maximum, f"{name}: limit {maximum}")
    require(not any(ord(c) < 32 and (single_line or c != "\n") for c in value), f"{name}: unsupported control character")


def https_url(value: object, maximum: int) -> None:
    text_limit(value, maximum, "URL")
    parsed = urlsplit(value)
    require(parsed.scheme == "https" and bool(parsed.hostname), "HTTPS URL required")
    require(not parsed.username and not parsed.password, "URL credentials forbidden")


def contrast(color: str, background: str) -> float:
    def luminance(hex_color: str) -> float:
        values = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
        return sum(v * weight for v, weight in zip(values, (.2126, .7152, .0722)))
    first, second = sorted((luminance(color), luminance(background)))
    return (second + .05) / (first + .05)


def validate(check_urls: bool) -> dict:
    objects = {}
    for filename in ("plugin.json", "mcp.json"):
        objects[filename] = json.loads((ROOT / filename).read_text())
        schema = json.loads((ROOT / "validation" / filename.replace(".json", ".schema.json")).read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(objects[filename])
    manifest = objects["plugin.json"]
    require(bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", manifest["name"])), "Submission name must use lowercase words and single hyphens")
    require(bool(re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])), "Explicit semantic version required")
    text_limit(manifest["description"], 4000, "description", False)
    text_limit(manifest["author"]["name"], 120, "author.name")
    https_url(manifest["author"]["url"], 2048)
    https_url(manifest["homepage"], 2048)
    ext = manifest["extensions"]["com.openai"]
    require(not any(key in ext for key in ("id", "apps", "hooks", "onboardingSkill", "skills", "mcpServers")), "Only the portable MCP component is permitted")
    interface = ext["interface"]
    for field, maximum in (("displayName", 30), ("shortDescription", 30), ("longDescription", 4000), ("developerName", 80)):
        text_limit(interface[field], maximum, field, field != "longDescription")
    require(interface["category"] == "Travel", "Travel is the documented category for this package")
    require(len(interface["capabilities"]) <= 20, "At most 20 capabilities")
    for capability in interface["capabilities"]:
        text_limit(capability, 120, "capability")
    for field in ("websiteURL", "supportURL", "privacyPolicyURL", "termsOfServiceURL"):
        https_url(interface[field], 1024)
        require(urlsplit(interface[field]).hostname == "trydayclub.com", "Listing URLs must identify Try Day Club")
    prompts = interface["defaultPrompt"]
    require(isinstance(prompts, list) and 1 <= len(prompts) <= 3, "One to three starter prompts")
    require(len(set(prompts)) == len(prompts), "Starter prompts must be unique")
    for prompt in prompts:
        text_limit(prompt, 128, "starter prompt")
        require("@" not in prompt, "No app mentions in starter prompts")
    color = interface["brandColor"]
    require(bool(re.fullmatch(r"#[0-9A-Fa-f]{6}", color)), "Six-digit brand color required")
    color_contrast = contrast(color, "#FFFFFF")
    require(color_contrast >= 2, "Brand color must have >= 2:1 contrast against white")
    for field in ("composerIcon", "logo"):
        require(interface[field] == "./assets/tdc-icon.svg", "Icon paths must refer to packaged official asset")
        path = ROOT / interface[field]
        require(path.is_file() and path.stat().st_size <= 5 * 1024 * 1024, "Icon missing or oversized")
        svg = ET.fromstring(path.read_bytes())
        box = [float(value) for value in svg.attrib["viewBox"].split()]
        require(box[2] == box[3] and box[2] >= 48, "Square SVG viewBox at least 48 required")
    sources = json.loads((ROOT / "validation" / "sources.json").read_text())
    require(hashlib.sha256((ROOT / "assets/tdc-icon.svg").read_bytes()).hexdigest() == sources["icon"]["sha256"], "Official downloaded SVG must be unmodified")
    servers = objects["mcp.json"]["mcpServers"]
    require(servers == {"trydayclub": {"type": "streamable-http", "url": ENDPOINT}}, "Exactly one public server with no headers or auth settings required")
    review = ext["review"]
    require(not any(key in review for key in ("test_credentials", "reviewer_instructions", "demo_recording_url")), "Keep secrets and unfinished recording fields out of package")
    cases = review["test_cases"]
    require(len(cases["positive"]) == 5 and len(cases["negative"]) == 3, "Exactly five positive and three negative cases required")
    for group in ("positive", "negative"):
        for case in cases[group]:
            require(set(case) == {"description", "prompt", "tools_triggered", "expected_behavior"}, "Unexpected case fields")
            for field in case:
                text_limit(case[field], 4000, f"{group}.{field}", False)
    require(review["commerce"] is True, "Rental commerce behavior must be disclosed")
    text_limit(review["commerce_description"], 4000, "commerce_description", False)
    text_limit(ext["publication"]["release_notes"], 4000, "release_notes", False)
    for filename in FILES:
        data = (ROOT / filename).read_bytes().lower()
        require(not any(token in data for token in (b"sketchy", b"demo", b"/ops", b"nexwave", b"example.com", b"placeholder", b"api_key", b"bearer")), f"Forbidden public-package content in {filename}")
    urls = []
    if check_urls:
        for url in dict.fromkeys(interface[field] for field in ("websiteURL", "supportURL", "privacyPolicyURL", "termsOfServiceURL")):
            with urllib.request.urlopen(url, timeout=30) as response:
                require(response.status == 200, f"Listing URL inaccessible: {url}")
                html = response.read().decode()
                require("Try Day Club" in html, f"Publisher mismatch: {url}")
                if url == interface["supportURL"]:
                    require("Contact us" in html and "Contact the team" in html, "Support contact controls missing from homepage")
                urls.append({"url": url, "status": response.status})
        with urllib.request.urlopen(sources["icon"]["url"], timeout=30) as response:
            require(response.read() == (ROOT / "assets/tdc-icon.svg").read_bytes(), "Packaged icon differs from official source")
    return {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "package_validation": "PASS",
        "canonical_schemas": "Draft 2020-12 validation passed for plugin.json and mcp.json",
        "openai_constraints": "Documented listing, case, path, icon, color, URL, and public-surface assertions passed",
        "color_contrast_white": round(color_contrast, 3),
        "listing_url_checks": urls,
        "files": list(FILES),
        "review_ready": False,
        "review_limitations": ["Live conversation cases remain pending until observed", "Video walkthrough URL must be supplied", "Dashboard developer and domain verification, scan findings, and policy attestations remain owner-controlled"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--check-urls", action="store_true")
    args = parser.parse_args()
    report = validate(args.check_urls)
    if args.build:
        output = ROOT / "dist" / "trydayclub-1.0.0.zip"
        output.parent.mkdir(exist_ok=True)
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            for filename in FILES:
                info = ZipInfo(filename, date_time=(2026, 10, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, (ROOT / filename).read_bytes())
        with ZipFile(output) as archive:
            require(archive.namelist() == list(FILES), "ZIP file allowlist mismatch")
            require(archive.testzip() is None, "ZIP integrity failure")
        report["zip"] = {"path": "dist/" + output.name, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "bytes": output.stat().st_size}
    (ROOT / "validation" / "package-checks.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Collects objective, verifiable facts about a repo's module structure and dependency
versions -- so the Tech Stack section of architecture.md is built from what the build
manifests actually say, not from memory of "typical" versions for a framework.

Supports Maven (single or multi-module, including a parent pom's <properties> used by
child modules), Gradle (build.gradle / build.gradle.kts, best-effort regex since Groovy/
Kotlin DSL isn't parsed properly), and npm/yarn/pnpm (package.json). Anything else is
reported as "found this manifest, read it yourself" -- this script does not guess.

No external dependencies. Prints a JSON report to stdout; real narrative judgment
(which libraries are actually load-bearing vs. incidental, what a version implies) is
yours to make from the report, not the script's.
"""
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

SKIP_DIRS = {".git", "target", "build", "node_modules", "dist", "out", ".gradle", "vendor"}


def walk(root):
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def parse_pom(path):
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        return {"error": f"unparseable pom.xml: {e}"}
    root = tree.getroot()

    def find(tag, parent=None):
        el = (parent if parent is not None else root).find(f"m:{tag}", ns)
        return el.text.strip() if el is not None and el.text else None

    props = {}
    props_el = root.find("m:properties", ns)
    if props_el is not None:
        for child in props_el:
            tag = child.tag.split("}")[-1]
            if child.text:
                props[tag] = child.text.strip()

    modules = [m.text.strip() for m in root.findall("m:modules/m:module", ns) if m.text]

    deps = []
    for dep_parent_tag in ("dependencies", "dependencyManagement/m:dependencies"):
        for dep in root.findall(f"m:{dep_parent_tag}/m:dependency", ns):
            deps.append({
                "groupId": find("groupId", dep),
                "artifactId": find("artifactId", dep),
                "version": find("version", dep),
            })

    return {
        "artifactId": find("artifactId"),
        "parent": find("artifactId", root.find("m:parent", ns)) if root.find("m:parent", ns) is not None else None,
        "packaging": find("packaging") or "jar",
        "properties": props,
        "modules": modules,
        "dependencies": deps,
    }


def parse_package_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return {"error": f"unparseable package.json: {e}"}
    return {
        "name": data.get("name"),
        "version": data.get("version"),
        "dependencies": data.get("dependencies", {}),
        "devDependencies": data.get("devDependencies", {}),
        "workspaces": data.get("workspaces"),
    }


def parse_gradle(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    deps = re.findall(
        r"""(?:implementation|api|compileOnly|runtimeOnly|testImplementation)\s*[\(\s]?["']([^"':]+):([^"':]+):([^"')\s]+)["']""",
        text,
    )
    return {
        "note": "best-effort regex scan, not a real Groovy/Kotlin DSL parser -- verify by reading the file",
        "dependencies": [{"group": g, "artifact": a, "version": v} for g, a, v in deps],
    }


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    report = {"root": str(root), "maven": [], "gradle": [], "npm": [], "other_manifests": []}

    OTHER_MANIFEST_NAMES = {
        "requirements.txt", "pyproject.toml", "Cargo.toml", "go.mod",
        "composer.json", "Gemfile", "mix.exs",
    }

    for f in walk(root):
        name = f.name
        if name == "pom.xml":
            report["maven"].append({"path": str(f.relative_to(root)), **parse_pom(f)})
        elif name in ("build.gradle", "build.gradle.kts"):
            report["gradle"].append({"path": str(f.relative_to(root)), **parse_gradle(f)})
        elif name == "package.json":
            report["npm"].append({"path": str(f.relative_to(root)), **parse_package_json(f)})
        elif name in OTHER_MANIFEST_NAMES:
            report["other_manifests"].append(str(f.relative_to(root)))

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

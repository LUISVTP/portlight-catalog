#!/usr/bin/env python3
"""Valida entries/*.json y los fusiona en catalog.json (esquema draft 2020-12).

Validates every entry in entries/ against schema/catalog.schema.json, merges
them with the generated fields (status, release, last_checked) coming from
build/fetched.json — or, when a fetch did not run or failed, kept from the
previous catalog.json — and writes catalog.json.

  python scripts/merge_and_validate.py --check   # validate only, write nothing
  python scripts/merge_and_validate.py           # validate and write catalog.json

Entries whose id starts with "demo-" are validated but never published.
The script exits non-zero on any validation error.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import (  # noqa: E402
    CATALOG_PATH,
    FETCHED_PATH,
    SCHEMA_PATH,
    is_anchored,
    is_demo,
    iter_entry_paths,
    load_json,
    now_iso,
    save_json,
    validate_instance,
)

GENERATED_FIELDS = ("status", "release", "last_checked")


def warnings_for(entry):
    """Avisos no bloqueantes (PLAN §4.3 traducciones, §8.5 patrón anclado)."""
    found = []
    eid = entry.get("id", "?")
    description = entry.get("description", {})
    if "es" not in description:
        found.append("[%s] descripción sin español / description missing Spanish" % eid)
    if "en" not in description:
        found.append("[%s] descripción sin inglés / description missing English" % eid)
    pattern = entry.get("asset_pattern", "")
    if pattern and not is_anchored(pattern):
        found.append("[%s] asset_pattern no está anclado con ^ y $ (PLAN §8.5) / asset_pattern is not anchored" % eid)
    return found


def merge_generated(entry, fetched, previous):
    """Entrada + campos generados (conservando datos previos si falló el fetch)."""
    port = dict(entry)
    result = fetched.get(entry["id"])
    if result is not None:
        port["status"] = result["status"]
        if result.get("release"):
            port["release"] = result["release"]
        if result.get("last_checked"):
            port["last_checked"] = result["last_checked"]
    else:
        prior = previous.get(entry["id"])
        if prior:
            for field in GENERATED_FIELDS:
                if field in prior:
                    port[field] = prior[field]
    return port


def main():
    check_only = "--check" in sys.argv[1:]
    schema = load_json(SCHEMA_PATH)
    errors = []
    warnings = []
    entries = []

    for path in iter_entry_paths():
        try:
            entry = load_json(path)
        except Exception as error:  # noqa: BLE001 - se reporta y se aborta
            errors.append("%s: JSON inválido / invalid JSON: %s" % (path.name, error))
            continue
        for problem in validate_instance(entry, {"$ref": "#/$defs/port"}, schema):
            errors.append("%s -> %s" % (path.name, problem))
        entries.append(entry)
        warnings.extend(warnings_for(entry))

    if errors:
        print("ERRORES de validación / validation errors:")
        for problem in errors:
            print("  - " + problem)
        return 1

    previous = {port.get("id"): port for port in load_json(CATALOG_PATH).get("ports", [])} if CATALOG_PATH.exists() else {}
    fetched = load_json(FETCHED_PATH) if FETCHED_PATH.exists() else {}

    published = [merge_generated(entry, fetched, previous) for entry in entries if not is_demo(entry)]
    published.sort(key=lambda port: port["id"])
    demo_count = sum(1 for entry in entries if is_demo(entry))

    catalog = {"schema_version": 1, "generated_at": now_iso(), "ports": published}
    for problem in validate_instance(catalog, schema, schema):
        errors.append("catalog.json -> " + problem)
    if errors:
        print("ERRORES en el catálogo fusionado / merged catalog errors:")
        for problem in errors:
            print("  - " + problem)
        return 1

    if warnings:
        print("Avisos / warnings:")
        for warning in warnings:
            print("  - " + warning)

    if check_only:
        print("OK: %d entradas válidas (%d demo omitidas) / valid entries, nothing written" % (len(entries), demo_count))
        return 0

    save_json(CATALOG_PATH, catalog)
    print(
        "OK: catalog.json generado con %d puerto(s), %d demo omitida(s) / catalog.json written"
        % (len(published), demo_count)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

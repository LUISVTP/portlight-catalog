#!/usr/bin/env python3
"""Informe markdown del catálogo para consola y $GITHUB_STEP_SUMMARY.

Markdown catalog report for humans: status counts, one row per port, pending
translations, unanchored patterns, assets without digest, demo entries and the
causes of any failed fetch. Always exits 0 (it is informational; validation and
fetch failures are handled by the other scripts).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import (  # noqa: E402
    CATALOG_PATH,
    FETCHED_PATH,
    is_anchored,
    is_demo,
    iter_entry_paths,
    load_json,
)

STATUS_LABELS = {
    "active": "active (con APK)",
    "no-release": "no-release (sin APK)",
    "broken": "broken (comprobación fallida)",
    "removed": "removed (retirado a mano)",
}


def main():
    print("# Informe del catálogo / Catalog report\n")

    if not CATALOG_PATH.exists():
        print("catalog.json aún no existe; ejecuta merge_and_validate.py primero. / catalog.json not generated yet.")
        return 0

    catalog = load_json(CATALOG_PATH)
    ports = catalog.get("ports", [])
    print("- Generado / Generated: `%s`" % catalog.get("generated_at"))
    print("- Esquema / Schema version: `%s`" % catalog.get("schema_version"))
    print("- Puertos publicados / Published ports: **%d**\n" % len(ports))

    counts = {}
    for port in ports:
        status = port.get("status", "sin estado / no status")
        counts[status] = counts.get(status, 0) + 1
    print("## Estados / Status\n")
    for status, count in sorted(counts.items()):
        print("- `%s`: %d" % (STATUS_LABELS.get(status, status), count))

    print("\n## Puertos / Ports\n")
    print("| id | estado / status | release | assets | digest | abi | comprobado / checked |")
    print("|---|---|---|---|---|---|---|")
    for port in ports:
        release = port.get("release") or {}
        assets = release.get("assets", [])
        digests = sum(1 for asset in assets if asset.get("digest"))
        abis = sorted({asset.get("abi", "?") for asset in assets})
        print(
            "| `%s` | %s | %s | %d | %d/%d | %s | %s |"
            % (
                port.get("id"),
                STATUS_LABELS.get(port.get("status"), port.get("status", "?")),
                release.get("tag", "—"),
                len(assets),
                digests,
                len(assets),
                ", ".join(abis) if abis else "—",
                port.get("last_checked", "—"),
            )
        )

    warnings = []
    for path in iter_entry_paths():
        entry = load_json(path)
        eid = entry.get("id", path.stem)
        if is_demo(entry):
            warnings.append("`%s`: entrada demo; validada, no publicada / demo entry; validated, not published" % eid)
            continue
        description = entry.get("description", {})
        for lang in ("es", "en"):
            if lang not in description:
                warnings.append("`%s`: descripción sin %s (PLAN §4.3) / description missing %s" % (eid, lang, lang))
        if not is_anchored(entry.get("asset_pattern", "")):
            warnings.append("`%s`: asset_pattern sin anclar (PLAN §8.5) / asset_pattern not anchored" % eid)
        port = next((p for p in ports if p.get("id") == eid), None)
        if port:
            for asset in (port.get("release") or {}).get("assets", []):
                if not asset.get("digest"):
                    warnings.append("`%s`: asset sin digest SHA-256, la app mostrará un aviso (PLAN §9) / asset without SHA-256 digest" % (eid,))

    print("\n## Avisos / Warnings\n")
    if warnings:
        for warning in warnings:
            print("- " + warning)
    else:
        print("- ninguno / none")

    if FETCHED_PATH.exists():
        results = load_json(FETCHED_PATH)
        failures = [(eid, data) for eid, data in sorted(results.items()) if data.get("error")]
        print("\n## Causas de la última consulta / Last fetch causes\n")
        if failures:
            for eid, data in failures:
                print("- `%s` [%s]: %s" % (eid, data.get("status"), data.get("error")))
        else:
            print("- sin fallos / no failures")

    return 0


if __name__ == "__main__":
    sys.exit(main())

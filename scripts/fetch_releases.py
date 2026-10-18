#!/usr/bin/env python3
"""Consulta releases/latest de GitHub (una llamada por port) y escribe build/fetched.json.

Fetches the latest release of each port from the GitHub API — exactly one GET
request per port — and records the result (status + release + last_checked) in
build/fetched.json, which merge_and_validate.py then merges into catalog.json.

Rules (PLAN §7, §8):
  * One request per port per run; no polling, no caching.
  * Every asset matching the port's asset_pattern is published with its size,
    its GitHub-exposed SHA-256 digest (when present) and the ABI inferred from
    its name (never guessed).
  * 404            -> no-release (no published releases, or repository not found).
  * HTTP/network failure -> keep the previous catalog data and record the cause;
    without previous data the port becomes broken.
  * More than one candidate asset and none universal -> broken (PLAN §8.4).
  * Entries whose id starts with "demo-" are never fetched.
  * GITHUB_TOKEN / GH_TOKEN in the environment is used when present.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import (  # noqa: E402
    BUILD_DIR,
    CATALOG_PATH,
    FETCHED_PATH,
    abi_from_name,
    is_demo,
    iter_entry_paths,
    load_json,
    now_iso,
    save_json,
)

API_URL = "https://api.github.com/repos/{repo}/releases/latest"


def fetch_latest(repo, token):
    """Una única petición GET a releases/latest del repo."""
    headers = {
        "User-Agent": "portlight-catalog-script (https://github.com/LUISVTP/portlight-catalog)",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(API_URL.format(repo=repo), headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def matching_assets(assets, asset_pattern):
    """Assets del release cuyo nombre cumple el patrón del port."""
    regex = re.compile(asset_pattern)
    return [asset for asset in assets if regex.search(asset.get("name", ""))]


def build_release(data, candidates):
    """Objeto release del esquema a partir de la respuesta de la API."""
    assets = []
    for asset in candidates:
        item = {
            "name": asset["name"],
            "size": asset["size"],
            "url": asset["browser_download_url"],
        }
        digest = asset.get("digest")
        if digest:
            item["digest"] = digest
        abi = abi_from_name(asset["name"])
        if abi:
            item["abi"] = abi
        assets.append(item)
    release = {
        "tag": data["tag_name"],
        "source_url_release": data["html_url"],
        "assets": assets,
    }
    published_at = data.get("published_at")
    if published_at:
        release["published_at"] = published_at
    return release


def previous_by_id(previous_catalog):
    return {port.get("id"): port for port in previous_catalog.get("ports", [])}


def keep_previous(eid, previous, cause):
    """Conserva los datos previos del port y anota la causa (PLAN §7.2)."""
    prior = previous.get(eid)
    if prior:
        return {
            "status": prior.get("status", "broken"),
            "release": prior.get("release"),
            "last_checked": prior.get("last_checked"),
            "error": cause,
        }
    return {"status": "broken", "release": None, "last_checked": None, "error": cause}


def main():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    previous = previous_by_id(load_json(CATALOG_PATH) if CATALOG_PATH.exists() else {})
    results = {}

    for path in iter_entry_paths():
        entry = load_json(path)
        eid = entry.get("id", path.stem)

        if is_demo(entry):
            print("[%s] demo -> omitida, sin red / demo -> skipped, no request" % eid)
            continue

        checked = now_iso()
        try:
            data = fetch_latest(entry["repo"], token)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                results[eid] = {
                    "status": "no-release",
                    "release": None,
                    "last_checked": checked,
                    "error": "HTTP 404: sin releases publicados (o repo inexistente) / no published releases (or repository not found)",
                }
                print("[%s] no-release (404)" % eid)
            else:
                results[eid] = keep_previous(
                    eid, previous, "HTTP %s al consultar releases/latest / HTTP %s fetching releases/latest" % (error.code, error.code)
                )
                print("[%s] fallo HTTP %s, se conservan los datos previos / HTTP %s, previous data kept" % (eid, error.code, error.code))
        except Exception as error:  # noqa: BLE001 - se registra la causa y se conservan datos
            results[eid] = keep_previous(
                eid, previous, "error de red: %s / network error: %s" % (error, error)
            )
            print("[%s] fallo de red, se conservan los datos previos / network error, previous data kept" % eid)
            continue

        candidates = matching_assets(data.get("assets", []), entry["asset_pattern"])
        if not candidates:
            results[eid] = {
                "status": "no-release",
                "release": None,
                "last_checked": checked,
                "error": "el último release no tiene assets que cumplan asset_pattern / latest release has no assets matching asset_pattern",
            }
            print("[%s] no-release: sin APK que cumpla el patrón / no APK matches the pattern" % eid)
            continue

        release = build_release(data, candidates)
        if len(candidates) > 1 and not any(abi_from_name(a["name"]) == "universal" for a in candidates):
            # PLAN §8.4: nunca elegir «a la vista»; el port queda roto hasta aclararlo.
            results[eid] = {
                "status": "broken",
                "release": release,
                "last_checked": checked,
                "error": "%d assets candidatos y ninguno universal (PLAN §8.4) / %d candidate assets and none universal" % (len(candidates), len(candidates)),
            }
            print("[%s] broken: %d candidatos sin universal / %d candidates, none universal" % (eid, len(candidates), len(candidates)))
            continue

        results[eid] = {"status": "active", "release": release, "last_checked": checked, "error": None}
        print("[%s] active: tag %s, %d asset(s)" % (eid, release["tag"], len(candidates)))

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    save_json(FETCHED_PATH, results)
    print("resultado / written: build/fetched.json (%d puerto(s) / port(s))" % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())

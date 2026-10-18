"""Utilidades compartidas de los scripts del catálogo de Portlight.

Shared helpers for the Portlight catalog scripts. Standard library only
(no third-party dependencies) so the same code runs locally and in CI.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_DIR = ROOT / "entries"
SCHEMA_PATH = ROOT / "schema" / "catalog.schema.json"
CATALOG_PATH = ROOT / "catalog.json"
BUILD_DIR = ROOT / "build"
FETCHED_PATH = BUILD_DIR / "fetched.json"

# Los ids con este prefijo se validan pero no se publican ni se consultan en la red
# (entradas de prueba). Ids with this prefix are validated but never published nor
# fetched (test entries).
DEMO_PREFIX = "demo-"

# Inferencia de ABI a partir del nombre del asset (PLAN §8.3): sin adivinar; si el
# nombre no lleva ningún token conocido, se deja sin ABI. ABI inference from the
# asset name (PLAN §8.3): never guessed; unknown names get no ABI.
ABI_RULES = [
    (re.compile(r"arm64|aarch64", re.IGNORECASE), "arm64-v8a"),
    (re.compile(r"armeabi-v7a|armv7|arm32", re.IGNORECASE), "armeabi-v7a"),
    (re.compile(r"x86[-_]?64|amd64", re.IGNORECASE), "x86_64"),
    (re.compile(r"(^|[-_.])x86($|[-_.])|i[3-6]86", re.IGNORECASE), "x86"),
    (re.compile(r"universal", re.IGNORECASE), "universal"),
]


def now_iso():
    """Marca de tiempo UTC en el formato que exige el esquema (…Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def iter_entry_paths():
    return sorted(ENTRIES_DIR.glob("*.json"))


def is_demo(entry):
    return str(entry.get("id", "")).startswith(DEMO_PREFIX)


def abi_from_name(name):
    """Devuelve la ABI inferida del nombre del asset o None (sin adivinar)."""
    for pattern, abi in ABI_RULES:
        if pattern.search(name):
            return abi
    return None


def is_anchored(pattern):
    """¿El patrón está anclado con ^ y $? (PLAN §8.5: aviso si no lo está)."""
    return pattern.startswith("^") and (pattern.endswith("$") and not pattern.endswith("\\$"))


# ---------------------------------------------------------------------------
# Validador JSON Schema (subconjunto draft 2020-12, sin dependencias).
# Soporta: $ref local, type, const, enum, pattern, minLength, maxLength,
# minimum, maximum, required, properties, additionalProperties y anyOf, que es
# todo lo que usa schema/catalog.schema.json.
# ---------------------------------------------------------------------------

def _resolve_ref(ref, root):
    if not ref.startswith("#/"):
        raise ValueError("solo se admiten referencias locales #/$defs/…: " + ref)
    node = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[part]
    return node


def _type_ok(value, declared):
    if declared == "string":
        return isinstance(value, str)
    if declared == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared == "boolean":
        return isinstance(value, bool)
    if declared == "object":
        return isinstance(value, dict)
    if declared == "array":
        return isinstance(value, list)
    if declared == "null":
        return value is None
    raise ValueError("tipo desconocido en el esquema: " + declared)


def validate_instance(instance, schema, root, path="$", errors=None):
    """Valida instance contra schema (subconjunto 2020-12). Devuelve la lista de errores."""
    if errors is None:
        errors = []

    if "$ref" in schema:
        validate_instance(instance, _resolve_ref(schema["$ref"], root), root, path, errors)
        return errors

    if "type" in schema and not _type_ok(instance, schema["type"]):
        errors.append("%s: tipo esperado %s, obtenido %s" % (path, schema["type"], type(instance).__name__))
        return errors

    if "const" in schema and instance != schema["const"]:
        errors.append("%s: debe ser exactamente %r" % (path, schema["const"]))

    if "enum" in schema and instance not in schema["enum"]:
        errors.append("%s: debe ser uno de %r" % (path, schema["enum"]))

    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            errors.append("%s: cadena demasiado corta / string too short" % path)
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append("%s: cadena demasiado larga / string too long" % path)
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append("%s: no cumple el patrón %r / does not match pattern" % (path, schema["pattern"]))

    if isinstance(instance, int) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append("%s: mínimo %s / below minimum" % (path, schema["minimum"]))
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append("%s: máximo %s / above maximum" % (path, schema["maximum"]))

    if isinstance(instance, dict):
        for required in schema.get("required", []):
            if required not in instance:
                errors.append("%s: falta el campo obligatorio '%s' / missing required field" % (path, required))
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                validate_instance(value, properties[key], root, "%s.%s" % (path, key), errors)
            else:
                additional = schema.get("additionalProperties", True)
                if additional is False:
                    errors.append("%s: campo no permitido '%s' / unknown field" % (path, key))
                elif isinstance(additional, dict):
                    validate_instance(value, additional, root, "%s.%s" % (path, key), errors)

    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errors.append("%s: faltan elementos / too few items" % path)
        if "items" in schema:
            for index, item in enumerate(instance):
                validate_instance(item, schema["items"], root, "%s[%d]" % (path, index), errors)

    if "anyOf" in schema:
        if not any(validate_instance(instance, branch, root, path, []) == [] for branch in schema["anyOf"]):
            errors.append("%s: no cumple ninguna rama de anyOf / no anyOf branch matches" % path)

    return errors

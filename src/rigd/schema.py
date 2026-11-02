"""Protocol v1 schemas and their validator (VS-14; ARCHITECTURE 4.6, 12.1; ENG-01).

``schema/protocol-v1.json`` is the authoritative copy of the visitor protocol. The page and
the fake engine (``tests/web/fake-engine/schema/protocol-v1.json``) carry the same bytes, and
``tests/rigd/test_schema.py`` fails if they drift. ``schema/rigd-v1.json`` adds rigd's staff,
passage and test-hook messages, which the page never sends.

The validator is a line-for-line port of ``tests/web/fake-engine/schema.mjs``: the same small
JSON-Schema subset (type, const, enum, required, properties, additionalProperties,
patternProperties, items, minItems, maxItems, minimum, maximum, pattern, $ref), with ``$ref``
naming a key in ``definitions`` or ``server:<type>`` / ``client:<type>``. No dependency.
"""

from __future__ import annotations

import json
import math
import re
from functools import cache
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent / "schema"
PROTOCOL_PATH = HERE / "protocol-v1.json"
RIGD_PATH = HERE / "rigd-v1.json"


@cache
def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def protocol() -> dict:
    return _load(PROTOCOL_PATH)


def extension() -> dict:
    return _load(RIGD_PATH)


def _resolve(schema_doc: dict, ref: str) -> dict:
    side, name = ref.split(":", 1) if ":" in ref else ("definitions", ref)
    for doc in (schema_doc, protocol()):
        target = doc.get(side, {}).get(name)
        if target is not None:
            return target
    raise KeyError(f"schema: unknown $ref {ref}")


def _type_of(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, list):
        return "array"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "integer" if v.is_integer() and math.isfinite(v) else "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _type_ok(want: str | list[str], v: Any) -> bool:
    t = _type_of(v)
    wants = want if isinstance(want, list) else [want]
    return any(w == t or (w == "number" and t == "integer") for w in wants)


def check(schema: dict, value: Any, where: str, errors: list[str], doc: dict) -> list[str]:
    if "$ref" in schema:
        return check(_resolve(doc, schema["$ref"]), value, where, errors, doc)
    if "const" in schema and not _equal(value, schema["const"]):
        errors.append(f"{where}: must be {json.dumps(schema['const'])}")
        return errors
    if "enum" in schema and not any(_equal(value, e) for e in schema["enum"]):
        errors.append(f"{where}: {json.dumps(value)} is not one of {', '.join(schema['enum'])}")
        return errors
    if "type" in schema and not _type_ok(schema["type"], value):
        errors.append(f"{where}: expected {schema['type']}, got {_type_of(value)}")
        return errors
    if isinstance(value, int | float) and not isinstance(value, bool):
        if not math.isfinite(value):
            errors.append(f"{where}: not a finite number")
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{where}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{where}: above {schema['maximum']}")
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append(f"{where}: {json.dumps(value)} does not match {schema['pattern']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{where}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{where}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                check(schema["items"], item, f"{where}[{i}]", errors, doc)
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{where}: missing {key}")
        props = schema.get("properties", {})
        patterns = [(re.compile(p), s) for p, s in schema.get("patternProperties", {}).items()]
        for key, v in value.items():
            if key in props:
                check(props[key], v, f"{where}.{key}", errors, doc)
                continue
            hit = next((s for rx, s in patterns if rx.search(key)), None)
            if hit is not None:
                check(hit, v, f"{where}.{key}", errors, doc)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{where}: unexpected key {key}")
    return errors


def _equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) != isinstance(b, bool):
        return False  # JSON true is not 1
    return a == b


def validate(side: str, message: Any, *, extensions: bool = True) -> list[str]:
    """Errors for one message; [] if it is valid. ``side``: "server" or "client"."""
    if not isinstance(message, dict):
        return ["not an object"]
    t = message.get("t")
    for doc in (protocol(), extension()) if extensions else (protocol(),):
        sch = doc.get(side, {}).get(t) if isinstance(t, str) else None
        if sch is not None:
            return check(sch, message, str(t), [], doc)
    return [f"unknown {side} message type {json.dumps(t)}"]


def visitor_types(side: str) -> list[str]:
    return list(protocol()[side])


def extension_types(side: str) -> list[str]:
    return list(extension()[side])

"""One schema for the real rigd and the fake engine (VS-14, VS-28 AC 1; ENG-01).

* src/rigd/schema/protocol-v1.json is the authoritative copy; the fake engine's
  tests/web/fake-engine/schema/protocol-v1.json must be byte-identical, so drift fails CI.
* The fake engine's own validator (schema.mjs, run with node) must accept the messages the real
  rigd sends, and rigd's Python port must agree with it on valid and invalid examples.

tests/web belongs to the UI lane. On a branch without it these tests skip and say so; set
SX_FAKE_ENGINE_DIR to a checkout's tests/web/fake-engine to run them against another tree.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import ROOT

from rigd import schema

FAKE = Path(os.environ.get("SX_FAKE_ENGINE_DIR", ROOT / "tests" / "web" / "fake-engine"))


def fake_schema() -> Path:
    path = FAKE / "schema" / "protocol-v1.json"
    if not path.exists():
        pytest.skip(f"{path} absent: the UI lane's fake engine is not on this branch (UNVERIFIED)")
    return path


def test_fake_engine_schema_is_identical_to_rigds():
    assert fake_schema().read_bytes() == schema.PROTOCOL_PATH.read_bytes(), (
        "tests/web/fake-engine/schema/protocol-v1.json has drifted from src/rigd/schema/: "
        "change src/rigd/schema/protocol-v1.json and copy it, never the other way round"
    )


def test_the_extension_schema_adds_types_and_redefines_none():
    visitor = set(schema.visitor_types("client")) | set(schema.visitor_types("server"))
    ext = set(schema.extension_types("client")) | set(schema.extension_types("server"))
    assert ext and not ext & visitor


VALID = [
    ("client", {"v": 1, "t": "keys.touch", "bits": "0000000000001000"}),
    ("client", {"v": 1, "t": "machine.speed", "id": 3, "position": "div300"}),
    ("client", {"v": 1, "t": "patch.connect", "id": 1, "from": "dac.0", "to": "v1.pitch"}),
    ("server", {"v": 1, "t": "ack", "id": 9}),
    ("server", {"v": 1, "t": "fault", "code": "midi_absent", "staff_line": "x", "since": 0}),
]
INVALID = [
    ("client", {"v": 1, "t": "keys.touch", "bits": "1000"}),
    ("client", {"v": 1, "t": "keys.touch", "bits": "000000000000100g"}),
    ("client", {"v": 2, "t": "machine.home", "id": 1}),
    ("client", {"v": 1, "t": "machine.home", "id": 0}),
    ("client", {"v": 1, "t": "machine.home", "id": 1, "extra": True}),
    ("client", {"v": 1, "t": "machine.speed", "id": 1, "position": "turbo"}),
    ("client", {"v": 1, "t": "nope"}),
    ("server", {"v": 1, "t": "ack", "id": 1.5}),
    ("server", {"v": 1, "t": "nack", "id": 1, "code": "sorry"}),
    ("server", {"v": 1, "t": "fault", "code": "midi_absent", "staff_line": "x", "since": -1}),
]


@pytest.mark.parametrize("side, msg", VALID)
def test_python_validator_accepts(side, msg):
    assert schema.validate(side, msg) == []


@pytest.mark.parametrize("side, msg", INVALID)
def test_python_validator_rejects(side, msg):
    assert schema.validate(side, msg)


def test_the_fake_engines_validator_accepts_real_rigd_messages(rigd_proc, client_factory, tmp_path):
    fake_schema()
    node = shutil.which("node")
    if not node or not (FAKE / "schema.mjs").exists():
        pytest.skip("node or tests/web/fake-engine/schema.mjs missing (UNVERIFIED)")
    c = client_factory(rigd_proc.url)
    c.touch(1 << 12)
    c.pump(0.6)
    c.command({"t": "machine.speed", "position": "crawl"})
    c.command({"t": "passage.start", "slug": "x"})  # an extension message: nack refused_gate
    c.pump(0.3)
    kinds = {m["t"] for m in c.seen}
    assert {"hello", "patch", "heartbeat", "state", "scope", "ack", "nack"} <= kinds
    msgs = tmp_path / "msgs.json"
    msgs.write_text(json.dumps(c.seen))
    probe = tmp_path / "probe.mjs"
    probe.write_text(
        f"import {{ validate }} from {json.dumps((FAKE / 'schema.mjs').as_uri())};\n"
        "import { readFileSync } from 'node:fs';\n"
        "const all = JSON.parse(readFileSync(process.argv[2], 'utf8'));\n"
        "const bad = all.map((m) => [m.t, validate('server', m)]).filter(([, e]) => e.length);\n"
        "console.log(JSON.stringify({ n: all.length, bad: bad.slice(0, 5) }));\n"
        "process.exit(bad.length ? 1 : 0);\n"
    )
    out = subprocess.run([node, str(probe), str(msgs)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stdout + out.stderr
    assert json.loads(out.stdout)["n"] == len(c.seen)
    # and the Python port agrees with schema.mjs on every one of them
    assert all(schema.validate("server", m, extensions=False) == [] for m in c.seen)

"""miniaudio is vendored unmodified at its pinned commit (VS-13; src/host/vendor/miniaudio)."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "src" / "host" / "vendor" / "miniaudio"

PINNED = {
    "miniaudio.h": "6b376c7fbb1352ba1e0e432ab66069b335ea9405e45cb6c30b97ef0f3c9c3e0e",
    "LICENSE": "457f1b500e0adf6bc059edddfa78a2f62012e7c3bb43476c20e0bd23b25ba0eb",
}


def test_vendored_files_match_the_pin() -> None:
    for name, digest in PINNED.items():
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == digest, name


def test_provenance_names_the_same_tag_commit_and_hashes() -> None:
    prov = (VENDOR / "PROVENANCE.md").read_text()
    header = (VENDOR / "miniaudio.h").read_text(errors="replace")
    ver = ".".join(
        re.search(rf"#define MA_VERSION_{k}\s+(\d+)", header).group(1)
        for k in ("MAJOR", "MINOR", "REVISION")
    )
    assert f"`{ver}`" in prov
    assert "877ea4a7c2601c7b0f2a44e83dfac42e6470fea6" in prov
    for digest in PINNED.values():
        assert digest in prov


def test_the_built_library_has_no_web_audio_or_generator_code() -> None:
    """The header's WebAudio (Emscripten) backend and its waveform generators are text in a
    vendored file only: the library rigd loads contains none of them (AUDIO-1, FLT-12)."""
    ext = "dylib" if sys.platform == "darwin" else "so"
    lib = ROOT / "build" / "host" / f"libsxhost.{ext}"
    if not lib.exists():
        pytest.skip("needs `make host`")
    blob = lib.read_bytes()
    for marker in (b"AudioContext", b"AudioWorklet", b"ma_waveform_init", b"ma_noise_init",
                   b"ma_decoder_init", b"ma_engine_init"):  # fmt: skip
        assert marker not in blob, marker


def test_only_the_device_layer_and_three_backends_are_built() -> None:
    cfg = (ROOT / "src" / "host" / "ma_config.h").read_text()
    for opt in ("MA_NO_DECODING", "MA_NO_ENCODING", "MA_NO_GENERATION", "MA_NO_ENGINE",
                "MA_NO_NODE_GRAPH", "MA_ENABLE_ONLY_SPECIFIC_BACKENDS"):  # fmt: skip
        assert f"#define {opt}" in cfg
    enabled = set(re.findall(r"#define MA_ENABLE_(\w+)", cfg)) - {"ONLY_SPECIFIC_BACKENDS"}
    assert enabled == {"NULL", "COREAUDIO", "ALSA"}

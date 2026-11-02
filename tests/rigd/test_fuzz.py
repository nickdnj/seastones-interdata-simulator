"""ENG-03 / VS-14 AC 4: malformed, hostile and oversized protocol traffic from many connections
causes no crash and no command-queue corruption.

`make ci` runs a short form (20,000 messages over 20 connections). The nightly form is the
issue's: SX_FUZZ_N=1000000 SX_FUZZ_CONNS=100 pytest tests/rigd/test_fuzz.py. Seeded; the seed
is printed. Afterwards rigd must still answer, still run the program, still apply commands in
order, and must not have sounded a key nobody holds.
"""

from __future__ import annotations

import json
import os
import random
import threading

from conftest import Client, sounding

N = int(os.environ.get("SX_FUZZ_N", "20000"))
CONNS = int(os.environ.get("SX_FUZZ_CONNS", "20"))
SEED = int(os.environ.get("SX_FUZZ_SEED", "20261102"))

TYPES = ["keys.touch", "machine.speed", "machine.step", "machine.home", "patch.connect",
         "patch.disconnect", "patch.load", "passage.start", "staff.mute", "test.inject",
         "memory.write", "", None, 7, "hello", "state"]  # fmt: skip
VALUES = [None, True, False, 0, -1, 1, 2**64, 1.5, float("nan"), "", "run", "step", "x" * 300,
          "0000000000000001", "FFFFFFFFFFFFFFFF", [], {}, [1, 2], {"a": 1}]  # fmt: skip


def message(rng: random.Random) -> str | bytes:
    k = rng.random()
    if k < 0.05:
        return bytes(rng.getrandbits(8) for _ in range(rng.randint(0, 64)))
    if k < 0.15:
        return "".join(
            rng.choice('{}[]":,0123456789abcdefnulltrue \\') for _ in range(rng.randint(0, 80))
        )
    msg: dict = {"v": rng.choice([1, 1, 1, 2, "1", None]), "t": rng.choice(TYPES)}
    for key in rng.sample(["id", "bits", "position", "from", "to", "slug", "pin", "on", "what",
                           "addr", "value"], rng.randint(0, 4)):  # fmt: skip
        msg[key] = rng.choice(VALUES)
    if rng.random() < 0.3:
        msg["id"] = rng.randint(-5, 2**31)
    try:
        return json.dumps(msg, allow_nan=True)
    except (TypeError, ValueError):
        return "{}"


def test_fuzzed_traffic_does_not_crash_or_corrupt(rigd_proc, client_factory):
    print(f"\nfuzz: {N} messages over {CONNS} connections, seed {SEED}")
    watch = client_factory(rigd_proc.url)
    watch.pump(0.3)
    per = N // CONNS
    errors: list = []
    done: list[int] = []

    def worker(i: int) -> None:
        rng = random.Random(SEED + i)
        try:
            c = Client(rigd_proc.url)
        except OSError as exc:
            errors.append(exc)
            return
        try:
            for _ in range(per):
                c.ws.send(message(rng))
            # a sentinel: its ack proves rigd read and handled everything sent before it (an id
            # above anything the fuzzer sends, so its reply cannot be mistaken for another's)
            c.next_id = 2**40 + i
            if c.command({"t": "machine.speed", "position": "run"}, timeout=60)["t"] == "ack":
                done.append(i)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"worker {i}: {exc!r}")
        finally:
            try:
                c.ws.close() if i % 2 else c.ws.socket.close()  # polite, or dropped like a dead page
            except Exception:  # noqa: BLE001
                pass

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(CONNS)]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        watch.pump(0.2)  # keep our own socket drained meanwhile
    assert not errors, errors
    assert sorted(done) == list(range(CONNS)), "every connection's traffic was handled"
    assert rigd_proc.proc.poll() is None, "rigd survived"
    # it still answers, in order, and the engine still runs the program
    for pos in ("div30", "run"):
        assert watch.command({"t": "machine.speed", "position": pos})["t"] == "ack"
    assert watch.command({"t": "machine.home"})["t"] == "ack"
    watch.pump(0.6)  # the fuzzers' touch keys are cleared 250 ms after their sockets close
    st = watch.last("state")
    assert st["speed"] == "run" and not st["halted"] and st["scan_hz"] > 1000
    assert not any(st["keys_raw"]) and not sounding(st), "no key is left held by a dead socket"
    assert not watch.invalid

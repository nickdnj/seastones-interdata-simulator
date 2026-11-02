# The 1974 Seastones Rig: top-level build (SP-01, SP-03).
#
# Every CI job is a target here, so `make ci` locally runs the same list as the
# workflows in .github/workflows/ (DEV-PLAN 7.4). A target with nothing to build
# yet says so and passes; it never pretends to have tested something.

SHELL := /bin/bash
.DEFAULT_GOAL := help
.DELETE_ON_ERROR:

PYTHON  ?= python3
PYTEST  ?= $(PYTHON) -m pytest
BUILD   ?= build

# Our C files (never the vendored SIMH tree).
OUR_C := $(shell find src/engine tests/engine -type f \( -name '*.c' -o -name '*.h' \) \
                 -not -path 'src/engine/simh/*' 2>/dev/null | sort)
# Our shell scripts.
OUR_SH := $(wildcard scripts/*.sh) $(wildcard deploy/*.sh)
WORKFLOWS := $(wildcard .github/workflows/*.yml)

.PHONY: help ci lint lint-py lint-sh lint-c lint-workflows test engine oracle \
        program web-test release-check private-check private-check-range \
        private-check-history ci-deps hardware-acceptance conformance conformance-nightly \
        test-engine sanitize rt-lint engine-production bless listen release-rights notices \
        notices-check install-station verify-units

help:
	@echo "make ci             lint + private-check + test + conformance"
	@echo "make lint           ruff, shellcheck, clang-format --dry-run, actionlint"
	@echo "make test           pytest suites"
	@echo "make test-engine    C unit tests for the engine"
	@echo "make sanitize       engine tests and a short lockstep under ASan + UBSan"
	@echo "make rt-lint        no allocation, locks, syscalls or logging in render/ and dsp/"
	@echo "make conformance    S-3 lockstep against stock id16"
	@echo "make engine         build libseastones and its CLI"
	@echo "make host           build libsxhost (engine + audio + MIDI) for rigd"
	@echo "make run            the live station here: rigd + page server, prints the URL"
	@echo "make oracle         build stock id16 from deploy/simh.pin"
	@echo "make program        assemble the 7/16 program"
	@echo "make web-test       fake engine + Playwright suite (tests/web/web.mk)"
	@echo "make qa-adversarial the real page against a real rigd (tests/qa-adversarial/qa.mk)"
	@echo "make release-check  release gate G1-G11 (PASS / FAIL / NEEDS-HUMAN, record in build/release)"
	@echo "make notices        regenerate THIRD-PARTY-NOTICES from the vendored files"
	@echo "make install-station ARGS=...  the station installer (dry run unless --apply)"
	@echo "make verify-units   systemd-analyze verify on deploy/systemd (Docker on a Mac)"

ci: lint rt-lint private-check notices-check release-rights test test-engine conformance sanitize web-test qa-adversarial

# --- lint -------------------------------------------------------------------

lint: lint-py lint-sh lint-c lint-workflows

lint-py:
	ruff check .
	ruff format --check .

lint-sh:
	@if [ -z "$(strip $(OUR_SH))" ]; then echo "lint-sh: no scripts"; \
	elif command -v shellcheck >/dev/null; then shellcheck $(OUR_SH); \
	else echo "lint-sh: SKIPPED, shellcheck not installed (UNVERIFIED)"; fi

lint-c:
	@if [ -z "$(strip $(OUR_C))" ]; then echo "lint-c: no C files yet"; \
	elif command -v clang-format >/dev/null; then clang-format --dry-run --Werror $(OUR_C); \
	else echo "lint-c: SKIPPED, clang-format not installed (UNVERIFIED)"; fi

lint-workflows:
	@if [ -z "$(strip $(WORKFLOWS))" ]; then echo "lint-workflows: no workflows yet"; \
	elif command -v actionlint >/dev/null; then actionlint -config-file .github/actionlint.yaml $(WORKFLOWS); \
	else $(PYTHON) -c 'import sys, yaml; [yaml.safe_load(open(f)) for f in sys.argv[1:]]' \
	       $(WORKFLOWS) && echo "lint-workflows: actionlint missing, YAML parse only"; fi

# --- tests ------------------------------------------------------------------

# pytest exits 5 when it collects nothing; on an empty tree that is a pass.
test:
	@$(PYTEST) -q -m "not lockstep" tests; rc=$$?; \
	if [ $$rc -eq 5 ]; then echo "test: no tests yet"; exit 0; fi; exit $$rc

# RE-1 layer 3: the working tree and every blob reachable from HEAD (GAT-02). CI also
# runs `--range <base>..HEAD` over the push range; `--all-history` checks every ref.
private-check:
	$(PYTHON) scripts/check-private.py --tree
	$(PYTHON) scripts/check-private.py --range HEAD

# Push range for CI. BASE is github.event.before; a new branch reports all zeros,
# and then every blob reachable from HEAD is checked instead.
private-check-range:
	@if [ -z "$(BASE)" ] || [ -z "$$(echo '$(BASE)' | tr -d 0)" ] \
	    || ! git cat-file -e '$(BASE)^{commit}' 2>/dev/null; then \
	  echo "private-check-range: no usable base, checking all of HEAD"; \
	  $(PYTHON) scripts/check-private.py --range HEAD; \
	else $(PYTHON) scripts/check-private.py --range '$(BASE)..HEAD'; fi

private-check-history:
	$(PYTHON) scripts/check-private.py --all-history

# Tools CI needs on a fresh ubuntu runner. On a Mac, scripts/dev-setup.sh --check.
ci-deps:
	$(PYTHON) -m pip install --quiet ruff pytest pyyaml numpy
	@if command -v apt-get >/dev/null; then \
	  sudo apt-get update -qq && sudo apt-get install -y -qq build-essential patch \
	    shellcheck clang-format clang; \
	else echo "ci-deps: not a Debian/Ubuntu runner; see scripts/dev-setup.sh --check"; fi

# The bench job (nightly.yml `hardware`). Nothing here until the bench exists.
hardware-acceptance:
	@echo "hardware-acceptance: no bench yet (SP-BUY); see scripts/acceptance.sh when it lands" ; exit 1

# --- builds that do not exist yet --------------------------------------------

# S-3 GO evidence (SP-S3C): 20 seeded subset streams x 10^6 instructions, all 65,536
# first words disassembled, the period programs when SX_FIXTURES_DIR is set, the planted-
# CC-bug negative test, the shim size line. Under a minute on a laptop.
conformance: oracle engine program
	SX_ORACLE="$$(scripts/build-oracle.sh 2>/dev/null | tail -1)" \
	  $(PYTEST) -q -rs -m lockstep tests/conformance tests/toolchain tests/program tests/engine

# Nightly sizes (QA-STRATEGY 12.1): 100 streams x 10^7 instructions.
conformance-nightly: oracle engine program
	SX_STREAMS=100 SX_INSTRUCTIONS=10000000 \
	SX_ORACLE="$$(scripts/build-oracle.sh 2>/dev/null | tail -1)" \
	  $(PYTEST) -q -rs -m lockstep tests/conformance tests/toolchain tests/program tests/engine

# --- the engine (SP-S3B) -------------------------------------------------------
#
# Vendored SIMH files are copied to $(SIMH_B) and the numbered patches applied there;
# src/engine/simh/ itself is never modified. Vendored code is compiled with the
# stock id16 defines (-DIFP_IN_MEM, from the upstream makefile) and warnings off,
# because it is not ours to change. Our code gets the strict flags.
#
# SX_EXTRA_PATCHES adds patches after 0001-0004 (the S-3 negative test uses it with
# BUILD=build/mutant to plant a CC bug; never set it for a real build).

ENG_B        := $(BUILD)/engine
SIMH_SRC     := src/engine/simh
SIMH_B       := $(ENG_B)/simh
SIMH_PATCHES := $(sort $(wildcard $(SIMH_SRC)/patches/*.patch)) $(SX_EXTRA_PATCHES)
SIMH_FILES   := $(shell find $(SIMH_SRC) -type f 2>/dev/null)
VENDOR_C     := id16_cpu id_io id_uvc id16_sys id_fp
VENDOR_O     := $(addprefix $(ENG_B)/obj/,$(addsuffix .o,$(VENDOR_C)))
# Our engine sources: everything under these directories is compiled into the library.
ENGINE_DIRS  := src/engine/shim src/engine/api src/engine/machine src/engine/devices \
                src/engine/dsp src/engine/render
ENGINE_C     := $(sort $(wildcard $(addsuffix /*.c,$(ENGINE_DIRS))))
ENGINE_H     := $(shell find src/engine -name '*.h' -not -path 'src/engine/simh/*')
ENGINE_O     := $(patsubst src/engine/%.c,$(ENG_B)/obj/our/%.o,$(ENGINE_C))
ENGINE_INC   := $(addprefix -I,$(ENGINE_DIRS)) -Isrc/engine/include
CC           ?= cc
CXX          ?= c++
SOEXT        := $(if $(filter Darwin,$(shell uname -s)),dylib,so)
# Reproducible floating point for golden hashes (QA request 7): no contraction into
# FMA, no fast-math, ever. Position-independent so the same objects make the .so/.dylib.
FP_FLAGS     := -ffp-contract=off -fno-fast-math -fPIC
# `make ... SX_SAN=1` builds everything with ASan and UBSan (VS-01, CNF-12).
SAN_LIST     ?= address,undefined
SAN_FLAGS    := $(if $(SX_SAN),-fsanitize=$(SAN_LIST) -fno-sanitize-recover=all \
                  -fno-omit-frame-pointer)
VENDOR_CFLAGS := -std=gnu99 -O2 -g -w -DIFP_IN_MEM -DSEASTONES_ENGINE $(FP_FLAGS) $(SAN_FLAGS) \
                 $(if $(SX_SAN),$(SAN_VENDOR_EXTRA)) \
                 -I$(SIMH_B) -I$(SIMH_B)/Interdata -Isrc/engine/machine
# Build profile (VS-27): `test` (default: development and CI) compiles the test hooks in;
# `production` removes them and research-only features. Build production in its own tree:
# `make engine-production` (BUILD=$(BUILD)/prod).
SX_PROFILE   ?= test
PROFILE_FLAGS := $(if $(filter production,$(SX_PROFILE)),-DSX_PROFILE_PRODUCTION,-DSX_TEST_HOOKS)
OUR_CFLAGS   := -std=c17 -O2 -g -D_POSIX_C_SOURCE=200809L -DSEASTONES_ENGINE $(FP_FLAGS) $(PROFILE_FLAGS) \
                $(SAN_FLAGS) -Wall -Wextra -Wpedantic -Wconversion -Werror \
                -isystem $(SIMH_B) -isystem $(SIMH_B)/Interdata $(ENGINE_INC)
LDLIBS       := -lm -pthread $(SAN_FLAGS)

engine: $(ENG_B)/libseastones.a $(ENG_B)/libseastones.$(SOEXT) $(ENG_B)/sx-cpu \
        $(ENG_B)/sx-render

engine-production:
	$(MAKE) --no-print-directory engine SX_PROFILE=production BUILD=$(BUILD)/prod

$(SIMH_B)/.patched: $(SIMH_FILES) $(SX_EXTRA_PATCHES)
	rm -rf $(SIMH_B)
	mkdir -p $(SIMH_B)
	cp -R $(SIMH_SRC)/. $(SIMH_B)/
	@for p in $(SIMH_PATCHES); do \
	  echo "patch $$p"; \
	  patch -d $(SIMH_B) -p1 -s --no-backup-if-mismatch -i "$(CURDIR)/$$p" || exit 1; \
	done
	touch $@

$(VENDOR_O): $(ENG_B)/obj/%.o: $(SIMH_B)/.patched src/engine/machine/cycles.h Makefile
	@mkdir -p $(dir $@)
	$(CC) $(VENDOR_CFLAGS) -c $(SIMH_B)/Interdata/$*.c -o $@

$(ENG_B)/obj/our/%.o: src/engine/%.c $(ENGINE_H) $(SIMH_B)/.patched Makefile
	@mkdir -p $(dir $@)
	$(CC) $(OUR_CFLAGS) -c $< -o $@

$(ENG_B)/libseastones.a: $(VENDOR_O) $(ENGINE_O)
	rm -f $@
	ar rcs $@ $^

$(ENG_B)/libseastones.$(SOEXT): $(VENDOR_O) $(ENGINE_O)
	$(CC) -shared $(SAN_FLAGS) $^ -o $@ -lm

$(ENG_B)/sx-cpu: src/engine/tools/sx-cpu.c $(ENGINE_H) $(ENG_B)/libseastones.a
	$(CC) $(OUR_CFLAGS) $< $(ENG_B)/libseastones.a -o $@ $(LDLIBS)

# The headless render CLI (VS-12): POSIX tool code, so it may use stdio, libm and realpath.
$(ENG_B)/sx-render: src/engine/tools/sx-render.c $(ENGINE_H) $(ENG_B)/libseastones.a
	$(CC) $(OUR_CFLAGS) -D_XOPEN_SOURCE=700 $< $(ENG_B)/libseastones.a -o $@ $(LDLIBS)

# The native host and rigd (host, host-production, run), in their own file; host lane.
include src/host/host.mk

# --- engine unit tests, RT-lint, sanitizers (VS-01) ----------------------------------

ENGINE_TESTS := $(patsubst tests/engine/%.c,$(ENG_B)/tests/%,$(wildcard tests/engine/test_*.c))

$(ENG_B)/tests/%: tests/engine/%.c $(ENGINE_H) $(ENG_B)/libseastones.a
	@mkdir -p $(dir $@)
	$(CC) $(OUR_CFLAGS) -Itests/engine $< $(ENG_B)/libseastones.a -o $@ $(LDLIBS)

test-engine: $(ENGINE_TESTS)
	@for t in $(ENGINE_TESTS); do echo "run $$t"; "$$t" || exit 1; done

# The engine unit tests and a short lockstep under ASan + UBSan, in their own build tree.
sanitize: oracle
	BUILD=$(BUILD) scripts/sanitize.sh

rt-lint:
	$(PYTHON) scripts/rt-lint.py

# Stock id16 from deploy/simh.pin, cached in $(SX_CACHE)/oracle/<commit>/ (SP-S3A), and
# id16-seastones, the same tag plus our device file (VS-06).
oracle:
	@scripts/build-oracle.sh | tail -1
	@scripts/build-oracle.sh --seastones | tail -1

# The 7/16 program (VS-09, PO-01, PO-05): assembled from source plus the rig data, twice: the
# floor default (four voices on the all-D/A channel map, rig.img.json) and the ADR-003
# eight-voice latch map (rig8.img.json). Same source; only the TABLE data differs.
PROGRAM_S := src/program/rig.s src/program/scan.s src/program/voices.s src/program/routines.s \
             src/program/score.s src/program/memory.s src/program/tables.s
RIG_DATA  := src/program/rig
SXASM     := PYTHONPATH=src/toolchain $(PYTHON) -m sxasm $(PROGRAM_S) \
             --subset src/program/subset/m74-portable-1.txt --dac $(RIG_DATA)/dac.md
program: $(BUILD)/program/rig.img.json $(BUILD)/program/rig8.img.json

$(BUILD)/program/rig.img.json: $(PROGRAM_S) $(wildcard $(RIG_DATA)/*.md) $(wildcard src/toolchain/sxasm/*.py)
	$(SXASM) --map $(RIG_DATA)/channel-map.md -o $(BUILD)/program --name rig

$(BUILD)/program/rig8.img.json: $(PROGRAM_S) $(wildcard $(RIG_DATA)/*.md) $(wildcard src/toolchain/sxasm/*.py)
	$(SXASM) --map $(RIG_DATA)/channel-map-8.md -o $(BUILD)/program --name rig8

# Golden renders (PO-10): re-bless every pinned render after a deliberate change, with the
# reason logged in tests/engine/golden/CHANGES.md. Without REASON it refuses.
bless:
	@if [ -z "$(strip $(REASON))" ]; then \
	  echo "make bless: say why: make bless REASON='what changed and why the sound may move'" >&2; \
	  exit 1; fi
	$(MAKE) --no-print-directory engine program
	SX_REBLESS=1 $(PYTEST) -q -m lockstep tests/engine/test_golden_render.py tests/engine/test_presets.py -k golden
	@printf '| %s | golden renders | %s | make bless |\n' "$$(date +%F)" "$(REASON)" >> tests/engine/golden/CHANGES.md
	@echo "make bless: re-blessed; review the diff of tests/engine/golden/ and commit it with the reason"

# Listening copies of every preset (tools/presets.py): build/listen/<slug>.wav, git-ignored.
listen: engine program
	$(PYTHON) tools/presets.py --listen

# The page's tests live with the UI lane, in their own file (web-ui-test, web-shots, web-dev).
include tests/web/web.mk
include tests/qa-adversarial/qa.mk
web-test: web-ui-test

# The release gate (CT-05, CT-16; QA-STRATEGY 8): G1 to G11 over a staged production install,
# each PASS, FAIL or NEEDS-HUMAN with evidence, and a release record in build/release/. Exit 1
# on any FAIL; the rights gate G1 always fails it. `release-rights` is G1 alone, run by `ci`.
release-check: host-production
	$(PYTHON) scripts/release-gate.py

release-rights:
	$(PYTHON) scripts/release-gate.py --gates G1 --no-record

# THIRD-PARTY-NOTICES from the vendored files (CT-12). `notices-check` fails when it is stale.
notices:
	$(PYTHON) scripts/notices.py

notices-check:
	$(PYTHON) scripts/notices.py --check

# Install the station (KP-11): a dry run unless ARGS has --apply; see docs/OPERATIONS.md.
install-station:
	scripts/install-station.sh $(ARGS)

verify-units:
	scripts/verify-units.sh

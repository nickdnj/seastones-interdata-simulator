# src/host/host.mk: the native host and rigd (host lane: VS-13, VS-14, VS-17, VS-18), included
# from the top Makefile so other lanes' edits to it do not collide with these.
#
#   make host             build/host/libsxhost.{dylib,so} (engine + audio + MIDI) and sxkeys
#   make host-production  the same in the production profile, under build/prod/
#   make run              the live station on this machine: rigd + the page server; prints the URL
#   make host-linux-check compile the ALSA backends in a Debian 13 container (needs Docker)
#
# libsxhost holds the engine's objects too, so rigd loads one library and there is exactly one
# engine in the process (R-A3). miniaudio is compiled as vendored code, warnings off; our host
# files get the engine's strict flags.

HOST_B      := $(BUILD)/host
HOST_SRC    := src/host
HOST_C      := $(HOST_SRC)/audio.c $(HOST_SRC)/clock.c $(HOST_SRC)/midi.c $(HOST_SRC)/rt/rt.c
HOST_H      := $(wildcard $(HOST_SRC)/*.h $(HOST_SRC)/rt/*.h)
MA_DIR      := $(HOST_SRC)/vendor/miniaudio
UNAME_S     := $(shell uname -s)

ifeq ($(UNAME_S),Darwin)
HOST_C      += $(HOST_SRC)/midi_coremidi.c
HOST_OSFLAGS := -D_DARWIN_C_SOURCE
BLOCKS      := -fblocks
HOST_LIBS   := -framework CoreMIDI -framework CoreAudio -framework AudioToolbox \
               -framework AudioUnit -framework CoreFoundation
else
HOST_C      += $(HOST_SRC)/midi_alsa.c
HOST_OSFLAGS := -D_GNU_SOURCE
BLOCKS      :=
HOST_LIBS   := -lasound -ldl
endif

HOST_O      := $(patsubst $(HOST_SRC)/%.c,$(HOST_B)/obj/%.o,$(HOST_C))
HOST_CFLAGS := $(OUR_CFLAGS) $(HOST_OSFLAGS) -I$(HOST_SRC) -I$(HOST_SRC)/rt -isystem $(MA_DIR)
# CoreMIDI's API takes blocks, a clang extension, so that file has -fblocks and no -Wpedantic.
HOST_BLOCKS := $(filter-out -Wpedantic,$(HOST_CFLAGS)) $(BLOCKS)
MA_CFLAGS   := -std=c99 -O2 -g -w -fPIC $(SAN_FLAGS) -I$(HOST_SRC) -I$(MA_DIR)

.PHONY: host host-production run host-linux-check host-live-smoke host-latency host-soak

host: $(HOST_B)/libsxhost.$(SOEXT) $(BUILD)/tools/sxkeys

host-production:
	$(MAKE) --no-print-directory host program SX_PROFILE=production BUILD=$(BUILD)/prod

$(HOST_B)/obj/%.o: $(HOST_SRC)/%.c $(HOST_H) $(ENGINE_H) $(SIMH_B)/.patched src/host/host.mk Makefile
	@mkdir -p $(dir $@)
	$(CC) $(if $(findstring coremidi,$<),$(HOST_BLOCKS),$(HOST_CFLAGS)) -c $< -o $@

$(HOST_B)/obj/miniaudio.o: $(HOST_SRC)/miniaudio_impl.c $(HOST_SRC)/ma_config.h $(MA_DIR)/miniaudio.h
	@mkdir -p $(dir $@)
	$(CC) $(MA_CFLAGS) -c $< -o $@

$(HOST_B)/libsxhost.$(SOEXT): $(HOST_O) $(HOST_B)/obj/miniaudio.o $(VENDOR_O) $(ENGINE_O)
	$(CC) -shared $(SAN_FLAGS) $^ -o $@ -lm -pthread $(HOST_LIBS)

# A test MIDI source: a virtual keyboard driven from stdin (tools/host/sxkeys.c).
$(BUILD)/tools/sxkeys: tools/host/sxkeys.c $(HOST_SRC)/clock.c $(HOST_SRC)/sxhost.h
	@mkdir -p $(dir $@)
	$(CC) $(filter-out -Wpedantic,$(HOST_CFLAGS)) $(BLOCKS) tools/host/sxkeys.c $(HOST_SRC)/clock.c \
	  -o $@ -pthread $(HOST_LIBS)

# The live station on this machine (DEV-PLAN 6: scripts/run-station.sh).
run: host program
	scripts/run-station.sh

host-linux-check:
	scripts/host-linux-check.sh

# The host on this machine's real output, silently (the device gets zeros), plus the supervision
# and fault tests: what `make ci` cannot do on a runner with no sound card.
host-live-smoke: host program
	SX_LIVE_AUDIO=1 $(PYTEST) -q -s -rs tests/rigd/test_live_device.py

# The 10-minute soak: random traffic, an engine fault every 20 s (tests/rigd/test_soak.py)
host-soak: host program
	SX_SOAK_S=$${SX_SOAK_S:-600} $(PYTEST) -q -s tests/rigd/test_soak.py

# Key-to-sound through the live host, LAT-02 Mode B (indicative on a Mac; tools/host/latency_run.py)
host-latency: host program
	$(PYTHON) tools/host/latency_run.py --presses 500

# --- wiring into the shared targets -------------------------------------------------------

# What rigd's tests need on a fresh runner: rigd's two runtime dependencies (DEV-PLAN 7.1:
# cffi and websockets; Debian packages them as python3-cffi and python3-websockets) and the
# ALSA headers for the Linux host build.
.PHONY: host-ci-deps
ci-deps: host-ci-deps
host-ci-deps:
	$(PYTHON) -m pip install --quiet cffi websockets
	@if command -v apt-get >/dev/null; then \
	  sudo apt-get update -qq && sudo apt-get install -y -qq libasound2-dev; \
	else echo "host-ci-deps: not Debian/Ubuntu; ALSA headers are only needed on Linux"; fi

# rigd's and the host's pytest suites (tests/rigd, tests/host) need the library and the image,
# in both profiles (tests/rigd/test_profiles.py runs rigd on the production build).
test: host program host-production
OUR_C += $(shell find src/host tests/host tools/host -type f \( -name '*.c' -o -name '*.h' \) \
                 -not -path 'src/host/vendor/*' 2>/dev/null | sort)

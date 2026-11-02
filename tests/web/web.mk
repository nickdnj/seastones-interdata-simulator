# tests/web/web.mk: the page's test targets (UI lane), included from the top Makefile so the
# engine lane's edits to the Makefile do not collide with these.
#
#   make web-test    (the Makefile's name for web-ui-test) fake-engine tests, the
#                    fake-vs-real CPU check, Playwright on the fake engine
#   make web-test WEB_CI=1   the same on a fresh hosted runner (ci.yml web-test job): Node 22
#                    from the runner's tool cache, Chromium with its Linux libraries
#   make web-shots   write the 1920 x 1080 review captures to docs/qa/results/ui/
#   make web-dev     run the fake engine and the page on loopback for development
#
# Dev-only tooling: Node and Playwright never ship on the station (DEV-PLAN 7.1). Playwright
# is pinned in tests/web/package-lock.json (1.64.0, Chromium build 1248).

WEB_TESTS := tests/web

# On a GitHub-hosted runner the default node can be older than 22; the runner's tool cache
# has a Node 22, which the workflow may not select with setup-node (tests/ci allows only
# checkout, setup-python and cache), so make puts it first on PATH here.
ifneq ($(WEB_CI),)
NODE22_BIN := $(lastword $(sort $(wildcard /opt/hostedtoolcache/node/22.*/x64/bin)))
ifneq ($(NODE22_BIN),)
export PATH := $(NODE22_BIN):$(PATH)
endif
PW_INSTALL := npx playwright install --with-deps chromium
else
PW_INSTALL := npx playwright install chromium
endif

.PHONY: web-deps web-node web-ui-test web-shots web-dev

# Node 22 or newer: the fake engine's tests use the global WebSocket and --test-force-exit.
web-node:
	@node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)' || \
	  { echo "web-test needs Node 22 or newer; found $$(node --version 2>/dev/null || echo none)"; exit 1; }

web-deps: web-node
	@if [ ! -d $(WEB_TESTS)/node_modules/@playwright/test ]; then \
	  cd $(WEB_TESTS) && npm ci --no-audit --no-fund; fi
	@cd $(WEB_TESTS) && $(PW_INSTALL) >/dev/null

# --test-timeout makes a stuck test a failure; --test-force-exit stops a handle left open
# (a server, a socket) from keeping node alive after the last test, so a hang cannot stall CI.
NODE_TEST := node --test --test-timeout=60000 --test-force-exit

web-ui-test: program engine web-deps
	$(NODE_TEST) $(WEB_TESTS)/fake-engine/engine.test.mjs $(WEB_TESTS)/fake-engine/wall.test.mjs $(WEB_TESTS)/fixture-isolation.test.mjs
	$(PYTEST) -q $(WEB_TESTS)/test_fake_cpu_conformance.py
	cd $(WEB_TESTS) && npx playwright test

web-shots: program engine web-deps
	cd $(WEB_TESTS) && SX_UI_SHOTS=1 npx playwright test ui/screenshots.spec.mjs

web-dev: program engine
	@echo "page: http://127.0.0.1:8080/   fake engine: ws://127.0.0.1:7690 (no sound)"
	node $(WEB_TESTS)/fake-engine/cli.mjs --port 7690 & \
	  $(PYTHON) src/web/serve.py --port 8080; kill $$! 2>/dev/null

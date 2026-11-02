# tests/qa-adversarial/qa.mk: the adversarial suite (docs/qa/results/adversarial-2026-11-03.md),
# included from the top Makefile.
#
#   make qa-adversarial   the real page against a real rigd on the null audio device (Playwright).
#                         The pytest half (tests/qa-adversarial/test_*.py) runs in `make test`.
#
# A known, unfixed bug is test.fail() (Playwright) or xfail(strict=True) (pytest) with its
# QA-ADV id, so the suite stays green while the bug stands and goes red the day it is fixed
# (then drop the marker).

.PHONY: qa-adversarial

qa-adversarial: host program web-deps
	cd tests/web && npx playwright test -c ../qa-adversarial/playwright.config.mjs

/* miniaudio_impl.c: the one translation unit that compiles the vendored miniaudio (VS-13).
 *
 * Vendored code is compiled as it is, with warnings off, like the SIMH files (src/host/host.mk);
 * the header in src/host/vendor/miniaudio/ is never edited (PROVENANCE.md there). The build
 * options are in ma_config.h, shared with audio.c.
 *
 * Copyright (c) 2026 Nick D. MIT licence (this file; miniaudio is public domain or MIT-0).
 */
#include "ma_config.h"

#define MINIAUDIO_IMPLEMENTATION
#include "miniaudio.h"

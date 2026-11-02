/* patch.h: building patch graphs off the audio thread (src/engine/api/patch.c; PM-05, PM-06).
 * Copyright (c) 2026 Nick D. MIT licence. */
#ifndef SX_PATCH_H
#define SX_PATCH_H

#include <stddef.h>

#include "graph.h"

/* [non-RT] Parse seastones.graph/1 text and build a graph at rate fs; NULL on error, with
 * "line N: why" in err. Free with sx_patch_free. */
sx_graph *sx_patch_build(const char *text, size_t len, double fs, char *err, size_t errn);
void sx_patch_free(sx_graph *g);

/* The built-in patch an engine starts with: four plain voices (saw, envelope, VCA) on the
 * all-D/A channel map, D/A 0-3 pitch and 4-7 gates (src/program/rig/channel-map.md). */
extern const char sx_patch_builtin[];

#endif

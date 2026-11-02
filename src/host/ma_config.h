/* ma_config.h: miniaudio's build options, included before miniaudio.h by every file that uses it
 * (miniaudio_impl.c and audio.c), so all of them see the same ma_device layout (VS-13).
 *
 * Only the device I/O layer is built: no decoders, encoders, generators, node graph or engine,
 * and only the backends the station and developer Macs use, plus the null device for tests.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SXH_MA_CONFIG_H
#define SXH_MA_CONFIG_H

#define MA_NO_DECODING
#define MA_NO_ENCODING
#define MA_NO_GENERATION
#define MA_NO_RESOURCE_MANAGER
#define MA_NO_NODE_GRAPH
#define MA_NO_ENGINE
#define MA_ENABLE_ONLY_SPECIFIC_BACKENDS
#define MA_ENABLE_NULL
#if defined(__APPLE__)
#define MA_ENABLE_COREAUDIO
#else
#define MA_ENABLE_ALSA
#endif
#define MA_PTHREAD_REALTIME_THREAD_PRIORITY 70 /* ARCHITECTURE 10: SCHED_FIFO prio 70 */

#endif

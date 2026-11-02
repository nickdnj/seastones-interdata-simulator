/* sha256.h: SHA-256 (FIPS 180-4) for image hashes (ASM-09) and golden renders (VS-12, VS-30).
 * Non-RT. Copyright (c) 2026 Nick D. MIT licence. */
#ifndef SX_SHA256_H
#define SX_SHA256_H

#include <stddef.h>
#include <stdint.h>

typedef struct sx_sha256 {
    uint32_t h[8];
    uint64_t len; /* bytes */
    uint8_t buf[64];
    uint32_t nbuf;
} sx_sha256;

void sx_sha256_init(sx_sha256 *s);
void sx_sha256_update(sx_sha256 *s, const void *data, size_t n);
void sx_sha256_final(sx_sha256 *s, uint8_t out[32]);
void sx_sha256_hex(const uint8_t d[32], char out[65]);

#endif

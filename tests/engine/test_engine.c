/* test_engine.c: the engine API end to end (VS-12; DSP-14, DSP-15, DSP-16, ASM-09).
 *
 *   one engine per process; configuration checks; a tampered image is refused, silently
 *   (image_hash_mismatch); a render is bit-identical across two engine lifetimes; commands
 *   (queue full, HALT, SPEED, MUTE, HOME); and the snapshot seqlock under a writer rendering at
 *   full rate and a reader at 1 kHz: no torn read (fields written together always agree).
 */
#include "seastones.h"
#include "sha256.h"
#if defined(SX_TEST_HOOKS)
#include "seastones_test.h"
#endif

#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

static int failures, checks;

#define CHECK(x)                                                                                   \
    do {                                                                                           \
        checks++;                                                                                  \
        if (!(x)) {                                                                                \
            failures++;                                                                            \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #x);                  \
        }                                                                                          \
    } while (0)

/* X'100' LHI R11,X'21' / LHI R12,X'22' / LHI R3,X'8000' / WHR R12,R3 (gate 0 up) /
 * LHI R13,X'20' / LIS R2,0
 * X'114' AIS R2,1 / WHR R11,R2 (D/A 0 = R2: a rising staircase) / RDR R13,R4 (reads the keyboard,
 * so the supervisor sees a live program) / B X'114' */
static const uint16_t prog[] = {0xC8B0, 0x0021, 0xC8C0, 0x0022, 0xC830, 0x8000, 0x98C3, 0xC8D0,
                                0x0020, 0x2420, 0x2621, 0x98B2, 0x9BD4, 0x4300, 0x0114};
static sx_segment seg = {0x100, sizeof prog / sizeof prog[0], prog};

static sx_image image(int tamper)
{
    sx_image img = {&seg, 1, 0x100, 0, {0}};
    sx_sha256 h;
    sx_sha256_init(&h);
    uint8_t hd[4] = {0x01, 0x00, 0x00, (uint8_t)seg.nwords};
    sx_sha256_update(&h, hd, 4);
    for (uint32_t i = 0; i < seg.nwords; i++) {
        uint8_t w[2] = {(uint8_t)(prog[i] >> 8), (uint8_t)prog[i]};
        sx_sha256_update(&h, w, 2);
    }
    sx_sha256_final(&h, img.sha256);
    if (tamper)
        img.sha256[5] ^= 1u;
    return img;
}

static sx_config config(void)
{
    sx_config c = {SX_API_VERSION, 48000, 32768, 250, 12, 10.24f, 0, 4096, 0, 0, 0};
    return c;
}

static float out[2 * 48000];

static void hash_render(sx_engine *e, uint32_t frames, char hex[65])
{
    sx_sha256 h;
    sx_sha256_init(&h);
    for (uint32_t f = 0; f < frames; f += 128) {
        sx_render(e, out, 128);
        sx_sha256_update(&h, out, 2 * 128 * sizeof(float));
    }
    uint8_t d[32];
    sx_sha256_final(&h, d);
    sx_sha256_hex(d, hex);
}

static void test_lifetime_and_config(void)
{
    sx_config c = config();
    c.api_version = 99;
    CHECK(sx_create(&c) == NULL);
    c = config();
    c.mem_bytes = 1000;
    CHECK(sx_create(&c) == NULL);
    CHECK(sx_create(NULL) == NULL);
    c = config();
    sx_engine *e = sx_create(&c);
    CHECK(e != NULL);
    CHECK(sx_create(&c) == NULL); /* one per process */
    CHECK(sx_api_version() == SX_API_VERSION);

    /* no image: silent, and the fault says so */
    sx_render(e, out, 4800);
    float pk = 0;
    for (int i = 0; i < 9600; i++)
        pk = out[i] > pk ? out[i] : (-out[i] > pk ? -out[i] : pk);
    sx_snapshot s;
    CHECK(sx_snapshot_read(e, &s) == SX_OK && (s.faults & SX_FAULT_IMAGE_MISSING));
    CHECK(pk == 0.0f);

    /* a tampered image is refused and nothing runs (ASM-09) */
    sx_image bad = image(1);
    CHECK(sx_load_image(e, &bad) == SX_E_HASH);
    sx_render(e, out, 4800);
    CHECK(sx_snapshot_read(e, &s) == SX_OK && (s.faults & SX_FAULT_IMAGE_HASH) && s.halted);
    for (int i = 0; i < 9600; i++)
        CHECK(out[i] == 0.0f);
    sx_image good = image(0);
    CHECK(sx_load_image(e, &good) == SX_OK);
    sx_render(e, out, 4800);
    CHECK(sx_snapshot_read(e, &s) == SX_OK && s.faults == 0 && !s.halted);
    printf("after 0.1 s: dac0 %04X gates %04X cycles %llu pc %04X\n", s.dac_code[0], s.gates,
           (unsigned long long)s.cycles, s.pc);
    CHECK(s.dac_code[0] != 0 && s.gates == 0x8000 && s.cycles >= 400000u);
    char buf[64];
    CHECK(sx_disasm(e, 0x100, buf, sizeof buf) == 4 && strcmp(buf, "LHI R11,21") == 0);
    sx_destroy(e);
    e = sx_create(&c); /* after destroy, a new one may be made */
    CHECK(e != NULL);
    sx_destroy(e);
}

/* DSP-14: the same inputs give the same bytes, across engine lifetimes too. */
static void test_determinism(void)
{
    char a[65], b[65];
    sx_config c = config();
    for (int run = 0; run < 2; run++) {
        sx_engine *e = sx_create(&c);
        sx_image img = image(0);
        CHECK(e && sx_load_image(e, &img) == SX_OK);
        hash_render(e, 48000, run ? b : a);
        sx_destroy(e);
    }
    printf("render of the staircase program, 1 s: %s\n", a);
    CHECK(strcmp(a, b) == 0);
}

static void test_commands(void)
{
    sx_config c = config();
    sx_engine *e = sx_create(&c);
    sx_image img = image(0);
    sx_load_image(e, &img);
    sx_cmd mute = {SX_CMD_MUTE, 1, 0, 0.0f};
    int n = 0;
    while (sx_command(e, &mute) == SX_OK)
        n++;
    CHECK(n == 256); /* the ring's size; the next is -EAGAIN */
    CHECK(sx_command(e, &mute) == SX_E_AGAIN);
    sx_render(e, out, 128); /* drains it */
    CHECK(sx_command(e, &mute) == SX_OK);
    sx_render(e, out, 384); /* 8 ms after the command: silent */
    sx_render(e, out, 4800);
    for (int i = 0; i < 9600; i++)
        CHECK(out[i] == 0.0f);
    sx_snapshot s;
    sx_snapshot_read(e, &s);
    CHECK(s.muted == 1);

    sx_cmd cmds[] = {{SX_CMD_MUTE, 0, 0, 0.0f},
                     {SX_CMD_SPEED, SX_SPEED_SLOW2, 0, 0.0f},
                     {SX_CMD_HALT, 0, 0, 0.0f}};
    for (int i = 0; i < 3; i++)
        CHECK(sx_command(e, &cmds[i]) == SX_OK);
    sx_render(e, out, 128);
    sx_snapshot_read(e, &s);
    CHECK(s.speed == SX_SPEED_SLOW2 && s.halted == 1 && s.muted == 0);
    uint64_t cyc = s.cycles;
    sx_render(e, out, 4800);
    sx_snapshot_read(e, &s);
    CHECK(s.cycles == cyc); /* halted: the computer stops, the synth keeps sounding */
    sx_cmd home = {SX_CMD_RESET_HOME, 0, 0, 0.0f}, run = {SX_CMD_SPEED, SX_SPEED_RUN, 0, 0.0f};
    sx_command(e, &home);
    sx_command(e, &run);
    sx_render(e, out, 480); /* HOME waits for the 5 ms mute ramp, then resets at a period start */
    sx_render(e, out, 4800);
    sx_snapshot_read(e, &s);
    CHECK(!s.halted && s.cycles >= 400000u && s.cycles < 400200u); /* time restarted at HOME */
    sx_cmd sr = {SX_CMD_SR_SET, 0x1234, 0, 0.0f};
    sx_command(e, &sr);
    sx_render(e, out, 128);
    sx_snapshot_read(e, &s);
    CHECK(s.sr == 0x1234);
    sx_destroy(e);
}

/* DSP-15/16: the seqlock. dac_code[0] and dac_volts[0], frames and seq are written together, so
 * a torn copy would show them disagreeing. */
static sx_engine *stress_e;
static atomic_int stop;

static void *writer(void *arg)
{
    (void)arg;
    static float buf[256];
    while (!atomic_load(&stop))
        sx_render(stress_e, buf, 128);
    return NULL;
}

static void test_snapshot_stress(void)
{
    sx_config c = config();
    stress_e = sx_create(&c);
    sx_image img = image(0);
    sx_load_image(stress_e, &img);
    pthread_t t;
    atomic_store(&stop, 0);
    CHECK(pthread_create(&t, NULL, writer, NULL) == 0);
    int reads = 0, torn = 0;
    uint64_t last = 0;
    struct timespec ms = {0, 1000000};
    for (int i = 0; i < 1500; i++) { /* 1.5 s at 1 kHz */
        sx_snapshot s;
        if (sx_snapshot_read(stress_e, &s) != SX_OK)
            continue;
        reads++;
        float v = (float)(s.dac_code[0] >> 4) * 10.24f / 4096.0f;
        if (s.frames != s.seq * 128u || s.dac_volts[0] != v || s.frames < last)
            torn++;
        last = s.frames;
        nanosleep(&ms, NULL);
    }
    atomic_store(&stop, 1);
    pthread_join(t, NULL);
    printf("snapshot stress: %d reads at about 1 kHz, %d torn, writer reached frame %llu\n", reads,
           torn, (unsigned long long)last);
    CHECK(reads > 1000 && torn == 0 && last > 48000);
    sx_destroy(stress_e);
}

/* DSP-20 (test profile only, VS-27): an injected NaN or Inf is caught before the output. */
static void test_injection(void)
{
#if defined(SX_TEST_HOOKS)
    sx_config c = config();
    sx_engine *e = sx_create(&c);
    sx_image img = image(0);
    sx_load_image(e, &img);
    sx_render(e, out, 9600);
    for (uint32_t what = SX_INJECT_NAN; what <= SX_INJECT_INF; what++) {
        sx_test_inject(e, what); /* once: caught, the chain reset, not a fault */
        sx_render(e, out, 4800);
        int finite = 1;
        for (int i = 0; i < 9600; i++)
            finite &= out[i] - out[i] == 0.0f;
        sx_snapshot s;
        sx_snapshot_read(e, &s);
        CHECK(finite && !(s.faults & SX_FAULT_DSP));
        sx_render(e, out, 48000); /* a second apart */
    }
    for (int k = 0; k < 3; k++) { /* three within a second: dsp_fault, muted */
        sx_test_inject(e, SX_INJECT_NAN);
        sx_render(e, out, 1280);
    }
    sx_render(e, out, 384); /* 8 ms */
    sx_render(e, out, 4800);
    int silent = 1;
    for (int i = 0; i < 9600; i++)
        silent &= out[i] == 0.0f;
    sx_snapshot s;
    sx_snapshot_read(e, &s);
    CHECK((s.faults & SX_FAULT_DSP) && silent);
    CHECK(strcmp(sx_profile(), "test") == 0);
    sx_destroy(e);
#else
    CHECK(strcmp(sx_profile(), "production") == 0);
#endif
}

int main(void)
{
    test_lifetime_and_config();
    test_determinism();
    test_commands();
    test_snapshot_stress();
    test_injection();
    printf("test_engine: %d checks, %d failures\n", checks, failures);
    return failures != 0;
}

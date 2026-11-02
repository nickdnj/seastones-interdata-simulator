/* test_audio1.c: AUDIO-1 in the engine (VS-19; PRG-06). Keys make no sound unless the program
 * turns them into D/A and gate writes: with every key held,
 *   - a program that reads the keyboard but writes nothing is silent (and is not a fault),
 *   - an engine with no program is silent,
 *   - the mono program halted from the panel stays silent when keys arrive.
 * There is no other way into the DSP (ARCHITECTURE 12.1): sound needs a write.
 */
#include "seastones.h"
#include "sha256.h"

#include <stdio.h>

static int failures, checks;

#define CHECK(x)                                                                                   \
    do {                                                                                           \
        checks++;                                                                                  \
        if (!(x)) {                                                                                \
            failures++;                                                                            \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #x);                  \
        }                                                                                          \
    } while (0)

/* X'100' LHI R10,KEYS / X'104' RDR R10,R4 / B X'104': reads, never writes */
static const uint16_t ignore[] = {0xC8A0, 0x0020, 0x9BA4, 0x4300, 0x0104};
/* the same, but it raises gate 0 and plays C4 when row 0 is non-zero (to show keys can sound) */
static const uint16_t plays[] = {0xC8A0,
                                 0x0020,
                                 0xC8B0,
                                 0x0021,
                                 0xC8C0,
                                 0x0022,
                                 0xC830,
                                 0x8000,
                                 0xC820,
                                 0x6400,
                                 /* X'114': */ 0x9BA4,
                                 0x0844,
                                 0x4330,
                                 0x0114,
                                 0x98B2,
                                 0x98C3,
                                 0x4300,
                                 0x0114};

static float out[2 * 128];

/* one voice on D/A 0 and gate line 0, as the control program writes them */
static const char latch_voice[] = "graph 1\nmodule osc vco\nmodule eg env\nmodule amp vca\n"
                                  "module o out\ncable dac.0 osc.pitch\ncable gate.0 eg.gate\n"
                                  "cable osc.saw amp.in\ncable eg.out amp.cv\ncable amp.out o.l\n";

static void latch_patch(sx_engine *e)
{
    char err[128];
    CHECK(sx_patch_load(e, latch_voice, sizeof latch_voice - 1u, err, sizeof err) == SX_OK);
}

static sx_engine *engine(const uint16_t *p, uint16_t n)
{
    sx_config c = {SX_API_VERSION, 48000, 32768, 250, 12, 10.24f, 0, 4096, 0, 0, 0};
    sx_engine *e = sx_create(&c);
    if (p) {
        sx_segment seg = {0x100, n, p};
        sx_image img = {&seg, 1, 0x100, 0, {0}};
        sx_sha256 h;
        sx_sha256_init(&h);
        uint8_t hd[4] = {0x01, 0x00, 0x00, (uint8_t)n};
        sx_sha256_update(&h, hd, 4);
        for (uint16_t i = 0; i < n; i++) {
            uint8_t w[2] = {(uint8_t)(p[i] >> 8), (uint8_t)p[i]};
            sx_sha256_update(&h, w, 2);
        }
        sx_sha256_final(&h, img.sha256);
        CHECK(sx_load_image(e, &img) == SX_OK);
    }
    return e;
}

static double peak_over(sx_engine *e, double seconds)
{
    double p = 0;
    for (long per = 0; per < (long)(seconds * 375.0); per++) {
        sx_render(e, out, 128);
        for (int i = 0; i < 256; i++)
            p = out[i] > p ? out[i] : (-out[i] > p ? -out[i] : p);
    }
    return p;
}

int main(void)
{
    const uint64_t all = (1ull << 37) - 1u;
    for (int src = SX_KEYS_MIDI; src < SX_KEYS_NSOURCES; src++) {
        sx_engine *e = engine(ignore, sizeof ignore / 2);
        sx_render(e, out, 128);
        sx_keys_set(e, (sx_key_source)src, all);
        double p = peak_over(e, 1.0);
        sx_snapshot s;
        sx_snapshot_read(e, &s);
        printf("source %d, program reads but never writes, 37 keys held: peak %g, faults %X, "
               "keys_seen row 0 %02X\n",
               src, p, s.faults, s.keys_seen[0]);
        CHECK(p == 0.0 && s.faults == 0 && s.keys_seen[0] == 0xFF);
        sx_destroy(e);
    }
    sx_engine *e = engine(NULL, 0);
    sx_keys_set(e, SX_KEYS_TOUCH, all);
    CHECK(peak_over(e, 0.5) == 0.0);
    sx_destroy(e);

    /* control: a program that does write makes the same keys sound... */
    e = engine(plays, sizeof plays / 2);
    latch_patch(e);
    sx_render(e, out, 128);
    sx_keys_set(e, SX_KEYS_MIDI, 1u);
    double loud = peak_over(e, 0.5);
    printf("control, a program that writes pitch and gate: peak %.3f\n", loud);
    CHECK(loud > 0.1);
    sx_destroy(e);
    /* ...but not while the computer is halted from the panel (PLAY-3) */
    e = engine(plays, sizeof plays / 2);
    sx_cmd halt = {SX_CMD_HALT, 0, 0, 0.0f};
    sx_command(e, &halt);
    latch_patch(e);
    sx_render(e, out, 128);
    sx_keys_set(e, SX_KEYS_MIDI, 1u);
    double halted = peak_over(e, 0.5);
    printf("halted, then a key: peak %g\n", halted);
    CHECK(halted == 0.0);
    sx_destroy(e);
    printf("test_audio1: %d checks, %d failures\n", checks, failures);
    return failures != 0;
}

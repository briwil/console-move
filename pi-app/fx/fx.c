/*
 * Console send effects: a reverb and a tape-style delay.
 *
 * The reverb is a port of the one in Mutable Instruments Elements (and Rings):
 * elements/dsp/fx/reverb.h and fx_engine.h, Copyright 2014 Emilie Gillet,
 * released under the MIT licence (see LICENSE-mutable.txt next to this file).
 * Same topology, coefficients and modulation. Changes: plain C, float storage
 * (the original packs samples into 16 bits; this keeps its clipping), and the
 * delay lengths are scaled from the module's 32 kHz to the tape's sample rate
 * so the room sounds the same size, and a ROOM setting shrinks every line (down
 * to an eighth), so it goes from Elements' big hall down to a small room
 * (Elements itself can only change how long the tail is, never the size).
 *
 * The delay is new: a stereo tape delay whose time glides (with a little
 * pitch bend, like tape) when you change it, with soft saturation and a
 * low-pass filter in the feedback so each repeat gets darker.
 *
 * Built by setup.sh (or by the app on first run):
 *   gcc -O2 -shared -fPIC -o libconsolefx.so fx.c -lm
 */
#include <math.h>
#include <stdlib.h>
#include <string.h>
#if defined(__aarch64__)
#include <stdint.h>
#elif defined(__SSE__)
#include <xmmintrin.h>
#endif

/* Round tiny numbers to zero on the calling thread. As a reverb tail fades the numbers go "denormal" and the
   processor handles them many times slower (the effects run on silence all the time). Call once from the
   audio thread; it then covers every C library that thread calls. */
void console_flush_denormals(void) {
#if defined(__aarch64__)
    uint64_t fpcr;
    __asm__ volatile("mrs %0, fpcr" : "=r"(fpcr));
    fpcr |= (1ull << 24);                       /* FZ */
    __asm__ volatile("msr fpcr, %0" : : "r"(fpcr));
#elif defined(__SSE__)
    _mm_setcsr(_mm_getcsr() | 0x8040);          /* FTZ and DAZ */
#endif
}

/* ------------------------------------------------------------------ reverb */

#define RV_SIZE 32768                      /* power of two, like the original */
#define RV_MASK (RV_SIZE - 1)
#define RV_LINES 10

static const int RV_LENGTHS[RV_LINES] = {  /* at 32 kHz, from Elements */
    150, 214, 319, 527, 2182, 2690, 4501, 2525, 2197, 6312
};
enum { AP1, AP2, AP3, AP4, DAP1A, DAP1B, DEL1, DAP2A, DAP2B, DEL2 };

typedef struct {
    float buf[RV_SIZE];
    int base[RV_LINES], len[RV_LINES];
    int write_ptr;
    float scale;                           /* sample rate / 32000 */
    float room;                            /* 0.125..1: how much of each line is used (the room's size) */
    /* the two slow LFOs: cosine, 0..1, stepped every 32 samples as in the original */
    float lfo_phase[2], lfo_inc[2], lfo_value[2];
    float amount, input_gain, reverb_time, diffusion, lp;
    float lp_decay_1, lp_decay_2;
} Reverb;

typedef struct {                           /* fx_engine.h's Context */
    Reverb *r;
    float acc, prev;
} Ctx;

static inline float clip1(float x) {      /* what packing into 16 bits does */
    return x > 0.99997f ? 0.99997f : (x < -1.0f ? -1.0f : x);
}

static inline float rv_at(Reverb *r, int line, int offset) {
    if (offset == -1) offset = r->len[line] - 1;             /* TAIL */
    return r->buf[(r->write_ptr + r->base[line] + offset) & RV_MASK];
}

static inline void c_read(Ctx *c, int line, int offset, float scale) {
    float v = rv_at(c->r, line, offset);
    c->prev = v;
    c->acc += v * scale;
}

static inline void c_write(Ctx *c, int line, int offset, float scale) {
    Reverb *r = c->r;
    if (offset == -1) offset = r->len[line] - 1;
    r->buf[(r->write_ptr + r->base[line] + offset) & RV_MASK] = clip1(c->acc);
    c->acc *= scale;
}

static inline void c_write_allpass(Ctx *c, int line, float scale) {
    c_write(c, line, 0, scale);
    c->acc += c->prev;
}

static inline void c_lp(Ctx *c, float *state, float coef) {
    *state += coef * (c->acc - *state);
    c->acc = *state;
}

static inline void c_interpolate(Ctx *c, int line, float offset, int lfo, float amplitude, float scale) {
    Reverb *r = c->r;
    offset += amplitude * r->lfo_value[lfo];
    int i = (int)offset;
    float f = offset - (float)i;
    float a = r->buf[(r->write_ptr + i + r->base[line]) & RV_MASK];
    float b = r->buf[(r->write_ptr + i + r->base[line] + 1) & RV_MASK];
    float x = a + (b - a) * f;
    c->prev = x;
    c->acc += x * scale;
}

void rev_clear(Reverb *r) {
    memset(r->buf, 0, sizeof(r->buf));
    r->lp_decay_1 = r->lp_decay_2 = 0.0f;
}

Reverb *rev_new(float sample_rate) {
    Reverb *r = calloc(1, sizeof(Reverb));
    if (!r) return NULL;
    r->scale = sample_rate / 32000.0f;
    int base = 0;
    for (int i = 0; i < RV_LINES; i++) {
        r->len[i] = (int)(RV_LENGTHS[i] * r->scale + 0.5f);
        r->base[i] = base;
        base += r->len[i] + 1;
    }
    /* SetLFOFrequency(LFO_1, 0.5 / 32000) and (LFO_2, 0.3 / 32000): 0.5 Hz and 0.3 Hz */
    r->lfo_inc[0] = 2.0f * (float)M_PI * 0.5f / sample_rate * 32.0f;
    r->lfo_inc[1] = 2.0f * (float)M_PI * 0.3f / sample_rate * 32.0f;
    r->lfo_value[0] = r->lfo_value[1] = 0.5f;
    r->amount = 1.0f;                      /* wet only: the app mixes it in */
    r->input_gain = 0.2f;
    r->reverb_time = 0.5f;
    r->diffusion = 0.625f;
    r->lp = 0.7f;
    r->room = 1.0f;
    return r;
}

/* The room's size: every line (and the modulation) shrinks together. Lines keep their place in the
 * buffer, so changing it only shortens how far back each one reads. */
void rev_room(Reverb *r, float room) {
    if (room < 0.125f) room = 0.125f;
    if (room > 1.0f) room = 1.0f;
    r->room = room;
    for (int i = 0; i < RV_LINES; i++) {
        int n = (int)(RV_LENGTHS[i] * r->scale * room + 0.5f);
        r->len[i] = n < 4 ? 4 : n;
    }
}

void rev_free(Reverb *r) { free(r); }

void rev_params(Reverb *r, float reverb_time, float lp, float diffusion, float input_gain) {
    r->reverb_time = reverb_time;
    r->lp = lp;
    r->diffusion = diffusion;
    r->input_gain = input_gain;
}

/* Wet output only. in and out may not overlap. */
void rev_process(Reverb *r, const float *in_l, const float *in_r, float *out_l, float *out_r, int n) {
    const float kap = r->diffusion, klp = r->lp, krt = r->reverb_time, gain = r->input_gain;
    const float s = r->scale * r->room;
    float lp_1 = r->lp_decay_1, lp_2 = r->lp_decay_2;
    Ctx c;
    c.r = r;
    for (int k = 0; k < n; k++) {
        float wet, apout;
        /* engine_.Start(&c) */
        if (--r->write_ptr < 0) r->write_ptr += RV_SIZE;
        c.acc = 0.0f;
        c.prev = 0.0f;
        if ((r->write_ptr & 31) == 0) {
            for (int i = 0; i < 2; i++) {
                r->lfo_phase[i] += r->lfo_inc[i];
                if (r->lfo_phase[i] > 2.0f * (float)M_PI) r->lfo_phase[i] -= 2.0f * (float)M_PI;
                r->lfo_value[i] = 0.5f + 0.5f * cosf(r->lfo_phase[i]);
            }
        }

        /* Smear AP1 inside the loop. */
        c_interpolate(&c, AP1, 10.0f * s, 0, 80.0f * s, 1.0f);
        c_write(&c, AP1, (int)(100.0f * s), 0.0f);

        c.acc += (in_l[k] + in_r[k]) * gain;

        /* Diffuse through 4 allpasses. */
        c_read(&c, AP1, -1, kap); c_write_allpass(&c, AP1, -kap);
        c_read(&c, AP2, -1, kap); c_write_allpass(&c, AP2, -kap);
        c_read(&c, AP3, -1, kap); c_write_allpass(&c, AP3, -kap);
        c_read(&c, AP4, -1, kap); c_write_allpass(&c, AP4, -kap);
        apout = c.acc;

        /* Main reverb loop. */
        c.acc = apout;
        c_interpolate(&c, DEL2, 6211.0f * s, 1, 100.0f * s, krt);
        c_lp(&c, &lp_1, klp);
        c_read(&c, DAP1A, -1, -kap); c_write_allpass(&c, DAP1A, kap);
        c_read(&c, DAP1B, -1, kap); c_write_allpass(&c, DAP1B, -kap);
        c_write(&c, DEL1, 0, 2.0f);
        wet = c.acc;
        c.acc = 0.0f;
        out_l[k] = wet;

        c.acc = apout;
        c_read(&c, DEL1, -1, krt);
        c_lp(&c, &lp_2, klp);
        c_read(&c, DAP2A, -1, kap); c_write_allpass(&c, DAP2A, -kap);
        c_read(&c, DAP2B, -1, -kap); c_write_allpass(&c, DAP2B, kap);
        c_write(&c, DEL2, 0, 2.0f);
        wet = c.acc;
        c.acc = 0.0f;
        out_r[k] = wet;
    }
    r->lp_decay_1 = lp_1;
    r->lp_decay_2 = lp_2;
}

/* ------------------------------------------------------------------ tape delay */

typedef struct {
    float *buf[2];
    int size, mask, w;
    float sample_rate;
    float time, target;                    /* in samples; time glides towards target */
    float glide;
    float feedback, tone;
    float lp[2], hp[2];
    float hp_coef;
} Delay;

Delay *dly_new(float sample_rate, float max_seconds) {
    Delay *d = calloc(1, sizeof(Delay));
    if (!d) return NULL;
    int size = 1;
    while (size < (int)(sample_rate * max_seconds) + 4) size <<= 1;
    d->size = size;
    d->mask = size - 1;
    for (int i = 0; i < 2; i++) {
        d->buf[i] = calloc(size, sizeof(float));
        if (!d->buf[i]) { free(d->buf[0]); free(d); return NULL; }
    }
    d->sample_rate = sample_rate;
    d->time = d->target = sample_rate * 0.375f;
    d->glide = 1.0f / (0.1f * sample_rate);        /* glides to a new time over about 0.1 s */
    d->feedback = 0.4f;
    d->tone = 0.6f;
    d->hp_coef = 2.0f * (float)M_PI * 60.0f / sample_rate;   /* keeps the low end from piling up */
    return d;
}

void dly_free(Delay *d) {
    if (!d) return;
    free(d->buf[0]);
    free(d->buf[1]);
    free(d);
}

void dly_clear(Delay *d) {
    memset(d->buf[0], 0, d->size * sizeof(float));
    memset(d->buf[1], 0, d->size * sizeof(float));
    d->lp[0] = d->lp[1] = d->hp[0] = d->hp[1] = 0.0f;
}

void dly_params(Delay *d, float time_samples, float feedback, float tone) {
    float max = (float)(d->size - 4);
    d->target = time_samples < 1.0f ? 1.0f : (time_samples > max ? max : time_samples);
    d->feedback = feedback;
    d->tone = tone;
}

static inline float soft(float x) {       /* gentle tape-like saturation */
    return x / (1.0f + fabsf(x) * 0.25f);
}

/* Wet output only. */
void dly_process(Delay *d, const float *in_l, const float *in_r, float *out_l, float *out_r, int n) {
    /* tone 0..1 -> low-pass in the feedback from about 1.2 kHz to 12 kHz */
    float cutoff = 1200.0f * powf(10.0f, d->tone);
    float lpc = 1.0f - expf(-2.0f * (float)M_PI * cutoff / d->sample_rate);
    const float *in[2] = {in_l, in_r};
    float *out[2] = {out_l, out_r};
    for (int k = 0; k < n; k++) {
        d->time += (d->target - d->time) * d->glide;
        float pos = (float)d->w - d->time;
        while (pos < 0.0f) pos += (float)d->size;
        int i = (int)pos;
        float f = pos - (float)i;
        for (int c = 0; c < 2; c++) {
            float a = d->buf[c][i & d->mask];
            float b = d->buf[c][(i + 1) & d->mask];
            float y = a + (b - a) * f;
            out[c][k] = y;
            d->lp[c] += lpc * (y - d->lp[c]);
            float x = d->lp[c];
            d->hp[c] += d->hp_coef * (x - d->hp[c]);
            x -= d->hp[c];
            d->buf[c][d->w] = soft(in[c][k] + x * d->feedback);
        }
        d->w = (d->w + 1) & d->mask;
    }
}

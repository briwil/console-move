/* The SAMPLER's sound engine: 16 sample players, one per drum, each its own output channel (Console's sound core
 * calls sw_render, like the other drum machines' libraries in drums/schwung/glue_common.h). Samples are loaded by
 * Python (sw_load); settings are sw_set("<name><drum>", value) with the names below. */
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#define VOICES 16
typedef struct { float *x; int n; int on; double pos, rate; float gain; int age, fade; } voice_t;

static voice_t V[VOICES];
static int level[VOICES], pitch[VOICES], start[VOICES], decay[VOICES];
static float RATE = 44100.f;
static int inited = 0;

static int parse(const char *key, char *name, int cap)
{
    int i = 0;
    while (key[i] && !(key[i] >= '0' && key[i] <= '9') && i < cap - 1) { name[i] = key[i]; i++; }
    name[i] = 0;
    return key[i] ? atoi(key + i) : -1;
}

int sw_init(float sr)
{
    if (!inited) {
        inited = 1;
        RATE = sr;
        memset(V, 0, sizeof V);
        for (int i = 0; i < VOICES; i++) { level[i] = 100; pitch[i] = 64; start[i] = 0; decay[i] = 127; }
    }
    return VOICES;
}

int sw_voices(void) { return VOICES; }

void sw_set(const char *key, int value)
{
    char name[16];
    int v = parse(key, name, sizeof name) - 1;       /* "level3" is the third drum */
    if (v < 0 || v >= VOICES) return;
    if (value < 0) value = 0;
    if (value > 127) value = 127;
    if (!strcmp(name, "level")) level[v] = value;
    else if (!strcmp(name, "pitch")) pitch[v] = value;
    else if (!strcmp(name, "start")) start[v] = value;
    else if (!strcmp(name, "decay")) decay[v] = value;
}

int sw_get(const char *key)
{
    char name[16];
    int v = parse(key, name, sizeof name) - 1;
    if (v < 0 || v >= VOICES) return -1;
    if (!strcmp(name, "level")) return level[v];
    if (!strcmp(name, "pitch")) return pitch[v];
    if (!strcmp(name, "start")) return start[v];
    if (!strcmp(name, "decay")) return decay[v];
    return -1;
}

/* the sample for a drum (mono floats at the engine's rate); n = 0 empties it */
void sw_load(int voice, const float *data, int n)
{
    if (voice < 0 || voice >= VOICES) return;
    voice_t *p = &V[voice];
    float *old = p->x;
    float *copy = 0;
    if (data && n > 1) {
        copy = (float *)malloc(sizeof(float) * n);
        if (copy) memcpy(copy, data, sizeof(float) * n);
    }
    p->on = 0;
    p->x = copy;
    p->n = copy ? n : 0;
    if (old) free(old);
}

void sw_trigger(int voice, int velocity)
{
    if (voice < 0 || voice >= VOICES || velocity <= 0) return;
    voice_t *p = &V[voice];
    if (!p->x || p->n < 2) return;
    if (velocity > 127) velocity = 127;
    p->rate = pow(2.0, ((pitch[voice] - 64) / 2.0) / 12.0);
    p->pos = (double)p->n * start[voice] / 127.0 * 0.95;
    p->gain = (level[voice] / 127.0f) * (velocity / 127.0f);
    p->age = 0;
    {
        double d = decay[voice] / 127.0;
        p->fade = decay[voice] >= 127 ? 0 : (int)(RATE * (0.03 + d * d * 2.5));
    }
    p->on = 1;
}

/* out: frames x VOICES floats, interleaved (a drum a channel) */
void sw_render(float *out, int frames)
{
    memset(out, 0, sizeof(float) * frames * VOICES);
    for (int v = 0; v < VOICES; v++) {
        voice_t *p = &V[v];
        if (!p->on) continue;
        for (int i = 0; i < frames; i++) {
            int k = (int)p->pos;
            if (k >= p->n - 1) { p->on = 0; break; }
            float fr = (float)(p->pos - k);
            float s = p->x[k] * (1.f - fr) + p->x[k + 1] * fr;
            float g = p->gain;
            if (p->age < 64) g *= p->age / 64.f;
            if (p->fade) {
                if (p->age >= p->fade) { p->on = 0; break; }
                g *= 1.f - (float)p->age / p->fade;
            }
            out[i * VOICES + v] += s * g;
            p->pos += p->rate;
            p->age++;
        }
    }
}

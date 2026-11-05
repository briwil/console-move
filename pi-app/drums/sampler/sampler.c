/* The SAMPLER's sound engine: 16 sample players, one per drum, each its own output channel (Console's sound core
 * calls sw_render, like the other drum machines' libraries in drums/schwung/glue_common.h). Samples are loaded by
 * Python (sw_load); settings are sw_set("<name><drum>", value) with the names below.
 *
 * Each drum has two samples (sw_load(drum, ...) and sw_load(16 + drum, ...)), played together from the same hit
 * with the same pitch, start and decay, and BLEND (0-127) between them: 0 only the first, 64 both at full
 * volume, 127 only the second. BLEND is read as the sound plays, so an LFO on it morphs a ringing sample. */
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#define VOICES 16
typedef struct { float *x; int n; int on; double pos; } player_t;      /* one sample of a drum, playing */
typedef struct { player_t p[2]; double rate; float gain; int age, fade; float mixed[2]; } voice_t;   /* mixed: last block's BLEND gains */

static voice_t V[VOICES];
static int level[VOICES], pitch[VOICES], start[VOICES], decay[VOICES], blend[VOICES];
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
        for (int i = 0; i < VOICES; i++) { level[i] = 100; pitch[i] = 64; start[i] = 0; decay[i] = 127; blend[i] = 0; }
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
    else if (!strcmp(name, "blend")) blend[v] = value;
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
    if (!strcmp(name, "blend")) return blend[v];
    return -1;
}

/* the sample for a drum (mono floats at the engine's rate): voice 0-15 its first sample, 16-31 its second;
   n = 0 empties it */
void sw_load(int voice, const float *data, int n)
{
    int which = voice >= VOICES;
    if (which) voice -= VOICES;
    if (voice < 0 || voice >= VOICES) return;
    player_t *p = &V[voice].p[which];
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
    int any = 0;
    for (int w = 0; w < 2; w++) {
        player_t *q = &p->p[w];
        q->on = q->x && q->n >= 2;
        if (q->on) { q->pos = (double)q->n * start[voice] / 127.0 * 0.95; any = 1; }
    }
    if (!any) return;
    if (velocity > 127) velocity = 127;
    p->rate = pow(2.0, ((pitch[voice] - 64) / 2.0) / 12.0);
    p->gain = (level[voice] / 127.0f) * (velocity / 127.0f);
    p->age = 0;
    p->mixed[0] = blend[voice] <= 64 ? 1.f : (127 - blend[voice]) / 63.f;     /* (no glide in from an old BLEND) */
    p->mixed[1] = blend[voice] >= 64 ? 1.f : blend[voice] / 64.f;
    {
        double d = decay[voice] / 127.0;
        p->fade = decay[voice] >= 127 ? 0 : (int)(RATE * (0.03 + d * d * 2.5));
    }
}

/* out: frames x VOICES floats, interleaved (a drum a channel) */
void sw_render(float *out, int frames)
{
    memset(out, 0, sizeof(float) * frames * VOICES);
    for (int v = 0; v < VOICES; v++) {
        voice_t *p = &V[v];
        if (!p->p[0].on && !p->p[1].on) continue;
        /* BLEND: the first sample full up to the middle then fading out, the second fading in up to the middle */
        int b = blend[v];
        float mix[2] = { b <= 64 ? 1.f : (127 - b) / 63.f, b >= 64 ? 1.f : b / 64.f };
        int age0 = p->age;
        for (int w = 0; w < 2; w++) {
            player_t *q = &p->p[w];
            if (!q->on) continue;
            int age = age0;
            for (int i = 0; i < frames; i++) {
                int k = (int)q->pos;
                if (k >= q->n - 1) { q->on = 0; break; }
                float fr = (float)(q->pos - k);
                float s = q->x[k] * (1.f - fr) + q->x[k + 1] * fr;
                float g = p->gain * (p->mixed[w] + (mix[w] - p->mixed[w]) * i / frames);   /* glides: no clicks */
                if (age < 64) g *= age / 64.f;
                if (p->fade) {
                    if (age >= p->fade) { q->on = 0; break; }
                    g *= 1.f - (float)age / p->fade;
                }
                out[i * VOICES + v] += s * g;
                q->pos += p->rate;
                age++;
            }
        }
        p->age = age0 + frames;
        p->mixed[0] = mix[0];
        p->mixed[1] = mix[1];
    }
}

/* Console's sound core: a JACK client whose process callback makes the sound, 128 frames at a time.
 *
 * No Python runs in the audio path. Python (core.py) sets it up and talks to it through:
 *   - sources: the instruments. Each is an "engine" (a library with render(float *out, n) writing n frames of
 *     `voices` interleaved channels, and trigger(voice, velocity)) or a Schwung "module" instance (rendered by
 *     the host's sh_render(inst, out, n) as stereo, played with sh_midi(inst, b0, b1, b2)). Python loads the
 *     libraries and hands over the function addresses.
 *   - an event queue (Python -> core): hits, MIDI and calls into a library (parameter changes), each with the
 *     frame it should happen at, so they land on the exact sample.
 *   - the Move's controls (core -> Python): MIDI from the pads, knobs and buttons, queued for Python to read.
 *   - lights and the screen (Python -> core): MIDI out and display frames, sent in the next cycle.
 *   - mixing settings (pans, sends, gains) in plain memory Python can write any time.
 *
 * libjack is opened at run time (dlopen), from the path Python gives: on the Move that's RNBO's own copy,
 * which has to match the JACK server it starts.
 */
#include <dlfcn.h>
#include <math.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(__SSE__)
#include <xmmintrin.h>
#endif

/* ------------------------------------------------------------------ JACK, opened at run time */

typedef uint32_t jack_nframes_t;
typedef struct { jack_nframes_t time; size_t size; unsigned char *buffer; } jack_midi_event_t;
typedef int (*JackProcess)(jack_nframes_t, void *);

static struct {
    void *(*client_open)(const char *, int, int *, ...);
    int (*client_close)(void *);
    int (*activate)(void *);
    int (*deactivate)(void *);
    void *(*port_register)(void *, const char *, const char *, unsigned long, unsigned long);
    void *(*port_get_buffer)(void *, jack_nframes_t);
    int (*set_process_callback)(void *, JackProcess, void *);
    int (*connect)(void *, const char *, const char *);
    jack_nframes_t (*get_sample_rate)(void *);
    jack_nframes_t (*get_buffer_size)(void *);
    uint32_t (*midi_get_event_count)(void *);
    int (*midi_event_get)(jack_midi_event_t *, void *, uint32_t);
    void (*midi_clear_buffer)(void *);
    int (*midi_event_write)(void *, jack_nframes_t, const unsigned char *, size_t);
    float (*cpu_load)(void *);
} J;

static const char *AUDIO = "32 bit float mono audio", *MIDI = "8 bit raw midi";
enum { IS_INPUT = 1, IS_OUTPUT = 2, NO_START_SERVER = 1 };

/* ------------------------------------------------------------------ sources */

#define MAX_SOURCES 24
#define MAX_VOICES 16
#define MAX_BLOCK 4096
#define TAIL (8 * 44100)                      /* a source sleeps this long after its last note or hit */

enum { ENGINE = 1, MODULE = 2 };

typedef struct {
    int kind, voices;                         /* 0 kind: slot unused */
    void (*render)(float *, int);             /* ENGINE */
    void (*trigger)(int, int);
    void *inst;                               /* MODULE */
    void (*sh_render)(void *, float *, int);
    void (*sh_midi)(void *, int, int, int);
    float pan[MAX_VOICES][2];                 /* each voice's left / right gain (Python sets them) */
    float rev[MAX_VOICES], dly[MAX_VOICES];   /* each voice's sends to the reverb and delay */
    float gain;                               /* how loud it's heard (0 mutes it) */
    int on;                                   /* rendered at all (Python turns off what isn't needed) */
    int64_t awake;                            /* frames left before it sleeps: renders only while > 0 */
    int held;                                 /* notes held down (a module stays awake while any are) */
    int silent;                               /* its buffer is all zeros (asleep) */
    float buf[MAX_BLOCK * MAX_VOICES];        /* this cycle's sound, interleaved */
} Source;

static Source sources[MAX_SOURCES];

/* ------------------------------------------------------------------ queues */

enum { EV_TRIGGER = 1, EV_MIDI = 2, EV_CALL = 3 };

typedef struct {
    uint64_t frame;                           /* when (core frames); 0 = as soon as possible */
    int32_t kind, src;
    intptr_t a, b, c;
    void *fn;                                 /* EV_CALL: fn(a, b, c) */
} Event;

#define EVENTS 4096                           /* power of two */
static Event events[EVENTS];
static atomic_uint_fast64_t ev_head, ev_tail;  /* Python writes at head, the core reads at tail */

#define MIDI_IN 1024
static struct { uint64_t frame; uint8_t b[4]; } midi_in[MIDI_IN];
static atomic_uint_fast64_t mi_head, mi_tail;  /* the core writes, Python reads */

#define MIDI_OUT 1024
static uint8_t midi_out[MIDI_OUT][4];          /* [0] = length */
static atomic_uint_fast64_t mo_head, mo_tail;  /* Python writes, the core sends */

#define DISPLAY_BYTES 1032
static uint8_t display[2][DISPLAY_BYTES];
static atomic_int display_ready = -1;          /* which buffer has a new frame to send, or -1 */
static int display_next;

/* ------------------------------------------------------------------ the rest of the state */

static void *client, *out_l, *out_r, *in_l, *in_r, *ctl_in, *ctl_out, *disp_out;
static atomic_uint_fast64_t now_frame;         /* frames played since the core started */
static atomic_uint cycles;
static jack_nframes_t rate, block;

static void (*rev_process)(void *, const float *, const float *, float *, float *, int);
static void (*dly_process)(void *, const float *, const float *, float *, float *, int);
static void *reverb, *delay;
static float rev_level = 0.0f, dly_level = 0.0f;
static float master = 1.0f, mix_gain = 0.6f;
static float send_l[2][MAX_BLOCK], fx_out[4][MAX_BLOCK], mix[2][MAX_BLOCK];

static void flush_denormals(void) {
#if defined(__aarch64__)
    uint64_t fpcr;
    __asm__ volatile("mrs %0, fpcr" : "=r"(fpcr));
    fpcr |= (1ull << 24);
    __asm__ volatile("msr fpcr, %0" : : "r"(fpcr));
#elif defined(__SSE__)
    _mm_setcsr(_mm_getcsr() | 0x8040);
#endif
}

/* ------------------------------------------------------------------ the callback */

static void render_source(Source *s, int from, int to) {
    if (to <= from || (s->awake <= 0 && s->held <= 0)) return;
    float *out = s->buf + from * s->voices;
    if (s->kind == ENGINE) s->render(out, to - from);
    else s->sh_render(s->inst, out, to - from);
}

static void apply(const Event *e) {
    Source *s = (e->src >= 0 && e->src < MAX_SOURCES) ? &sources[e->src] : NULL;
    switch (e->kind) {
    case EV_TRIGGER:
        if (s && s->kind == ENGINE) { s->awake = TAIL; s->trigger((int)e->a, (int)e->b); }
        break;
    case EV_MIDI:
        if (s && s->kind == MODULE) {
            int st = (int)e->a & 0xF0;
            if (st == 0x90 && e->c > 0) s->held++;
            else if ((st == 0x80 || st == 0x90) && s->held > 0) s->held--;
            else if (st == 0xB0 && (e->b == 123 || e->b == 120)) s->held = 0;     /* all notes off */
            s->awake = TAIL;
            s->sh_midi(s->inst, (int)e->a, (int)e->b, (int)e->c);
        }
        break;
    case EV_CALL: if (e->fn) ((void (*)(intptr_t, intptr_t, intptr_t))e->fn)(e->a, e->b, e->c); break;
    }
}

static int process(jack_nframes_t n, void *arg) {
    (void)arg;
    static int fz;
    if (!fz) { flush_denormals(); fz = 1; }
    if (n > MAX_BLOCK) n = MAX_BLOCK;
    uint64_t t0 = atomic_load(&now_frame), t1 = t0 + n;

    /* the Move's controls -> Python */
    void *cin = J.port_get_buffer(ctl_in, n);
    uint32_t k = J.midi_get_event_count(cin);
    for (uint32_t i = 0; i < k; i++) {
        jack_midi_event_t ev;
        if (J.midi_event_get(&ev, cin, i) || ev.size < 1 || ev.size > 3) continue;
        uint64_t h = atomic_load(&mi_head);
        if (h - atomic_load(&mi_tail) >= MIDI_IN) break;          /* Python isn't reading: drop */
        midi_in[h % MIDI_IN].frame = t0 + ev.time;
        memset(midi_in[h % MIDI_IN].b, 0, 4);
        memcpy(midi_in[h % MIDI_IN].b, ev.buffer, ev.size);
        atomic_store(&mi_head, h + 1);
    }

    /* events due in this cycle, in order, each at its exact frame: every source renders up to it first */
    int pos = 0;
    for (;;) {
        uint64_t tail = atomic_load(&ev_tail);
        if (tail == atomic_load(&ev_head)) break;
        Event *e = &events[tail % EVENTS];
        if (e->frame >= t1) break;                                  /* a later cycle's */
        int at = e->frame <= t0 ? 0 : (int)(e->frame - t0);
        if (at > pos) {
            for (int s = 0; s < MAX_SOURCES; s++)
                if (sources[s].kind && sources[s].on) render_source(&sources[s], pos, at);
            pos = at;
        }
        apply(e);
        atomic_store(&ev_tail, tail + 1);
    }
    for (int s = 0; s < MAX_SOURCES; s++)
        if (sources[s].kind && sources[s].on) render_source(&sources[s], pos, n);
    for (int s = 0; s < MAX_SOURCES; s++) {
        Source *src = &sources[s];
        if (!src->kind || !src->on) continue;
        if (src->awake <= 0 && src->held <= 0 && !src->silent) {
            memset(src->buf, 0, sizeof(float) * n * src->voices);   /* asleep: nothing to mix */
            src->silent = 1;
        }
        if (src->awake > 0 || src->held > 0) src->silent = 0;
        if (src->awake > 0) src->awake -= n;
    }

    /* mix: each voice panned, its sends to the effects */
    memset(mix, 0, sizeof(float) * 2 * MAX_BLOCK);
    memset(send_l, 0, sizeof(float) * 2 * MAX_BLOCK);
    static float send_d[2][MAX_BLOCK];
    memset(send_d, 0, sizeof(float) * 2 * MAX_BLOCK);
    for (int s = 0; s < MAX_SOURCES; s++) {
        Source *src = &sources[s];
        if (!src->kind || !src->on || src->gain <= 0.0f || src->silent) continue;
        int V = src->voices;
        for (int v = 0; v < V; v++) {
            float gl = src->pan[v][0] * src->gain, gr = src->pan[v][1] * src->gain;
            float rs = src->rev[v], ds = src->dly[v];
            const float *x = src->buf + v;
            for (jack_nframes_t i = 0; i < n; i++) {
                float a = x[i * V];
                float l = a * gl, r = a * gr;
                mix[0][i] += l; mix[1][i] += r;
                if (rs > 0.0f) { send_l[0][i] += l * rs; send_l[1][i] += r * rs; }
                if (ds > 0.0f) { send_d[0][i] += l * ds; send_d[1][i] += r * ds; }
            }
        }
    }
    if (reverb && rev_process) {
        rev_process(reverb, send_l[0], send_l[1], fx_out[0], fx_out[1], (int)n);
        for (jack_nframes_t i = 0; i < n; i++) { mix[0][i] += fx_out[0][i] * rev_level; mix[1][i] += fx_out[1][i] * rev_level; }
    }
    if (delay && dly_process) {
        dly_process(delay, send_d[0], send_d[1], fx_out[2], fx_out[3], (int)n);
        for (jack_nframes_t i = 0; i < n; i++) { mix[0][i] += fx_out[2][i] * dly_level; mix[1][i] += fx_out[3][i] * dly_level; }
    }

    float *ol = J.port_get_buffer(out_l, n), *orr = J.port_get_buffer(out_r, n);
    for (jack_nframes_t i = 0; i < n; i++) {
        ol[i] = tanhf(mix[0][i] * mix_gain) * master;              /* tanh: gentle limiting, as the Pi does */
        orr[i] = tanhf(mix[1][i] * mix_gain) * master;
    }

    /* lights and the screen */
    void *cout = J.port_get_buffer(ctl_out, n);
    J.midi_clear_buffer(cout);
    for (int sent = 0; sent < 64; sent++) {
        uint64_t t = atomic_load(&mo_tail);
        if (t == atomic_load(&mo_head)) break;
        uint8_t *m = midi_out[t % MIDI_OUT];
        J.midi_event_write(cout, 0, m + 1, m[0]);
        atomic_store(&mo_tail, t + 1);
    }
    void *dout = J.port_get_buffer(disp_out, n);
    J.midi_clear_buffer(dout);
    int d = atomic_exchange(&display_ready, -1);
    if (d >= 0) J.midi_event_write(dout, 0, display[d], DISPLAY_BYTES);

    atomic_store(&now_frame, t1);
    atomic_fetch_add(&cycles, 1);
    return 0;
}

/* ------------------------------------------------------------------ Python's side */

#define GET(name, field) if (!(J.field = dlsym(lib, "jack_" name))) return -2
int core_open(const char *libjack, const char *name) {
    void *lib = dlopen(libjack, RTLD_NOW | RTLD_GLOBAL);
    if (!lib) return -1;
    GET("client_open", client_open); GET("client_close", client_close); GET("activate", activate);
    GET("deactivate", deactivate); GET("port_register", port_register); GET("port_get_buffer", port_get_buffer);
    GET("set_process_callback", set_process_callback); GET("connect", connect);
    GET("get_sample_rate", get_sample_rate); GET("get_buffer_size", get_buffer_size);
    GET("midi_get_event_count", midi_get_event_count); GET("midi_event_get", midi_event_get);
    GET("midi_clear_buffer", midi_clear_buffer); GET("midi_event_write", midi_event_write);
    J.cpu_load = dlsym(lib, "jack_cpu_load");
    int status = 0;
    client = J.client_open(name, NO_START_SERVER, &status);
    if (!client) return -3;
    rate = J.get_sample_rate(client);
    block = J.get_buffer_size(client);
    out_l = J.port_register(client, "out_L", AUDIO, IS_OUTPUT, 0);
    out_r = J.port_register(client, "out_R", AUDIO, IS_OUTPUT, 0);
    in_l = J.port_register(client, "in_L", AUDIO, IS_INPUT, 0);
    in_r = J.port_register(client, "in_R", AUDIO, IS_INPUT, 0);
    ctl_in = J.port_register(client, "controls_in", MIDI, IS_INPUT, 0);
    ctl_out = J.port_register(client, "lights_out", MIDI, IS_OUTPUT, 0);
    disp_out = J.port_register(client, "display_out", MIDI, IS_OUTPUT, 0);
    if (!out_l || !out_r || !in_l || !in_r || !ctl_in || !ctl_out || !disp_out) return -4;
    for (int s = 0; s < MAX_SOURCES; s++) sources[s].kind = 0;
    J.set_process_callback(client, process, NULL);
    if (J.activate(client)) return -5;
    char me[300];
    const char *pairs[][2] = {{"out_L", "system:playback_1"}, {"out_R", "system:playback_2"}};
    for (int i = 0; i < 2; i++) {
        snprintf(me, sizeof me, "%s:%s", name, pairs[i][0]);
        J.connect(client, me, pairs[i][1]);
    }
    snprintf(me, sizeof me, "%s:controls_in", name);   J.connect(client, "system:midi_capture", me);
    snprintf(me, sizeof me, "%s:lights_out", name);    J.connect(client, me, "system:midi_playback");
    snprintf(me, sizeof me, "%s:display_out", name);   J.connect(client, me, "system:display");
    snprintf(me, sizeof me, "%s:in_L", name);          J.connect(client, "system:capture_1", me);
    snprintf(me, sizeof me, "%s:in_R", name);          J.connect(client, "system:capture_2", me);
    return 0;
}

void core_close(void) {
    if (client) { J.deactivate(client); J.client_close(client); client = NULL; }
}

int core_rate(void) { return (int)rate; }
int core_block(void) { return (int)block; }
uint64_t core_now(void) { return atomic_load(&now_frame); }
unsigned core_cycles(void) { return atomic_load(&cycles); }
/* JACK's own measure of how busy the audio cycle is, 0-100 (all its clients together) */
float core_load(void) { return (client && J.cpu_load) ? J.cpu_load(client) : -1.0f; }

/* a new source (call before turning it on): returns its number, or -1 */
static int new_source(int kind, int voices) {
    if (voices < 1 || voices > MAX_VOICES) return -1;
    for (int s = 0; s < MAX_SOURCES; s++) if (!sources[s].kind) {
        Source *src = &sources[s];
        memset(src->pan, 0, sizeof src->pan);
        memset(src->rev, 0, sizeof src->rev);
        memset(src->dly, 0, sizeof src->dly);
        src->voices = voices; src->gain = 1.0f; src->on = 0;
        src->awake = 0; src->held = 0; src->silent = 1;
        memset(src->buf, 0, sizeof src->buf);
        src->kind = kind;
        return s;
    }
    return -1;
}

int core_add_engine(void *render, void *trigger, int voices) {
    int s = new_source(ENGINE, voices);
    if (s >= 0) { sources[s].render = render; sources[s].trigger = trigger; }
    return s;
}

int core_add_module(void *sh_render, void *sh_midi, void *inst) {
    int s = new_source(MODULE, 2);
    if (s >= 0) {
        sources[s].sh_render = sh_render; sources[s].sh_midi = sh_midi; sources[s].inst = inst;
        sources[s].pan[0][0] = sources[s].pan[1][1] = 1.0f;          /* stereo as it comes */
    }
    return s;
}

/* turn a source off before removing it, and wait a cycle (core_cycles) before freeing what it uses */
void core_source_on(int s, int on) { if (s >= 0 && s < MAX_SOURCES) sources[s].on = on; }
void core_remove(int s) { if (s >= 0 && s < MAX_SOURCES) { sources[s].on = 0; sources[s].kind = 0; } }
void core_set_pan(int s, int v, float l, float r) {
    if (s >= 0 && s < MAX_SOURCES && v >= 0 && v < MAX_VOICES) { sources[s].pan[v][0] = l; sources[s].pan[v][1] = r; }
}
void core_set_sends(int s, int v, float rev, float dly) {
    if (s >= 0 && s < MAX_SOURCES && v >= 0 && v < MAX_VOICES) { sources[s].rev[v] = rev; sources[s].dly[v] = dly; }
}
void core_set_gain(int s, float g) { if (s >= 0 && s < MAX_SOURCES) sources[s].gain = g; }
void core_set_master(float g) { master = g; }

void core_set_effects(void *rp, void *r, void *dp, void *d) { rev_process = rp; reverb = r; dly_process = dp; delay = d; }
void core_set_effect_levels(float r, float d) { rev_level = r; dly_level = d; }

/* queue an event; returns 0, or -1 if the queue is full */
int core_push(uint64_t frame, int kind, int src, intptr_t a, intptr_t b, intptr_t c, void *fn) {
    uint64_t h = atomic_load(&ev_head);
    if (h - atomic_load(&ev_tail) >= EVENTS) return -1;
    Event *e = &events[h % EVENTS];
    e->frame = frame; e->kind = kind; e->src = src; e->a = a; e->b = b; e->c = c; e->fn = fn;
    atomic_store(&ev_head, h + 1);
    return 0;
}

/* how far the core has got through the events (Python keeps strings for EV_CALL alive until then) */
uint64_t core_events_done(void) { return atomic_load(&ev_tail); }

/* the Move's controls: fills up to max messages of 12 bytes (8: frame, 4: MIDI); returns how many */
int core_read_midi(uint8_t *out, int max) {
    int k = 0;
    while (k < max) {
        uint64_t t = atomic_load(&mi_tail);
        if (t == atomic_load(&mi_head)) break;
        memcpy(out + 12 * k, &midi_in[t % MIDI_IN].frame, 8);
        memcpy(out + 12 * k + 8, midi_in[t % MIDI_IN].b, 4);
        atomic_store(&mi_tail, t + 1);
        k++;
    }
    return k;
}

int core_send_midi(const uint8_t *m, int len) {
    if (len < 1 || len > 3) return -1;
    uint64_t h = atomic_load(&mo_head);
    if (h - atomic_load(&mo_tail) >= MIDI_OUT) return -1;
    midi_out[h % MIDI_OUT][0] = (uint8_t)len;
    memcpy(midi_out[h % MIDI_OUT] + 1, m, len);
    atomic_store(&mo_head, h + 1);
    return 0;
}

/* a whole screen: "MOVEDISP" + 1024 bytes */
void core_set_display(const uint8_t *frame) {
    memcpy(display[display_next], frame, DISPLAY_BYTES);
    atomic_store(&display_ready, display_next);
    display_next ^= 1;
}

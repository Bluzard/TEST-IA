// Motor de inferencia minimalista para el núcleo BitNet (formato NUCL0001, ver exportar_cpp.py).
// Sin dependencias en tiempo de ejecución (solo la biblioteca estándar y OpenMP).
// Pesos de las capas lineales: ternarios (-1,0,+1) empaquetados a 2 bits, se desempaquetan por fila al calcular.
// Embeddings y capa de salida: fp16. Activaciones y acumuladores: fp32.
//
// Compilar: compilar_motor.bat   ->   motor.dll
#include <immintrin.h>
#include <omp.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>

#define EXPORT extern "C" __declspec(dllexport)

namespace {

struct Lin {
    float escala = 1.f;
    int out = 0, in = 0;
    std::vector<uint8_t> w;  // out * in/4 bytes
};
struct Capa {
    std::vector<float> ln1w, ln1b, ln2w, ln2b;
    Lin qkv, proy, fc1, fc2;
};
// Adaptador LoRA (formato LORA0001): por capa y por matriz objetivo (0 qkv, 1 proy, 2 fc1, 3 fc2)
// A: r×in en fp16 | Bt: B transpuesta, r×out en fp16 (así la salida es una suma vectorizada)
struct LoraMat {
    std::vector<uint16_t> A, Bt;
    int in = 0, out = 0;
    bool tiene = false;
};
struct Lora {
    int r = 0;
    float escala = 0.f;  // alpha / r
    std::vector<LoraMat> m;  // capas * 4
};

struct Modelo {
    int V, T, d, L, H, vueltas, ff, fin, herr, asist, usuario, relleno, bitnet;
    std::vector<uint16_t> tok, cab, pos;
    std::vector<float> vuelta, lnw, lnb;
    std::vector<Capa> capas;
    // Caché multi-slot (Etapa 3, paso 2): hasta 2 adaptadores en RAM. Estados: 0 frío (descargado), 1 tibio (en RAM pero fuera del
    // forward, con vida que decae por turno sin uso), 2 activo (el forward lo usa). `act` es el ÚNICO puntero que mira el forward:
    // nullptr = núcleo base, idéntico bit a bit. Cambiar de experto es reasignar `act`.
    static const int RANURAS = 2;
    std::shared_ptr<Lora> rs[RANURAS];
    int estado[RANURAS] = {0, 0};
    int vida[RANURAS] = {0, 0};
    int vida_tibia = 6;          // turnos que un adaptador tibio sobrevive sin uso antes de descargarse
    const Lora* act = nullptr;
};

float LUT[256][4];
bool lut_lista = false;
void iniciar_lut() {
    if (lut_lista) return;
    for (int b = 0; b < 256; ++b)
        for (int k = 0; k < 4; ++k) {
            int c = (b >> (2 * k)) & 3;
            LUT[b][k] = c == 1 ? 1.f : (c == 2 ? -1.f : 0.f);
        }
    lut_lista = true;
}

inline float dot(const float* a, const float* b, int n) {  // n múltiplo de 8
    __m256 s0 = _mm256_setzero_ps(), s1 = _mm256_setzero_ps();
    int i = 0;
    for (; i + 16 <= n; i += 16) {
        s0 = _mm256_fmadd_ps(_mm256_loadu_ps(a + i), _mm256_loadu_ps(b + i), s0);
        s1 = _mm256_fmadd_ps(_mm256_loadu_ps(a + i + 8), _mm256_loadu_ps(b + i + 8), s1);
    }
    for (; i + 8 <= n; i += 8) s0 = _mm256_fmadd_ps(_mm256_loadu_ps(a + i), _mm256_loadu_ps(b + i), s0);
    s0 = _mm256_add_ps(s0, s1);
    __m128 lo = _mm256_castps256_ps128(s0), hi = _mm256_extractf128_ps(s0, 1);
    lo = _mm_add_ps(lo, hi);
    lo = _mm_hadd_ps(lo, lo);
    lo = _mm_hadd_ps(lo, lo);
    return _mm_cvtss_f32(lo);
}

// fila fp16 -> fp32 (n múltiplo de 8)
inline void fp16_a_fp32(const uint16_t* p, float* out, int n) {
    for (int i = 0; i < n; i += 8) _mm256_storeu_ps(out + i, _mm256_cvtph_ps(_mm_loadu_si128((const __m128i*)(p + i))));
}

// y[t][j] = escala * sum_i W[j][i] * x[t][i],  W ternario empaquetado
void matmul_bit(const float* x, int T, const Lin& L, float* y) {
    const int in = L.in, out = L.out, bytes = in / 4;
#pragma omp parallel
    {
        float* buf = (float*)_aligned_malloc((size_t)in * sizeof(float), 32);
#pragma omp for schedule(static)
        for (int j = 0; j < out; ++j) {
            const uint8_t* p = L.w.data() + (size_t)j * bytes;
            for (int i = 0; i < bytes; ++i) memcpy(buf + 4 * i, LUT[p[i]], 16);
            for (int t = 0; t < T; ++t) y[(size_t)t * out + j] = L.escala * dot(buf, x + (size_t)t * in, in);
        }
        _aligned_free(buf);
    }
}

// y[t] += (alpha/r) * B (A x[t])  para la matriz objetivo 'tgt' de la capa 'capa'.
// Decodificación (T pequeño): serie, sin OpenMP (su arranque costaría más que el trabajo). Prefill: paralelo por token.
void lora_sumar(const Lora& L, int capa, int tgt, const float* x, int T, float* y) {
    const LoraMat& M = L.m[(size_t)capa * 4 + tgt];
    if (!M.tiene) return;
    const int in = M.in, out = M.out, r = L.r;
    const float esc = L.escala;
    std::vector<float> Af;
    const float* Aptr = nullptr;
    if (T >= 8) {  // convertir A a fp32 una sola vez para todos los tokens
        Af.resize((size_t)r * in);
        for (int k = 0; k < r; ++k) fp16_a_fp32(&M.A[(size_t)k * in], &Af[(size_t)k * in], in);
        Aptr = Af.data();
    }
    auto uno = [&](int t, float* buf, float* z) {
        const float* xt = x + (size_t)t * in;
        for (int k = 0; k < r; ++k) {
            const float* ak = Aptr + (size_t)k * in;
            if (!Aptr) { fp16_a_fp32(&M.A[(size_t)k * in], buf, in); ak = buf; }
            z[k] = dot(ak, xt, in) * esc;
        }
        float* yt = y + (size_t)t * out;
        for (int k = 0; k < r; ++k) {
            const __m256 zz = _mm256_set1_ps(z[k]);
            const uint16_t* b = &M.Bt[(size_t)k * out];
            for (int j = 0; j < out; j += 8) {
                __m256 bb = _mm256_cvtph_ps(_mm_loadu_si128((const __m128i*)(b + j)));
                _mm256_storeu_ps(yt + j, _mm256_fmadd_ps(zz, bb, _mm256_loadu_ps(yt + j)));
            }
        }
    };
    if (T >= 8) {
#pragma omp parallel
        {
            std::vector<float> z(r);
#pragma omp for schedule(static)
            for (int t = 0; t < T; ++t) uno(t, nullptr, z.data());
        }
    } else {
        std::vector<float> z(r), buf(in);
        for (int t = 0; t < T; ++t) uno(t, buf.data(), z.data());
    }
}

void layernorm(const float* x, int T, int d, const float* w, const float* b, float* out) {
    for (int t = 0; t < T; ++t) {
        const float* r = x + (size_t)t * d;
        float m = 0.f;
        for (int i = 0; i < d; ++i) m += r[i];
        m /= d;
        float v = 0.f;
        for (int i = 0; i < d; ++i) v += (r[i] - m) * (r[i] - m);
        v /= d;
        float inv = 1.f / std::sqrt(v + 1e-5f);
        float* o = out + (size_t)t * d;
        for (int i = 0; i < d; ++i) o[i] = (r[i] - m) * inv * w[i] + b[i];
    }
}

struct Estado {
    std::vector<float> K, V;  // [(vueltas*capas)][T][d]
    void iniciar(const Modelo& m) {
        size_t n = (size_t)m.vueltas * m.L * m.T * m.d;
        K.assign(n, 0.f);
        V.assign(n, 0.f);
    }
};

// Procesa n tokens nuevos situados en las posiciones p0..p0+n-1 (con caché de las anteriores).
// Devuelve en 'ult' el estado oculto del último token (antes de la LN final).
void avanzar(const Modelo& m, Estado& e, const int* ids, int n, int p0, std::vector<float>& ult) {
    const int d = m.d, H = m.H, hd = d / H, ff = m.ff;
    std::vector<float> x((size_t)n * d), h((size_t)n * d), qkv((size_t)n * 3 * d), at((size_t)n * d), mlp((size_t)n * ff), tmp((size_t)n * d);
    for (int t = 0; t < n; ++t) {
        float* r = &x[(size_t)t * d];
        float* a = &h[(size_t)t * d];
        fp16_a_fp32(&m.tok[(size_t)ids[t] * d], r, d);
        fp16_a_fp32(&m.pos[(size_t)(p0 + t) * d], a, d);
        for (int i = 0; i < d; ++i) r[i] += a[i];
    }
    const float esc = 1.f / std::sqrt((float)hd);
    for (int v = 0; v < m.vueltas; ++v) {
        for (int t = 0; t < n; ++t)
            for (int i = 0; i < d; ++i) x[(size_t)t * d + i] += m.vuelta[(size_t)v * d + i];
        for (int l = 0; l < m.L; ++l) {
            const Capa& c = m.capas[l];
            float* K = &e.K[((size_t)(v * m.L + l) * m.T) * d];
            float* V = &e.V[((size_t)(v * m.L + l) * m.T) * d];
            layernorm(x.data(), n, d, c.ln1w.data(), c.ln1b.data(), h.data());
            const bool con_lora = m.act != nullptr;
            matmul_bit(h.data(), n, c.qkv, qkv.data());
            if (con_lora) lora_sumar(*m.act, l, 0, h.data(), n, qkv.data());
            for (int t = 0; t < n; ++t) {
                memcpy(K + (size_t)(p0 + t) * d, &qkv[(size_t)t * 3 * d + d], d * sizeof(float));
                memcpy(V + (size_t)(p0 + t) * d, &qkv[(size_t)t * 3 * d + 2 * d], d * sizeof(float));
            }
#pragma omp parallel
            {
                std::vector<float> p(m.T);
#pragma omp for schedule(dynamic)
                for (int th = 0; th < n * H; ++th) {
                    int t = th / H, hh = th % H, pos = p0 + t;
                    const float* q = &qkv[(size_t)t * 3 * d + hh * hd];
                    float mx = -1e30f;
                    for (int s = 0; s <= pos; ++s) {
                        p[s] = dot(q, K + (size_t)s * d + hh * hd, hd) * esc;
                        mx = std::max(mx, p[s]);
                    }
                    float suma = 0.f;
                    for (int s = 0; s <= pos; ++s) { p[s] = std::exp(p[s] - mx); suma += p[s]; }
                    float inv = 1.f / suma;
                    float* o = &at[(size_t)t * d + hh * hd];
                    for (int i = 0; i < hd; ++i) o[i] = 0.f;
                    for (int s = 0; s <= pos; ++s) {
                        float w = p[s] * inv;
                        const float* vv = V + (size_t)s * d + hh * hd;
                        for (int i = 0; i < hd; ++i) o[i] += w * vv[i];
                    }
                }
            }
            matmul_bit(at.data(), n, c.proy, tmp.data());
            if (con_lora) lora_sumar(*m.act, l, 1, at.data(), n, tmp.data());
            for (size_t i = 0; i < (size_t)n * d; ++i) x[i] += tmp[i];
            layernorm(x.data(), n, d, c.ln2w.data(), c.ln2b.data(), h.data());
            matmul_bit(h.data(), n, c.fc1, mlp.data());
            if (con_lora) lora_sumar(*m.act, l, 2, h.data(), n, mlp.data());
            for (size_t i = 0; i < (size_t)n * ff; ++i) {
                float u = mlp[i];
                mlp[i] = 0.5f * u * (1.f + std::erf(u * 0.70710678118f));
            }
            matmul_bit(mlp.data(), n, c.fc2, tmp.data());
            if (con_lora) lora_sumar(*m.act, l, 3, mlp.data(), n, tmp.data());
            for (size_t i = 0; i < (size_t)n * d; ++i) x[i] += tmp[i];
        }
    }
    ult.assign(x.begin() + (size_t)(n - 1) * d, x.end());
}

void logits_de(const Modelo& m, const std::vector<float>& ult, std::vector<float>& out) {
    const int d = m.d;
    std::vector<float> z(d);
    layernorm(ult.data(), 1, d, m.lnw.data(), m.lnb.data(), z.data());
    out.resize(m.V);
#pragma omp parallel
    {
        float* buf = (float*)_aligned_malloc((size_t)d * sizeof(float), 32);
#pragma omp for schedule(static)
        for (int v = 0; v < m.V; ++v) {
            fp16_a_fp32(&m.cab[(size_t)v * d], buf, d);
            out[v] = dot(buf, z.data(), d);
        }
        _aligned_free(buf);
    }
}

bool leer(FILE* f, void* dst, size_t bytes) { return fread(dst, 1, bytes, f) == bytes; }
bool leer_lin(FILE* f, Lin& L, int out, int in) {
    L.out = out; L.in = in;
    L.w.resize((size_t)out * in / 4);
    return leer(f, &L.escala, 4) && leer(f, L.w.data(), L.w.size());
}

}  // namespace

EXPORT void* nucleo_cargar(const char* ruta) {
    iniciar_lut();
    FILE* f = fopen(ruta, "rb");
    if (!f) return nullptr;
    char magia[8];
    int32_t c[13];
    if (!leer(f, magia, 8) || memcmp(magia, "NUCL0001", 8) != 0 || !leer(f, c, sizeof(c))) { fclose(f); return nullptr; }
    Modelo* m = new Modelo();
    m->V = c[0]; m->T = c[1]; m->d = c[2]; m->L = c[3]; m->H = c[4]; m->vueltas = c[5]; m->ff = c[6];
    m->fin = c[7]; m->herr = c[8]; m->asist = c[9]; m->usuario = c[10]; m->relleno = c[11]; m->bitnet = c[12];
    const int d = m->d;
    bool ok = d % 8 == 0 && d <= 4096 && (d / m->H) % 8 == 0;
    m->tok.resize((size_t)m->V * d); m->pos.resize((size_t)m->T * d); m->vuelta.resize((size_t)m->vueltas * d);
    ok = ok && leer(f, m->tok.data(), m->tok.size() * 2) && leer(f, m->pos.data(), m->pos.size() * 2) &&
         leer(f, m->vuelta.data(), m->vuelta.size() * 4);
    m->capas.resize(m->L);
    for (int i = 0; ok && i < m->L; ++i) {
        Capa& k = m->capas[i];
        k.ln1w.resize(d); k.ln1b.resize(d); k.ln2w.resize(d); k.ln2b.resize(d);
        ok = leer(f, k.ln1w.data(), d * 4) && leer(f, k.ln1b.data(), d * 4) && leer_lin(f, k.qkv, 3 * d, d) &&
             leer_lin(f, k.proy, d, d) && leer(f, k.ln2w.data(), d * 4) && leer(f, k.ln2b.data(), d * 4) &&
             leer_lin(f, k.fc1, m->ff, d) && leer_lin(f, k.fc2, d, m->ff);
    }
    m->lnw.resize(d); m->lnb.resize(d); m->cab.resize((size_t)m->V * d);
    ok = ok && leer(f, m->lnw.data(), d * 4) && leer(f, m->lnb.data(), d * 4) && leer(f, m->cab.data(), m->cab.size() * 2);
    fclose(f);
    if (!ok) { delete m; return nullptr; }
    return m;
}

EXPORT void nucleo_liberar(void* h) { delete (Modelo*)h; }

// ---- Adaptadores LoRA al vuelo (formato LORA0001, ver exportar_lora_cpp.py) ----
// Lee un .lora. 0 = ok; -1 no se pudo abrir; -2 formato inválido; -3 no calza con el núcleo.
static int leer_lora(const Modelo& m, const char* ruta, std::shared_ptr<Lora>& salida) {
    FILE* f = fopen(ruta, "rb");
    if (!f) return -1;
    char magia[8];
    int32_t c[5];
    float alpha;
    if (!leer(f, magia, 8) || memcmp(magia, "LORA0001", 8) != 0 || !leer(f, c, sizeof(c)) || !leer(f, &alpha, 4)) { fclose(f); return -2; }
    const int r = c[0], capas = c[1], d = c[2], ff = c[3], mascara = c[4];
    if (capas != m.L || d != m.d || ff != m.ff) { fclose(f); return -3; }
    if (r < 1 || r > 64) { fclose(f); return -2; }
    auto L = std::make_shared<Lora>();
    L->r = r;
    L->escala = alpha / r;
    L->m.resize((size_t)capas * 4);
    const int entradas[4] = {d, d, d, ff}, salidas[4] = {3 * d, d, ff, d};
    for (int i = 0; i < capas; ++i)
        for (int t = 0; t < 4; ++t) {
            if (!(mascara >> t & 1)) continue;
            LoraMat& M = L->m[(size_t)i * 4 + t];
            M.in = entradas[t]; M.out = salidas[t]; M.tiene = true;
            M.A.resize((size_t)r * M.in);
            M.Bt.resize((size_t)r * M.out);
            if (!leer(f, M.A.data(), M.A.size() * 2) || !leer(f, M.Bt.data(), M.Bt.size() * 2)) { fclose(f); return -2; }
        }
    fclose(f);
    salida = std::move(L);
    return 0;
}

static void soltar_ranura(Modelo& m, int i) {
    if (m.act == m.rs[i].get()) m.act = nullptr;
    m.rs[i].reset();
    m.estado[i] = 0;
    m.vida[i] = 0;
}

// --- API multi-slot ---
// Carga un .lora en la ranura `id` (0..1) en estado TIBIO (no entra al forward hasta `seleccionar`). Si la ranura estaba ocupada se reemplaza.
EXPORT int nucleo_lora_cargar_ranura(void* h, const char* ruta, int id) {
    Modelo& m = *(Modelo*)h;
    if (id < 0 || id >= Modelo::RANURAS) return -4;
    std::shared_ptr<Lora> L;
    int r = leer_lora(m, ruta, L);
    if (r != 0) return r;
    if (m.rs[id]) soltar_ranura(m, id);
    m.rs[id] = std::move(L);
    m.estado[id] = 1;
    m.vida[id] = m.vida_tibia;
    return 0;
}

// Activa la ranura `id` (la que estaba activa pasa a tibia con la vida completa). id = -1 duerme todo (núcleo base). Es solo una
// asignación de puntero. Devuelve 0, o -1 si la ranura está fría (hay que cargarla).
EXPORT int nucleo_lora_seleccionar(void* h, int id) {
    Modelo& m = *(Modelo*)h;
    for (int i = 0; i < Modelo::RANURAS; ++i)
        if (m.estado[i] == 2) { m.estado[i] = 1; m.vida[i] = m.vida_tibia; }
    m.act = nullptr;
    if (id < 0) return 0;
    if (id >= Modelo::RANURAS || !m.rs[id]) return -1;
    m.estado[id] = 2;
    m.act = m.rs[id].get();
    return 0;
}

// Un turno de conversación: cada adaptador TIBIO pierde 1 de vida; al llegar a 0 pasa a frío y libera su memoria. Devuelve cuántos descargó.
EXPORT int nucleo_lora_turno(void* h) {
    Modelo& m = *(Modelo*)h;
    int n = 0;
    for (int i = 0; i < Modelo::RANURAS; ++i)
        if (m.estado[i] == 1 && --m.vida[i] <= 0) { soltar_ranura(m, i); ++n; }
    return n;
}

EXPORT int nucleo_lora_estado(void* h, int id) { Modelo& m = *(Modelo*)h; return (id >= 0 && id < Modelo::RANURAS) ? m.estado[id] : -1; }
EXPORT int nucleo_lora_vida(void* h, int id) { Modelo& m = *(Modelo*)h; return (id >= 0 && id < Modelo::RANURAS) ? m.vida[id] : -1; }
EXPORT void nucleo_lora_config(void* h, int vida_tibia) { ((Modelo*)h)->vida_tibia = vida_tibia < 1 ? 1 : vida_tibia; }

// --- API anterior (compatible): opera sobre la ranura 0 ---
// Carga un .lora en la ranura 0 y lo activa. 0 = ok; -1 no se pudo abrir; -2 formato inválido; -3 no calza con el núcleo.
EXPORT int nucleo_lora_cargar(void* h, const char* ruta) {
    int r = nucleo_lora_cargar_ranura(h, ruta, 0);
    if (r == 0) nucleo_lora_seleccionar(h, 0);
    return r;
}

// Despierta (1) o duerme (0) el adaptador de la ranura 0 sin descargarlo. Dormido = idéntico al núcleo base.
EXPORT void nucleo_lora_activar(void* h, int activo) {
    Modelo& m = *(Modelo*)h;
    if (activo) { if (m.rs[0]) nucleo_lora_seleccionar(h, 0); }
    else nucleo_lora_seleccionar(h, -1);
}

// Libera la memoria de la ranura 0.
EXPORT void nucleo_lora_descargar(void* h) {
    Modelo& m = *(Modelo*)h;
    if (m.rs[0]) soltar_ranura(m, 0);
}

// Bytes de TODOS los adaptadores cargados (tibios y activo).
EXPORT long long nucleo_lora_bytes(void* h) {
    const Modelo& m = *(Modelo*)h;
    long long n = 0;
    for (int i = 0; i < Modelo::RANURAS; ++i)
        if (m.rs[i]) for (const LoraMat& M : m.rs[i]->m) n += (long long)(M.A.size() + M.Bt.size()) * 2;
    return n;
}

// Logits del último token de 'ids' (para verificar contra PyTorch). Devuelve V.
EXPORT int nucleo_logits(void* h, const int* ids, int n, float* salida) {
    const Modelo& m = *(Modelo*)h;
    if (n < 1 || n > m.T) return -1;
    Estado e; e.iniciar(m);
    std::vector<float> ult, lg;
    avanzar(m, e, ids, n, 0, ult);
    logits_de(m, ult, lg);
    memcpy(salida, lg.data(), lg.size() * sizeof(float));
    return m.V;
}

// Generación voraz con penalización por repetición (solo sobre lo generado en esta llamada).
// Escribe los tokens nuevos (incluido el de parada) en 'salida'; parada = id de <fin> o <herramienta>, o -1.
// tiempos[0] = ms de prefill, tiempos[1] = ms de decodificación, tiempos[2] = pasos de decodificación.
EXPORT int nucleo_generar(void* h, const int* prompt, int n, float pen, int max_nuevos, int* salida, int* parada, double* tiempos) {
    using reloj = std::chrono::steady_clock;
    const Modelo& m = *(Modelo*)h;
    *parada = -1;
    if (n < 1 || n >= m.T) return -1;
    Estado e; e.iniciar(m);
    std::vector<float> ult, lg;
    std::vector<char> usados(m.V, 0);
    auto t0 = reloj::now();
    avanzar(m, e, prompt, n, 0, ult);
    logits_de(m, ult, lg);
    auto t1 = reloj::now();
    double dec_ms = 0; int pasos = 0, k = 0, largo = n;
    while (k < max_nuevos && largo < m.T) {
        if (pen != 1.f)
            for (int v = 0; v < m.V; ++v)
                if (usados[v]) lg[v] = lg[v] > 0 ? lg[v] / pen : lg[v] * pen;
        int mejor = (int)(std::max_element(lg.begin(), lg.end()) - lg.begin());
        salida[k++] = mejor;
        ++largo;
        if (mejor == m.fin || mejor == m.herr) { *parada = mejor; break; }
        usados[mejor] = 1;
        if (k >= max_nuevos || largo >= m.T) break;
        auto a = reloj::now();
        avanzar(m, e, &mejor, 1, largo - 1, ult);
        logits_de(m, ult, lg);
        dec_ms += std::chrono::duration<double, std::milli>(reloj::now() - a).count();
        ++pasos;
    }
    if (tiempos) {
        tiempos[0] = std::chrono::duration<double, std::milli>(t1 - t0).count();
        tiempos[1] = dec_ms;
        tiempos[2] = pasos;
    }
    return k;
}

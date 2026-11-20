"""Fase 0 de la Etapa 4 (sin GPU): el motor C++ con el formato NUCL0002 del núcleo v2 y PESOS ALEATORIOS.

Qué comprueba (antes de gastar horas de entrenamiento):
  1. Exactitud: logits del motor vs una implementación de referencia en PyTorch fp32 (GQA, KV fp16, embedding atado int8, bloques de prefill,
     adaptadores LoRA con qkv de salida d + 2·kvd) con prompts de 1 a 1.000 tokens.
  2. Invariancia: el prefill por bloques (128) da los mismos bits que procesar todo junto; v1 sigue dando los mismos bits (lo verifica
     verificar_multiexperto.py).
  3. RAM pico del proceso y velocidad (ms/token de decodificación, prefill) en ESTE equipo, para la configuración del diseño y variantes
     (sin GQA, KV fp32, embedding fp16...) que muestran qué decisión de diseño ahorra cuánto.

  python fase0_nucleo_v2.py verificar          # 1 y 2
  python fase0_nucleo_v2.py bench              # 3 (cada configuración en un proceso aparte)
Los .bin aleatorios se escriben en modelos/experimentos/v2_fase0/ (no se versionan).
"""
import argparse
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).parent
CARPETA = RAIZ / "modelos" / "experimentos" / "v2_fase0"

# configuración del diseño v2-A (estudios/ETAPA4_DISENO_nucleo_v2.md)
V2A = dict(V=24004, T=1024, d=768, L=22, H=12, HK=4, ff=3072, tied=True, emb8=True, kv16=True)
VARIANTES = {
    "A_diseno (GQA 4, KV fp16, embedding atado int8)": V2A,
    "B embedding atado fp16": {**V2A, "emb8": False},
    "C KV fp32": {**V2A, "kv16": False},
    "D sin GQA (12 cabezas KV), KV fp16": {**V2A, "HK": 12},
    "E sin GQA, KV fp32, embedding sin atar fp16 (estilo v1)": {**V2A, "HK": 12, "kv16": False, "tied": False, "emb8": False},
}


def nombre_archivo(cfg, extra=""):
    return f"v2_d{cfg['d']}_L{cfg['L']}_hk{cfg['HK']}_{'tied' if cfg['tied'] else 'untied'}_{'i8' if cfg['emb8'] else 'f16'}_{'kv16' if cfg['kv16'] else 'kv32'}{extra}"


# ------------------------------------------------------------------ escritura de un .bin / .lora aleatorios
def _ternario(rng, out, n_in):
    """Códigos 0 -> 0, 1 -> +1, 2 -> -1, cuatro por byte (el primero en los 2 bits menos significativos), al azar."""
    c = rng.integers(0, 3, size=(out, n_in // 4, 4), dtype=np.uint8)
    return (c[..., 0] | (c[..., 1] << 2) | (c[..., 2] << 4) | (c[..., 3] << 6)).astype(np.uint8)


def crear_bin(ruta, V, T, d, L, H, HK, ff, tied, emb8, kv16, seed=0, bloque=128):
    rng = np.random.default_rng(seed)
    kvd = HK * (d // H)
    with open(ruta, "wb") as f:
        f.write(b"NUCL0002")
        f.write(struct.pack("<16i", V, T, d, L, H, 1, ff, -1, -1, V - 3, V - 4, V - 1, 1, HK,
                            (1 if tied else 0) | (2 if emb8 else 0) | (4 if kv16 else 0), bloque))  # fin/herramienta = -1: nunca paran
        emb = rng.normal(0, 0.05, size=(V, d)).astype(np.float32)
        if emb8:
            esc = np.maximum(np.abs(emb).max(axis=1), 1e-6) / 127.0
            esc16 = esc.astype(np.float16)
            q = np.clip(np.round(emb / esc16.astype(np.float32)[:, None]), -127, 127).astype(np.int8)
            f.write(q.tobytes()); f.write(esc16.tobytes())
        else:
            f.write(emb.astype(np.float16).tobytes())
        f.write(rng.normal(0, 0.02, size=(T, d)).astype(np.float16).tobytes())
        f.write(np.zeros((1, d), dtype=np.float32).tobytes())

        def lineal(out, n_in):
            esc = 0.5 / np.sqrt(2.0 * n_in / 3.0)  # mantiene las activaciones en una escala razonable
            f.write(struct.pack("<f", float(esc)))
            f.write(_ternario(rng, out, n_in).tobytes())

        def ln():
            f.write((1.0 + 0.1 * rng.normal(size=d)).astype(np.float32).tobytes())
            f.write((0.05 * rng.normal(size=d)).astype(np.float32).tobytes())

        for _ in range(L):
            ln(); lineal(d + 2 * kvd, d); lineal(d, d); ln(); lineal(ff, d); lineal(d, ff)
        ln()
        if not tied:
            f.write(rng.normal(0, 0.05, size=(V, d)).astype(np.float16).tobytes())
    return Path(ruta)


def crear_lora_para(ruta, cfg, r=16, alpha=32.0, seed=1):
    rng = np.random.default_rng(seed)
    d, ff, L = cfg["d"], cfg["ff"], cfg["L"]
    kvd = cfg["HK"] * (d // cfg["H"])
    ent = (d, d, d, ff)
    sal = (d + 2 * kvd, d, ff, d)
    with open(ruta, "wb") as f:
        f.write(b"LORA0002")
        f.write(struct.pack("<5if", r, L, d, ff, 15, alpha))
        for _ in range(L):
            for i in range(4):
                f.write(rng.normal(0, 0.05, size=(r, ent[i])).astype(np.float16).tobytes())
                f.write(rng.normal(0, 0.05, size=(r, sal[i])).astype(np.float16).tobytes())
    return Path(ruta)


# ------------------------------------------------------------------ referencia en PyTorch (lee el mismo .bin con otro código)
def leer_bin(ruta):
    import torch

    b = open(ruta, "rb").read()
    assert b[:8] == b"NUCL0002"
    c = struct.unpack("<16i", b[8:72])
    V, T, d, L, H, _, ff, _, _, _, _, _, _, HK, flags, _ = c
    tied, emb8, kv16 = bool(flags & 1), bool(flags & 2), bool(flags & 4)
    o = 72
    kvd = HK * (d // H)

    def tomar(dtype, *forma):
        nonlocal o
        n = int(np.prod(forma))
        a = np.frombuffer(b, dtype=dtype, count=n, offset=o).reshape(forma)
        o += a.nbytes
        return a

    if emb8:
        q = tomar(np.int8, V, d)
        esc = tomar(np.float16, V).astype(np.float32)
        emb = torch.from_numpy(q.astype(np.float32) * esc[:, None])
    else:
        emb = torch.from_numpy(tomar(np.float16, V, d).astype(np.float32))
    pos = torch.from_numpy(tomar(np.float16, T, d).astype(np.float32))
    tomar(np.float32, 1, d)

    def lineal(out, n_in):
        nonlocal o
        escala = struct.unpack("<f", b[o:o + 4])[0]
        o += 4
        by = tomar(np.uint8, out, n_in // 4)
        cod = np.stack([(by >> (2 * k)) & 3 for k in range(4)], axis=-1).reshape(out, n_in)
        w = np.where(cod == 1, 1.0, np.where(cod == 2, -1.0, 0.0)).astype(np.float32) * escala
        return torch.from_numpy(w)

    capas = []
    for _ in range(L):
        cp = {}
        cp["ln1w"], cp["ln1b"] = (torch.from_numpy(tomar(np.float32, d).copy()) for _ in range(2))
        cp["qkv"] = lineal(d + 2 * kvd, d)
        cp["proy"] = lineal(d, d)
        cp["ln2w"], cp["ln2b"] = (torch.from_numpy(tomar(np.float32, d).copy()) for _ in range(2))
        cp["fc1"] = lineal(ff, d)
        cp["fc2"] = lineal(d, ff)
        capas.append(cp)
    lnw, lnb = (torch.from_numpy(tomar(np.float32, d).copy()) for _ in range(2))
    cab = emb if tied else torch.from_numpy(tomar(np.float16, V, d).astype(np.float32))
    return dict(V=V, T=T, d=d, L=L, H=H, HK=HK, ff=ff, kv16=kv16, emb=emb, pos=pos, capas=capas, lnw=lnw, lnb=lnb, cab=cab)


def leer_lora(ruta, M):
    import torch

    b = open(ruta, "rb").read()
    r, L, d, ff, mascara, alpha = struct.unpack("<5if", b[8:32])
    o, kvd = 32, M["HK"] * (M["d"] // M["H"])
    ent = (d, d, d, ff)
    sal = (d + 2 * kvd, d, ff, d)
    capas = []
    for _ in range(L):
        c = []
        for i in range(4):
            A = np.frombuffer(b, dtype=np.float16, count=r * ent[i], offset=o).reshape(r, ent[i]).astype(np.float32); o += A.size * 2
            Bt = np.frombuffer(b, dtype=np.float16, count=r * sal[i], offset=o).reshape(r, sal[i]).astype(np.float32); o += Bt.size * 2
            c.append((torch.from_numpy(A), torch.from_numpy(Bt)))
        capas.append(c)
    return dict(escala=alpha / r, capas=capas)


def referencia_logits(M, ids, lora=None):
    """Logits del último token en fp32, con la misma aritmética que el motor (GQA, K/V redondeados a fp16 si kv16)."""
    import torch
    import torch.nn.functional as F

    d, H, HK, hd = M["d"], M["H"], M["HK"], M["d"] // M["H"]
    kvd, n = HK * hd, len(ids)
    x = M["emb"][torch.tensor(ids)] + M["pos"][:n]

    def con_lora(i, j, h, y):
        if lora is None:
            return y
        A, Bt = lora["capas"][i][j]
        return y + lora["escala"] * ((h @ A.T) @ Bt)

    for i, c in enumerate(M["capas"]):
        h = F.layer_norm(x, (d,), c["ln1w"], c["ln1b"], 1e-5)
        qkv = con_lora(i, 0, h, h @ c["qkv"].T)
        q, k, v = qkv[:, :d].reshape(n, H, hd), qkv[:, d:d + kvd].reshape(n, HK, hd), qkv[:, d + kvd:].reshape(n, HK, hd)
        if M["kv16"]:
            k, v = k.half().float(), v.half().float()
        k, v = k.repeat_interleave(H // HK, dim=1), v.repeat_interleave(H // HK, dim=1)
        sc = torch.einsum("thd,shd->hts", q, k) / np.sqrt(hd)
        sc = sc.masked_fill(torch.triu(torch.ones(n, n, dtype=torch.bool), 1), float("-inf"))
        at = torch.einsum("hts,shd->thd", torch.softmax(sc, -1), v).reshape(n, d)
        x = x + con_lora(i, 1, at, at @ c["proy"].T)
        h = F.layer_norm(x, (d,), c["ln2w"], c["ln2b"], 1e-5)
        m = con_lora(i, 2, h, h @ c["fc1"].T)
        m = F.gelu(m)
        x = x + con_lora(i, 3, m, m @ c["fc2"].T)
    z = F.layer_norm(x[-1:], (d,), M["lnw"], M["lnb"], 1e-5)
    return (z @ M["cab"].T)[0].numpy()


# ------------------------------------------------------------------ 1-2. verificación
def verificar():
    from motor_cpp import MotorCpp

    CARPETA.mkdir(parents=True, exist_ok=True)
    fallos = []

    def chequeo(nombre, ok, detalle=""):
        print(f"  [{'OK ' if ok else 'FALLA'}] {nombre}" + (f"  -> {detalle}" if detalle else ""), flush=True)
        if not ok:
            fallos.append(nombre)

    # configuración reducida (rápida) y la real del diseño; ambas con las 4 combinaciones relevantes de formato
    casos = [("reducida: d=128, 3 capas, 8 cabezas / 2 KV, T=256, embedding atado int8, KV fp16", dict(V=500, T=256, d=128, L=3, H=8, HK=2, ff=512, tied=True, emb8=True, kv16=True), (1, 17, 128, 129, 250)),
             ("reducida: sin atar, embedding fp16, KV fp32, GQA 4/4 (= MHA)", dict(V=500, T=256, d=128, L=3, H=4, HK=4, ff=512, tied=False, emb8=False, kv16=False), (1, 40, 200)),
             ("v2-A completa: d=768, 22 capas, 12/4 cabezas, T=1024, atado int8, KV fp16", V2A, (1, 64, 129, 400, 1000))]
    for titulo, cfg, largos in casos:
        print(f"\n[{titulo}]")
        ruta = crear_bin(CARPETA / (nombre_archivo(cfg) + ("_peq" if cfg["d"] < 256 else "") + ".bin"), **cfg)
        M = leer_bin(ruta)
        m = MotorCpp(ruta)
        rng = np.random.default_rng(3)
        info = (ctypes_info(m))
        chequeo("el motor lee la cabecera NUCL0002", info[:6] == [cfg["V"], cfg["T"], cfg["d"], cfg["L"], cfg["H"], cfg["HK"]], str(info))
        for n in largos:
            ids = rng.integers(0, cfg["V"] - 8, size=n).tolist()
            ref = referencia_logits(M, ids)
            got = m.logits(ids)
            dif = float(np.abs(ref - got).max())
            rel = dif / float(np.abs(ref).max())
            chequeo(f"{n:4d} tokens: logits motor vs PyTorch fp32 (dif. máx. {dif:.2e}, relativa {rel:.1e}) y mismo token siguiente",
                    rel < 2e-3 and int(ref.argmax()) == int(got.argmax()))
        # bloques de prefill: mismos bits con 1 bloque que con muchos
        n = largos[-1]
        ids = rng.integers(0, cfg["V"] - 8, size=n).tolist()
        m.lib.nucleo_config_bloque.argtypes = [__import__("ctypes").c_void_p, __import__("ctypes").c_int]
        m.lib.nucleo_config_bloque(m.h, 1 << 20)
        a = m.logits(ids)
        for b in (128, 64, 7):
            m.lib.nucleo_config_bloque(m.h, b)
            chequeo(f"prefill en bloques de {b} == todo junto (bit a bit, {n} tokens)", np.array_equal(a, m.logits(ids)))
        # adaptador LoRA con GQA
        ruta_l = crear_lora_para(CARPETA / (nombre_archivo(cfg) + ".lora"), cfg)
        m.registrar_experto("x", ruta_l, 0)
        m.cargar_ranura(ruta_l, 0)
        m.lib.nucleo_config_bloque(m.h, 128)
        ids = rng.integers(0, cfg["V"] - 8, size=min(150, cfg["T"] - 10)).tolist()
        m.seleccionar(None)
        base = m.logits(ids)
        m.seleccionar("x")
        con = m.logits(ids)
        ref = referencia_logits(M, ids, leer_lora(ruta_l, M))
        dif = float(np.abs(ref - con).max()) / float(np.abs(ref).max())
        chequeo("LoRA r=16 con qkv de salida d + 2·kvd: motor vs PyTorch", dif < 2e-3 and int(ref.argmax()) == int(con.argmax()), f"relativa {dif:.1e}")
        chequeo("el adaptador cambia los logits (la prueba discrimina) y tibio == base", float(np.abs(base - con).max()) > 1e-3)
        m.seleccionar(None)
        chequeo("adaptador tibio: logits idénticos al base bit a bit", np.array_equal(base, m.logits(ids)))
    print(f"\n{'TODO CORRECTO' if not fallos else 'FALLARON: ' + '; '.join(fallos)}")
    sys.exit(1 if fallos else 0)


def ctypes_info(m):
    import ctypes

    m.lib.nucleo_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    a = (ctypes.c_int * 8)()
    m.lib.nucleo_info(m.h, a)
    return list(a)


# ------------------------------------------------------------------ 3. benchmark
def trabajador(ruta_bin, ruta_lora, largo_prompt, n_gen, con_lora):
    import psutil

    from motor_cpp import MotorCpp

    proc = psutil.Process()
    antes = proc.memory_info().wset
    m = MotorCpp(ruta_bin)
    if ruta_lora:
        for i in range(2):  # los dos adaptadores (Activo + Tibio), como en el sistema real
            m.registrar_experto(f"x{i}", ruta_lora, i)
            m.cargar_ranura(ruta_lora, i)
        m.seleccionar("x0" if con_lora else None)
    rng = np.random.default_rng(0)
    res = {}
    tope = m.bloque - n_gen - 2  # m.bloque = ventana del modelo (v1: 512)
    for n in [x for x in (32, 128, 512, largo_prompt) if x <= tope]:
        ids = rng.integers(0, 1000, size=n).tolist()
        m.generar(ids, 1.0, 2)  # calentar
        pf = []
        for _ in range(3):
            m.generar(ids, 1.0, 1)
            pf.append(m.ultimos_tiempos[0])
        res[f"prefill_{n}_ms"] = sorted(pf)[1]
    for n in [x for x in (64, 512, largo_prompt) if x <= tope]:
        ids = rng.integers(0, 1000, size=n).tolist()
        m.generar(ids, 1.0, 4)
        dec = []
        for _ in range(3):
            m.generar(ids, 1.0, n_gen)
            _, dms, pasos = m.ultimos_tiempos
            dec.append(dms / max(1, pasos))
        res[f"decod_ctx{n}_ms_tok"] = sorted(dec)[1]
    mem = proc.memory_info()
    res.update(pico_mb=mem.peak_wset / 1e6, antes_mb=antes / 1e6, adaptadores_mb=m.bytes_lora / 1e6 if ruta_lora else 0.0,
               bin_mb=Path(ruta_bin).stat().st_size / 1e6)
    print(json.dumps(res))


def correr(ruta_bin, ruta_lora=None, hilos=None, con_lora=False, largo_prompt=950):
    env = dict(os.environ)
    if hilos:
        env["OMP_NUM_THREADS"] = str(hilos)
    cmd = [sys.executable, __file__, "--trabajador", str(ruta_bin), str(ruta_lora or ""), str(largo_prompt), "50", "1" if con_lora else "0"]
    for _ in range(3):  # el pico de RAM varía un poco: se reporta el peor de 3 corridas y el resto de métricas de la última
        salida = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=RAIZ).stdout.strip().splitlines()[-1]
        r = json.loads(salida)
        pico = max(r["pico_mb"], locals().get("pico_prev", 0))
        pico_prev = pico
    r["pico_mb"] = pico
    return r


def bench_v1():
    """Solo la referencia v1 (mismo arnés), por separado."""
    ref = {}
    for etiqueta, hilos in (("todos los hilos", None), ("1 hilo", 1)):
        r = correr(RAIZ / "modelos" / "nucleo_sft_v3.bin", None, hilos=hilos, largo_prompt=450)
        ref[etiqueta] = r
        print(f"  v1 ({etiqueta}): {r['decod_ctx64_ms_tok']:.2f} ms/tok (ctx 64) · {r['decod_ctx450_ms_tok']:.2f} (ctx 450) | prefill 32/128/450 tok: "
              f"{r['prefill_32_ms']:.0f} / {r['prefill_128_ms']:.0f} / {r['prefill_450_ms']:.0f} ms | RAM pico {r['pico_mb']:.1f} MB (antes {r['antes_mb']:.1f})", flush=True)
    (RAIZ / "resultados" / "ETAPA4_fase0_v1.json").write_text(json.dumps(ref, indent=1), encoding="utf-8")


def bench():
    CARPETA.mkdir(parents=True, exist_ok=True)
    print("Fase 0 · benchmark con pesos ALEATORIOS en este equipo (Ryzen 7 7800X3D, 8 núcleos / 16 hilos)\n")
    resultados = {}
    for nombre, cfg in VARIANTES.items():
        ruta = CARPETA / (nombre_archivo(cfg) + ".bin")
        if not ruta.exists():
            crear_bin(ruta, **cfg)
        lora = crear_lora_para(CARPETA / (nombre_archivo(cfg) + ".lora"), cfg)
        r = correr(ruta, lora)
        resultados[nombre] = r
        print(f"{nombre}\n   .bin {r['bin_mb']:.1f} MB | 2 LoRA {r['adaptadores_mb']:.1f} MB | RAM pico del proceso {r['pico_mb']:.1f} MB "
              f"(antes de cargar {r['antes_mb']:.1f})", flush=True)
    cfg = V2A
    ruta = CARPETA / (nombre_archivo(cfg) + ".bin")
    lora = CARPETA / (nombre_archivo(cfg) + ".lora")
    print("\nVelocidad de la configuración del diseño (A)")
    vel = {}
    for etiqueta, hilos, con_lora in (("todos los hilos, sin adaptador", None, False), ("todos los hilos, LoRA activo", None, True),
                                      ("1 hilo, sin adaptador", 1, False)):
        r = correr(ruta, lora, hilos=hilos, con_lora=con_lora)
        vel[etiqueta] = r
        print(f"  {etiqueta}: decodificación {r['decod_ctx64_ms_tok']:.2f} ms/tok (ctx 64) · {r['decod_ctx512_ms_tok']:.2f} (ctx 512) · "
              f"{r['decod_ctx950_ms_tok']:.2f} (ctx 950)  |  prefill 32/128/512/950 tok: {r['prefill_32_ms']:.0f} / {r['prefill_128_ms']:.0f} / "
              f"{r['prefill_512_ms']:.0f} / {r['prefill_950_ms']:.0f} ms", flush=True)
    # v1 con el mismo arnés, como referencia directa
    v1 = RAIZ / "modelos" / "nucleo_sft_v3.bin"
    ref = {}
    for etiqueta, hilos in (("todos los hilos", None), ("1 hilo", 1)):
        r = correr(v1, None, hilos=hilos, largo_prompt=450)
        ref[etiqueta] = r
        print(f"  v1 (referencia, {etiqueta}): {r['decod_ctx64_ms_tok']:.2f} ms/tok (ctx 64) · {r['decod_ctx450_ms_tok']:.2f} (ctx 450) | RAM pico {r['pico_mb']:.1f} MB"
              if "decod_ctx450_ms_tok" in r else f"  v1 ({etiqueta}): {r}", flush=True)
    (RAIZ / "resultados" / "ETAPA4_fase0.json").write_text(json.dumps({"variantes": resultados, "velocidad_v2A": vel, "referencia_v1": ref}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--trabajador":
        trabajador(sys.argv[2], sys.argv[3] or None, int(sys.argv[4]), int(sys.argv[5]), sys.argv[6] == "1")
        sys.exit(0)
    ap = argparse.ArgumentParser()
    ap.add_argument("orden", choices=["verificar", "bench", "bench_v1"])
    a = ap.parse_args()
    {"verificar": verificar, "bench": bench, "bench_v1": bench_v1}[a.orden]()

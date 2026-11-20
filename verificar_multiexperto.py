"""Verificación de la conmutación multi-experto (Etapa 3, paso 2): caché de 2 ranuras en motor.cpp + enrutador de 3 estados.

Seis métricas obligatorias:
  1. cambio entre dos expertos TIBIOS por puntero < 0,1 ms
  2. RAM pico del proceso con ambos expertos cargados <= 118 MB
  3. núcleo base sin degradación (71,6 / 98,1 / 100 %) con los expertos dormidos o tibios, y logits idénticos bit a bit
  4. experto_codigo sin degradación (82,2 %) con experto_redaccion tibio en la otra ranura (y logits idénticos al motor anterior)
  5. 0 colisiones en una conversación multi-dominio (nunca dos expertos activos)
  6. pesos congelados con el mismo SHA-256

  python verificar_multiexperto.py [--rapido]       # --rapido omite las evaluaciones largas (3 y 4)
"""
import argparse
import hashlib
import json
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).parent
BIN = RAIZ / "modelos" / "nucleo_sft_v3.bin"
COD = RAIZ / "modelos" / "experto_codigo.lora"
RED = RAIZ / "modelos" / "experto_redaccion.lora"
DLL_ANTERIOR = RAIZ / "modelos" / "archivo" / "motor_etapa2_ref.dll"  # motor de la Etapa 2 (un solo adaptador), referencia de bit-exactitud
CONGELADOS = ["modelos/nucleo_sft_v3.pt", "modelos/nucleo_sft_v3.bin", "modelos/experto_codigo.lora", "modelos/experto_redaccion.lora"]
FALLOS = []


def chequeo(nombre, ok, detalle=""):
    print(f"  [{'OK ' if ok else 'FALLA'}] {nombre}" + (f"  -> {detalle}" if detalle else ""), flush=True)
    if not ok:
        FALLOS.append(nombre)


def sha(ruta):
    h = hashlib.sha256()
    with open(RAIZ / ruta, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def prompts(fmt, n=60):
    filas = [json.loads(l) for l in open(RAIZ / "datos" / "experto_eval_B2.jsonl", encoding="utf-8")][::17][: n // 2]
    filas += [json.loads(l) for l in open(RAIZ / "datos" / "redaccion_eval.jsonl", encoding="utf-8")][::11][: n // 2]
    out = []
    for r in filas:
        p = fmt.ids_prompt(r["pregunta"])
        out.append(p)
        if "consulta" in r:
            out.append(p + fmt.texto(f" {r['pref']}: " + r["consulta"]) + [fmt.herramienta] + fmt.ids_tras_herramienta(r["resultados"], r.get("tope")))
    return out


# ---------------------------------------------------------------- RAM (cada configuración en un proceso aparte)
def trabajador_ram(n_expertos):
    import psutil

    from motor_cpp import MotorCpp
    from protocolo import Formato

    proc = psutil.Process()
    fmt = Formato()
    ps = prompts(fmt, 40)
    antes = proc.memory_info().wset
    m = MotorCpp(BIN)
    nombres = []
    for i, (nombre, ruta) in enumerate((("codigo", COD), ("redaccion", RED))[:n_expertos]):
        m.registrar_experto(nombre, ruta, i)
        m.cargar_ranura(ruta, i)
        nombres.append(nombre)
    for k, p in enumerate(ps):  # genera alternando experto (o sin ninguno) para tocar toda la memoria de trabajo
        m.seleccionar(nombres[k % len(nombres)] if nombres and k % 3 != 2 else None)
        m.generar(p, 1.0, 60)
    mem = proc.memory_info()
    print(json.dumps({"expertos": n_expertos, "antes_mb": antes / 1e6, "pico_mb": mem.peak_wset / 1e6, "final_mb": mem.wset / 1e6,
                      "bytes_lora_mb": m.bytes_lora / 1e6}))


def medir_ram():
    print("\n[2] RAM pico del proceso (un proceso por configuración, 40 prompts generando)")
    res = {}
    for n in (0, 1, 2):
        mejor = None
        for _ in range(3):  # el pico varía un poco entre corridas: se reporta el peor de 3
            salida = subprocess.run([sys.executable, __file__, "--ram", str(n)], capture_output=True, text=True, cwd=RAIZ).stdout.strip().splitlines()[-1]
            r = json.loads(salida)
            mejor = r if mejor is None or r["pico_mb"] > mejor["pico_mb"] else mejor
        res[n] = mejor
        print(f"   {n} experto(s) cargado(s): pico {mejor['pico_mb']:.1f} MB (adaptadores {mejor['bytes_lora_mb']:.2f} MB)")
    chequeo("RAM pico con ambos expertos <= 118 MB", res[2]["pico_mb"] <= 118, f"{res[2]['pico_mb']:.1f} MB")
    return res


# ---------------------------------------------------------------- bit-exactitud
def exactitud(fmt):
    from motor_cpp import MotorCpp

    print("\n[3-4] Logits idénticos bit a bit (motor nuevo vs motor de la Etapa 2)")
    ps = prompts(fmt, 60)
    ref_base = MotorCpp(BIN, dll=DLL_ANTERIOR)
    ref_cod = MotorCpp(BIN, dll=DLL_ANTERIOR)
    ref_cod.cargar_lora(COD)
    ref_red = MotorCpp(BIN, dll=DLL_ANTERIOR)
    ref_red.cargar_lora(RED)
    nuevo = MotorCpp(BIN)
    for i, (n, r) in enumerate((("codigo", COD), ("redaccion", RED))):
        nuevo.registrar_experto(n, r, i)
        nuevo.cargar_ranura(r, i)

    def comparar(modo, ref):
        nuevo.seleccionar(modo)
        mx = max(float(np.abs(nuevo.logits(p) - ref.logits(p)).max()) for p in ps)
        return mx

    d0 = comparar(None, ref_base)
    chequeo(f"ambos TIBIOS (cargados, fuera del forward) == núcleo base ({len(ps)} prompts)", d0 == 0.0, f"diferencia máxima {d0}")
    d1 = comparar("codigo", ref_cod)
    chequeo("experto_codigo activo (redacción tibio) == motor anterior con experto_codigo", d1 == 0.0, f"diferencia máxima {d1}")
    d2 = comparar("redaccion", ref_red)
    chequeo("experto_redaccion activo (código tibio) == motor anterior con experto_redaccion", d2 == 0.0, f"diferencia máxima {d2}")
    d3 = comparar(None, ref_base)
    chequeo("tras alternar vuelve a ser idéntico al núcleo base", d3 == 0.0, f"diferencia máxima {d3}")
    mx = max(float(np.abs(ref_cod.logits(p) - ref_red.logits(p)).max()) for p in ps)
    chequeo("los dos adaptadores son realmente distintos (la prueba discrimina)", mx > 0.01, f"diferencia código vs redacción {mx:.3f}")


# ---------------------------------------------------------------- latencia y enfriamiento
def latencia():
    from motor_cpp import MotorCpp

    print("\n[1] Cambio entre expertos tibios por puntero")
    m = MotorCpp(BIN)
    for i, (n, r) in enumerate((("codigo", COD), ("redaccion", RED))):
        m.registrar_experto(n, r, i)
        m.cargar_ranura(r, i)
    lib, h = m.lib, m.h
    tiempos = []
    for k in range(20000):
        t = time.perf_counter_ns()
        lib.nucleo_lora_seleccionar(h, k & 1)
        tiempos.append(time.perf_counter_ns() - t)
    ms = sorted(x / 1e6 for x in tiempos)
    print(f"   llamada C directa (ctypes): mediana {st.median(ms) * 1000:.1f} µs | p99 {ms[int(len(ms) * .99)] * 1000:.1f} µs | máx {ms[-1] * 1000:.1f} µs")
    tiempos = []
    for k in range(20000):
        t = time.perf_counter_ns()
        m.seleccionar("codigo" if k & 1 else "redaccion")
        tiempos.append(time.perf_counter_ns() - t)
    ms2 = sorted(x / 1e6 for x in tiempos)
    print(f"   envoltorio Python seleccionar(nombre): mediana {st.median(ms2) * 1000:.1f} µs | p99 {ms2[int(len(ms2) * .99)] * 1000:.1f} µs | máx {ms2[-1] * 1000:.1f} µs")
    chequeo("cambio tibio<->activo < 0,1 ms (mediana y p99, llamada C)", st.median(ms) < 0.1 and ms[int(len(ms) * .99)] < 0.1,
            f"mediana {st.median(ms) * 1000:.1f} µs, p99 {ms[int(len(ms) * .99)] * 1000:.1f} µs")
    chequeo("cambio < 0,1 ms también con el envoltorio Python (p99)", ms2[int(len(ms2) * .99)] < 0.1, f"p99 {ms2[int(len(ms2) * .99)] * 1000:.1f} µs")


def enfriamiento():
    from motor_cpp import MotorCpp

    print("\n[Caché] Activo -> Tibio -> Frío")
    m = MotorCpp(BIN)
    m.vida_tibia(6)
    for i, (n, r) in enumerate((("codigo", COD), ("redaccion", RED))):
        m.registrar_experto(n, r, i)
        m.cargar_ranura(r, i)
    chequeo("ambos cargan tibios", m.estado("codigo") == "tibio" and m.estado("redaccion") == "tibio")
    m.seleccionar("codigo")
    chequeo("seleccionar deja 1 activo y el otro tibio", m.estado("codigo") == "activo" and m.estado("redaccion") == "tibio")
    bytes_dos = m.bytes_lora
    for _ in range(5):
        m.turno()
    chequeo("el activo no decae; el tibio pierde 1 de vida por turno", m.estado("codigo") == "activo" and m.vida("redaccion") == 1, f"vida {m.vida('redaccion')}")
    desc = m.turno()
    chequeo("al llegar a 0 el tibio se descarga (frío) y libera su memoria", desc == 1 and m.estado("redaccion") == "frío" and m.bytes_lora < bytes_dos,
            f"{bytes_dos / 1e6:.2f} -> {m.bytes_lora / 1e6:.2f} MB")
    t = time.perf_counter()
    r = m.seleccionar("redaccion")
    ms = (time.perf_counter() - t) * 1000
    chequeo("un experto frío se recarga solo al pedirlo", r == "recargado" and m.estado("redaccion") == "activo" and m.estado("codigo") == "tibio",
            f"recarga {ms:.1f} ms")
    m.seleccionar(None)
    chequeo("seleccionar(None) deja a todos tibios (núcleo base)", m.estado("codigo") == "tibio" and m.estado("redaccion") == "tibio")


# ---------------------------------------------------------------- calidad
def calidad(fmt):
    from evaluar_experto import evaluar_experto
    from inferir import evaluar as evaluar_general
    from motor_cpp import MotorCpp

    print("\n[3-4] Calidad con el motor multi-slot (C++)")
    m = MotorCpp(BIN)
    for i, (n, r) in enumerate((("codigo", COD), ("redaccion", RED))):
        m.registrar_experto(n, r, i)
        m.cargar_ranura(r, i)
    m.seleccionar(None)
    g = evaluar_general(m, fmt, "cpu", ruta=RAIZ / "datos" / "sft_eval_real.jsonl", n_por_tipo=300, penalizacion=1.1)
    print("   núcleo base con ambos expertos TIBIOS:", {t: {k: round(v, 3) for k, v in d.items()} for t, d in g.items()})
    chequeo("núcleo base: hechos 71,6 %", abs(g["buscar_ok"]["respuesta_exacta"] - 0.716) < 0.0005, f"{g['buscar_ok']['respuesta_exacta']:.1%}")
    chequeo("núcleo base: abstención 98,1 %", abs(g["irrelevante"]["se_abstuvo"] - 0.981) < 0.0005, f"{g['irrelevante']['se_abstuvo']:.1%}")
    chequeo("núcleo base: conversación/vacío 100 %", g["vacio"]["se_abstuvo"] == 1.0, f"{g['vacio']['se_abstuvo']:.1%}")
    m.seleccionar("codigo")
    r = evaluar_experto(m, fmt, "cpu", ruta=RAIZ / "datos" / "experto_eval_B2.jsonl", pen=1.0)
    print(f"   experto_codigo ACTIVO con redacción tibio: puntaje {r['_puntaje']:.1%}")
    chequeo("experto_codigo 82,2 % (±0,3 por redondeo de motor)", r["_puntaje"] >= 0.819, f"{r['_puntaje']:.1%}")
    m.seleccionar("redaccion")
    r2 = evaluar_experto(m, fmt, "cpu", ruta=RAIZ / "datos" / "redaccion_eval.jsonl", pen=1.0)
    print(f"   experto_redaccion ACTIVO con código tibio: puntaje {r2['_puntaje']:.1%} (PyTorch: 56,2 %)")
    chequeo("experto_redaccion conserva su puntaje (56,2 % ±1)", abs(r2["_puntaje"] - 0.562) <= 0.01, f"{r2['_puntaje']:.1%}")


# ---------------------------------------------------------------- conversación multi-dominio
CONVERSACION = [
    "hola, ¿cómo estás?", "Recuerda que mi proyecto se llama TEST-IA", "¿Qué es la recursividad?", "¿y para qué sirve?",
    "Ejecuta: sum([x*x for x in range(1, 6)])", "Corrige la ortografía: ayer fui al mercado y compre berduras",
    "¿y la tilde de compré?", "Hazlo más formal: oye, mándame la factura", "¿Cómo se llama mi proyecto?",
    "¿Cuál es la diferencia entre porque y por qué?", "¿Cómo se usa merge en pandas?", "Explícame el dequeísmo",
    "¿Quién fue Gabriela Mistral?", "Simplifica esta función: def f(x): return x*2", "Mejora la redacción de este correo: hola, quiero un reembolso",
    "gracias", "ok", "cuéntame más", "¿Qué es un decorador?", "Corrige: el ni;o juga en la plasa", "¿Qué es un hiato?",
    "Ejecuta: print(len('hola'))", "Reescribe en tono formal: Dame el archivo ya.", "¿Qué hora es en Tokio?", "¿Qué es una lista en Python?",
    "Acórtalo sin cambiar el sentido: la verdad es que llegué tarde", "¿Cómo funciona un diccionario?", "1+1", "¿Qué es el Teide?", "gracias",
]


def web_local(consulta, modo=None):
    """Cadena de búsqueda sin red: bases locales de cada dominio y, si no hay ficha, «Sin resultados.» (determinista)."""
    from herramientas import SIN_RESULTADOS, buscar_ficha
    from redaccion_fichas import buscar_ficha_gramatica

    local = buscar_ficha(consulta) if modo == "codigo" else (buscar_ficha_gramatica(consulta) if modo == "redaccion" else None)
    return local or SIN_RESULTADOS


def conversacion(fmt):
    import tempfile

    from inferir import Sesion
    from motor_cpp import MotorCpp

    print("\n[5] Conversación multi-dominio de 30 turnos (motor C++, búsqueda web simulada)")
    m = MotorCpp(BIN)
    with tempfile.TemporaryDirectory() as d:
        s = Sesion(m, fmt, "cpu", motor=True, expertos={"codigo": str(COD), "redaccion": str(RED)}, buscador=web_local,
                   ruta_memoria=Path(d) / "m.json")
        modos, max_activos, recargas = [], 0, 0
        for p in CONVERSACION:
            r, tz, modo = s.atender(p)
            est = s.estados()
            max_activos = max(max_activos, sum(v == "activo" for v in est.values()))
            modos.append(modo)
            print(f"   [{str(modo):9s}] {p[:58]:60s} -> {r[:50]!r}")
        usados = {x for x in modos if x}
        chequeo("usó los tres estados (dormido, codigo, redaccion)", usados == {"codigo", "redaccion"} and None in modos, str(sorted(map(str, set(modos)))))
        chequeo("nunca hubo más de 1 experto activo", max_activos <= 1, f"máximo simultáneo {max_activos}")
        chequeo("0 colisiones (activos != lo que decidió el enrutador)", s.colisiones == 0, f"{s.colisiones} colisiones")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ram", type=int, default=None, help="(interno) mide un solo proceso con N expertos")
    ap.add_argument("--rapido", action="store_true")
    args = ap.parse_args()
    if args.ram is not None:
        trabajador_ram(args.ram)
        return
    from protocolo import Formato

    fmt = Formato()
    antes = {r: sha(r) for r in CONGELADOS}
    latencia()
    enfriamiento()
    exactitud(fmt)
    medir_ram()
    conversacion(fmt)
    if not args.rapido:
        calidad(fmt)
    print("\n[6] SHA-256 de los pesos congelados")
    for r in CONGELADOS:
        chequeo(f"{r} intacto", antes[r] == sha(r), sha(r)[:16] + "…")
    print(f"\n{'TODO CORRECTO' if not FALLOS else 'FALLARON: ' + '; '.join(FALLOS)}")
    sys.exit(1 if FALLOS else 0)


if __name__ == "__main__":
    main()

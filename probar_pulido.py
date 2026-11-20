"""Batería en vivo de los tres arreglos deterministas de la Etapa 3 (sin tocar pesos): motor C++ con núcleo + los dos expertos.

  1. Memoria de trabajo sin contaminación: «¿y la tilde de compré?» no arrastra el turno anterior; las referencias anafóricas reales sí.
  2. Búsqueda difusa contra las fichas locales: «recursbilidad» (error del modelo) encuentra «recursión» sin ir a internet.
  3. Corrección ortográfica determinista: «Corrige: …» se resuelve en capa 1 (sin red neuronal) con corrector.py.

La búsqueda web está bloqueada a propósito: si algún turno llegara a internet, la prueba falla.

  python probar_pulido.py          # sale con código 1 si algún chequeo falla
"""
import hashlib
import sys
import tempfile
import time
from pathlib import Path

from herramientas import buscar_ficha_difusa, capa1
from inferir import Sesion
from motor_cpp import MotorCpp
from protocolo import Formato

RAIZ = Path(__file__).parent
CONGELADOS = ["modelos/nucleo_sft_v3.pt", "modelos/nucleo_sft_v3.bin", "modelos/experto_codigo.lora", "modelos/experto_redaccion.lora"]
FALLOS = []
LLAMADAS_WEB = []


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


def sin_internet(consulta, modo=None, memoria=None):
    """buscar_web real (memoria + fichas exactas y difusas) pero si hiciera falta ir a ddgs se registra y se devuelve «Sin resultados.»."""
    import herramientas

    local = herramientas.buscar_memoria(consulta, memoria)
    if local:
        return local
    if modo == "codigo":
        local = herramientas.buscar_ficha(consulta) or herramientas.buscar_ficha_difusa(consulta)
    elif modo == "redaccion":
        from redaccion_fichas import buscar_ficha_gramatica

        local = buscar_ficha_gramatica(consulta) or herramientas.buscar_ficha_difusa(consulta)
    if local:
        return local
    LLAMADAS_WEB.append(consulta)
    return herramientas.SIN_RESULTADOS


def main():
    antes = {r: sha(r) for r in CONGELADOS}
    m, fmt = MotorCpp(RAIZ / "modelos" / "nucleo_sft_v3.bin"), Formato()
    with tempfile.TemporaryDirectory() as d:
        s = Sesion(m, fmt, "cpu", motor=True, expertos={"codigo": str(RAIZ / "modelos" / "experto_codigo.lora"),
                                                        "redaccion": str(RAIZ / "modelos" / "experto_redaccion.lora")},
                   buscador=sin_internet, ruta_memoria=Path(d) / "m.json")

        def turno(p):
            r, tz, modo = s.atender(p)
            print(f"   P: {p}   [experto: {modo or 'dormido'}]")
            for t in tz:
                print("      ", t[:140])
            print(f"   R: {r[:140]}")
            return r, tz, modo

        # ------------------------------------------------------------ 1. memoria de trabajo limpia
        print("\n[1] Memoria de trabajo sin contaminación")
        turno("Corrige: ayer fui al mercado y compre berduras")
        T = s.trabajo
        for q, esperado in [("¿y la tilde de compré?", False), ("¿y el hiato?", False), ("¿y la pila en Python?", False),
                            ("¿y cuándo nació?", True), ("¿y eso?", True), ("Dame un ejemplo", True), ("¿Qué hizo él?", True),
                            ("¿Cuál es la capital de Chile?", False)]:
            chequeo(f"{q!r} {'recibe' if esperado else 'NO recibe'} el turno anterior", T.es_seguimiento(q) == esperado)
        r, tz, modo = turno("¿y la tilde de compré?")
        chequeo("la consulta B: no está contaminada con el turno anterior",
                not any(("mercado" in t.lower() or "verduras" in t.lower()) for t in tz[:1]), tz[0] if tz else "")
        turno("¿Quién fue Gabriela Mistral?")
        ctx = T.contextualizar("¿y cuándo nació?")
        chequeo("«¿y cuándo nació?» sí recibe «Gabriela Mistral»", "Mistral" in ctx, ctx)

        # ------------------------------------------------------------ 2. búsqueda difusa
        print("\n[2] Búsqueda difusa contra las fichas locales (difflib, umbral 0,75)")
        for typo, esperada in [("recursbilidad programación", "recursión"), ("polimorfimso", "polimorfismo"), ("hiatto", "hiato"),
                               ("pilas", "pila"), ("dequeismo", "dequeísmo"), ("recursividad", "recursión")]:
            t0 = time.perf_counter()
            r = buscar_ficha_difusa(typo)
            ms = (time.perf_counter() - t0) * 1000
            chequeo(f"{typo!r} -> ficha «{esperada}» ({ms:.2f} ms, sin red)", bool(r) and r.startswith(f"1. {esperada} - base local"), (r or "None")[:60])
        for ajeno in ("capital de Chile", "Teide", "Gabriela Mistral", "Plutón"):
            chequeo(f"{ajeno!r} no cae en ninguna ficha", buscar_ficha_difusa(ajeno) is None)
        LLAMADAS_WEB.clear()
        r, tz, modo = turno("¿Qué es la recursividad?")
        chequeo("el enrutador despierta el experto de código", modo == "codigo")
        chequeo("la respuesta sale de la ficha local «recursión» (el modelo escribió su B: con o sin error)",
                any("[herramienta] 1. recursión - base local" in t for t in tz) and "recursión" in r.lower(), r[:80])
        chequeo("no se consultó internet", not LLAMADAS_WEB, str(LLAMADAS_WEB))

        # ------------------------------------------------------------ 3. corrección determinista
        print("\n[3] Corrección ortográfica determinista (capa 1)")
        casos = [("Corrige: ayer fui al mercado y compre berduras", "Ayer fui al mercado y compre verduras."),
                 ("Corrige la ortografía: el ni;o juega en la plasa", "El niño juega en la plaza."),
                 ("Corrige: tambien quiero un cafe", "También quiero un café."),
                 ("Corrige la ortografía: hola , que tal ?", "Hola, ¿qué tal?"),
                 ("Corrige: ablamos mañana sobre el informe", "Hablamos mañana sobre el informe."),
                 ("Corrige: Hola, ¿cómo estás?", "El texto ya está bien escrito.")]
        for entrada, esperado in casos:
            t0 = time.perf_counter()
            r, tz, modo = s.atender(entrada)
            ms = (time.perf_counter() - t0) * 1000
            print(f"   P: {entrada}\n   R: {r}   [{ms:.1f} ms, {tz}]")
            chequeo(f"«{entrada[:46]}…» -> resuelto en capa 1 y correcto", tz == ["[capa 1, sin IA]"] and r == esperado, f"{r!r}")
        r, tz, modo = turno("Corrige este código: print('hola'")
        chequeo("«Corrige este código: …» NO lo toma el corrector de texto", tz != ["[capa 1, sin IA]"])
        chequeo("capa1() sin sesión también lo resuelve", capa1("Corrige: tambien quiero un cafe") == "También quiero un café.")
        chequeo("la web nunca se tocó en toda la batería", not LLAMADAS_WEB, str(LLAMADAS_WEB))
        chequeo("0 colisiones entre expertos", s.colisiones == 0, str(s.colisiones))

    print("\n[SHA-256 de los pesos congelados]")
    for r in CONGELADOS:
        chequeo(f"{r} intacto", antes[r] == sha(r), sha(r)[:16] + "…")
    print(f"\n{'TODO CORRECTO' if not FALLOS else 'FALLARON: ' + '; '.join(FALLOS)}")
    sys.exit(1 if FALLOS else 0)


if __name__ == "__main__":
    main()

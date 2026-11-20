"""Prueba automatizada multi-turno de la memoria externa con enfriamiento (Etapa 3, paso 1).

Escenarios (cada uno con una memoria nueva en un archivo temporal; datos/memoria.json no se toca):
  1. experto DORMIDO : guardar en capa 1 -> recuperar con B: -> el núcleo responde con el dato
  2. experto ACTIVO  : lo mismo con experto_codigo despierto (el enrutador lo despierta por «Python»), sin colisión
  3. ENFRIAMIENTO    : 10 turnos sin mención -> temperatura 0 -> archivado -> el núcleo se abstiene; un dato reforzado sobrevive
  4. MEMORIA DE TRABAJO: «¿y cuándo nació?» tras «¿Quién fue Gabriela Mistral?», con tope de 80 tokens y ventana de 512
La búsqueda web se simula (sin red) para que la prueba sea determinista; el núcleo y el experto son los reales.

  python probar_memoria.py [--motor]     # sale con código 1 si algún chequeo falla
"""
import argparse
import hashlib
import sys
import tempfile
from pathlib import Path

from herramientas import SIN_RESULTADOS
from inferir import Sesion, cargar
from modelo import elegir_dispositivo
from protocolo import SIN_INFO, Formato

RAIZ = Path(__file__).parent
CONGELADOS = ["modelos/nucleo_sft_v3.pt", "modelos/nucleo_sft_v3.bin", "modelos/experto_codigo.lora"]
INTERMEDIO = ["¿Qué es el Teide?", "¿Cuál es la capital de Chile?", "hola, ¿cómo estás?", "Explícame la fotosíntesis.",
              "¿Quién fue Gabriela Mistral?", "Dame una receta de empanadas.", "¿Qué sabes de Tenerife?", "¿Qué hora es en Tokio?",
              "Cuéntame sobre los volcanes.", "¿Qué es la relatividad?"]


def sha(ruta):
    h = hashlib.sha256()
    with open(RAIZ / ruta, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def web_simulada(consulta, modo=None):
    q = consulta.lower()
    if "mistral" in q:
        return ("1. Gabriela Mistral - Wikipedia: Gabriela Mistral (Vicuña, 7 de abril de 1889 - Nueva York, 10 de enero de 1957) "
                "fue una poeta, diplomática y pedagoga chilena. Premio Nobel de Literatura en 1945…")
    return SIN_RESULTADOS


FALLOS = []


def chequeo(nombre, ok, detalle=""):
    print(f"  [{'OK ' if ok else 'FALLA'}] {nombre}" + (f"  -> {detalle}" if detalle else ""))
    if not ok:
        FALLOS.append(nombre)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--motor", action="store_true")
    ap.add_argument("--modelo", default=str(RAIZ / "modelos" / "nucleo_sft_v3.pt"))
    args = ap.parse_args()
    antes = {r: sha(r) for r in CONGELADOS}
    disp = elegir_dispositivo()
    if args.motor:
        from motor_cpp import MotorCpp

        modelo, fmt = MotorCpp(Path(args.modelo).with_suffix(".bin")), Formato()
        experto = str(RAIZ / "modelos" / "experto_codigo.lora")
    else:
        modelo, fmt = cargar(args.modelo, disp)
        experto = str(RAIZ / "modelos" / "archivo" / "experto_r16_B2_e3.lora.pt")  # mismos pesos que experto_codigo.lora, formato PyTorch
    print(f"=== Motor: {'C++' if args.motor else 'PyTorch (' + disp + ')'} ===")

    def sesion(con_experto, ruta):
        return Sesion(modelo, fmt, disp, motor=args.motor, experto=experto if con_experto else None, pen=1.1, buscador=web_simulada,
                      ruta_memoria=ruta)

    def turno(s, p):
        r, traza, modo = s.atender(p)
        print(f"   P: {p}   [experto: {modo or 'dormido'}]")
        for t in traza:
            print("      ", t[:150])
        print(f"   R: {r}")
        return r, traza, modo

    with tempfile.TemporaryDirectory() as d:
        # ---------------------------------------------------------------- 1. experto dormido
        print("\n[1] Experto dormido")
        s = sesion(False, Path(d) / "m1.json")
        r, tz, _ = turno(s, "Recuerda que mi proyecto se llama TEST-IA")
        chequeo("capa 1 guarda y confirma sin red neuronal", tz == ["[capa 1, sin IA]"] and "TEST-IA" in r, r)
        chequeo("temperatura inicial 10", s.memoria.temperatura("proyecto") == 10)
        r, tz, _ = turno(s, "¿Cómo se llama mi proyecto?")
        chequeo("el núcleo recupera el dato vía B:", "TEST-IA" in r, r)
        chequeo("la memoria fue la fuente (no la web)", any("[herramienta] 1. Mi proyecto" in t for t in tz))
        chequeo("refuerzo: 10 - 1 (turno) + 3 = 12", s.memoria.temperatura("proyecto") == 12, str(s.memoria.temperatura("proyecto")))

        # ---------------------------------------------------------------- 2. experto activo
        print("\n[2] Experto de código activo")
        s = sesion(True, Path(d) / "m2.json")
        _, _, m0 = turno(s, "Recuerda que mi proyecto se llama TEST-IA")
        r, tz, modo = turno(s, "En Python, ¿cómo se llama mi proyecto?")
        chequeo("el enrutador despertó al experto", modo == "codigo")
        chequeo("recupera el dato con el experto activo", "TEST-IA" in r, r)
        r, tz, modo = turno(s, "Ejecuta: sum([x*x for x in range(1, 6)])")
        chequeo("el experto sigue ejecutando código (sin colisión)", modo == "codigo" and "55" in " ".join(tz), r)
        chequeo("la memoria sigue viva tras el turno de código", s.memoria.temperatura("proyecto") is not None)

        # ---------------------------------------------------------------- 3. enfriamiento
        print("\n[3] Enfriamiento: 10 turnos sin mención")
        s = sesion(False, Path(d) / "m3.json")
        turno(s, "Recuerda que mi proyecto se llama TEST-IA")
        turno(s, "Anota que mi color favorito es el azul")
        for i, p in enumerate(INTERMEDIO, 1):
            if i == 4:  # refuerzo del segundo dato a mitad de camino
                r, _, _ = turno(s, "¿Cuál es mi color favorito?")
                chequeo("(turno 4) el dato reforzado se recupera", "azul" in r.lower(), r)
            else:
                turno(s, p)
            print(f"      temperaturas: proyecto={s.memoria.temperatura('proyecto')}  color favorito={s.memoria.temperatura('color favorito')}")
        chequeo("tras 10 turnos el recuerdo no reforzado llegó a 0 y se archivó",
                s.memoria.temperatura("proyecto") is None and any(a["clave_o_entidad"] == "proyecto" for a in s.memoria.archivados))
        chequeo("el recuerdo reforzado sigue vivo", s.memoria.temperatura("color favorito") is not None,
                str(s.memoria.temperatura("color favorito")))
        r, tz, _ = turno(s, "¿Cómo se llama mi proyecto?")
        chequeo("el núcleo se abstiene honestamente", r == SIN_INFO, r)
        chequeo("no inventa el dato", "TEST-IA" not in r)

        # ---------------------------------------------------------------- 4. memoria de trabajo
        print("\n[4] Memoria de trabajo de 2 turnos (tope 80 tokens)")
        s = sesion(False, Path(d) / "m4.json")
        turno(s, "¿Quién fue Gabriela Mistral?")
        ctx = s.trabajo.contextualizar("¿y cuándo nació?")
        n = len(fmt.tok.encode(ctx).ids)
        print(f"   pregunta enviada al núcleo: {ctx!r} ({n} tokens)")
        chequeo("el seguimiento recibe el referente", "Mistral" in ctx)
        chequeo("contexto <= 80 tokens", n <= 80, str(n))
        chequeo("«¿y la tilde de compré?» (término de ficha) NO arrastra el turno anterior",
                s.trabajo.contextualizar("¿y la tilde de compré?") == "¿y la tilde de compré?")
        chequeo("«¿y el hiato?» tampoco", s.trabajo.contextualizar("¿y el hiato?") == "¿y el hiato?")
        r, tz, _ = turno(s, "¿y cuándo nació?")
        chequeo("la búsqueda B: conserva el referente", any("mistral" in t.lower() for t in tz[:1]), tz[0])
        chequeo("responde con la fecha", "1889" in r, r)
        # una pregunta larga no debe desbordar jamás: se recorta a 80 tokens
        s.trabajo.registrar("pregunta " + "muy larga " * 80, "respuesta " + "enorme " * 80)
        ctx = s.trabajo.contextualizar("¿y eso qué es?")
        n = len(fmt.tok.encode(ctx).ids)
        chequeo("con turnos enormes el contexto sigue <= 80 tokens", n <= 80, str(n))
        # ventana total: contexto + B: + resultados (tope dinámico) + respuesta < 512
        ids = fmt.ids_prompt(ctx)
        total = len(ids) + 20 + min(330, max(40, 400 - len(ids) - 20)) + 100
        chequeo("ventana total < 512 en el peor caso", total < 512, str(total))

        # ---------------------------------------------------------------- 5. permanente y olvido explícito
        print("\n[5] «Recuerda siempre que…» y «Olvida que…»")
        s = sesion(False, Path(d) / "m5.json")
        r, tz, _ = turno(s, "Recuerda siempre que mi alergia es el maní")
        chequeo("permanente guardado en capa 1", tz == ["[capa 1, sin IA]"] and "para siempre" in r, r)
        turno(s, "Recuerda que mi proyecto se llama TEST-IA")
        for i in range(12):
            s.atender(f"{i + 1}+{i + 2}")  # turnos baratos de capa 1
        chequeo("tras 12 turnos el temporal se enfrió y el permanente no", s.memoria.temperatura("proyecto") is None
                and s.memoria.temperatura("alergia") == 10, str(s.memoria.temperatura("alergia")))
        r, _, _ = turno(s, "¿Cuál es mi alergia?")
        chequeo("el permanente se recupera tras 12 turnos", "maní" in r, r)
        r, tz, _ = turno(s, "Olvida que mi alergia es el maní")
        chequeo("olvido inmediato en capa 1 (sin IA)", tz == ["[capa 1, sin IA]"] and r.startswith("Olvidado"), r)
        chequeo("quedó archivado con motivo", s.memoria.archivados and s.memoria.archivados[-1]["motivo"].startswith("olvidado"))
        r, _, _ = turno(s, "¿Cuál es mi alergia?")
        chequeo("tras olvidar el núcleo se abstiene", r == SIN_INFO, r)

    despues = {r: sha(r) for r in CONGELADOS}
    print("\n=== SHA-256 de los pesos congelados ===")
    for r in CONGELADOS:
        chequeo(f"{r} intacto", antes[r] == despues[r], despues[r][:16] + "…")
    print(f"\n{'TODO CORRECTO' if not FALLOS else 'FALLARON: ' + '; '.join(FALLOS)}")
    sys.exit(1 if FALLOS else 0)


if __name__ == "__main__":
    main()

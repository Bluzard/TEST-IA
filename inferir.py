"""Inferencia del núcleo ajustado: generación, bucle con herramienta y evaluación.

Parada automática: <fin> (termina) o <herramienta> (el entorno ejecuta la búsqueda,
agrega los resultados y le devuelve el turno al modelo).
Penalización por repetición: solo sobre tokens que el modelo ya generó en este turno
(no sobre la pregunta ni los resultados, para no impedir que copie datos).

  python inferir.py "¿Qué es el Teide?"            # uno a uno con búsqueda web real (ddgs)
  python inferir.py --experto modelos/experto_codigo.lora --motor   # sin preguntas: chat interactivo
  python inferir.py --evaluar                      # mide en sft_eval.jsonl con resultados simulados
"""
import argparse
import json
from pathlib import Path

import torch

from herramientas import buscar_memoria, buscar_web, capa1
from modelo import Config, Nucleo, elegir_dispositivo
from protocolo import MAX_TOKENS_RESULTADOS, SIN_INFO, TOPE_EJECUCION, TOPE_EXPERTO, Formato

RAIZ = Path(__file__).parent


def cargar(ruta, dispositivo):
    d = torch.load(ruta, map_location="cpu", weights_only=False)
    modelo = Nucleo(Config(**d["config"]))
    modelo.load_state_dict(d["pesos"])
    return modelo.to(dispositivo).eval(), Formato()


@torch.no_grad()
def generar_lote(modelo, fmt, prompts, dispositivo, penalizacion=1.1, max_nuevos=100):
    """Voraz en lote. Devuelve [(ids_nuevos, token_de_parada)]; parada ∈ {fin, herramienta, None}."""
    if not isinstance(modelo, Nucleo):  # motor C++ (motor_cpp.MotorCpp): mismo contrato, de a un prompt
        return [modelo.generar(p, penalizacion, max_nuevos) for p in prompts]
    B, T = len(prompts), modelo.cfg.bloque
    ids = torch.full((B, T), fmt.relleno, dtype=torch.long)
    largos = torch.tensor([len(p) for p in prompts])
    for i, p in enumerate(prompts):
        ids[i, : len(p)] = torch.tensor(p)
    ids, largos = ids.to(dispositivo), largos.to(dispositivo)
    inicio = largos.clone()
    activo = torch.ones(B, dtype=torch.bool, device=dispositivo)
    paradas = [None] * B
    usados = torch.zeros(B, fmt.vocab, dtype=torch.bool, device=dispositivo)
    filas = torch.arange(B, device=dispositivo)
    for _ in range(max_nuevos):
        if not activo.any():
            break
        tope = int(largos.max())
        with torch.autocast(dispositivo, dtype=torch.bfloat16, enabled=dispositivo == "cuda"):
            logits, _ = modelo(ids[:, :tope])
        l = logits[filas, largos - 1].float()
        if penalizacion != 1.0:
            l = torch.where(usados, torch.where(l > 0, l / penalizacion, l * penalizacion), l)
        sig = l.argmax(-1)
        escribir = activo & (largos < T)
        ids[filas[escribir], largos[escribir]] = sig[escribir]
        largos = largos + escribir.long()
        es_parada = (sig == fmt.fin) | (sig == fmt.herramienta)
        nuevos = escribir & ~es_parada
        usados[filas[nuevos], sig[nuevos]] = True
        for i in (activo & es_parada).nonzero().flatten().tolist():
            paradas[i] = int(sig[i])
        activo = escribir & ~es_parada
    salida = []
    for i in range(B):
        salida.append((ids[i, inicio[i] : largos[i]].tolist(), paradas[i]))
    return salida


def _texto(fmt, ids):
    return fmt.tok.decode([i for i in ids if i not in (fmt.fin, fmt.herramienta, fmt.asistente, fmt.usuario)]).strip()


def _tiempo_real(modelo, fmt, pregunta, partes, dispositivo, buscador, penalizacion):
    """Consultas de hora/fecha (reloj del equipo), clima y datos en vivo (solo con --v2): cada parte se resuelve y se unen sin repetir.
    Las búsquedas se hacen con un turno de herramienta normal: pregunta + «B: consulta» + resultados -> el núcleo responde."""
    from tiempo_real import lugar

    traza, respuestas = ["[tiempo real]"], []
    for tipo, valor in partes:
        if tipo == "texto":
            respuestas.append(valor)
            continue
        resultados = buscador(valor)
        traza += [f"B: {valor}", "[herramienta] " + resultados.replace("\n", " | ")]
        pregunta_modelo = f"¿Cómo está el {valor}?" if valor.startswith("clima ") else pregunta
        ids = fmt.ids_prompt(pregunta_modelo) + fmt.texto(" B: " + valor) + [fmt.herramienta] + fmt.ids_tras_herramienta(resultados, MAX_TOKENS_RESULTADOS)
        nuevo, _ = generar_lote(modelo, fmt, [ids], dispositivo, penalizacion, max_nuevos=100)[0]
        r = _texto(fmt, nuevo).removeprefix("R:").strip()
        traza.append("R: " + r)
        if not r or r.startswith("No tengo información"):  # los resultados no traen el dato: se dice y se apunta a la mejor fuente
            import re

            m = re.match(r"\s*1\.\s*(.+?):", resultados)
            fuente = f" Fuente que encontré: {m.group(1).strip()}." if m else ""
            if valor.startswith("clima "):
                lug = " ".join(w if w in ("de", "del", "la", "las", "los", "el") else w.capitalize() for w in valor.removeprefix("clima ").split())
                r = f"No pude leer la temperatura actual de {lug} en los resultados.{fuente}"
            else:
                r = f"No pude leer ese dato en los resultados.{fuente}"
        respuestas.append(r)
    return " ".join(respuestas), traza


def responder(modelo, fmt, pregunta, dispositivo, buscador=buscar_web, penalizacion=1.1, max_busquedas=2, modo=None,
              memoria=None, trabajo=None, extras=False):
    """Bucle completo: capa 1 (Python) -> núcleo [+ experto] -> herramienta. Devuelve (respuesta, traza).

    modo="codigo": el experto de código está activo en este turno: herramientas B: (base local de conceptos y ddgs en modo
    código) y E: (sandbox de Python), con sus topes de tokens, y sin penalización por repetición (copiar código repite tokens).
    memoria: Memoria externa (guardado en capa 1 y primera fuente de B:). trabajo: MemoriaTrabajo (referente de los seguimientos).
    """
    exacta = capa1(pregunta, memoria)
    if exacta is not None:
        return exacta, ["[capa 1, sin IA]"]
    if extras:  # v2: hora/fecha del reloj, clima con lugar y datos en vivo (tiempo_real.py)
        from tiempo_real import dividir

        partes = dividir(pregunta)
        if partes:
            return _tiempo_real(modelo, fmt, pregunta, partes, dispositivo, buscador, penalizacion)
    if modo:  # con cualquier experto activo: sin penalización por repetición (copiar código o texto repite tokens)
        penalizacion = 1.0
    ids = fmt.ids_prompt(trabajo.contextualizar(pregunta) if trabajo else pregunta)
    traza = []
    for _ in range(max_busquedas + 1):
        nuevo, parada = generar_lote(modelo, fmt, [ids], dispositivo, penalizacion, max_nuevos=140 if modo else 100)[0]
        texto = _texto(fmt, nuevo)
        traza.append(texto)
        if parada != fmt.herramienta or texto.startswith("R:"):  # «R: …» ya es la respuesta, aunque cierre con <herramienta>
            return texto.removeprefix("R:").strip(), traza
        if modo == "codigo" and texto.startswith("E:"):
            from sandbox import ejecutar_codigo

            resultados, tope = ejecutar_codigo(texto.removeprefix("E:").strip()), TOPE_EJECUCION
        else:
            consulta = texto.removeprefix("B:").strip()
            resultados = buscar_memoria(consulta, memoria) or (buscador(consulta, modo=modo) if modo else buscador(consulta))
            tope = TOPE_EXPERTO if modo else MAX_TOKENS_RESULTADOS
        tope = min(tope, max(40, getattr(fmt, "ventana", 512) - 112 - len(ids) - len(nuevo)))  # lo que sobre de la ventana (512 en v1, 1024 en v2) tras el contexto y la respuesta
        traza.append("[herramienta] " + resultados.replace("\n", " | "))
        ids = ids + nuevo + fmt.ids_tras_herramienta(resultados, tope)
    return SIN_INFO, traza


def evaluar(modelo, fmt, dispositivo, ruta=RAIZ / "datos" / "sft_eval.jsonl", n_por_tipo=150, penalizacion=1.1, lote=50):
    filas = [json.loads(l) for l in open(ruta, encoding="utf-8")]
    por_tipo = {}
    for r in filas:
        por_tipo.setdefault(r["tipo"], []).append(r)
    resumen = {}
    for tipo, rs in por_tipo.items():
        rs = rs[:n_por_tipo]
        buscó = exacta = abst = 0
        for a in range(0, len(rs), lote):
            grupo = rs[a : a + lote]
            prompts = [fmt.ids_prompt(r["pregunta"]) for r in grupo]
            f1 = generar_lote(modelo, fmt, prompts, dispositivo, penalizacion)
            fase2, idx2 = [], []
            for j, (r, (nuevo, parada)) in enumerate(zip(grupo, f1)):
                if parada == fmt.herramienta:
                    buscó += 1
                    if tipo != "directo":  # en conversación directa buscar ya es un error: no hay resultados que simular
                        fase2.append(prompts[j] + nuevo + fmt.ids_tras_herramienta(r["resultados"]))
                        idx2.append(j)
                elif tipo == "directo":
                    t = _texto(fmt, nuevo).removeprefix("R:").strip()
                    exacta += t == r["respuesta"]
            if fase2:
                for j, (nuevo, _) in zip(idx2, generar_lote(modelo, fmt, fase2, dispositivo, penalizacion)):
                    t = _texto(fmt, nuevo).removeprefix("R:").strip()
                    if tipo == "buscar_ok":
                        exacta += t == grupo[j]["respuesta"]
                    else:
                        abst += t == SIN_INFO
        n = len(rs)
        if tipo == "directo":
            resumen[tipo] = {"no_buscó": 1 - buscó / n, "respuesta_exacta": exacta / n}
        elif tipo == "buscar_ok":
            resumen[tipo] = {"buscó": buscó / n, "respuesta_exacta": exacta / n}
        else:
            resumen[tipo] = {"buscó": buscó / n, "se_abstuvo": abst / n}
    return resumen


class Sesion:
    """Una conversación: enrutador de 3 estados + expertos + memoria externa con enfriamiento + memoria de trabajo de 2 turnos.

    expertos = {"codigo": ruta, "redaccion": ruta}. Con el motor C++ ambos viven en la caché de 2 ranuras (Activo / Tibio / Frío): el
    enrutador elige UNO por turno (o ninguno) y cambiar de experto es una asignación de puntero. Con PyTorch solo se admite un experto.
    """

    def __init__(self, modelo, fmt, dispositivo, motor=False, experto=None, expertos=None, pen=1.1, memoria=True, buscador=buscar_web,
                 ruta_memoria=None, vida_tibia=None, v2=False):
        from memoria import Memoria, MemoriaTrabajo

        self.modelo, self.fmt, self.disp, self.motor, self.pen, self.buscador = modelo, fmt, dispositivo, motor, pen, buscador
        self.v2 = v2  # núcleo v2c: enrutador ampliado y consultas de tiempo real (hora, clima, datos en vivo)
        self.enr, self._lora, self.expertos = None, None, dict(expertos or {})
        if experto and "codigo" not in self.expertos:
            self.expertos["codigo"] = experto
        if self.expertos:  # el enrutador despierta, cambia o duerme al experto turno a turno
            from enrutador import Enrutador, EnrutadorV2

            self.enr = EnrutadorV2() if v2 else Enrutador()
            if motor:
                if vida_tibia:
                    modelo.vida_tibia(vida_tibia)
                for i, (nombre, ruta) in enumerate(self.expertos.items()):
                    modelo.registrar_experto(nombre, ruta, i)
                    modelo.cargar_ranura(ruta, i)  # entran tibios
                modelo.seleccionar(None)
            else:
                if len(self.expertos) > 1:
                    raise ValueError("PyTorch admite un solo experto; usa --motor para tener código y redacción a la vez")
                import lora

                self._lora = lora
                (nombre, ruta), = self.expertos.items()
                self._nombre_unico = nombre
                lora.cargar_lora(modelo, ruta)
                modelo.to(dispositivo).eval()
        else:  # sin experto: un adaptador cargado antes en el mismo modelo no debe seguir despierto
            try:
                if motor:
                    modelo.seleccionar(None) if modelo.rutas_ranuras else modelo.activar_lora(False)
                else:
                    import lora

                    lora.activar(modelo, False)
            except Exception:
                pass
        self.memoria = (Memoria(ruta_memoria) if ruta_memoria else Memoria()) if memoria else None
        self.trabajo = MemoriaTrabajo(fmt.tok) if memoria else None
        self.colisiones = 0

    def estados(self):
        """{experto: 'activo'|'tibio'|'frío'} (solo motor C++)."""
        return {n: self.modelo.estado(n) for n in self.expertos} if self.motor and self.expertos else {}

    def atender(self, p, imprimir=False):
        """Un turno. Devuelve (respuesta, traza, modo). Orden: enfriar memoria -> enrutador -> capa 1 / núcleo -> memoria de trabajo."""
        if self.memoria:
            self.memoria.enfriar()  # cada turno todos los recuerdos bajan 1
        modo = self.enr.paso(p) if self.enr else None
        if self.enr and self.motor:
            self.modelo.turno()           # los expertos tibios pierden 1 de vida; al llegar a 0 se descargan
            self.modelo.seleccionar(modo)  # cambio de experto = asignación de puntero (recarga solo si estaba frío)
            if sum(v == "activo" for v in self.estados().values()) != (modo is not None):
                self.colisiones += 1       # exclusión mutua: exactamente 1 activo si hay modo, 0 si no
        elif self.enr:
            self._lora.activar(self.modelo, modo == self._nombre_unico)
        r, traza = responder(self.modelo, self.fmt, p, self.disp, buscador=self.buscador, penalizacion=self.pen, modo=modo,
                             memoria=self.memoria, trabajo=self.trabajo, extras=self.v2)
        if self.trabajo:
            self.trabajo.registrar(p, r)
        if imprimir:
            print(f"P: {p}" + (f"   [experto: {modo or 'dormido'}]" if self.enr else ""))
            for t in traza:  # la traza solo muestra lo que pasó de más (B:/E:/herramienta); la respuesta final se imprime una sola vez
                if t == r or (t.startswith("R:") and t.removeprefix("R:").strip() == r):
                    continue
                print("   ", t)
            print(f"R: {r}\n")
        return r, traza, modo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("preguntas", nargs="*")
    ap.add_argument("--modelo", default=str(RAIZ / "modelos" / "nucleo_sft_v3.pt"))
    ap.add_argument("--motor", action="store_true", help="usar el motor C++ (motor.dll) en vez de PyTorch")
    ap.add_argument("--experto", default=None, help="adaptador del experto de código (.lora con --motor, .lora.pt con PyTorch); "
                    "las preguntas se tratan como una conversación y el enrutador lo despierta o duerme")
    ap.add_argument("--sin-memoria", action="store_true", help="desactiva la memoria externa (datos/memoria.json) y la de trabajo")
    ap.add_argument("--redaccion", default=None, help="adaptador del experto de redacción (.lora; requiere --motor junto a --experto)")
    ap.add_argument("--v2", action="store_true", help="núcleo v2c (EXPERIMENTAL: modelos/experimentos/, tokenizador 24k, int8 atado): implica --motor y carga ambos expertos")
    ap.add_argument("--sin-expertos", action="store_true", help="con --v2: solo el núcleo, sin adaptadores")
    ap.add_argument("--evaluar", action="store_true")
    ap.add_argument("--datos", default=str(RAIZ / "datos" / "sft_eval.jsonl"), help="conjunto de evaluación (sft_eval_real.jsonl = ddgs real)")
    ap.add_argument("--pen", type=float, default=1.1, help="penalización por repetición (1.0 = ninguna)")
    args = ap.parse_args()
    disp = elegir_dispositivo()
    if args.v2:  # v2c experimental: no pisa nada de v1; los adaptadores v2 (LORA0002) solo se usan con el núcleo v2
        from protocolo_v2 import FormatoV2

        exp = RAIZ / "modelos" / "experimentos"
        args.motor = True
        if args.modelo == str(RAIZ / "modelos" / "nucleo_sft_v3.pt"):
            args.modelo = str(exp / "nucleo_v2c_sft.bin")
        if not args.sin_expertos:
            args.experto = args.experto or str(exp / "experto_codigo_g_v2.lora")
            args.redaccion = args.redaccion or str(exp / "experto_redaccion_f_v2.lora")
        from motor_cpp import MotorCpp

        modelo, fmt = MotorCpp(args.modelo), FormatoV2()
        print(f"[v2c experimental] núcleo {Path(args.modelo).name} | expertos: {', '.join(Path(x).name for x in (args.experto, args.redaccion) if x) or 'ninguno'}", flush=True)
    elif args.motor:  # motor C++ nativo: lee el .bin exportado con exportar_cpp.py (capa1 y ddgs siguen en Python)
        from motor_cpp import MotorCpp

        modelo, fmt = MotorCpp(Path(args.modelo).with_suffix(".bin")), Formato()
    else:
        modelo, fmt = cargar(args.modelo, disp)
    if args.evaluar:
        for tipo, m in evaluar(modelo, fmt, disp, ruta=args.datos, n_por_tipo=300, penalizacion=args.pen).items():
            print(f"{tipo:12s}", "  ".join(f"{k}={v:.1%}" for k, v in m.items()))
        return
    expertos = {}
    if args.experto:
        expertos["codigo"] = args.experto
    if args.redaccion:
        expertos["redaccion"] = args.redaccion
    sesion = Sesion(modelo, fmt, disp, motor=args.motor, expertos=expertos, pen=args.pen, memoria=not args.sin_memoria, v2=args.v2)
    if args.preguntas:
        for p in args.preguntas:
            sesion.atender(p, imprimir=True)
        return
    # sin preguntas por argumento: chat interactivo (una sola conversación: enrutador y memorias conservan su estado entre turnos)
    print("Chat interactivo. Escribe tu pregunta; «salir» (o Ctrl+C / Ctrl+Z) para terminar.\n")
    while True:
        try:
            p = input("Tú> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if p.lower() in ("salir", "exit", "quit"):
            break
        if p:
            sesion.atender(p, imprimir=True)


if __name__ == "__main__":
    main()

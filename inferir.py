"""Inferencia del núcleo ajustado: generación, bucle con herramienta y evaluación.

Parada automática: <fin> (termina) o <herramienta> (el entorno ejecuta la búsqueda,
agrega los resultados y le devuelve el turno al modelo).
Penalización por repetición: solo sobre tokens que el modelo ya generó en este turno
(no sobre la pregunta ni los resultados, para no impedir que copie datos).

  python inferir.py                                # chat interactivo con v2c (producción: modelos/nucleo_v2c_sft.bin + expertos de código y redacción)
  python inferir.py --v1 --motor --experto modelos/experto_codigo.lora   # respaldo de v1
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


def escribir_cuerpo_imagen(modelo, fmt, k, idea_en, dispositivo):
    """Opción B del experto de imagen: el prompt EMPIEZA con la idea del usuario (ya en inglés) y el núcleo solo la CONTINÚA con estilo, luz y cámara, forzando ese comienzo.
    La idea nunca pasa por el modelo, así que no se pierde. Devuelve (cuerpo, continuación_del_núcleo)."""
    import re

    from imagen_fichas import FICHAS_IMAGEN, buscar_ficha_imagen
    from imagen_formato import limpiar_cuerpo

    natural = FICHAS_IMAGEN[k]["estilo"] == "natural"
    inicio = idea_en.strip().rstrip(" .,;")
    if not natural:  # etiquetas: sin artículo inicial y en minúsculas, salvo lo que va entre comillas
        inicio = re.sub(r"^(?:an?|the)\s+", "", inicio, flags=re.I)
        inicio = re.sub(r'("[^"]*")|([^"]+)', lambda m: m.group(1) or m.group(2).lower(), inicio)
    ficha = buscar_ficha_imagen(k) or ""
    pedido = f"write a prompt for {FICHAS_IMAGEN[k]['nombres'][0]}: {idea_en.strip()}"
    ids = fmt.ids_prompt(pedido) + fmt.texto(f" B: {k}") + [fmt.herramienta] + fmt.ids_tras_herramienta(ficha, 330) + fmt.texto(" R: " + inicio)
    nuevo, _ = generar_lote(modelo, fmt, [ids], dispositivo, 1.15, max_nuevos=130)[0]
    cont = _texto(fmt, nuevo)
    cont = limpiar_cuerpo(cont) if cont else ""
    if natural:  # la continuación se corta en la última oración completa
        m = list(re.finditer(r"[.!?](?=\s|$)", cont))
        cont = cont[:m[-1].end()] if m else ""
    else:  # etiquetas: se corta en la última coma
        cont = cont[:cont.rfind(",")] if "," in cont else ""
    cont = re.sub(r"^[\s,.;:]+", "", cont)
    base = re.sub(r"\W+", " ", inicio.lower()).strip()
    if cont and base and base in re.sub(r"\W+", " ", cont.lower()):  # no repetir la idea
        cont = ""
    sep = ". " if natural else ", "
    return (inicio + (sep + cont if cont else ("." if natural else ""))), cont


def _busqueda_forzada(modelo, fmt, pregunta_modelo, consulta, dispositivo, buscador, penalizacion, traza, etiqueta):
    """Búsqueda que decide la capa de inferencia (no el núcleo): ddgs con `consulta` y turno de herramienta normal (pregunta + B: + resultados) para que el núcleo
    responda con evidencia. Devuelve la respuesta del núcleo (puede ser la abstención si los resultados no alcanzan)."""
    resultados = buscador(consulta)
    traza += [f"[{etiqueta}] B: {consulta}", "[herramienta] " + resultados.replace("\n", " | ")]
    from respaldo_busqueda import normalizar_con_resultados  # tildes y mayúsculas restauradas con evidencia de los resultados (el núcleo es sensible a ellas)

    pregunta_modelo = normalizar_con_resultados(pregunta_modelo, resultados)
    ids = fmt.ids_prompt(pregunta_modelo) + fmt.texto(" B: " + consulta) + [fmt.herramienta] + fmt.ids_tras_herramienta(resultados, MAX_TOKENS_RESULTADOS)
    nuevo, _ = generar_lote(modelo, fmt, [ids], dispositivo, penalizacion, max_nuevos=100)[0]
    r = _texto(fmt, nuevo).removeprefix("R:").strip()
    traza.append("R: " + r)
    if r and not r.startswith("No tengo información"):  # cita fiel: oración exacta de los resultados, o abstención si lo copiado no es fiable
        from respaldo_busqueda import reparar_cita

        fiel = reparar_cita(r, resultados, consulta)
        if fiel != r:
            traza.append("[cita reparada con el texto de los resultados]" if fiel else "[respuesta no fiable: no coincide con los resultados]")
        r = fiel or SIN_INFO
    return r


def responder(modelo, fmt, pregunta, dispositivo, buscador=buscar_web, penalizacion=1.1, max_busquedas=2, modo=None,
              memoria=None, trabajo=None, extras=False, contexto_busqueda=None, modelo_imagen_previo=None, idea_literal=True, continuacion_nucleo=False, idea_imagen_previa=None):
    """Bucle completo: capa 1 (Python) -> núcleo [+ experto] -> herramienta. Devuelve (respuesta, traza).

    modo="codigo": el experto de código está activo en este turno: herramientas B: (base local de conceptos y ddgs en modo
    código) y E: (sandbox de Python), con sus topes de tokens, y sin penalización por repetición (copiar código repite tokens).
    memoria: Memoria externa (guardado en capa 1 y primera fuente de B:). trabajo: MemoriaTrabajo (referente de los seguimientos).
    """
    exacta = capa1(pregunta, memoria) if modo != "imagen" else None  # un pedido de prompt de imagen no es una cuenta ni una orden de memoria
    if exacta is not None:
        return exacta, ["[capa 1, sin IA]"]
    if extras and modo != "imagen":  # v2: hora/fecha del reloj, clima con lugar y datos en vivo (tiempo_real.py); «lluvia» en un prompt de imagen no es una consulta de clima
        from tiempo_real import dividir

        partes = dividir(pregunta)
        if partes:
            return _tiempo_real(modelo, fmt, pregunta, partes, dispositivo, buscador, penalizacion)
    if extras and modo != "imagen":  # v2c: «¿puedes buscarlo?» / «búscalo» -> busca la última consulta informativa de la sesión (respaldo_busqueda.py)
        from respaldo_busqueda import es_orden_buscar, limpiar

        if es_orden_buscar(pregunta):
            if not contexto_busqueda:
                return "Dime qué quieres que busque y lo busco.", ["[orden de buscar sin tema previo]"]
            limpia, consulta = limpiar(contexto_busqueda)
            traza = []
            r = _busqueda_forzada(modelo, fmt, limpia, consulta, dispositivo, buscador, penalizacion, traza, "orden de buscar")
            return (r if r and not r.startswith("No tengo información") else SIN_INFO), traza
    if modo:  # con cualquier experto activo: sin penalización por repetición (copiar código o texto repite tokens)
        penalizacion = 1.15 if modo == "imagen" else 1.0  # el prompt de imagen es texto nuevo, no una copia: sin penalización entra en bucles («8k, 8k, 8k…»)
    nota_entrada = []
    if modo == "imagen":  # sin modelo destino (ni nombrado ahora ni usado antes en la sesión) no se escribe nada: se pregunta, con texto fijo (el núcleo lo reproducía corrupto)
        from imagen_compactar import preparar_entrada
        from imagen_fichas import resolver_modelo
        from imagen_vocab import PREGUNTA_MODELO

        k_pedido = resolver_modelo(pregunta)
        if k_pedido is None and not modelo_imagen_previo:
            return PREGUNTA_MODELO[0], ["[falta el modelo destino]"]
        # entradas largas (JSON anidado, especificaciones de escena): no caben en la ventana del núcleo (1.024 tokens); se compactan sin perder lo visual (imagen_compactar.py)
        pregunta, resumen, obj_json = preparar_entrada(pregunta, fmt.tok)
        if resumen:
            nota_entrada.append("[" + resumen + "]")
            if k_pedido and resolver_modelo(pregunta) is None:  # el modelo estaba dentro del JSON: se conserva como prefijo
                pregunta = f"prompt para {k_pedido}:\n{pregunta}"
        if obj_json is None and idea_literal and (k_pedido or modelo_imagen_previo):
            # opción B: la idea del usuario se traduce al inglés y encabeza el prompt; el núcleo solo añade estilo, luz y cámara (imagen_idea.py)
            from imagen_fichas import FICHAS_IMAGEN
            from imagen_formato import formatear
            from imagen_idea import idea_en_ingles

            k_dest = k_pedido or modelo_imagen_previo
            from enrutador import _SEGUIMIENTO_IMG, _n as _nn
            import re as _re_

            _RE_CAMBIO = _re_.compile(r"^(?:mas|menos|sin|con|pero|mucho|un\s+poco|bien|de\s+(?:noche|dia)|en\s+(?:estilo|modo|version|blanco)|estilo|realista|oscur|clar|colorid|detall|cinemat|artistic)")
            from imagen_idea import modificador_de_seguimiento

            mod_previo = modificador_de_seguimiento(pregunta) if idea_imagen_previa else ""
            # seguimiento = el mensaje solo pide un cambio (vacío, o corto y empezando por «más/menos/sin/con/pero…»); una idea nueva con «para qwen» no lo es
            es_seguimiento = bool(idea_imagen_previa) and bool(_SEGUIMIENTO_IMG.search(_nn(pregunta))) and (not mod_previo or (len(mod_previo.split()) <= 6 and bool(_RE_CAMBIO.match(_nn(mod_previo)))))
            if es_seguimiento:  # «otra versión más oscura», «ahora para sdxl»: se modifica la idea anterior, no se empieza otra
                mod = modificador_de_seguimiento(pregunta)
                mod_en, idioma, idea = idea_en_ingles(mod, traducir=True) if mod else ("", "en", "")
                en = idea_imagen_previa + (", " + mod_en[:1].lower() + mod_en[1:] if mod_en else "")
                idioma = "seguimiento"
            else:
                en, idioma, idea = idea_en_ingles(pregunta, traducir=True)
            sin_traducir = idioma == "es" and en.lower().strip(" .") == idea.lower().strip(" .")  # no hay traductor instalado: se usa el camino anterior
            if en and not sin_traducir:
                if continuacion_nucleo:  # EXPERIMENTAL: el núcleo continúa la idea (medido: incoherente); por defecto se enriquece con vocabulario curado (imagen_idea.enriquecer)
                    cuerpo, cont = escribir_cuerpo_imagen(modelo, fmt, k_dest, en, dispositivo)
                else:
                    from imagen_idea import enriquecer

                    import random as _rnd

                    cuerpo = enriquecer(k_dest, en, variante=_rnd.randrange(1, 10**6) if (idioma == "seguimiento" and not mod_previo) else 0)  # «otra versión»: mismo contenido, otra luz/composición/calidad
                return (formatear(k_dest, cuerpo, con_texto='"' in cuerpo, limpiar=False),
                        nota_entrada + [f"[idea {'traducida del español' if idioma == 'es' else ('modificada a partir de la anterior' if idioma == 'seguimiento' else 'en inglés')}: {en}]", f"B: {k_dest}", "[herramienta] ficha", "R: " + cuerpo, f"[modelo imagen: {k_dest}]"])
        if obj_json is not None:
            # especificación completa (ya es un plan de render): el núcleo no la usa con fidelidad (medido), así que se COMPONE el prompt con sus propios campos y se aplica el formato del modelo
            from imagen_compactar import a_etiquetas, componer_json
            from imagen_fichas import FICHAS_IMAGEN
            from imagen_formato import formatear

            k_dest = k_pedido or modelo_imagen_previo
            comp, _ = componer_json(obj_json, fmt.tok, 420)
            cuerpo = comp if FICHAS_IMAGEN[k_dest]["estilo"] == "natural" else a_etiquetas(comp)
            return (formatear(k_dest, cuerpo, con_texto='"' in cuerpo),
                    nota_entrada + [f"[composición determinista con los campos de la especificación (el núcleo no la sigue con fidelidad)]", f"[modelo imagen: {k_dest}]"])
        if k_pedido is None:  # sin modelo nombrado pero con uno previo en la sesión: se consulta SU ficha y el núcleo solo escribe el cuerpo del prompt
            from imagen_fichas import buscar_ficha_imagen
            from imagen_formato import formatear

            ficha = buscar_ficha_imagen(modelo_imagen_previo) or ""
            ids0 = fmt.ids_prompt(pregunta) + fmt.texto(" B: " + modelo_imagen_previo) + [fmt.herramienta] + fmt.ids_tras_herramienta(ficha, 330)
            nuevo0, _ = generar_lote(modelo, fmt, [ids0], dispositivo, 1.15, max_nuevos=280)[0]
            cuerpo = _texto(fmt, nuevo0).removeprefix("R:").strip()
            return (formatear(modelo_imagen_previo, cuerpo, con_texto='"' in cuerpo),
                    nota_entrada + [f"B: {modelo_imagen_previo}", "[herramienta] ficha (modelo de la sesión)", "R: " + cuerpo, f"[modelo imagen: {modelo_imagen_previo}]"])
    pregunta_ctx = trabajo.contextualizar(pregunta) if trabajo else pregunta
    ids = fmt.ids_prompt(pregunta_ctx)
    buscado = None  # v2c: resultados web de este turno (para restaurar tildes/mayúsculas y reparar la cita)
    traza = list(nota_entrada)
    k_img = None  # modelo de imagen consultado en este turno (experto de prompts de imagen)
    for _ in range(max_busquedas + 1):
        nuevo, parada = generar_lote(modelo, fmt, [ids], dispositivo, penalizacion, max_nuevos=280 if modo == "imagen" else (140 if modo else 100))[0]
        texto = _texto(fmt, nuevo)
        traza.append(texto)
        if parada != fmt.herramienta or texto.startswith("R:"):  # «R: …» ya es la respuesta, aunque cierre con <herramienta>
            respuesta = texto.removeprefix("R:").strip()
            if extras and len(traza) == 1:  # sin haber buscado nada: abstención, o charla que promete buscar («puedo buscarlo…») ante una pregunta de contenido
                from respaldo_busqueda import contenido, es_charla_plantilla, informativa, limpiar, promete_buscar, sobre_asistente
                from tiempo_real import RE_CLIMA, _n as _norm

                abstiene = respuesta.startswith("No tengo información")
                # respuesta de charla («Soy TEST-IA…», «puedo buscarlo…») a una pregunta de contenido sobre el mundo: el núcleo no la entendió como consulta
                desvia = ((promete_buscar(respuesta) or es_charla_plantilla(respuesta)) and contenido(pregunta) and not sobre_asistente(pregunta)
                          and not RE_CLIMA.search(_norm(pregunta)))  # sin lugar, el clima se pregunta, no se busca
                if (abstiene or desvia) and informativa(pregunta):
                    limpia, consulta = limpiar(pregunta)
                    r = _busqueda_forzada(modelo, fmt, limpia, consulta, dispositivo, buscador, penalizacion, traza, "búsqueda de respaldo")
                    return (r if r and not r.startswith("No tengo información") else SIN_INFO), traza
            if extras and buscado is not None and respuesta and not respuesta.startswith("No tengo información"):  # cita fiel también cuando buscó el propio núcleo
                from respaldo_busqueda import reparar_cita

                fiel = reparar_cita(respuesta, buscado, consulta)
                if fiel != respuesta:
                    traza.append("[cita reparada con el texto de los resultados]" if fiel else "[respuesta no fiable: no coincide con los resultados]")
                respuesta = fiel or SIN_INFO
            if modo == "imagen" and respuesta:  # el núcleo escribió el cuerpo del prompt; la capa determinista añade prefijo de calidad y prompt negativo según la ficha
                from imagen_fichas import resolver_modelo
                from imagen_formato import formatear

                k_img = k_img or resolver_modelo(pregunta) or modelo_imagen_previo  # si el núcleo no consultó la ficha, se usa el modelo nombrado (o el de la sesión)
                if k_img:
                    respuesta = formatear(k_img, respuesta, con_texto='"' in respuesta)
                    traza.append(f"[modelo imagen: {k_img}]")
            return respuesta, traza
        if modo == "imagen":  # B: <modelo> -> ficha local del modelo (no hay búsqueda web)
            from imagen_fichas import buscar_ficha_imagen, resolver_modelo

            consulta = texto.removeprefix("B:").strip()
            k_img = resolver_modelo(consulta) or k_img
            resultados = buscar_ficha_imagen(consulta) or ""
            tope = 330
        elif modo == "codigo" and texto.startswith("E:"):
            from sandbox import ejecutar_codigo

            resultados, tope = ejecutar_codigo(texto.removeprefix("E:").strip()), TOPE_EJECUCION
        else:
            consulta = texto.removeprefix("B:").strip()
            resultados = buscar_memoria(consulta, memoria)
            en_web = not resultados
            if en_web:
                resultados = buscador(consulta, modo=modo) if modo else buscador(consulta)
            if extras and modo is None and en_web and len(traza) == 1:  # v2c, primera búsqueda web del núcleo: tildes/mayúsculas con evidencia y contexto rehecho
                from respaldo_busqueda import normalizar_con_resultados

                buscado = resultados
                pregunta_ctx = normalizar_con_resultados(pregunta_ctx, resultados)
                ids = fmt.ids_prompt(pregunta_ctx)
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
                 ruta_memoria=None, vida_tibia=None, v2=False, idea_literal=True, continuacion_nucleo=False):
        from memoria import Memoria, MemoriaTrabajo

        self.modelo, self.fmt, self.disp, self.motor, self.pen, self.buscador = modelo, fmt, dispositivo, motor, pen, buscador
        self.continuacion_nucleo = continuacion_nucleo
        self.idea_literal = idea_literal  # experto de imagen: la idea del usuario se traduce y encabeza el prompt (imagen_idea.py)
        self.v2 = v2  # núcleo v2c: enrutador ampliado y consultas de tiempo real (hora, clima, datos en vivo)
        self.enr, self._lora, self.expertos = None, None, dict(expertos or {})
        if experto and "codigo" not in self.expertos:
            self.expertos["codigo"] = experto
        if self.expertos:  # el enrutador despierta, cambia o duerme al experto turno a turno
            from enrutador import Enrutador, EnrutadorV2, EnrutadorV3

            self.enr = (EnrutadorV3() if "imagen" in self.expertos else EnrutadorV2()) if v2 else Enrutador()
            if motor:
                if vida_tibia:
                    modelo.vida_tibia(vida_tibia)
                for i, (nombre, ruta) in enumerate(self.expertos.items()):
                    modelo.registrar_experto(nombre, ruta, i % 2)  # con 3 expertos (código, redacción, imagen) el tercero comparte ranura y se recarga al pedirlo (≈ 4 ms)
                    if i < 2:
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
        self.ultima_idea_imagen = None  # idea (en inglés) del último pedido de prompt: un «otra versión más oscura» la modifica
        self.ultimo_modelo_imagen = None  # modelo de imagen del último pedido de prompt (un «otra versión» sin modelo reutiliza el anterior)
        self.ultima_info = None  # última pregunta informativa (con búsqueda o abstención): referente de «¿puedes buscarlo?» (solo v2c)

    def estados(self):
        """{experto: 'activo'|'tibio'|'frío'} (solo motor C++)."""
        return {n: self.modelo.estado(n) for n in self.expertos} if self.motor and self.expertos else {}

    def atender(self, p, imprimir=False):
        """Un turno. Devuelve (respuesta, traza, modo). Orden: enfriar memoria -> enrutador -> capa 1 / núcleo -> memoria de trabajo."""
        if self.memoria:
            self.memoria.enfriar()  # cada turno todos los recuerdos bajan 1
        modo = self.enr.paso(p) if self.enr else None
        if modo and modo not in self.expertos:  # el enrutador pidió un dominio sin adaptador cargado
            modo = None
        if self.enr and self.motor:
            self.modelo.turno()           # los expertos tibios pierden 1 de vida; al llegar a 0 se descargan
            self.modelo.seleccionar(modo)  # cambio de experto = asignación de puntero (recarga solo si estaba frío)
            if sum(v == "activo" for v in self.estados().values()) != (modo is not None):
                self.colisiones += 1       # exclusión mutua: exactamente 1 activo si hay modo, 0 si no
        elif self.enr:
            self._lora.activar(self.modelo, modo == self._nombre_unico)
        r, traza = responder(self.modelo, self.fmt, p, self.disp, buscador=self.buscador, penalizacion=self.pen, modo=modo,
                             memoria=self.memoria, trabajo=self.trabajo, extras=self.v2,
                             contexto_busqueda=self.ultima_info, modelo_imagen_previo=self.ultimo_modelo_imagen, idea_literal=self.idea_literal, continuacion_nucleo=self.continuacion_nucleo, idea_imagen_previa=self.ultima_idea_imagen)
        for t in traza:
            if t.startswith("[idea ") and ": " in t:
                self.ultima_idea_imagen = t.split(": ", 1)[1].rstrip("]")
            if t.startswith("[modelo imagen: "):
                self.ultimo_modelo_imagen = t[len("[modelo imagen: "):-1]
        if self.v2:
            from respaldo_busqueda import es_orden_buscar

            if not es_orden_buscar(p) and any(t.startswith("B:") or t.startswith("[búsqueda de respaldo]") for t in traza):
                self.ultima_info = p
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


def preparar_mensaje(t, leer_linea=None):
    """Prepara lo que el usuario escribe o pega: 1) «@ruta» se sustituye por el contenido del archivo (las consolas de Windows cortan una línea pegada a ≈ 4.000 caracteres);
    2) un JSON pegado en varias líneas se completa leyendo líneas hasta cerrar las llaves; 3) un texto que es un literal de cadena JSON («"{\\n  \\"a\\": 1}"») se desescapa."""
    import re

    def desescapar(x):
        s = x.strip()
        if len(s) > 2 and s[0] == '"' and s[-1] == '"':
            try:
                v = json.loads(s)
                if isinstance(v, str):
                    return v
            except ValueError:
                pass
        return x

    def archivo(m):
        ruta = Path(m.group(1).strip('"'))
        for base in (Path.cwd(), RAIZ):
            c = ruta if ruta.is_absolute() else base / ruta
            if c.is_file():
                return desescapar(c.read_text(encoding="utf-8"))
        return m.group(0)

    t = re.sub(r'@("[^"]+"|[^\s"]+)', archivo, t)
    if leer_linea is not None:
        n = 0
        while (t.count("{") - t.count("}") > 0 or t.count("[") - t.count("]") > 0) and n < 3000:
            try:
                t += "\n" + leer_linea()
            except EOFError:
                break
            n += 1
    return desescapar(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("preguntas", nargs="*")
    ap.add_argument("--modelo", default=None, help="v2c (defecto): modelos/nucleo_v2c_sft.bin; con --v1: modelos/nucleo_sft_v3.pt")
    ap.add_argument("--motor", action="store_true", help="usar el motor C++ (motor.dll) en vez de PyTorch")
    ap.add_argument("--experto", default=None, help="adaptador del experto de código (.lora con --motor, .lora.pt con PyTorch); "
                    "las preguntas se tratan como una conversación y el enrutador lo despierta o duerme")
    ap.add_argument("--sin-memoria", action="store_true", help="desactiva la memoria externa (datos/memoria.json) y la de trabajo")
    ap.add_argument("--imagen", action="store_true", help="activa el experto de prompts de imagen (EXPERIMENTAL, usa modelos/experimentos/experto_imagen_d_v2.lora)")
    ap.add_argument("--sin-traductor", action="store_true", help="experto de imagen: no conservar/traducir la idea del usuario (usa solo la generación del núcleo, sin cargar el traductor)")
    ap.add_argument("--continuacion-nucleo", action="store_true", help="experto de imagen (EXPERIMENTAL): el núcleo continúa la idea del usuario en vez del enriquecimiento curado (medido: incoherente)")
    ap.add_argument("--imagen_lora", default=None, help="ruta de otro adaptador .lora para el experto de prompts de imagen (implica --imagen)")
    ap.add_argument("--redaccion", default=None, help="adaptador del experto de redacción (.lora; requiere --motor junto a --experto)")
    ap.add_argument("--v1", action="store_true", help="núcleo v1 (respaldo: modelos/nucleo_sft_v3.*, tokenizador v1, expertos v1 si se indican con --experto/--redaccion)")
    ap.add_argument("--v2", action="store_true", help="(obsoleto: v2c es el modelo por defecto)")
    ap.add_argument("--sin-expertos", action="store_true", help="solo el núcleo, sin adaptadores (v2c)")
    ap.add_argument("--evaluar", action="store_true")
    ap.add_argument("--datos", default=str(RAIZ / "datos" / "sft_eval.jsonl"), help="conjunto de evaluación (sft_eval_real.jsonl = ddgs real)")
    ap.add_argument("--pen", type=float, default=1.1, help="penalización por repetición (1.0 = ninguna)")
    args = ap.parse_args()
    disp = elegir_dispositivo()
    args.v2 = not args.v1  # producción: v2c (tokenizador 24k, int8 atado, expertos LORA0002). --v1 abre el respaldo de v1
    if args.v2:
        from protocolo_v2 import FormatoV2

        prod = RAIZ / "modelos"
        args.motor = True
        args.modelo = args.modelo or str(prod / "nucleo_v2c_sft.bin")
        if not args.sin_expertos:
            args.experto = args.experto or str(prod / "experto_codigo_g_v2.lora")
            args.redaccion = args.redaccion or str(prod / "experto_redaccion_f_v2.lora")
            if not (args.imagen or args.imagen_lora) and (prod / "experto_imagen_v2.lora").exists():
                args.imagen_lora = str(prod / "experto_imagen_v2.lora")
        from motor_cpp import MotorCpp

        modelo, fmt = MotorCpp(args.modelo), FormatoV2()
        print(f"[v2c] núcleo {Path(args.modelo).name} | expertos: {', '.join(Path(x).name for x in (args.experto, args.redaccion) if x) or 'ninguno'}", flush=True)
    elif args.motor:  # motor C++ nativo: lee el .bin exportado con exportar_cpp.py (capa1 y ddgs siguen en Python)
        from motor_cpp import MotorCpp

        args.modelo = args.modelo or str(RAIZ / "modelos" / "nucleo_sft_v3.pt")
        modelo, fmt = MotorCpp(Path(args.modelo).with_suffix(".bin")), Formato()
    else:
        args.modelo = args.modelo or str(RAIZ / "modelos" / "nucleo_sft_v3.pt")
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
    if args.imagen or args.imagen_lora:
        expertos["imagen"] = args.imagen_lora or str(RAIZ / "modelos" / "experimentos" / "experto_imagen_d_v2.lora")
    sesion = Sesion(modelo, fmt, disp, motor=args.motor, expertos=expertos, pen=args.pen, memoria=not args.sin_memoria, v2=args.v2, idea_literal=not args.sin_traductor, continuacion_nucleo=args.continuacion_nucleo)

    def atender(p):
        try:
            sesion.atender(p, imprimir=True)
        except ValueError as e:  # entrada que no cabe en la ventana del núcleo (1.024 tokens) fuera del modo imagen
            if "demasiado largo" not in str(e):
                raise
            print(f"El texto es demasiado largo para el núcleo (máximo ≈ 900 tokens, unos 3.000 caracteres). Para especificaciones largas de prompts de imagen arranca con --imagen y pasa el archivo con @ruta.\n")

    if args.preguntas:
        for p in args.preguntas:
            atender(preparar_mensaje(p))
        return
    # sin preguntas por argumento: chat interactivo (una sola conversación: enrutador y memorias conservan su estado entre turnos)
    print("Chat interactivo. Escribe tu pregunta; «salir» (o Ctrl+C / Ctrl+Z) para terminar.")
    print("Textos largos: escribe @ruta/al/archivo.json (la consola de Windows corta las líneas pegadas a ~4.000 caracteres); también se acepta pegar un JSON en varias líneas.\n")
    while True:
        try:
            p = input("Tú> ").strip()
            p = preparar_mensaje(p, leer_linea=lambda: input(""))
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if p.lower() in ("salir", "exit", "quit"):
            break
        if p:
            atender(p)


if __name__ == "__main__":
    main()

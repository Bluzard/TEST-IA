"""Experto de prompts de imagen sobre el modelo base: la idea del usuario se traduce, se enriquece y se formatea de forma determinista.

El modelo de lenguaje solo interviene como respaldo (sin traductor instalado): escribe el cuerpo del prompt y la capa determinista le da el formato del modelo destino.
Devuelve (respuesta, traza) o None si el mensaje no es un pedido de prompt de imagen resoluble.
"""
import random
import re


class _Tok:
    """Contador aproximado de tokens (≈ 3 caracteres por token); imagen_compactar solo necesita un orden de magnitud."""

    class _Enc:
        def __init__(self, n):
            self.ids = [0] * n

    def encode(self, s):
        return self._Enc(max(1, len(s) // 3))


_RE_CAMBIO = re.compile(r"^(?:mas|menos|sin|con|pero|mucho|un\s+poco|bien|de\s+(?:noche|dia)|en\s+(?:estilo|modo|version|blanco)|estilo|realista|oscur|clar|colorid|detall|cinemat|artistic)")


def prompt_imagen(pregunta, modelo_previo=None, idea_previa=None, escribir_cuerpo=None, traducir=True):
    """escribir_cuerpo(idea_en_ingles, ficha) -> texto: respaldo con el LLM cuando no hay traductor."""
    from enrutador import _SEGUIMIENTO_IMG, _n
    from imagen_compactar import a_etiquetas, componer_json, preparar_entrada
    from imagen_fichas import FICHAS_IMAGEN, buscar_ficha_imagen, resolver_modelo
    from imagen_formato import formatear
    from imagen_idea import enriquecer, idea_en_ingles, modificador_de_seguimiento
    from imagen_vocab import PREGUNTA_MODELO

    tok = _Tok()
    k_pedido = resolver_modelo(pregunta)
    if k_pedido is None and not modelo_previo:
        return PREGUNTA_MODELO[0], ["[falta el modelo destino]"]
    k_dest = k_pedido or modelo_previo
    pregunta, resumen, obj_json = preparar_entrada(pregunta, tok)
    traza = ["[" + resumen + "]"] if resumen else []
    if resumen and k_pedido and resolver_modelo(pregunta) is None:  # el modelo estaba dentro del JSON: se conserva como prefijo
        pregunta = f"prompt para {k_pedido}:\n{pregunta}"
    if obj_json is not None:  # especificación completa: se compone con sus propios campos y se aplica el formato del modelo
        comp, _ = componer_json(obj_json, tok, 420)
        cuerpo = comp if FICHAS_IMAGEN[k_dest]["estilo"] == "natural" else a_etiquetas(comp)
        return formatear(k_dest, cuerpo, con_texto='"' in cuerpo), traza + ["[composición determinista con los campos de la especificación]", f"[modelo imagen: {k_dest}]"]

    mod_previo = modificador_de_seguimiento(pregunta) if idea_previa else ""
    es_seguimiento = bool(idea_previa) and bool(_SEGUIMIENTO_IMG.search(_n(pregunta))) and (
        not mod_previo or (len(mod_previo.split()) <= 6 and bool(_RE_CAMBIO.match(_n(mod_previo)))))
    if es_seguimiento:  # «otra versión más oscura», «ahora para sdxl»: se modifica la idea anterior
        mod_en = idea_en_ingles(mod_previo, traducir=traducir)[0] if mod_previo else ""
        en = idea_previa + (", " + mod_en[:1].lower() + mod_en[1:] if mod_en else "")
        idioma = "seguimiento"
    else:
        en, idioma, idea = idea_en_ingles(pregunta, traducir=traducir)
        if idioma == "es" and en.lower().strip(" .") == idea.lower().strip(" ."):  # no hay traductor: lo traduce el modelo de lenguaje
            en = ""
    if en:
        cuerpo = enriquecer(k_dest, en, variante=random.randrange(1, 10**6) if (idioma == "seguimiento" and not mod_previo) else 0)
        origen = {"es": "traducida del español", "seguimiento": "modificada a partir de la anterior"}.get(idioma, "en inglés")
        return (formatear(k_dest, cuerpo, con_texto='"' in cuerpo, limpiar=False),
                traza + [f"[idea {origen}: {en}]", f"[modelo imagen: {k_dest}]"])
    if escribir_cuerpo is None:
        return None
    cuerpo = escribir_cuerpo(pregunta, buscar_ficha_imagen(k_dest) or "")
    if not cuerpo:
        return None
    return formatear(k_dest, cuerpo, con_texto='"' in cuerpo), traza + ["[cuerpo escrito por el modelo de lenguaje]", f"[modelo imagen: {k_dest}]"]

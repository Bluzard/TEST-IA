"""Experto de EXTRACCIÓN DE ESTADO de escena para el núcleo v2c: dataset, formato de preguntas cortas y lectura de respuestas.

El extractor actual de b_chat pide a Mistral un JSON de ~500-700 tokens por turno (30-44 s). El núcleo lee 1.024 tokens, así que el turno se parte en 4 preguntas cortas
que se responden por separado y un código determinista arma el estado:
  persona char | persona user | relación (disposición + contactos) | cambios de escena (lugar, hora, ropa, ambiente…)
Las respuestas son líneas `clave=valor | clave=valor` (valores de enumeración o frases cortas copiadas del propio mensaje).
Las etiquetas salen de pares REALES (Mistral + reducer de b_chat, ya validados) registrados por gen_datos.cjs: `extraction-pairs.jsonl`.

  python extractor_datos.py PARES.jsonl [--sal datos/extractor] [--prop-eval 0.12]
"""
import argparse
import json
import re
from pathlib import Path

PREGUNTAS = ("char", "user", "relacion", "escena")
CAMPOS_ESCENA = ("location", "time", "outfit", "userOutfit", "atmosphere", "relationship", "tone", "narrativeStyle")
ALIAS = {"location": "lugar", "time": "hora", "outfit": "ropa", "userOutfit": "ropa_user", "atmosphere": "ambiente", "relationship": "relacion", "tone": "tono", "narrativeStyle": "estilo"}
ALIAS_INV = {v: k for k, v in ALIAS.items()}
MAX_MSG_USER, MAX_MSG_CHAR = 420, 1000


def _limpio(t):
    return re.sub(r"\s+", " ", str(t or "")).strip()


def _cola(t, n):
    t = _limpio(t)
    return t if len(t) <= n else "…" + t[-(n - 1):]  # el estado final lo decide el final del turno


def _o(t):
    t = _limpio(t)
    return t if t else "-"


def _objetos(p):
    out = []
    for o in p.get("heldObjects") or []:
        out.append(_limpio(o.get("object") if isinstance(o, dict) else o))
    return ", ".join(x for x in out if x)


def _contacto(c):
    return f"{c['actor']} {c['act']} {c.get('part') or '-'} > {c['target']} {c.get('targetPart') or '-'}"


def _contactos(lista):
    return " ; ".join(_contacto(c) for c in lista) if lista else "-"


def _antes(req):
    ps = req.get("previousState")
    if not ps:
        return "Antes: " + _cola(req.get("previousScene", {}).get("currentSituation", ""), 260)
    def persona(p):
        s = f"{p.get('posture', 'unspecified')} {_o(p.get('support'))}"
        if p.get("asleep"):
            s += " dormido"
        if _limpio(p.get("restraint")):
            s += f" sujeto: {_limpio(p['restraint'])}"
        return s
    prev_c = req.get("previousContacts") or []
    return (f"Antes: char {persona(ps['char'])}; user {persona(ps['user'])}; disposición {ps.get('arrangement', 'unspecified')}; "
            f"contactos {_contactos([{k: v for k, v in c.items() if k != 'index'} for c in prev_c])}")


def prompt(par, pregunta):
    """Entrada del núcleo: estado anterior + los dos mensajes + la pregunta. ~430-560 tokens."""
    req = json.loads(par["request"]) if isinstance(par.get("request"), str) else par["request"]
    cabeza = {"char": "estado final de char", "user": "estado final de user", "relacion": "disposición y contactos finales", "escena": "cambios de escena"}[pregunta]
    return (f"{_antes(req)}\n{{{{user}}}}: {_cola(req['user'], MAX_MSG_USER)}\n{{{{char}}}}: {_cola(req['assistant'], MAX_MSG_CHAR)}\nPregunta: {cabeza}")


def _persona(p):
    return " | ".join([f"postura={p.get('posture', 'unspecified')}", f"soporte={_o(p.get('support'))}", f"dormido={'si' if p.get('asleep') else 'no'}",
                       f"sujecion={_o(p.get('restraint'))}", f"accion={_o(p.get('action'))}", f"gesto={_o(p.get('expression'))}", f"objetos={_o(_objetos(p))}"])


def respuesta(par, pregunta):
    """Etiqueta (estado FINAL validado por el reducer de b_chat)."""
    st = par["scene"]["situationState"]
    if pregunta in ("char", "user"):
        return _persona(st[pregunta])
    if pregunta == "relacion":
        return f"disposicion={st.get('arrangement', 'unspecified')} | contactos={_contactos(st.get('contactos') or st.get('contacts') or [])}"
    cambios = (par["raw"].get("scene") or {})
    partes = [f"{ALIAS[k]}={_limpio(v)}" for k, v in cambios.items() if k in ALIAS and v]
    return " | ".join(partes) if partes else "-"


def parsear(pregunta, texto):
    """Respuesta del núcleo -> dict. Tolerante: lo que no se puede leer queda fuera (el evaluador y el ensamblado lo tratan como ausente)."""
    texto = _limpio(texto)
    if pregunta == "escena":
        if texto in ("", "-"):
            return {}
        out = {}
        for trozo in texto.split(" | "):
            k, _, v = trozo.partition("=")
            if k.strip() in ALIAS_INV and v.strip():
                out[ALIAS_INV[k.strip()]] = v.strip()
        return out
    campos = {}
    for trozo in texto.split(" | "):
        k, _, v = trozo.partition("=")
        if k.strip():
            campos[k.strip()] = v.strip()
    if pregunta == "relacion":
        contactos = []
        c = campos.get("contactos", "-")
        if c and c != "-":
            for item in c.split(" ; "):
                m = re.fullmatch(r"(char|user) (\S+) (\S+) > (char|user) (\S+)", item.strip())
                if m:
                    contactos.append({"actor": m[1], "act": m[2], "part": "" if m[3] == "-" else m[3], "target": m[4], "targetPart": "" if m[5] == "-" else m[5]})
        return {"arrangement": campos.get("disposicion", "unspecified"), "contacts": contactos}
    sin = lambda v: "" if v in ("-", "") else v
    return {"posture": campos.get("postura", "unspecified"), "support": sin(campos.get("soporte", "")), "asleep": campos.get("dormido") == "si",
            "restraint": sin(campos.get("sujecion", "")), "action": sin(campos.get("accion", "")), "expression": sin(campos.get("gesto", "")),
            "heldObjects": [x.strip() for x in sin(campos.get("objetos", "")).split(",") if x.strip()]}


def filas(par):
    return [{"tipo": f"extraccion_{q}", "pregunta": prompt(par, q), "respuesta": respuesta(par, q), "pregunta_id": q} for q in PREGUNTAS]


def cargar(ruta):
    pares = [json.loads(l) for l in open(ruta, encoding="utf-8") if l.strip()]
    return sorted(pares, key=lambda p: p["at"])


def partir(pares, prop_eval=0.12, buffer=12):
    """Por TIEMPO: las conversaciones del final no se ven al entrenar. El buffer descarta las que estaban en curso en la frontera."""
    corte = int(len(pares) * (1 - prop_eval))
    return pares[:max(0, corte - buffer)], pares[corte:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pares")
    ap.add_argument("--sal", default="datos/extractor")
    ap.add_argument("--prop-eval", type=float, default=0.12)
    ap.add_argument("--buffer", type=int, default=12, help="pares descartados en la frontera tiempo-entrenamiento/evaluación (conversaciones en curso)")
    a = ap.parse_args()
    pares = cargar(a.pares)
    train, ev = partir(pares, a.prop_eval, a.buffer)
    sal = Path(a.sal)
    sal.mkdir(parents=True, exist_ok=True)
    for nombre, lote in (("train", train), ("eval", ev)):
        with open(sal / f"{nombre}.jsonl", "w", encoding="utf-8") as f:
            for par in lote:
                for fila in filas(par):
                    f.write(json.dumps(fila, ensure_ascii=False) + "\n")
    print(f"{len(pares)} pares -> {len(train)} entrenamiento + {len(ev)} evaluación ({len(PREGUNTAS)} preguntas cada uno) en {sal}")


if __name__ == "__main__":
    main()

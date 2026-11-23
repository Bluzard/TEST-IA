"""Dataset del micro-SFT (v2b -> v2c): habilidades de copia/transformación (≈ 42 %) + repaso de v2b (≈ 58 %). Escribe datos/v2/sft/microsft_train.jsonl.

Habilidades (solo datos de ENTRENAMIENTO de los expertos): ejecución («Imprime X», bloques multilínea con sangría), errores de ejecución,
interpretación de errores, documentación en inglés técnico (doc_ok), ortografía y reescritura de tono (formal/cercano/conciso/claro).
Repaso: hechos/búsqueda, abstención y charla (39 intenciones) de sft_train_v2b, más gramática, conceptos y abstención de documentación.
Verifica 0 fugas: ninguna pregunta ni consulta de entrenamiento coincide (normalizada) con las de los conjuntos de evaluación, ni una frase de charla reservada.

  python microsft_datos_v2.py
"""
import collections
import glob
import json
import random
import re
import unicodedata
from pathlib import Path

import charla_v2

RAIZ = Path(__file__).parent
DATOS = RAIZ / "datos"
SALIDA = DATOS / "v2" / "sft" / "microsft_train.jsonl"


def leer(f):
    return [json.loads(l) for l in open(f, encoding="utf-8")]


def norm(t):
    t = "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\W+", " ", t).strip()


def main():
    rng = random.Random(11)
    exp, red = leer(DATOS / "experto_train_B2.jsonl"), leer(DATOS / "redaccion_train.jsonl")
    sft = leer(DATOS / "v2" / "sft" / "sft_train_v2b.jsonl")
    por = collections.defaultdict(list)
    for r in exp + red:
        por[r["tipo"]].append(r)
    sft_por = collections.defaultdict(list)
    for r in sft:
        sft_por[r["tipo"]].append(r)

    habilidades = []
    for tipo, veces in (("ejec_ok", 2), ("ejec_error", 1), ("ejec_nameerror", 1), ("ejec_noperm", 1), ("error_interp", 2), ("doc_ok", 1),
                        ("ortografia", 1), ("ortografia_ok", 1), ("tono_formal", 2), ("tono_cercano", 2), ("tono_conciso", 2), ("tono_claro", 2)):
        for r in por.get(tipo, []):
            habilidades += [r] * veces
            if tipo.startswith("ejec") and "\n" in (r.get("consulta") or ""):  # bloques multilínea con sangría: una repetición más
                habilidades.append(r)
    repaso = []
    for tipo, n in (("charla", 8000), ("buscar_ok", 9000), ("irrelevante", 3500), ("vacio", 3000)):
        repaso += rng.sample(sft_por[tipo], n)
    for tipo in ("gramatica", "gramatica_ejemplo", "cola_ok", "cola_abst", "cola_inexistente", "concepto", "concepto_ejemplo", "doc_abst"):
        repaso += por.get(tipo, [])

    # --- verificación de fugas contra todos los conjuntos de evaluación ---
    # 1) ninguna pregunta de entrenamiento coincide con una de evaluación; 2) ningún concepto/consulta RESERVADO (tipos *_reservado/a) aparece en
    # entrenamiento. Los tipos concepto/gramatica no reservados comparten concepto con el entrenamiento por diseño (miden reformulaciones).
    preguntas, reservadas = set(), set()
    for f in glob.glob(str(DATOS / "*eval*.jsonl")) + glob.glob(str(DATOS / "v2" / "sft" / "*eval*.jsonl")):
        for r in leer(f):
            if r.get("tipo") != "charla":
                preguntas.add(norm(r.get("pregunta")))
                if str(r.get("tipo", "")).endswith(("reservado", "reservada")) and r.get("consulta"):
                    reservadas.add(norm(r["consulta"]))
    todo = habilidades + repaso
    fugas_p = [r for r in todo if r["tipo"] != "charla" and norm(r["pregunta"]) in preguntas]
    fugas_c = [r for r in todo if r.get("consulta") and norm(r["consulta"]) in reservadas]
    fugas_ch = [r for r in todo if r["tipo"] == "charla" and norm(r["pregunta"]) in charla_v2._RESERVADAS]
    print(f"fugas encontradas: preguntas {len(fugas_p)} | conceptos reservados {len(fugas_c)} (de {len(reservadas)}) | charla reservada {len(fugas_ch)}")
    ids = {id(r) for r in fugas_p + fugas_c + fugas_ch}
    habilidades = [r for r in habilidades if id(r) not in ids]
    repaso = [r for r in repaso if id(r) not in ids]
    todo = habilidades + repaso
    resto = [r for r in todo if (r["tipo"] != "charla" and norm(r["pregunta"]) in preguntas) or (r.get("consulta") and norm(r["consulta"]) in reservadas)]
    print(f"tras filtrar: fugas restantes = {len(resto)} (debe ser 0)")
    assert not resto
    rng.shuffle(todo)
    with open(SALIDA, "w", encoding="utf-8") as f:
        for r in todo:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(todo):,} filas: habilidades {len(habilidades):,} ({len(habilidades) / len(todo):.1%}) + repaso {len(repaso):,} ({len(repaso) / len(todo):.1%}) -> {SALIDA}")
    print("habilidades:", dict(collections.Counter(r["tipo"] for r in habilidades)))
    print("repaso:", dict(collections.Counter(r["tipo"] for r in repaso)))


if __name__ == "__main__":
    main()

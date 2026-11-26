"""LoRA sobre Qwen2.5-3B-Instruct (pesos HF en modelos/base/qwen2.5-3b-instruct) con los datos de redacción, código y abstención conservados.

  python lora3b.py entrenar [--epocas 2] [--r 16]      -> modelos/lora3b/adaptador
  python lora3b.py evaluar  [--sin-lora]                -> resultados/ETAPA7_lora3b_{base|lora}.json

Formato: el mismo de inferir.py sin herramientas. system = SISTEMA; user = pregunta (+ «Resultados de búsqueda:» o «Salida del código:» cuando el ejemplo los trae);
assistant = respuesta. La pérdida es solo sobre la respuesta.
"""
import argparse
import json
import random
import re
import time
import unicodedata
from pathlib import Path

import torch

RAIZ = Path(__file__).parent
BASE = RAIZ / "modelos" / "base" / "qwen2.5-3b-instruct"
SALIDA = RAIZ / "modelos" / "lora3b" / "adaptador"
SISTEMA = ("Eres TEST-IA. Responde en español, en una o dos frases, SOLO con lo que digan los resultados de búsqueda o la salida del código, copiando el dato tal como aparece. "
           "Si los resultados no responden la pregunta, di exactamente: No tengo información suficiente para responder eso.")
TRAIN = ["datos/redaccion_train.jsonl", "datos/experto_train_B.jsonl"]
EVAL = ["datos/redaccion_eval.jsonl", "datos/experto_eval_B.jsonl"]


def mensajes(x):
    u = x["pregunta"]
    if x.get("resultados"):
        u += ("\n\nSalida del código:\n" if x.get("pref") == "E" else "\n\nResultados de búsqueda:\n") + x["resultados"]
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": u}]


def cargar(rutas):
    return [json.loads(l) for r in rutas for l in open(RAIZ / r, encoding="utf-8")]


def _n(t):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFD", t.lower()).encode("ascii", "ignore").decode()).strip(" .")


def modelo_y_tok(con_lora=None):
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(BASE)
    tok.padding_side = "left"
    m = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16, device_map="cuda")
    if con_lora:
        from peft import PeftModel

        m = PeftModel.from_pretrained(m, con_lora)
    return m, tok


def entrenar(a):
    from peft import LoraConfig, get_peft_model

    random.seed(0)
    torch.manual_seed(0)
    datos = cargar(TRAIN)
    random.shuffle(datos)
    m, tok = modelo_y_tok()
    m.gradient_checkpointing_enable()
    m.enable_input_require_grads()
    m = get_peft_model(m, LoraConfig(r=a.r, lora_alpha=2 * a.r, lora_dropout=0.05, task_type="CAUSAL_LM",
                                     target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    m.print_trainable_parameters()
    ejemplos = []
    for x in datos:
        p = tok.apply_chat_template(mensajes(x), tokenize=False, add_generation_prompt=True)
        ip, ir = tok(p, add_special_tokens=False).input_ids, tok(x["respuesta"] + "<|im_end|>\n", add_special_tokens=False).input_ids
        if len(ip) + len(ir) <= 640:
            ejemplos.append((ip, ir))
    print(f"{len(ejemplos)} ejemplos de {len(datos)}", flush=True)
    opt = torch.optim.AdamW([p for p in m.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)
    lote = a.lote
    pasos = a.epocas * (len(ejemplos) // lote)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=pasos, pct_start=0.05, anneal_strategy="cos")
    m.train()
    paso, t0 = 0, time.time()
    for ep in range(a.epocas):
        random.shuffle(ejemplos)
        ejemplos.sort(key=lambda e: len(e[0]) + len(e[1]) + random.random() * 40)  # lotes de longitud parecida
        orden = list(range(0, len(ejemplos) - lote + 1, lote))
        random.shuffle(orden)
        for i in orden:
            b = ejemplos[i:i + lote]
            n = max(len(p) + len(r) for p, r in b)
            ids = torch.full((len(b), n), tok.pad_token_id)
            lab = torch.full((len(b), n), -100)
            att = torch.zeros((len(b), n), dtype=torch.long)
            for j, (p, r) in enumerate(b):
                s = p + r
                ids[j, :len(s)] = torch.tensor(s)
                lab[j, len(p):len(s)] = torch.tensor(r)
                att[j, :len(s)] = 1
            out = m(input_ids=ids.cuda(), attention_mask=att.cuda(), labels=lab.cuda())
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad(set_to_none=True)
            paso += 1
            if paso % 50 == 0:
                print(f"época {ep + 1}/{a.epocas} paso {paso}/{pasos} | pérdida {out.loss.item():.4f} | {time.time() - t0:.0f}s", flush=True)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    m.save_pretrained(SALIDA)
    print("guardado en", SALIDA)


@torch.no_grad()
def generar(m, tok, lista, max_nuevos=140, lote=24):
    salida = []
    for i in range(0, len(lista), lote):
        ps = [tok.apply_chat_template(mensajes(x), tokenize=False, add_generation_prompt=True) for x in lista[i:i + lote]]
        enc = tok(ps, return_tensors="pt", padding=True, add_special_tokens=False).to("cuda")
        o = m.generate(**enc, max_new_tokens=max_nuevos, do_sample=False, pad_token_id=tok.pad_token_id)
        salida += [t.strip() for t in tok.batch_decode(o[:, enc.input_ids.shape[1]:], skip_special_tokens=True)]
    return salida


def evaluar(a):
    sys_path = str(RAIZ)
    import sys

    sys.path.insert(0, sys_path)
    from relevancia import ORDEN_ABSTENCION, filtrar

    m, tok = modelo_y_tok(None if a.sin_lora else SALIDA)
    m.eval()
    casos = cargar(EVAL)
    real = [json.loads(l) for l in open(RAIZ / "datos" / "sft_eval_real.jsonl", encoding="utf-8")]
    res = {}
    t0 = time.time()
    sal = generar(m, tok, casos)
    por = {}
    for x, r in zip(casos, sal):
        e = por.setdefault(x["tipo"], [0, 0, 0])
        e[0] += _n(r) == _n(x["respuesta"])
        e[1] += _n(x["respuesta"]) in _n(r)
        e[2] += 1
    res["habilidades"] = {t: {"exacto": v[0] / v[2], "contiene": v[1] / v[2], "n": v[2]} for t, v in sorted(por.items())}
    # casos de ddgs real (los mismos de evaluar_3b.py), con el filtro de relevancia delante
    ABST = re.compile(r"no tengo informacion|no encuentro|no se menciona|no hay informacion|no pude|no puedo|no (?:se )?(?:dice|indica|proporcion)|no contienen|no responden|lo siento")
    pr = [{"pregunta": c["pregunta"], "resultados": filtrar(c["consulta"], c.get("resultados") or "")} for c in real]
    sal = generar(m, tok, [p for p in pr if p["resultados"] != ORDEN_ABSTENCION], max_nuevos=120)
    it = iter(sal)
    ok = {}
    for c, p in zip(real, pr):
        r = "no tengo informacion suficiente para responder eso." if p["resultados"] == ORDEN_ABSTENCION else _n(next(it))
        abst = bool(ABST.search(r))
        v = (not abst and _n(c["gold"]) in r) if c["tipo"] == "buscar_ok" else abst
        e = ok.setdefault(c["tipo"], [0, 0])
        e[0] += v
        e[1] += 1
    res["ddgs_real"] = {t: v[0] / v[1] for t, v in ok.items()}
    res["segundos"] = round(time.time() - t0)
    nombre = "base" if a.sin_lora else "lora"
    (RAIZ / "resultados").mkdir(exist_ok=True)
    json.dump(res, open(RAIZ / "resultados" / f"ETAPA7_lora3b_{nombre}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["entrenar", "evaluar"])
    ap.add_argument("--epocas", type=int, default=2)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--lote", type=int, default=8)
    ap.add_argument("--sin-lora", action="store_true")
    a = ap.parse_args()
    entrenar(a) if a.modo == "entrenar" else evaluar(a)

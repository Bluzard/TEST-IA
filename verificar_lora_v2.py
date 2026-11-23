"""Verifica un LoRA del núcleo v2 en el motor C++: logits del motor (núcleo .bin + .lora seleccionado) vs PyTorch (NucleoV2 + LoRA, embedding int8).
  python verificar_lora_v2.py modelos/experimentos/piloto_v2.pt modelos/experimentos/piloto_v2.bin modelos/experimentos/experto_X_v2.lora.pt"""
import sys

import numpy as np
import torch
from tokenizers import Tokenizer

import lora
from exportar_lora_v2 import exportar
from exportar_v2 import TOK_V2_SFT, cargar, emb_int8
from motor_cpp import MotorCpp

pt, binf, lpt = sys.argv[1:4]
modelo, cfg = cargar(pt)
lora.cargar_lora(modelo, lpt)
ruta_l = exportar(lpt, cfg=cfg)
m = MotorCpp(binf)
m.registrar_experto("x", ruta_l, 0)
m.cargar_ranura(ruta_l, 0)
tok = Tokenizer.from_file(str(TOK_V2_SFT))
q, esc = emb_int8(modelo.tok.weight.detach().float())
Eq = torch.from_numpy(q.astype(np.float32) * esc.astype(np.float32)[:, None])
fallos = 0
for t in ["La capital de Chile es Santiago", "def suma(a, b):\n    return a + b", "<usuario> ¿Qué es la fotosíntesis?<asistente> B: fotosíntesis", "Corrige: ayer fui al mercado y compre pan " * 4]:
    ids = tok.encode(t).ids
    with torch.no_grad():
        ref = modelo(torch.tensor([ids]), emb_head=Eq)[0, -1].numpy()
    m.seleccionar(None); base = m.logits(ids)
    m.seleccionar("x"); con = m.logits(ids)
    rel = float(np.abs(ref - con).max()) / float(np.abs(ref).max())
    cambia = float(np.abs(base - con).max()) / float(np.abs(ref).max())
    ok = rel < 5e-3 and int(ref.argmax()) == int(con.argmax()) and cambia > 1e-4
    fallos += not ok
    print(f"  {len(ids):3d} tokens | PyTorch(+LoRA)↔motor {rel:.1e} | el LoRA cambia los logits en {cambia:.1e} | mismo token: {int(ref.argmax()) == int(con.argmax())} | {'OK' if ok else 'FALLA'}")
m.seleccionar(None)
print("verificación LoRA:", "TODO CORRECTO" if not fallos else f"{fallos} FALLOS")
sys.exit(1 if fallos else 0)

"""Exporta el núcleo v2-A (modelo_v2.NucleoV2) al formato NUCL0002 del motor C++ y verifica los logits contra PyTorch.

  python exportar_v2.py modelos/experimentos/piloto_v2.pt [--salida X.bin] [--verificar]

Formato NUCL0002 (lo lee motor.cpp; ver fase0_nucleo_v2.crear_bin): "NUCL0002" + 16 int32
  [vocab, bloque, d, capas, cabezas, vueltas(=1), ff, id_fin, id_herramienta, id_asistente, id_usuario, id_relleno, bitnet(=1), kv_cabezas, flags, bloque_prefill]
  flags: 1 = embedding atado, 2 = embedding int8 por fila (+ escala fp16 por fila), 4 = caché KV fp16
  emb | pos fp16 | vuelta fp32 (ceros) | por capa: ln1 w,b | qkv | proy | ln2 w,b | fc1 | fc2 | ln final w,b
  cada lineal = escala fp32 (media |w|) + ternarios a 2 bits (0->0, 1->+1, 2->-1, el primero en los 2 bits bajos).
El tokenizador (con las 4 etiquetas) se copia junto al .bin como <nombre>.vocab.json.
"""
import argparse
import shutil
import struct
import sys
from pathlib import Path

import numpy as np
import torch

from modelo_v2 import ConfigV2, NucleoV2

RAIZ = Path(__file__).parent
TOK_V2_SFT = RAIZ / "datos" / "v2" / "tokenizador_v2_sft.json"
MAGIA = b"NUCL0002"
BLOQUE_PREFILL = 128


def ternarizar(w):
    escala = w.abs().mean().clamp(min=1e-5)
    q = (w / escala).round().clamp(-1, 1).to(torch.int8).numpy()
    codigos = np.where(q == 1, 1, np.where(q == -1, 2, 0)).astype(np.uint8)
    out, n = codigos.shape
    assert n % 4 == 0
    c = codigos.reshape(out, n // 4, 4)
    return float(escala), (c[..., 0] | (c[..., 1] << 2) | (c[..., 2] << 4) | (c[..., 3] << 6)).astype(np.uint8)


def emb_int8(E):
    """int8 por fila con escala fp16 (igual que cuantizar_int8_por_fila del piloto). Devuelve (q int8, escala fp16)."""
    esc = (E.abs().amax(dim=1) / 127).clamp(min=1e-8).to(torch.float16)
    q = (E / esc.float()[:, None]).round().clamp(-127, 127).to(torch.int8)
    return q.numpy(), esc.numpy()


def ids_especiales():
    from tokenizers import Tokenizer

    t = Tokenizer.from_file(str(TOK_V2_SFT))
    g = t.token_to_id
    return dict(fin=g("<fin>"), herramienta=g("<herramienta>"), asistente=g("<asistente>"), usuario=g("<usuario>"), relleno=g("<|relleno|>"), vocab=t.get_vocab_size())


def cargar(ruta_pt):
    d = torch.load(ruta_pt, map_location="cpu", weights_only=False)
    cfg = ConfigV2(**d["config"]) if "config" in d else ConfigV2()
    m = NucleoV2(cfg)
    m.load_state_dict(d["pesos"])
    return m.float().eval(), cfg


def exportar(ruta_pt, salida=None):
    modelo, cfg = cargar(ruta_pt)
    ids = ids_especiales()
    assert ids["vocab"] == cfg.vocab, (ids["vocab"], cfg.vocab)
    sd = {k: v.detach().float().cpu() for k, v in modelo.state_dict().items()}
    ruta_pt = Path(ruta_pt)
    salida = Path(salida) if salida else ruta_pt.with_suffix(".bin")
    flags = 1 | 2 | 4
    with open(salida, "wb") as f:
        f.write(MAGIA)
        f.write(struct.pack("<16i", cfg.vocab, cfg.bloque, cfg.d, cfg.capas, cfg.cabezas, 1, cfg.ff, ids["fin"], ids["herramienta"], ids["asistente"], ids["usuario"], ids["relleno"], 1, cfg.kv, flags, BLOQUE_PREFILL))
        q, esc = emb_int8(sd["tok.weight"])
        f.write(q.tobytes())
        f.write(esc.tobytes())
        f.write(sd["pos.weight"].numpy().astype(np.float16).tobytes())
        f.write(np.zeros((1, cfg.d), dtype=np.float32).tobytes())

        def lineal(clave):
            e, b = ternarizar(sd[clave])
            f.write(struct.pack("<f", e))
            f.write(b.tobytes())

        def vec(clave):
            f.write(sd[clave].numpy().astype(np.float32).tobytes())

        for i in range(cfg.capas):
            p = f"bloques.{i}."
            vec(p + "ln1.weight"); vec(p + "ln1.bias")
            lineal(p + "qkv.weight"); lineal(p + "proy.weight")
            vec(p + "ln2.weight"); vec(p + "ln2.bias")
            lineal(p + "fc1.weight"); lineal(p + "fc2.weight")
        vec("ln.weight"); vec("ln.bias")
    vocab = salida.with_suffix(".vocab.json")
    shutil.copyfile(TOK_V2_SFT, vocab)
    print(f"{ruta_pt.name} ({ruta_pt.stat().st_size / 1e6:.0f} MB) -> {salida.name} ({salida.stat().st_size / 1e6:.1f} MB) + {vocab.name}", flush=True)
    return salida


@torch.no_grad()
def logits_pytorch(modelo, ids):
    """Logits del último token con el modelo de entrenamiento: pesos ternarios (BitLinear) y embedding atado en int8 (lo que exporta el motor)."""
    E = modelo.tok.weight.float()
    q, esc = emb_int8(E)
    Eq = torch.from_numpy(q.astype(np.float32) * esc.astype(np.float32)[:, None])
    x = torch.tensor([ids])
    return modelo(x, emb_head=Eq)[0, -1].numpy()


def verificar(ruta_pt, ruta_bin, n_prompts=6):
    from motor_cpp import MotorCpp

    sys.path.insert(0, str(RAIZ))
    from fase0_nucleo_v2 import leer_bin, referencia_logits

    torch.set_num_threads(4)
    modelo, cfg = cargar(ruta_pt)
    M = leer_bin(ruta_bin)
    m = MotorCpp(ruta_bin)
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(str(TOK_V2_SFT))
    textos = ["La capital de Chile es Santiago, una ciudad que", "def suma(a, b):\n    return a + b\n\nprint(suma(2, 3))",
              "El sistema solar está formado por el Sol y los planetas que giran a su alrededor. El planeta más grande es",
              "Para instalar el paquete ejecuta el siguiente comando en la terminal:", "En 1810 comenzó el proceso de independencia en",
              "x = [i**2 for i in range(10)]\nprint(sum(x))"]
    rng = np.random.default_rng(0)
    largo = tok.encode("Historia de España. " * 90).ids[:600]
    pruebas = [tok.encode(t).ids for t in textos][:n_prompts] + [largo, largo[:129]]
    fallos = 0
    for ids in pruebas:
        a = logits_pytorch(modelo, ids)          # modelo de entrenamiento
        b = referencia_logits(M, ids)            # lectura independiente del .bin
        c = m.logits(ids)                        # motor C++
        sc = float(np.abs(a).max())
        d_exp, d_mot, d_tot = float(np.abs(a - b).max()) / sc, float(np.abs(b - c).max()) / sc, float(np.abs(a - c).max()) / sc
        mismo = int(a.argmax()) == int(c.argmax())
        ok = d_tot < 5e-3 and mismo
        fallos += not ok
        print(f"  {len(ids):4d} tokens | PyTorch↔.bin {d_exp:.1e} | .bin↔motor {d_mot:.1e} | PyTorch↔motor {d_tot:.1e} | mismo token siguiente: {mismo} | {'OK' if ok else 'FALLA'}", flush=True)
    print("verificación:", "TODO CORRECTO" if not fallos else f"{fallos} FALLOS", flush=True)
    return fallos


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modelo")
    ap.add_argument("--salida", default=None)
    ap.add_argument("--verificar", action="store_true")
    a = ap.parse_args()
    ruta = exportar(a.modelo, a.salida)
    if a.verificar:
        sys.exit(1 if verificar(a.modelo, ruta) else 0)

"""Exporta un modelo BitNet a su formato real: 4 pesos ternarios por byte.

Durante el entrenamiento BitNet guarda una copia en decimales de cada peso
(por eso el .pt pesa lo mismo que un modelo normal). Para usarlo solo hacen
falta los valores -1/0/+1 y una escala por capa.

  python exportar_bitnet.py modelos/cmp_bitnet_s0_v3.pt
  python exportar_bitnet.py modelos/cmp_bitnet_s0_v3.pt --verificar
"""
import argparse
import io
from pathlib import Path

import torch

from modelo import BitLinear, Config, Nucleo, cargar, elegir_dispositivo

# -1 -> 0, 0 -> 1, +1 -> 2 (2 bits por peso)


def empaquetar(t):
    """Tensor de enteros en {-1,0,1} -> bytes con 4 valores cada uno."""
    v = (t.flatten() + 1).to(torch.uint8)
    relleno = (-len(v)) % 4
    v = torch.cat([v, torch.ones(relleno, dtype=torch.uint8)])
    v = v.view(-1, 4)
    return v[:, 0] | (v[:, 1] << 2) | (v[:, 2] << 4) | (v[:, 3] << 6)


def desempaquetar(b, n):
    v = torch.stack([(b >> s) & 3 for s in (0, 2, 4, 6)], dim=1).flatten()[:n]
    return v.to(torch.int8) - 1


def exportar(ruta_entrada, ruta_salida):
    datos = torch.load(ruta_entrada, map_location="cpu", weights_only=False)
    cfg = Config(**datos["config"])
    if not cfg.bitnet:
        raise SystemExit("Este modelo no fue entrenado con --bitnet; no se puede empaquetar en ternario.")
    modelo = Nucleo(cfg)
    modelo.load_state_dict(datos["pesos"])
    ternarios, resto = {}, {}
    nombres_bit = {f"{n}.weight" for n, m in modelo.named_modules() if isinstance(m, BitLinear)}
    for nombre, p in modelo.state_dict().items():
        if nombre in nombres_bit:
            escala = p.abs().mean().clamp(min=1e-5)
            q = (p / escala).round().clamp(-1, 1).to(torch.int8)
            ternarios[nombre] = {"bytes": empaquetar(q), "forma": tuple(p.shape), "escala": escala.half()}
        else:
            resto[nombre] = p.half()  # embeddings, normas y salida en 16 bits
    torch.save({"config": datos["config"], "stoi": datos["stoi"], "ternarios": ternarios, "resto": resto}, ruta_salida)
    return ternarios, resto


def cargar_empaquetado(ruta, dispositivo):
    datos = torch.load(ruta, map_location="cpu", weights_only=False)
    modelo = Nucleo(Config(**datos["config"]))
    estado = {k: v.float() for k, v in datos["resto"].items()}
    for nombre, t in datos["ternarios"].items():
        n = 1
        for d in t["forma"]:
            n *= d
        estado[nombre] = desempaquetar(t["bytes"], n).float().view(t["forma"]) * t["escala"].float()
    modelo.load_state_dict(estado)
    for m in modelo.modules():
        if isinstance(m, BitLinear):
            m.cuantizado = True
    modelo.to(dispositivo).eval()
    stoi = datos["stoi"]
    return modelo, stoi, {i: c for c, i in stoi.items()}


def tamano_real(ternarios, resto):
    """Bytes de los números en sí, sin el envoltorio del archivo."""
    b = sum(t["bytes"].numel() + 2 for t in ternarios.values())
    return b + sum(p.numel() * 2 for p in resto.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("modelo")
    ap.add_argument("--salida", default=None)
    ap.add_argument("--verificar", action="store_true", help="compara respuestas con el original")
    args = ap.parse_args()
    entrada = Path(args.modelo)
    salida = Path(args.salida) if args.salida else entrada.with_name(entrada.stem + "_empaquetado.pt")

    ternarios, resto = exportar(entrada, salida)
    n_tern = sum(t["bytes"].numel() * 4 for t in ternarios.values())
    print(f"Original:    {entrada.stat().st_size / 1e6:.2f} MB  ({entrada.name}, pesos en decimales de entrenamiento)")
    print(f"Empaquetado: {salida.stat().st_size / 1e6:.2f} MB  ({salida.name})")
    print(f"  de eso, números puros: {tamano_real(ternarios, resto) / 1e6:.2f} MB "
          f"(~{n_tern:,} pesos ternarios a 2 bits + {sum(p.numel() for p in resto.values()):,} en 16 bits)")

    if args.verificar:
        from evaluar import GRUPOS, cargar_casos, responder
        from herramientas import Diccionario
        dispositivo = elegir_dispositivo()
        casos, dic = cargar_casos(), Diccionario()
        terminos = [c["termino"] for c in casos]
        a = responder(*cargar(entrada, dispositivo), dispositivo, terminos, dic)
        b = responder(*cargar_empaquetado(salida, dispositivo), dispositivo, terminos, dic)
        iguales = sum(x["respuesta"] == y["respuesta"] for x, y in zip(a, b))
        print(f"\nRespuestas idénticas al original: {iguales}/{len(casos)} ({100 * iguales / len(casos):.1f}%)")
        for g in GRUPOS:
            idx = [i for i, c in enumerate(casos) if c["grupo"] == g]
            if idx:
                ac = sum(b[i]["respuesta"] == casos[i]["cat"] for i in idx)
                print(f"  {g:22s} acierto empaquetado {100 * ac / len(idx):5.1f}%")


if __name__ == "__main__":
    main()

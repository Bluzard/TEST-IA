"""LoRA para el núcleo BitNet congelado.

Cada matriz objetivo pasa de  y = BitLinear(x)  a  y = BitLinear(x) + (alpha/r) · B(A x).
A (r×in) y B (out×r) están en precisión normal; los pesos ternarios del núcleo NO se tocan ni se fusionan.
B parte en cero: al inicio el modelo es idéntico al núcleo base, y con el adaptador dormido (activo=False) también.

Matrices objetivo por capa:  qkv (512→1536), proy (512→512), fc1 (512→2048), fc2 (2048→512).
"""
import math
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F

OBJETIVOS = ("qkv", "proy", "fc1", "fc2")


def _get(b, n):
    return {"qkv": b.qkv, "proy": b.proy, "fc1": b.mlp[0], "fc2": b.mlp[2]}[n]


def _set(b, n, m):
    if n == "qkv":
        b.qkv = m
    elif n == "proy":
        b.proy = m
    elif n == "fc1":
        b.mlp[0] = m
    else:
        b.mlp[2] = m


class LoraLinear(nn.Module):
    def __init__(self, base, r, alpha):
        super().__init__()
        self.base, self.r, self.escala, self.activo = base, r, alpha / r, True
        self.A = nn.Parameter(torch.empty(r, base.in_features))
        self.B = nn.Parameter(torch.zeros(base.out_features, r))
        nn.init.kaiming_uniform_(self.A, a=math.sqrt(5))

    def forward(self, x):
        y = self.base(x)
        if not self.activo:
            return y
        return y + F.linear(F.linear(x, self.A), self.B) * self.escala


@dataclass
class ConfigLora:
    r: int = 8
    alpha: float = 16.0
    objetivos: tuple = OBJETIVOS


def aplicar_lora(modelo, cfg: ConfigLora):
    """Congela TODO el núcleo y agrega adaptadores entrenables en las matrices objetivo de todas las capas."""
    for p in modelo.parameters():
        p.requires_grad_(False)
    for b in modelo.bloques:
        for n in cfg.objetivos:
            _set(b, n, LoraLinear(_get(b, n), cfg.r, cfg.alpha))
    modelo.cfg_lora = cfg
    return modelo


def lineales_lora(modelo):
    return [m for m in modelo.modules() if isinstance(m, LoraLinear)]


def activar(modelo, activo):
    """Despierta o duerme el adaptador (dormido = comportamiento idéntico al núcleo base)."""
    for m in lineales_lora(modelo):
        m.activo = activo


def parametros_lora(modelo):
    return [p for m in lineales_lora(modelo) for p in (m.A, m.B)]


def contar(modelo):
    n = sum(p.numel() for p in parametros_lora(modelo))
    return n, n * 2 / 1e6  # parámetros y MB en fp16


def estado_lora(modelo):
    d = {}
    for i, b in enumerate(modelo.bloques):
        for n in modelo.cfg_lora.objetivos:
            m = _get(b, n)
            d[f"bloques.{i}.{n}.A"] = m.A.detach().cpu()
            d[f"bloques.{i}.{n}.B"] = m.B.detach().cpu()
    return d


def guardar_lora(modelo, ruta):
    c = modelo.cfg_lora
    torch.save({"r": c.r, "alpha": c.alpha, "objetivos": list(c.objetivos), "pesos": estado_lora(modelo)}, ruta)


def cargar_lora(modelo, ruta):
    d = torch.load(ruta, map_location="cpu", weights_only=False)
    aplicar_lora(modelo, ConfigLora(d["r"], d["alpha"], tuple(d["objetivos"])))
    for i, b in enumerate(modelo.bloques):
        for n in modelo.cfg_lora.objetivos:
            m = _get(b, n)
            m.A.data.copy_(d["pesos"][f"bloques.{i}.{n}.A"])
            m.B.data.copy_(d["pesos"][f"bloques.{i}.{n}.B"])
    return modelo


def suma_base(modelo):
    """Suma de verificación de los pesos del núcleo (no de los adaptadores): debe no cambiar al entrenar."""
    return sum(float(p.detach().double().sum()) + float(p.detach().double().abs().sum())
               for n, p in modelo.named_parameters() if not n.endswith((".A", ".B")))

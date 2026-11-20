"""Núcleo de razonamiento compacto: un Transformer diminuto a nivel de caracteres.

Opciones para experimentar con las ideas de la arquitectura:
  --bitnet   pesos ternarios (-1, 0, +1) estilo BitNet b1.58 (solo pesos; las
             activaciones quedan en precisión normal para simplificar).
  --vueltas  pasa N veces por las mismas capas (bucle latente): más
             "pensamiento" sin agregar parámetros.
"""
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class Config:
    vocab: int
    bloque: int = 192
    d: int = 128
    capas: int = 4
    cabezas: int = 4
    vueltas: int = 1
    bitnet: bool = False


class BitLinear(nn.Linear):
    """Lineal con pesos cuantizados a {-1, 0, +1} * escala.

    Durante el entrenamiento se guarda una copia en decimal y se usa el
    "straight-through estimator": hacia adelante se usan los pesos ternarios,
    hacia atrás el gradiente pasa como si no hubiera redondeo.
    """

    cuantizado = False  # True cuando los pesos ya vienen como {-1,0,+1}*escala (modelo exportado)

    def forward(self, x):
        if self.cuantizado:
            return F.linear(x, self.weight, self.bias)
        w = self.weight
        escala = w.abs().mean().clamp(min=1e-5)
        wq = (w / escala).round().clamp(-1, 1) * escala
        w = w + (wq - w).detach()
        return F.linear(x, w, self.bias)


class Bloque(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        Lin = BitLinear if cfg.bitnet else nn.Linear
        self.cabezas = cfg.cabezas
        self.ln1 = nn.LayerNorm(cfg.d)
        self.qkv = Lin(cfg.d, 3 * cfg.d, bias=False)
        self.proy = Lin(cfg.d, cfg.d, bias=False)
        self.ln2 = nn.LayerNorm(cfg.d)
        self.mlp = nn.Sequential(Lin(cfg.d, 4 * cfg.d, bias=False), nn.GELU(), Lin(4 * cfg.d, cfg.d, bias=False))

    def forward(self, x):
        B, T, C = x.shape
        q, k, v = self.qkv(self.ln1(x)).split(C, dim=2)
        q, k, v = (t.view(B, T, self.cabezas, C // self.cabezas).transpose(1, 2) for t in (q, k, v))
        a = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        x = x + self.proy(a.transpose(1, 2).contiguous().view(B, T, C))
        return x + self.mlp(self.ln2(x))


class Nucleo(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.tok = nn.Embedding(cfg.vocab, cfg.d)
        self.pos = nn.Embedding(cfg.bloque, cfg.d)
        self.vuelta = nn.Embedding(cfg.vueltas, cfg.d)  # le indica en qué vuelta va
        self.bloques = nn.ModuleList(Bloque(cfg) for _ in range(cfg.capas))
        self.ln = nn.LayerNorm(cfg.d)
        self.cabeza = nn.Linear(cfg.d, cfg.vocab, bias=False)

    def forward(self, idx, objetivos=None, mascara=None):
        T = idx.shape[1]
        x = self.tok(idx) + self.pos(torch.arange(T, device=idx.device))
        for v in range(self.cfg.vueltas):
            x = x + self.vuelta.weight[v]
            for b in self.bloques:
                x = b(x)
        logits = self.cabeza(self.ln(x))
        if objetivos is None:
            return logits, None
        perdida = F.cross_entropy(logits.view(-1, logits.size(-1)), objetivos.view(-1), reduction="none")
        if mascara is None:
            perdida = perdida.mean()
        else:
            perdida = (perdida * mascara.view(-1)).sum() / mascara.sum().clamp(min=1)
        return logits, perdida

    def parametros(self):
        return sum(p.numel() for p in self.parameters())


@torch.no_grad()
def generar_lineas(modelo, textos, stoi, itos, dispositivo, max_chars=100):
    """Continúa cada texto (en lote) hasta el siguiente salto de línea."""
    modelo.eval()
    T = modelo.cfg.bloque
    B = len(textos)
    ids = torch.zeros(B, T, dtype=torch.long)
    largos = torch.zeros(B, dtype=torch.long)
    for i, t in enumerate(textos):
        e = [stoi[c] for c in t if c in stoi][: T - 1]
        ids[i, : len(e)] = torch.tensor(e)
        largos[i] = len(e)
    inicio = largos.clone()
    ids, largos = ids.to(dispositivo), largos.to(dispositivo)
    activo = torch.ones(B, dtype=torch.bool, device=dispositivo)
    salto = stoi["\n"]
    filas = torch.arange(B, device=dispositivo)
    for _ in range(max_chars):
        if not activo.any():
            break
        logits, _ = modelo(ids)
        sig = logits[filas, largos - 1].argmax(-1)
        escribir = activo & (largos < T)
        ids[filas[escribir], largos[escribir]] = sig[escribir]
        largos = largos + escribir.long()
        activo = escribir & (sig != salto)
    ids, largos = ids.cpu(), largos.cpu()
    salida = []
    for i in range(B):
        s = "".join(itos[int(c)] for c in ids[i, inicio[i] : largos[i]])
        salida.append(s.rstrip("\n"))
    return salida


def cargar(ruta, dispositivo):
    datos = torch.load(ruta, map_location="cpu", weights_only=False)
    modelo = Nucleo(Config(**datos["config"]))
    modelo.load_state_dict(datos["pesos"])
    modelo.to(dispositivo).eval()
    stoi = datos["stoi"]
    itos = {i: c for c, i in stoi.items()}
    return modelo, stoi, itos


def elegir_dispositivo():
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"

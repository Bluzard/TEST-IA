"""Núcleo v2-A (≈158 M): mismo estilo que el motor C++ (LayerNorm, GELU, posiciones aprendidas, BitNet ternario en qkv/proy/fc1/fc2),
con GQA (12 cabezas / 4 KV) y embeddings atados (entrada = salida)."""
import math
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class ConfigV2:
    vocab: int = 24004
    bloque: int = 1024
    d: int = 768
    capas: int = 22
    cabezas: int = 12
    kv: int = 4
    ff: int = 3072


class BitLinear(nn.Linear):
    """Pesos {-1,0,+1}·escala (escala = media |w| por tensor), straight-through; igual que modelo.BitLinear."""

    def forward(self, x):
        w = self.weight
        escala = w.abs().mean().clamp(min=1e-5)
        wq = (w / escala).round().clamp(-1, 1) * escala
        return F.linear(x, w + (wq - w).detach())


class BloqueV2(nn.Module):
    def __init__(self, c: ConfigV2):
        super().__init__()
        self.h, self.kv, self.hd = c.cabezas, c.kv, c.d // c.cabezas
        self.ln1 = nn.LayerNorm(c.d)
        self.qkv = BitLinear(c.d, c.d + 2 * c.kv * self.hd, bias=False)
        self.proy = BitLinear(c.d, c.d, bias=False)
        self.ln2 = nn.LayerNorm(c.d)
        self.fc1 = BitLinear(c.d, c.ff, bias=False)
        self.fc2 = BitLinear(c.ff, c.d, bias=False)

    def forward(self, x):
        B, T, C = x.shape
        kvd = self.kv * self.hd
        q, k, v = self.qkv(self.ln1(x)).split([C, kvd, kvd], dim=2)
        q = q.view(B, T, self.h, self.hd).transpose(1, 2)
        k = k.view(B, T, self.kv, self.hd).transpose(1, 2)
        v = v.view(B, T, self.kv, self.hd).transpose(1, 2)
        a = F.scaled_dot_product_attention(q, k, v, is_causal=True, enable_gqa=True)
        x = x + self.proy(a.transpose(1, 2).reshape(B, T, C))
        return x + self.fc2(F.gelu(self.fc1(self.ln2(x))))


class NucleoV2(nn.Module):
    def __init__(self, c: ConfigV2):
        super().__init__()
        self.cfg = c
        self.tok = nn.Embedding(c.vocab, c.d)
        self.pos = nn.Embedding(c.bloque, c.d)
        self.bloques = nn.ModuleList(BloqueV2(c) for _ in range(c.capas))
        self.ln = nn.LayerNorm(c.d)
        self.apply(self._init)
        for n, p in self.named_parameters():  # proyecciones residuales más pequeñas (GPT-2)
            if n.endswith(("proy.weight", "fc2.weight")):
                nn.init.normal_(p, 0.0, 0.02 / math.sqrt(2 * c.capas))

    @staticmethod
    def _init(m):
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, 0.0, 0.02)

    def forward(self, idx, objetivos=None, emb_head=None):
        """emb_head: tabla alternativa para entrada y salida (p. ej. cuantizada); por defecto la propia."""
        E = self.tok.weight if emb_head is None else emb_head
        T = idx.shape[1]
        x = F.embedding(idx, E) + self.pos.weight[:T]
        for b in self.bloques:
            x = b(x)
        logits = F.linear(self.ln(x), E)
        if objetivos is None:
            return logits
        return F.cross_entropy(logits.reshape(-1, logits.size(-1)).float(), objetivos.reshape(-1))

    def parametros(self):
        return sum(p.numel() for p in self.parameters())

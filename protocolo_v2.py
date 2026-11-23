"""Formato de conversación del núcleo v2: igual que protocolo.Formato pero con el tokenizador de 24.004 tokens (datos/v2/tokenizador_v2_sft.json).
Las etiquetas se resuelven por nombre, así que el protocolo (B:/E:/R:, <usuario>/<asistente>/<herramienta>/<fin>) no cambia."""
from pathlib import Path

from tokenizers import Tokenizer

from protocolo import ETIQUETAS, Formato

RAIZ = Path(__file__).parent
TOK_V2_SFT = RAIZ / "datos" / "v2" / "tokenizador_v2_sft.json"
CONTEXTO_V2 = 1024


class FormatoV2(Formato):
    def __init__(self):
        self.tok = Tokenizer.from_file(str(TOK_V2_SFT))
        self.usuario, self.asistente, self.herramienta, self.fin = (self.tok.token_to_id(e) for e in ETIQUETAS)
        self.relleno = self.tok.token_to_id("<|relleno|>")
        self.vocab = self.tok.get_vocab_size()
        assert None not in (self.usuario, self.asistente, self.herramienta, self.fin, self.relleno)

"""Formato de conversación del núcleo (compartido por datos, entrenamiento e inferencia).

  <usuario> pregunta <asistente> R: respuesta <fin>
  <usuario> pregunta <asistente> B: consulta <herramienta> resultados <asistente> R: respuesta <fin>

El modelo escribe lo que sigue a <asistente> (hasta <fin> o <herramienta>).
Lo que pone el entorno (usuario, resultados de la herramienta y las etiquetas que
los rodean) no cuenta para la pérdida: el modelo solo aprende a escribir B:/R:.
"""
from pathlib import Path

from tokenizers import Tokenizer

RAIZ = Path(__file__).parent
TOK_BASE = RAIZ / "datos" / "tokenizador.json"
TOK_SFT = RAIZ / "datos" / "tokenizador_sft.json"
ETIQUETAS = ["<usuario>", "<asistente>", "<herramienta>", "<fin>"]
MAX_TOKENS_RESULTADOS = 330  # tope para que pregunta + resultados + respuesta quepan en el contexto de 512
TOPE_EXPERTO = 200   # documentación (B:) con el experto de código: el código gasta ~2,6x más tokens por carácter
TOPE_EJECUCION = 80  # salida del sandbox (E:): solo el resultado o la última línea de la excepción
TOPE_EJEMPLO = 440   # tope duro de pregunta + herramienta + resultados + respuesta (el contexto es 512)
SIN_INFO ="No tengo información suficiente para responder eso."


def tokenizador():
    """Tokenizador del preentrenamiento más las 4 etiquetas de turno (ids al final del vocabulario)."""
    if not TOK_SFT.exists():
        t = Tokenizer.from_file(str(TOK_BASE))
        t.add_special_tokens(ETIQUETAS)
        t.save(str(TOK_SFT))
    return Tokenizer.from_file(str(TOK_SFT))


class Formato:
    def __init__(self):
        self.tok = tokenizador()
        self.usuario, self.asistente, self.herramienta, self.fin = (self.tok.token_to_id(e) for e in ETIQUETAS)
        self.relleno = self.tok.token_to_id("<|relleno|>")
        self.vocab = self.tok.get_vocab_size()

    def texto(self, t):
        return self.tok.encode(t).ids

    def ids_prompt(self, pregunta):
        return [self.usuario] + self.texto(" " + pregunta) + [self.asistente]

    def ids_tras_herramienta(self, resultados, tope=None):
        """Lo que el entorno agrega después de que el modelo emite <herramienta> (tope = máximo de tokens del resultado)."""
        return self.texto(" " + resultados)[: tope or MAX_TOKENS_RESULTADOS] + [self.asistente]

    def ejemplo(self, pregunta, consulta=None, resultados=None, respuesta="", prefijo="B", tope=None):
        """Devuelve (ids, mascara): mascara=1 solo en lo que escribe el modelo. prefijo: B (buscar) o E (ejecutar)."""
        ids, m = [], []

        def poner(trozo, aprende):
            ids.extend(trozo)
            m.extend([1.0 if aprende else 0.0] * len(trozo))

        poner(self.ids_prompt(pregunta), False)
        if consulta is not None:
            poner(self.texto(f" {prefijo}: " + consulta), True)
            poner([self.herramienta], True)
            poner(self.ids_tras_herramienta(resultados, tope), False)
        poner(self.texto(" R: " + respuesta), True)
        poner([self.fin], True)
        return ids, m

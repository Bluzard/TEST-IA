"""TEST-IA sobre un modelo base de 3B (Ollama, qwen2.5:3b) con la capa propia de herramientas.

  .venv\\Scripts\\python.exe inferir.py                      # chat interactivo
  .venv\\Scripts\\python.exe inferir.py "¿Quién escribió Rayuela?" "calcula 17*23"

Orden por turno: capa 1 (cuentas exactas y órdenes de memoria, sin IA) -> prompts de imagen (determinista) -> hora/clima/datos en vivo
-> modelo de 3B con herramientas: buscar_web, recordar, ejecutar_python.
"""
import argparse
import json
from pathlib import Path

import llm
from herramientas import buscar_memoria, buscar_web, capa1

RAIZ = Path(__file__).parent
SIN_INFO = "No tengo información suficiente para responder eso."

SISTEMA = (
    "Eres TEST-IA, un asistente en español, claro y directo, con un toque de humor ligero solo cuando la charla es ligera. "
    "Si el usuario está triste o preocupado, responde con empatía y sin chistes. "
    "Para datos que cambian, hechos que no conozcas con seguridad, definiciones precisas o cualquier duda sobre el mundo, usa la herramienta buscar_web "
    "y responde SOLO con lo que digan los resultados, copiando el dato tal como aparece y nombrando la fuente. Si los resultados no traen la respuesta, dilo: no inventes. "
    "Usa recordar para lo que el usuario te pidió guardar. Usa ejecutar_python (solo `import math`) para cálculos y para comprobar código antes de darlo por bueno. "
    "No uses herramientas para saludos ni charla. Responde breve, salvo que te pidan detalle."
)

HERRAMIENTAS = [
    {"type": "function", "function": {"name": "buscar_web", "description": "Busca en la web (fichas locales y DuckDuckGo) y devuelve los mejores resultados con título y fragmento.",
                                      "parameters": {"type": "object", "properties": {"consulta": {"type": "string", "description": "Consulta corta en español"}}, "required": ["consulta"]}}},
    {"type": "function", "function": {"name": "recordar", "description": "Busca en la memoria personal del usuario (lo que pidió recordar).",
                                      "parameters": {"type": "object", "properties": {"consulta": {"type": "string"}}, "required": ["consulta"]}}},
    {"type": "function", "function": {"name": "ejecutar_python", "description": "Ejecuta Python seguro (solo `import math`, 3 s) e imprime el resultado.",
                                      "parameters": {"type": "object", "properties": {"codigo": {"type": "string"}}, "required": ["codigo"]}}},
]


def _tiempo_real(pregunta, partes, buscador, modelo=None):
    """Hora/fecha del reloj del equipo; clima y datos en vivo: se busca y el modelo responde solo con los resultados."""
    traza, respuestas = ["[tiempo real]"], []
    for tipo, valor in partes:
        if tipo == "texto":
            respuestas.append(valor)
            continue
        resultados = buscador(valor)
        traza.append(f"[buscar_web] {valor} -> {resultados.replace(chr(10), ' | ')[:200]}")
        pregunta_modelo = f"¿Cómo está el {valor}?" if valor.startswith("clima ") else pregunta
        msg = [{"role": "system", "content": "Responde en una o dos frases, solo con los datos de los resultados; si no traen el dato, dilo y nombra la fuente."},
               {"role": "user", "content": f"{pregunta_modelo}\n\nResultados:\n{resultados}"}]
        r = (llm.chat(msg, modelo=modelo, temperatura=0.1).get("content") or "").strip()
        respuestas.append(r or "No pude leer ese dato en los resultados.")
    return " ".join(respuestas), traza


class Sesion:
    """Una conversación: historial corto, memoria externa con enfriamiento y estado del último pedido de imagen."""

    def __init__(self, memoria=True, buscador=buscar_web, ruta_memoria=None, modelo=None, traducir=True, historial=12):
        from enrutador import EnrutadorV3
        from memoria import Memoria

        self.modelo, self.buscador, self.traducir, self.max_hist = modelo, buscador, traducir, historial
        self.memoria = (Memoria(ruta_memoria) if ruta_memoria else Memoria()) if memoria else None
        self.enr = EnrutadorV3()
        self.mensajes = [{"role": "system", "content": SISTEMA}]
        self.ultima_idea_imagen = None
        self.ultimo_modelo_imagen = None

    def _recortar(self):
        resto = self.mensajes[1:]
        if len(resto) > self.max_hist:
            resto = resto[-self.max_hist:]
            while resto and resto[0]["role"] != "user":  # nunca empezar en medio de una llamada a herramienta
                resto = resto[1:]
        self.mensajes = self.mensajes[:1] + resto

    def _recordar(self, consulta):
        return (buscar_memoria(consulta, self.memoria) if self.memoria else "") or "No hay nada guardado sobre eso."

    def atender(self, p, imprimir=False):
        """Un turno. Devuelve (respuesta, traza, modo)."""
        if self.memoria:
            self.memoria.enfriar()
        modo = "imagen" if self.enr.paso(p) == "imagen" else None
        r, traza = self._responder(p, modo)
        if imprimir:
            print(f"P: {p}" + (f"   [{modo}]" if modo else ""))
            for t in traza:
                print("   ", t)
            print(f"R: {r}\n")
        return r, traza, modo

    def _responder(self, p, modo):
        exacta = capa1(p, self.memoria) if modo != "imagen" else None
        if exacta is not None:
            return exacta, ["[capa 1, sin IA]"]
        if modo == "imagen":
            from imagen_prompt import prompt_imagen

            def escribir(pregunta, ficha):
                msg = [{"role": "system", "content": "You write image-generation prompts in English. Output ONLY the prompt body, no explanations. Model notes: " + ficha},
                       {"role": "user", "content": pregunta}]
                return (llm.chat(msg, modelo=self.modelo, temperatura=0.7, max_tokens=300).get("content") or "").strip()

            res = prompt_imagen(p, self.ultimo_modelo_imagen, self.ultima_idea_imagen, escribir_cuerpo=escribir, traducir=self.traducir)
            if res:
                r, traza = res
                for t in traza:
                    if t.startswith("[idea ") and ": " in t:
                        self.ultima_idea_imagen = t.split(": ", 1)[1].rstrip("]")
                    if t.startswith("[modelo imagen: "):
                        self.ultimo_modelo_imagen = t[len("[modelo imagen: "):-1]
                return r, traza
        from tiempo_real import dividir

        partes = dividir(p)
        if partes:
            return _tiempo_real(p, partes, self.buscador, self.modelo)
        from sandbox import ejecutar_codigo

        traza = []
        ejecutores = {"buscar_web": lambda consulta: self.buscador(consulta), "recordar": self._recordar, "ejecutar_python": ejecutar_codigo}
        from datetime import datetime

        ahora = datetime.now()
        contexto = f"[Contexto del sistema: la fecha de hoy es {ahora:%Y-%m-%d} (el año actual es {ahora.year}) y son las {ahora:%H:%M}. No pidas la fecha al usuario.]"
        recuerdo = buscar_memoria(p, self.memoria) if self.memoria else ""
        if recuerdo:
            contexto += f"\n[Memoria del usuario: {recuerdo}]"
        self.mensajes.append({"role": "user", "content": f"{p}\n\n{contexto}"})
        r = llm.agente(self.mensajes, HERRAMIENTAS, ejecutores, modelo=self.modelo, traza=traza)
        self._recortar()
        return r or SIN_INFO, traza


def preparar_mensaje(t, leer_linea=None):
    """Prepara lo que el usuario escribe o pega: 1) «@ruta» se sustituye por el contenido del archivo (las consolas de Windows cortan una línea pegada a ≈ 4.000 caracteres);
    2) un JSON pegado en varias líneas se completa leyendo líneas hasta cerrar las llaves; 3) un texto que es un literal de cadena JSON («"{\\n  \\"a\\": 1}"») se desescapa."""
    import re

    def desescapar(x):
        s = x.strip()
        if len(s) > 2 and s[0] == '"' and s[-1] == '"':
            try:
                v = json.loads(s)
                if isinstance(v, str):
                    return v
            except ValueError:
                pass
        return x

    def archivo(m):
        ruta = Path(m.group(1).strip('"'))
        for base in (Path.cwd(), RAIZ):
            c = ruta if ruta.is_absolute() else base / ruta
            if c.is_file():
                return desescapar(c.read_text(encoding="utf-8"))
        return m.group(0)

    t = re.sub(r'@("[^"]+"|[^\s"]+)', archivo, t)
    if leer_linea is not None:
        n = 0
        while (t.count("{") - t.count("}") > 0 or t.count("[") - t.count("]") > 0) and n < 3000:
            try:
                t += "\n" + leer_linea()
            except EOFError:
                break
            n += 1
    return desescapar(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("preguntas", nargs="*")
    ap.add_argument("--modelo", default=None, help=f"modelo de Ollama (defecto {llm.MODELO})")
    ap.add_argument("--sin-memoria", action="store_true", help="desactiva la memoria externa (datos/memoria.json)")
    ap.add_argument("--sin-traductor", action="store_true", help="prompts de imagen: no cargar el traductor (los escribe el modelo)")
    args = ap.parse_args()
    if not llm.disponible(args.modelo):
        raise SystemExit(f"Ollama no responde o falta el modelo. Ejecuta:  ollama pull {args.modelo or llm.MODELO}")
    sesion = Sesion(memoria=not args.sin_memoria, modelo=args.modelo, traducir=not args.sin_traductor)
    print(f"[modelo] {args.modelo or llm.MODELO}", flush=True)
    if args.preguntas:
        for p in args.preguntas:
            sesion.atender(preparar_mensaje(p), imprimir=True)
        return
    print("Chat interactivo. Escribe tu pregunta; «salir» (o Ctrl+C / Ctrl+Z) para terminar.")
    print("Textos largos: escribe @ruta/al/archivo.json (la consola de Windows corta las líneas pegadas a ~4.000 caracteres).\n")
    while True:
        try:
            p = input("Tú> ").strip()
            p = preparar_mensaje(p, leer_linea=lambda: input(""))
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if p.lower() in ("salir", "exit", "quit"):
            break
        if p:
            sesion.atender(p, imprimir=True)


if __name__ == "__main__":
    main()

"""Cliente mínimo de Ollama para el modelo base (por defecto qwen2.5:3b) con llamadas a herramientas. Solo biblioteca estándar.

  OLLAMA_URL   (defecto http://127.0.0.1:11434)
  TEST_IA_MODELO (defecto qwen2.5:3b)

`agente()` ejecuta el bucle: el modelo pide una herramienta -> se ejecuta en Python -> el resultado vuelve al modelo -> respuesta final.
"""
import json
import os
import urllib.error
import urllib.request

URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODELO = os.environ.get("TEST_IA_MODELO", "qwen2.5:3b")
CONTEXTO = 8192


class ErrorLLM(RuntimeError):
    pass


def _post(ruta, cuerpo, tiempo=300):
    req = urllib.request.Request(URL + ruta, data=json.dumps(cuerpo).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=tiempo) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise ErrorLLM(f"No pude hablar con Ollama en {URL} ({e.reason}). ¿Está abierto? Prueba: ollama run {MODELO}") from e


def disponible(modelo=None):
    """True si Ollama responde y tiene el modelo descargado."""
    try:
        with urllib.request.urlopen(URL + "/api/tags", timeout=5) as r:
            nombres = [m["name"] for m in json.loads(r.read().decode("utf-8")).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return False
    m = modelo or MODELO
    return m in nombres or (":" not in m and any(n.split(":")[0] == m for n in nombres))


def chat(mensajes, herramientas=None, modelo=None, temperatura=0.3, max_tokens=700):
    """Un turno al modelo. Devuelve el mensaje del asistente ({role, content, tool_calls?})."""
    cuerpo = {"model": modelo or MODELO, "messages": mensajes, "stream": False, "keep_alive": "30m",
              "options": {"temperature": temperatura, "num_ctx": CONTEXTO, "num_predict": max_tokens}}
    if herramientas:
        cuerpo["tools"] = herramientas
    return _post("/api/chat", cuerpo).get("message", {"role": "assistant", "content": ""})


def agente(mensajes, herramientas, ejecutores, modelo=None, max_pasos=4, temperatura=0.3, traza=None):
    """Bucle de herramientas. `mensajes` se modifica (se le añaden las llamadas y sus resultados). Devuelve el texto final."""
    traza = traza if traza is not None else []
    for paso in range(max_pasos + 1):
        msg = chat(mensajes, herramientas if paso < max_pasos else None, modelo, temperatura)
        llamadas = msg.get("tool_calls") or []
        if not llamadas:
            mensajes.append({"role": "assistant", "content": msg.get("content", "")})
            return (msg.get("content") or "").strip()
        mensajes.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": llamadas})
        for ll in llamadas:
            f = ll.get("function", {})
            nombre, args = f.get("name", ""), f.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            try:
                salida = str(ejecutores[nombre](**args))
            except KeyError:
                salida = f"Herramienta desconocida: {nombre}"
            except Exception as e:  # el modelo ve el error y puede corregirse
                salida = f"Error: {type(e).__name__}: {str(e)[:200]}"
            traza.append(f"[{nombre}] {json.dumps(args, ensure_ascii=False)[:120]} -> {salida.replace(chr(10), ' | ')[:200]}")
            mensajes.append({"role": "tool", "tool_name": nombre, "content": salida[:3000]})
    return ""

"""Servicio LOCAL del redactor determinista de escenas (escena_prompt.componer) para que b_chat lo llame por HTTP.

  .venv\\Scripts\\python.exe servicio_escenas.py [--puerto 8765]

Solo escucha en 127.0.0.1. No guarda ni registra el texto de las escenas (solo el tiempo y el tamaño).
  GET  /salud           -> {"ok": true}
  POST /extraer         -> cuerpo {"request": {...payload del extractor de b_chat...}}  =>  {"answers": {char,user,relacion,escena}, "ms": 123}   (si hay --extractor-lora)
  POST /escena          -> cuerpo {"source": {...igual que buildImageVisibleSource...}}  =>  {"body": "...", "ms": 123, "descartadas": n}
                           body = «One woman in … + hechos actuales + lugar/hora/luz + mirada», SIN la apertura de cámara ni el estilo (b_chat los añade).
"""
import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

from escena_prompt import componer

CERROJO = Lock()  # el traductor no es reentrante: una escena a la vez
EXTRACTOR = {"motor": None, "fmt": None, "lora": None}
CERROJO_NUCLEO = Lock()


def _extractor():
    """Núcleo v2c + experto de extracción (motor C++, CPU). Se carga la primera vez que se pide. Sin LoRA configurada no hay extractor."""
    if EXTRACTOR["motor"] is None:
        ruta = EXTRACTOR["lora"]
        if not ruta or not os.path.exists(ruta):
            raise RuntimeError("extractor no configurado (--extractor-lora)")
        from motor_cpp import MotorCpp
        from protocolo_v2 import FormatoV2
        raiz = os.path.dirname(os.path.abspath(__file__))
        EXTRACTOR["fmt"], EXTRACTOR["motor"] = FormatoV2(), MotorCpp(os.path.join(raiz, "modelos", "nucleo_v2c_sft.bin"))
        EXTRACTOR["motor"].cargar_lora(ruta)
    return EXTRACTOR["motor"], EXTRACTOR["fmt"]


def extraer(request):
    """Las 4 preguntas cortas del turno -> {char, user, relacion, escena} ya interpretadas."""
    import extractor_datos as E
    from inferir import _texto, generar_lote
    motor, fmt = _extractor()
    salida, crudo = {}, {}
    with CERROJO_NUCLEO:
        for q in E.PREGUNTAS:
            ids = fmt.ids_prompt(E.prompt({"request": request}, q)) + fmt.texto(" R:")
            nuevo, _ = generar_lote(motor, fmt, [ids], "cpu", 1.0, max_nuevos=190)[0]
            crudo[q] = _texto(fmt, nuevo)
            salida[q if q in ("char", "user") else q] = E.parsear(q, crudo[q])
    return {"char": salida["char"], "user": salida["user"], "relacion": salida["relacion"], "escena": salida["escena"]}, crudo


class Manejador(BaseHTTPRequestHandler):
    def _responder(self, codigo, obj):
        datos = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        if self.path == "/salud":
            return self._responder(200, {"ok": True})
        self._responder(404, {"error": "no existe"})

    def do_POST(self):
        if self.path == "/extraer":
            try:
                n = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(n).decode("utf-8")).get("request")
                t0 = time.time()
                respuestas, crudo = extraer(request)
                ms = round((time.time() - t0) * 1000)
                print(f"[extraer] {ms} ms", flush=True)
                return self._responder(200, {"answers": respuestas, "ms": ms})
            except Exception as e:
                print(f"[extraer] ERROR {type(e).__name__}: {str(e)[:200]}", flush=True)
                return self._responder(503, {"error": f"{type(e).__name__}: {str(e)[:200]}"})
        if self.path != "/escena":
            return self._responder(404, {"error": "no existe"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            fuente = json.loads(self.rfile.read(n).decode("utf-8")).get("source")
            if not isinstance(fuente, dict):
                return self._responder(400, {"error": "falta «source»"})
            t0 = time.time()
            with CERROJO:
                cuerpo, traza = componer(fuente, cuerpo=True)
            ms = round((time.time() - t0) * 1000)
            print(f"[escena] {ms} ms | {len(cuerpo)} caracteres | {len(traza['descartadas'])} cláusulas descartadas", flush=True)
            self._responder(200, {"body": cuerpo, "ms": ms, "descartadas": len(traza["descartadas"])})
        except Exception as e:  # el cliente cae a su respaldo; aquí solo se informa
            print(f"[escena] ERROR {type(e).__name__}: {str(e)[:200]}", flush=True)
            self._responder(500, {"error": f"{type(e).__name__}: {str(e)[:200]}"})

    def log_message(self, *a):  # sin registro de peticiones: no queda texto de escenas en consola
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8765)
    ap.add_argument("--extractor-lora", default=os.environ.get("EXTRACTOR_LORA"), help="LoRA del experto de extracción (opcional; activa POST /extraer)")
    a = ap.parse_args()
    EXTRACTOR["lora"] = a.extractor_lora
    componer({"camera": "pov", "main": {"person": "woman"}, "situation": "MAIN_ADULT está de pie."}, cuerpo=True)  # calienta el traductor
    print(f"[escena] listo en http://127.0.0.1:{a.puerto}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.puerto), Manejador).serve_forever()


if __name__ == "__main__":
    sys.exit(main())

"""Servicio LOCAL del redactor determinista de escenas (escena_prompt.componer) para que b_chat lo llame por HTTP.

  .venv\\Scripts\\python.exe servicio_escenas.py [--puerto 8765]

Solo escucha en 127.0.0.1. No guarda ni registra el texto de las escenas (solo el tiempo y el tamaño).
  GET  /salud           -> {"ok": true}
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
    a = ap.parse_args()
    componer({"camera": "pov", "main": {"person": "woman"}, "situation": "MAIN_ADULT está de pie."}, cuerpo=True)  # calienta el traductor
    print(f"[escena] listo en http://127.0.0.1:{a.puerto}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.puerto), Manejador).serve_forever()


if __name__ == "__main__":
    sys.exit(main())

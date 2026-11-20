"""Envoltorio ctypes del motor C++ (motor.dll). No importa PyTorch.

    m = MotorCpp("modelos/nucleo_sft_v3.bin")
    nuevos, parada = m.generar(ids_prompt, pen=1.1)
"""
import ctypes
import os
import struct
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).parent


class MotorCpp:
    def __init__(self, ruta_bin, dll=RAIZ / "motor.dll"):
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(Path(dll).parent))
        self.lib = ctypes.CDLL(str(dll))
        self.lib.nucleo_cargar.restype = ctypes.c_void_p
        self.lib.nucleo_cargar.argtypes = [ctypes.c_char_p]
        self.lib.nucleo_liberar.argtypes = [ctypes.c_void_p]
        self.lib.nucleo_logits.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.POINTER(ctypes.c_float)]
        self.lib.nucleo_generar.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_float, ctypes.c_int,
                                            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_double)]
        self.lib.nucleo_lora_cargar.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self.lib.nucleo_lora_activar.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.lib.nucleo_lora_descargar.argtypes = [ctypes.c_void_p]
        self.lib.nucleo_lora_bytes.argtypes = [ctypes.c_void_p]
        self.lib.nucleo_lora_bytes.restype = ctypes.c_longlong
        # caché multi-slot (2 ranuras): Activo / Tibio / Frío (un motor.dll de la Etapa 2 no las tiene: solo la API de una ranura)
        try:
            self.lib.nucleo_lora_cargar_ranura.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            self.lib.nucleo_lora_seleccionar.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self.lib.nucleo_lora_turno.argtypes = [ctypes.c_void_p]
            self.lib.nucleo_lora_estado.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self.lib.nucleo_lora_vida.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self.lib.nucleo_lora_config.argtypes = [ctypes.c_void_p, ctypes.c_int]
        except AttributeError:
            pass
        self.rutas_ranuras = {}   # nombre -> (ranura, ruta); para recargar un experto que se enfrió
        self.h = self.lib.nucleo_cargar(str(ruta_bin).encode())
        if not self.h:
            raise RuntimeError(f"No se pudo cargar {ruta_bin}")
        with open(ruta_bin, "rb") as f:
            magia = f.read(8)
            assert magia in (b"NUCL0001", b"NUCL0002"), magia
            c = struct.unpack("<13i", f.read(52))
            self.formato = magia.decode()
            # NUCL0002 (núcleo v2): cabezas de KV, flags (bit0 embedding atado, bit1 int8, bit2 KV fp16) y tokens por bloque de prefill
            self.cabezas_kv, self.flags = (self.__class__._extra(f) if magia == b"NUCL0002" else (c[4], 0))
        (self.vocab, self.bloque, self.d, self.capas, self.cabezas, self.vueltas, _, self.fin, self.herramienta,
         self.asistente, self.usuario, self.relleno, _) = c
        self.ultimos_tiempos = (0.0, 0.0, 0)

    @staticmethod
    def _extra(f):
        hk, flags, _bloque = struct.unpack("<3i", f.read(12))
        return hk, flags

    # --- adaptadores LoRA al vuelo ---
    def cargar_lora(self, ruta):
        """Carga un .lora en memoria y lo activa. Devuelve los milisegundos que tardó."""
        import time

        t = time.perf_counter()
        r = self.lib.nucleo_lora_cargar(self.h, str(ruta).encode())
        if r != 0:
            raise RuntimeError(f"no se pudo cargar {ruta} (código {r}: -1 no abre, -2 formato, -3 no calza con el núcleo)")
        return (time.perf_counter() - t) * 1000

    def activar_lora(self, activo=True):
        """Despierta o duerme el adaptador sin descargarlo (dormido = idéntico al núcleo base)."""
        self.lib.nucleo_lora_activar(self.h, int(bool(activo)))

    def descargar_lora(self):
        self.lib.nucleo_lora_descargar(self.h)

    @property
    def bytes_lora(self):
        return self.lib.nucleo_lora_bytes(self.h)

    # --- caché multi-slot con enfriamiento ---
    ESTADOS = {0: "frío", 1: "tibio", 2: "activo"}

    def registrar_experto(self, nombre, ruta, ranura):
        """Asocia un nombre con una ranura (0|1) y la ruta de su .lora; no lo carga todavía."""
        self.rutas_ranuras[nombre] = (ranura, str(ruta))

    def cargar_ranura(self, ruta, ranura):
        """Carga un .lora en la ranura dada en estado TIBIO. Devuelve los milisegundos que tardó."""
        import time

        t = time.perf_counter()
        r = self.lib.nucleo_lora_cargar_ranura(self.h, str(ruta).encode(), ranura)
        if r != 0:
            raise RuntimeError(f"no se pudo cargar {ruta} en la ranura {ranura} (código {r}: -1 no abre, -2 formato, -3 no calza, -4 ranura inválida)")
        return (time.perf_counter() - t) * 1000

    def seleccionar(self, nombre):
        """Pone como ACTIVO al experto `nombre` (None = núcleo base). Si estaba frío lo recarga primero. El resto queda tibio.
        Devuelve 'activo' | 'recargado' | 'dormido'. Con el experto ya tibio es solo una asignación de puntero."""
        if nombre is None:
            self.lib.nucleo_lora_seleccionar(self.h, -1)
            return "dormido"
        ranura, ruta = self.rutas_ranuras[nombre]
        recargado = False
        if self.lib.nucleo_lora_seleccionar(self.h, ranura) != 0:  # estaba frío
            self.cargar_ranura(ruta, ranura)
            self.lib.nucleo_lora_seleccionar(self.h, ranura)
            recargado = True
        return "recargado" if recargado else "activo"

    def turno(self):
        """Fin de un turno: los tibios pierden 1 de vida y los que llegan a 0 se descargan. Devuelve cuántos se descargaron."""
        return self.lib.nucleo_lora_turno(self.h)

    def estado(self, nombre):
        return self.ESTADOS[self.lib.nucleo_lora_estado(self.h, self.rutas_ranuras[nombre][0])]

    def vida(self, nombre):
        return self.lib.nucleo_lora_vida(self.h, self.rutas_ranuras[nombre][0])

    def vida_tibia(self, turnos):
        self.lib.nucleo_lora_config(self.h, turnos)

    def logits(self, ids):
        a = (ctypes.c_int * len(ids))(*ids)
        out = np.zeros(self.vocab, dtype=np.float32)
        self.lib.nucleo_logits(self.h, a, len(ids), out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)))
        return out

    def generar(self, ids, pen=1.1, max_nuevos=100):
        """Devuelve (ids_nuevos, parada) con parada ∈ {fin, herramienta, None}, como generar_lote de inferir.py."""
        a = (ctypes.c_int * len(ids))(*ids)
        salida = (ctypes.c_int * max_nuevos)()
        parada = ctypes.c_int()
        tiempos = (ctypes.c_double * 3)()
        k = self.lib.nucleo_generar(self.h, a, len(ids), pen, max_nuevos, salida, ctypes.byref(parada), tiempos)
        if k < 0:
            raise ValueError("prompt demasiado largo para el contexto del modelo")
        self.ultimos_tiempos = (tiempos[0], tiempos[1], int(tiempos[2]))
        return list(salida[:k]), (parada.value if parada.value >= 0 else None)

    def __del__(self):
        if getattr(self, "h", None):
            self.lib.nucleo_liberar(self.h)
            self.h = None

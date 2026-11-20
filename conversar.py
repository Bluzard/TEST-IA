"""Prueba interactiva del sistema completo (capa 1 sin IA + núcleo + diccionario).

  python conversar.py                      (modo interactivo, modelo bucle)
  python conversar.py "banco de arena" "1244123/2344" "trelino"
  python conversar.py --modelo modelos/cmp_bitnet_s0_v3_empaquetado.pt "banco de arena"
"""
import sys
from pathlib import Path

from evaluar import responder
from herramientas import Diccionario, filtro_determinista
from modelo import cargar, elegir_dispositivo

RAIZ = Path(__file__).parent


def limpiar(texto):
    t = texto.strip().lower().rstrip("?").strip()
    for prefijo in ("¿qué es ", "qué es ", "que es "):
        if t.startswith(prefijo):
            t = t[len(prefijo):]
    return t.strip()


def atender(texto, modelo, stoi, itos, dispositivo, diccionario):
    exacto = filtro_determinista(texto)
    if exacto is not None:
        print(f"  [capa 1, sin IA] {texto.strip()} = {exacto}")
        return
    r = responder(modelo, stoi, itos, dispositivo, [limpiar(texto)], diccionario)[0]
    print(f"  P: ¿qué es {limpiar(texto)}?")
    for linea in r["traza"]:
        print(f"  {linea}")


def cargar_cualquiera(ruta, dispositivo):
    if str(ruta).endswith("_empaquetado.pt"):
        from exportar_bitnet import cargar_empaquetado
        return cargar_empaquetado(ruta, dispositivo)
    return cargar(ruta, dispositivo)


def main():
    argumentos = sys.argv[1:]
    ruta = RAIZ / "modelos" / "cmp_bucle_s0_v3.pt"
    if argumentos[:1] == ["--modelo"]:
        ruta, argumentos = Path(argumentos[1]), argumentos[2:]
    dispositivo = elegir_dispositivo()
    modelo, stoi, itos = cargar_cualquiera(ruta, dispositivo)
    print(f"(modelo: {Path(ruta).name})")
    diccionario = Diccionario()
    if argumentos:
        for t in argumentos:
            atender(t, modelo, stoi, itos, dispositivo, diccionario)
        return
    print("Escribe una palabra, una frase tipo «banco de arena» o una cuenta. Enter vacío para salir.")
    while True:
        try:
            t = input("> ")
        except EOFError:
            break
        if not t.strip():
            break
        atender(t, modelo, stoi, itos, dispositivo, diccionario)


if __name__ == "__main__":
    main()

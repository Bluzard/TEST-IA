"""Sandbox para ejecutar código de Python que escribe el modelo (herramienta `E:`).

Defensas, en capas:
  1. Lista blanca por AST: solo `import math`; sin open/exec/eval/getattr/__import__...; sin atributos con "__" salvo
     los métodos mágicos habituales de las clases; sin str.format (recorre atributos); sin async; sin enteros enormes.
  2. Proceso hijo aparte (`python -I -S`) con builtins mínimos y un `__import__` que solo deja pasar `math`.
  3. Tiempo máximo de 3 s (se mata el proceso) y, en Windows, un objeto Job con tope de 256 MB de memoria y
     sin poder crear procesos hijos.

Salida pensada para el límite de 512 tokens del núcleo: SOLO el resultado impreso (o el valor de la última
expresión) o la ÚLTIMA línea de la excepción, sin traza, recortado a MAX_SALIDA caracteres.

  python sandbox.py            # corre las pruebas de seguridad
"""
import ast
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

MAX_SALIDA = 100
TIEMPO = 3.0
MEMORIA_MB = 256

NO_PERMITIDO = "No permitido en el sandbox."
TIEMPO_AGOTADO = "Tiempo agotado (3 s)."

_PROHIBIDOS = {"open", "exec", "eval", "compile", "__import__", "input", "globals", "locals", "getattr", "setattr",
               "delattr", "vars", "dir", "breakpoint", "help", "exit", "quit", "memoryview", "bytearray", "classmethod_",
               "__builtins__", "__loader__", "__spec__"}
_ATRIBUTOS_PROHIBIDOS = {"format", "format_map"}
_DUNDER_OK = {"__init__", "__str__", "__repr__", "__len__", "__eq__", "__lt__", "__add__", "__getitem__", "__iter__",
              "__next__", "__name__", "__class__"}
_DUNDER_OK.discard("__class__")  # se usa para escapar; no se permite
_NODOS_PROHIBIDOS = (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)

# Código que corre en el proceso hijo (builtins mínimos, solo math)
_RUNNER = r'''
import sys, ast, io, math, traceback, json
codigo = sys.stdin.read()
real_import = __import__
def _imp(nombre, *a, **k):
    if nombre != "math":
        raise ImportError("solo se permite math")
    return real_import(nombre, *a, **k)
import builtins as B
nombres = ("print range len sum min max abs round sorted reversed enumerate zip map filter list dict set tuple str int "
           "float bool isinstance issubclass type super object repr any all divmod pow chr ord hash id iter next slice "
           "frozenset complex bin hex oct Exception BaseException ValueError TypeError ZeroDivisionError KeyError IndexError "
           "NameError AttributeError RuntimeError StopIteration ArithmeticError OverflowError AssertionError "
           "NotImplementedError LookupError RecursionError UnboundLocalError ImportError MemoryError property "
           "staticmethod classmethod True False None").split()
seguros = {n: getattr(B, n) for n in nombres if hasattr(B, n)}
seguros["__build_class__"] = B.__build_class__
seguros["__import__"] = _imp
sys.setrecursionlimit(400)
buf = io.StringIO()
real_out = sys.stdout
resultado = {"ok": True, "salida": ""}
try:
    arbol = ast.parse(codigo)
    if arbol.body and isinstance(arbol.body[-1], ast.Expr):
        v = arbol.body[-1].value
        if not (isinstance(v, ast.Call) and getattr(v.func, "id", "") == "print"):
            arbol.body[-1] = ast.Expr(ast.Call(ast.Name("print", ast.Load()), [ast.Call(ast.Name("repr", ast.Load()), [v], [])], []))
            ast.fix_missing_locations(arbol)
    sys.stdout = buf
    # El modelo a veces omite el prefijo `math.`: las funciones principales también quedan como nombres sueltos (`pow` ya es el builtin)
    globales = {"__builtins__": seguros, "__name__": "__main__", "math": math}
    for n in "sqrt factorial sin cos tan log pi e ceil floor".split():
        globales[n] = getattr(math, n)
    exec(compile(arbol, "<sandbox>", "exec"), globales)
    sys.stdout = real_out
    resultado["salida"] = buf.getvalue()
except BaseException as e:
    sys.stdout = real_out
    resultado = {"ok": False, "salida": traceback.format_exception_only(type(e), e)[-1].strip()}
real_out.write(json.dumps(resultado))
'''


def validar(codigo):
    """None si el código es aceptable; si no, el motivo. Los errores de sintaxis se dejan pasar: los reporta la ejecución."""
    try:
        arbol = ast.parse(codigo)
    except SyntaxError:
        return None
    for n in ast.walk(arbol):
        if isinstance(n, _NODOS_PROHIBIDOS):
            return "async"
        if isinstance(n, ast.Import) and any(a.name != "math" for a in n.names):
            return "import"
        if isinstance(n, ast.ImportFrom) and (n.module != "math" or n.level):
            return "import"
        if isinstance(n, ast.Name) and (n.id in _PROHIBIDOS or (n.id.startswith("__") and n.id != "__name__")):
            return f"nombre {n.id}"
        if isinstance(n, ast.Attribute):
            if n.attr in _ATRIBUTOS_PROHIBIDOS:
                return "format"
            if n.attr.startswith("__") and n.attr not in _DUNDER_OK:
                return f"atributo {n.attr}"
        if isinstance(n, ast.Constant) and isinstance(n.value, int) and not isinstance(n.value, bool) and abs(n.value) > 10**8:
            return "número enorme"
        if isinstance(n, ast.FunctionDef) and n.name.startswith("__") and n.name not in _DUNDER_OK:
            return f"método {n.name}"
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Pow):
            if isinstance(n.right, ast.Constant) and isinstance(n.right.value, int) and n.right.value > 64 and not (
                    isinstance(n.left, ast.Constant) and n.left.value in (0, 1, -1)):
                return "potencia enorme"
    return None


def _limite_job():
    """(Windows) Job con tope de memoria y sin procesos hijos. Devuelve una función que asigna un proceso al job."""
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("a", "b", "c", "d", "e", "f")]

    class Ext(ctypes.Structure):
        _fields_ = [("Basic", Basic), ("Io", Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    job = k32.CreateJobObjectW(None, None)
    info = Ext()
    # 0x100 memoria por proceso | 0x8 límite de procesos activos | 0x2000 matar al cerrar el job
    info.Basic.LimitFlags = 0x100 | 0x8 | 0x2000
    info.Basic.ActiveProcessLimit = 1
    info.ProcessMemoryLimit = MEMORIA_MB * 1024 * 1024
    k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    return job, lambda p: k32.AssignProcessToJobObject(job, int(p._handle)), lambda: k32.CloseHandle(job)


def _recortar(t, n=MAX_SALIDA):
    t = t.strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def ejecutar_codigo(codigo, tiempo=TIEMPO):
    """Ejecuta `codigo` y devuelve el texto que verá el modelo (resultado o última línea de la excepción)."""
    if validar(codigo):
        return NO_PERMITIDO
    cierre = None
    try:
        # intérprete base (no el lanzador del venv, que crearía un segundo proceso y chocaría con el límite del job)
        p = subprocess.Popen([getattr(sys, "_base_executable", sys.executable), "-I", "-S", "-X", "utf8", "-c", _RUNNER], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        if sys.platform == "win32":
            try:
                _, asignar, cierre = _limite_job()
                asignar(p)
            except Exception:
                cierre = None  # sin job object queda el timeout como única barrera
        try:
            salida, _ = p.communicate(codigo, timeout=tiempo)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            return TIEMPO_AGOTADO
        finally:
            if cierre:
                cierre()
        try:
            r = json.loads(salida)
        except (json.JSONDecodeError, ValueError):
            return "MemoryError" if p.returncode else "Sin salida."
        s = _recortar(r["salida"])
        return s if s else "(sin salida)"
    except Exception as e:  # nunca romper al llamador
        return _recortar(f"{type(e).__name__}: {e}")


def ejecutar_lote(codigos, hilos=12):
    with ThreadPoolExecutor(hilos) as ex:
        return list(ex.map(ejecutar_codigo, codigos))


if __name__ == "__main__":
    casos = [
        ("print(sum(range(5)))", "10"),
        ("2 + 3 * 4", "14"),
        ("x = [3, 1, 2]\nx.sort()\nx", "[1, 2, 3]"),
        ("print(1 / 0)", "ZeroDivisionError: division by zero"),
        ("d = {'a': 1}\nprint(d['b'])", "KeyError: 'b'"),
        ("print(f'{1+1}')", "2"),
        ("import math\nprint(math.sqrt(16))", "4.0"),
        ("math.sqrt(144) + math.factorial(5)", "132.0"),
        ("sqrt(144) + factorial(5)", "132.0"),
        ("round(pi, 2), floor(e), ceil(2.1), log(1), sin(0), cos(0), tan(0)", "(3.14, 2, 3, 0.0, 0.0, 1.0, 0.0)"),
        ("class A:\n    def __init__(self): self.x = 1\n    def v(self): return self.x\nprint(A().v())", "1"),
        ("def f(n): return 1 if n < 2 else n * f(n - 1)\nprint(f(5))", "120"),
        ("print(undefined_fn(3))", "NameError: name 'undefined_fn' is not defined"),
        ("print(", "SyntaxError"),
        ("while True: pass", TIEMPO_AGOTADO),
        ("def f(n): return f(n + 1)\nf(0)", "RecursionError"),
        # --- ataques: todos deben quedar bloqueados ---
        ("import os\nprint(os.listdir('.'))", NO_PERMITIDO),
        ("open('C:/Windows/win.ini').read()", NO_PERMITIDO),
        ("__import__('os').system('whoami')", NO_PERMITIDO),
        ("print(().__class__.__bases__[0].__subclasses__())", NO_PERMITIDO),
        ("print('{0.__class__}'.format(1))", NO_PERMITIDO),
        ("exec('print(1)')", NO_PERMITIDO),
        ("eval('1+1')", NO_PERMITIDO),
        ("getattr(math, 'sqrt')", NO_PERMITIDO),
        ("x = [0] * 999999999999", NO_PERMITIDO),
        ("print(2 ** 10000000)", NO_PERMITIDO),
        ("from os import path", NO_PERMITIDO),
        ("x = [0] * (10 ** 7) * 100", "MemoryError"),
    ]
    mal = 0
    for codigo, espera in casos:
        r = ejecutar_codigo(codigo)
        ok = espera in r
        mal += not ok
        print(("OK " if ok else "MAL"), repr(codigo[:48]), "->", repr(r[:60]))
    print(f"\n{len(casos) - mal}/{len(casos)} correctos")
    sys.exit(1 if mal else 0)

"""Contenido del experto de código: fichas de conceptos (van al LoRA) y listas para consultar (van a ddgs).

FICHAS: conceptos fundamentales estables. (nombre, forma con artículo, definición corta, ejemplo en Python o None)
COLA: conceptos menos comunes que el experto NO memoriza: debe buscarlos.
APIS: (biblioteca/tecnología, elemento) de sintaxis cambiante: se consultan, no se memorizan.
"""
import hashlib
import random

FICHAS = [
    # --- fundamentos ---
    ("variable", "una variable", "Una variable es un nombre que guarda un valor en la memoria para poder usarlo y cambiarlo después.", "edad = 30"),
    ("constante", "una constante", "Una constante es un valor que no debe cambiar mientras el programa se ejecuta.", "PI = 3.14159"),
    ("tipo de dato", "un tipo de dato", "Un tipo de dato indica qué clase de valor es algo y qué operaciones se pueden hacer con él, como número, texto o booleano.", "type(5)"),
    ("entero", "un entero", "Un entero es un número sin parte decimal, positivo, negativo o cero.", "n = 42"),
    ("número decimal", "un número decimal", "Un número decimal, o float, representa valores con parte fraccionaria.", "x = 3.14"),
    ("cadena de texto", "una cadena de texto", "Una cadena de texto, o string, es una secuencia de caracteres entre comillas.", "nombre = 'Ana'"),
    ("booleano", "un booleano", "Un booleano es un valor que solo puede ser verdadero o falso.", "activo = True"),
    ("comentario", "un comentario", "Un comentario es texto dentro del código que el programa ignora y sirve para explicarlo a quien lo lee.", "# esto es un comentario"),
    ("operador", "un operador", "Un operador es un símbolo que realiza una operación sobre uno o más valores, como suma, comparación o negación lógica.", "a + b"),
    ("expresión", "una expresión", "Una expresión es una combinación de valores y operadores que se evalúa y produce un resultado.", "2 * (3 + 4)"),
    ("asignación", "una asignación", "Una asignación guarda un valor en una variable usando el signo igual.", "total = 10"),
    ("condicional", "un condicional", "Un condicional ejecuta un bloque de código solo si se cumple una condición.", "if x > 0: print('positivo')"),
    ("bucle for", "un bucle for", "Un bucle for repite un bloque de código para cada elemento de una secuencia.", "for i in range(3): print(i)"),
    ("bucle while", "un bucle while", "Un bucle while repite un bloque de código mientras una condición sea verdadera.", "while n > 0: n -= 1"),
    ("bucle infinito", "un bucle infinito", "Un bucle infinito es uno cuya condición nunca deja de cumplirse, así que el programa no termina.", "while True: pass"),
    ("índice", "un índice", "Un índice es el número que indica la posición de un elemento en una secuencia; en la mayoría de los lenguajes empieza en cero.", "lista[0]"),
    ("rebanado", "un rebanado", "Un rebanado, o slicing, extrae una parte de una secuencia indicando desde dónde y hasta dónde.", "texto[1:4]"),
    ("algoritmo", "un algoritmo", "Un algoritmo es una secuencia finita de pasos bien definidos para resolver un problema.", None),
    ("pseudocódigo", "un pseudocódigo", "Un pseudocódigo describe los pasos de un algoritmo con lenguaje cotidiano, sin la sintaxis de un lenguaje real.", None),
    ("módulo", "un módulo", "Un módulo es un archivo de código que agrupa funciones y variables para poder reutilizarlas desde otros programas.", "import math"),
    # --- estructuras de datos ---
    ("lista", "una lista", "Una lista es una colección ordenada y modificable de elementos.", "nums = [1, 2, 3]"),
    ("tupla", "una tupla", "Una tupla es una colección ordenada de elementos que no se puede modificar una vez creada.", "punto = (2, 5)"),
    ("diccionario", "un diccionario", "Un diccionario guarda pares de clave y valor, y permite buscar un valor por su clave.", "edades = {'Ana': 30}"),
    ("conjunto", "un conjunto", "Un conjunto es una colección de elementos únicos y sin orden.", "s = {1, 2, 3}"),
    ("arreglo", "un arreglo", "Un arreglo es una colección de elementos del mismo tipo guardados de forma contigua en la memoria y accesibles por índice.", None),
    ("matriz", "una matriz", "Una matriz es una tabla de valores organizada en filas y columnas, que se representa como una lista de listas.", "m = [[1, 2], [3, 4]]"),
    ("pila", "una pila", "Una pila es una estructura donde el último elemento en entrar es el primero en salir, llamada LIFO.", "pila.append(1); pila.pop()"),
    ("cola", "una cola", "Una cola es una estructura donde el primer elemento en entrar es el primero en salir, llamada FIFO.", None),
    ("lista enlazada", "una lista enlazada", "Una lista enlazada es una secuencia de nodos donde cada nodo guarda un valor y una referencia al siguiente.", None),
    ("nodo", "un nodo", "Un nodo es un elemento de una estructura como una lista enlazada o un árbol, que guarda un dato y referencias a otros nodos.", None),
    ("árbol", "un árbol", "Un árbol es una estructura jerárquica de nodos con una raíz de la que cuelgan otros nodos, sin ciclos.", None),
    ("árbol binario", "un árbol binario", "Un árbol binario es un árbol en el que cada nodo tiene como máximo dos hijos, izquierdo y derecho.", None),
    ("árbol de búsqueda binaria", "un árbol de búsqueda binaria", "Un árbol de búsqueda binaria es un árbol binario donde los valores menores van a la izquierda y los mayores a la derecha de cada nodo.", None),
    ("grafo", "un grafo", "Un grafo es un conjunto de nodos conectados por aristas, y sirve para modelar redes y relaciones.", None),
    ("tabla hash", "una tabla hash", "Una tabla hash guarda pares de clave y valor y usa una función hash para encontrar rápido la posición de cada clave.", None),
    ("referencia", "una referencia", "Una referencia es un valor que apunta a un objeto en la memoria en lugar de contener una copia de él.", None),
    ("mutabilidad", "la mutabilidad", "Un objeto es mutable si puede modificarse después de crearse, como una lista, e inmutable si no, como una tupla o un texto.", None),
    ("copia superficial", "una copia superficial", "Una copia superficial duplica el objeto pero comparte los objetos internos con el original.", "b = a.copy()"),
    ("copia profunda", "una copia profunda", "Una copia profunda duplica el objeto y también todos los objetos que contiene, así que no comparte nada con el original.", None),
    # --- funciones ---
    ("función", "una función", "Una función es un bloque de código con nombre que se puede reutilizar, recibe datos y puede devolver un resultado.", "def suma(a, b): return a + b"),
    ("parámetro", "un parámetro", "Un parámetro es una variable que aparece en la definición de una función y recibe un valor cuando la función se llama.", "def saludar(nombre): ..."),
    ("argumento", "un argumento", "Un argumento es el valor concreto que se entrega a una función cuando se la llama.", "saludar('Ana')"),
    ("valor de retorno", "un valor de retorno", "El valor de retorno es el resultado que una función devuelve a quien la llamó mediante la palabra return.", "return a + b"),
    ("recursión", "la recursión", "La recursión es una técnica en la que una función se llama a sí misma para resolver una versión más pequeña del mismo problema.", "def f(n): return 1 if n < 2 else n * f(n - 1)"),
    ("caso base", "un caso base", "El caso base de una función recursiva es la condición que detiene las llamadas y devuelve un resultado directo.", "if n < 2: return 1"),
    ("función lambda", "una función lambda", "Una función lambda es una función pequeña y anónima que se escribe en una sola línea.", "doble = lambda x: x * 2"),
    ("variable local", "una variable local", "Una variable local existe solo dentro de la función donde se crea.", None),
    ("variable global", "una variable global", "Una variable global está definida fuera de las funciones y puede leerse desde cualquier parte del programa.", None),
    ("ámbito", "un ámbito", "El ámbito, o scope, es la región del código donde una variable es visible y se puede usar.", None),
    ("efecto secundario", "un efecto secundario", "Una función tiene un efecto secundario si además de devolver un valor modifica algo fuera de ella, como una variable global o un archivo.", None),
    ("función pura", "una función pura", "Una función pura siempre devuelve el mismo resultado para los mismos argumentos y no tiene efectos secundarios.", None),
    ("iterador", "un iterador", "Un iterador es un objeto que entrega los elementos de una colección uno a uno cada vez que se le pide el siguiente.", "it = iter([1, 2]); next(it)"),
    ("generador", "un generador", "Un generador es una función que produce valores uno a uno con yield, sin crear toda la colección en memoria.", "def gen(): yield 1"),
    ("decorador", "un decorador", "Un decorador es una función que recibe otra función y devuelve una versión modificada de ella.", "@decorador"),
    ("comprensión de listas", "una comprensión de listas", "Una comprensión de listas crea una lista nueva a partir de otra secuencia en una sola línea.", "[x * 2 for x in nums]"),
    # --- programación orientada a objetos ---
    ("clase", "una clase", "Una clase es un molde que define los atributos y métodos que tendrán los objetos creados a partir de ella.", "class Perro: ..."),
    ("objeto", "un objeto", "Un objeto es una instancia concreta de una clase, con sus propios valores de atributos.", "mi_perro = Perro()"),
    ("atributo", "un atributo", "Un atributo es una variable que pertenece a un objeto o a una clase y guarda su estado.", "self.nombre = nombre"),
    ("método", "un método", "Un método es una función definida dentro de una clase que actúa sobre los objetos de esa clase.", "def ladrar(self): ..."),
    ("constructor", "un constructor", "El constructor es el método especial que se ejecuta al crear un objeto y se encarga de iniciar sus atributos.", "def __init__(self, nombre): ..."),
    ("self", "self", "En Python, self es el nombre que se usa dentro de un método para referirse al propio objeto sobre el que se llamó.", None),
    ("instancia", "una instancia", "Una instancia es un objeto concreto creado a partir de una clase.", None),
    ("herencia", "la herencia", "La herencia permite que una clase reciba los atributos y métodos de otra clase y los extienda o modifique.", "class Gato(Animal): ..."),
    ("polimorfismo", "el polimorfismo", "El polimorfismo permite que objetos de clases distintas respondan al mismo método cada uno a su manera.", None),
    ("sobrescritura de método", "una sobrescritura de método", "Sobrescribir un método es volver a definirlo en una clase hija para cambiar el comportamiento heredado.", None),
    ("encapsulamiento", "el encapsulamiento", "El encapsulamiento consiste en ocultar los detalles internos de un objeto y exponer solo lo necesario mediante sus métodos.", None),
    ("abstracción", "la abstracción", "La abstracción consiste en mostrar solo lo esencial de algo y ocultar los detalles de cómo funciona por dentro.", None),
    ("clase abstracta", "una clase abstracta", "Una clase abstracta es una clase que no se puede instanciar directamente y sirve como base para otras clases.", None),
    ("interfaz", "una interfaz", "Una interfaz define qué métodos debe tener una clase sin decir cómo se implementan.", None),
    ("composición", "la composición", "La composición construye objetos complejos incluyendo otros objetos como atributos, en lugar de heredar de ellos.", None),
    ("método estático", "un método estático", "Un método estático pertenece a la clase y no necesita un objeto para ser llamado.", "@staticmethod"),
    # --- errores y calidad ---
    ("excepción", "una excepción", "Una excepción es un error que ocurre mientras el programa se ejecuta y que interrumpe el flujo normal si no se maneja.", None),
    ("try y except", "un bloque try y except", "Un bloque try y except intenta ejecutar código y, si ocurre una excepción, ejecuta un código alternativo en lugar de detener el programa.", "try: ... except ValueError: ..."),
    ("raise", "raise", "La instrucción raise lanza una excepción a propósito para indicar que algo salió mal.", "raise ValueError('dato inválido')"),
    ("error de sintaxis", "un error de sintaxis", "Un error de sintaxis ocurre cuando el código está mal escrito según las reglas del lenguaje, así que ni siquiera puede ejecutarse.", None),
    ("error en tiempo de ejecución", "un error en tiempo de ejecución", "Un error en tiempo de ejecución ocurre mientras el programa corre, aunque el código esté bien escrito, como dividir entre cero.", "1 / 0"),
    ("error lógico", "un error lógico", "Un error lógico es un fallo en el razonamiento del programa: el código corre sin errores pero produce un resultado incorrecto.", None),
    ("bug", "un bug", "Un bug es un defecto en un programa que hace que se comporte de forma incorrecta o inesperada.", None),
    ("depuración", "la depuración", "Depurar es buscar y corregir los errores de un programa, por ejemplo con impresiones o un depurador paso a paso.", None),
    ("traza de error", "una traza de error", "Una traza de error, o stack trace, muestra la secuencia de llamadas que llevó hasta un error y ayuda a ubicarlo.", None),
    ("prueba unitaria", "una prueba unitaria", "Una prueba unitaria verifica automáticamente que una pieza pequeña del código, como una función, produce el resultado esperado.", None),
    ("aserción", "una aserción", "Una aserción comprueba que una condición es verdadera y detiene el programa con un error si no lo es.", "assert x > 0"),
    ("refactorización", "una refactorización", "Refactorizar es reorganizar el código para que sea más claro y fácil de mantener sin cambiar lo que hace.", None),
    ("desbordamiento de pila", "un desbordamiento de pila", "Un desbordamiento de pila, o stack overflow, ocurre cuando hay demasiadas llamadas anidadas, por ejemplo en una recursión sin caso base.", None),
    # --- algoritmos ---
    ("complejidad algorítmica", "la complejidad algorítmica", "La complejidad algorítmica mide cuántos recursos, como tiempo o memoria, necesita un algoritmo según el tamaño de la entrada.", None),
    ("notación O grande", "la notación O grande", "La notación O grande describe cómo crece el costo de un algoritmo al aumentar el tamaño de la entrada.", None),
    ("búsqueda lineal", "una búsqueda lineal", "La búsqueda lineal recorre los elementos uno por uno hasta encontrar el que se busca.", None),
    ("búsqueda binaria", "una búsqueda binaria", "La búsqueda binaria encuentra un elemento en una lista ordenada dividiendo el rango de búsqueda por la mitad en cada paso.", None),
    ("ordenamiento", "un ordenamiento", "Un algoritmo de ordenamiento reorganiza los elementos de una colección según un criterio, por ejemplo de menor a mayor.", "sorted([3, 1, 2])"),
    ("ordenamiento burbuja", "un ordenamiento burbuja", "El ordenamiento burbuja compara pares de elementos vecinos y los intercambia si están en el orden incorrecto, repitiendo hasta ordenar todo.", None),
    ("divide y vencerás", "divide y vencerás", "Divide y vencerás es una estrategia que divide un problema en partes más pequeñas, las resuelve y combina los resultados.", None),
    # --- sistemas y herramientas ---
    ("API", "una API", "Una API es un conjunto de reglas y funciones que permite que un programa use los servicios de otro.", None),
    ("JSON", "JSON", "JSON es un formato de texto para intercambiar datos organizado en pares de clave y valor y listas.", None),
    ("HTTP", "HTTP", "HTTP es el protocolo que usan los navegadores y los servidores para intercambiar páginas y datos en la web.", None),
    ("cliente y servidor", "un modelo cliente y servidor", "En el modelo cliente y servidor, el cliente hace peticiones y el servidor las recibe y responde.", None),
    ("base de datos", "una base de datos", "Una base de datos es un conjunto organizado de información guardada para consultarla y modificarla de forma eficiente.", None),
    ("SQL", "SQL", "SQL es un lenguaje para consultar y modificar datos guardados en bases de datos relacionales.", "SELECT * FROM usuarios"),
    ("clave primaria", "una clave primaria", "Una clave primaria es la columna cuyo valor identifica de forma única cada fila de una tabla.", None),
    ("framework", "un framework", "Un framework es un conjunto de herramientas y reglas ya hechas que sirve de base para construir aplicaciones.", None),
    ("librería", "una librería", "Una librería es un conjunto de funciones ya escritas que un programa puede importar y reutilizar.", None),
    ("control de versiones", "el control de versiones", "El control de versiones registra los cambios del código a lo largo del tiempo y permite volver a estados anteriores.", None),
    ("commit", "un commit", "Un commit es un registro guardado en el control de versiones que captura un conjunto de cambios con un mensaje.", None),
    ("compilador", "un compilador", "Un compilador traduce todo el código fuente a código de máquina antes de que el programa se ejecute.", None),
    ("intérprete", "un intérprete", "Un intérprete ejecuta el código fuente línea por línea sin traducirlo antes por completo.", None),
    ("puntero", "un puntero", "Un puntero es una variable que guarda la dirección de memoria de otro dato.", None),
    ("hilo", "un hilo", "Un hilo es una secuencia de instrucciones que un programa puede ejecutar de forma independiente junto con otras.", None),
    ("programación asíncrona", "la programación asíncrona", "La programación asíncrona permite iniciar una tarea lenta y seguir haciendo otras cosas mientras termina.", None),
]

COLA = [
    "mutex", "semáforo", "árbol AVL", "árbol rojo-negro", "trie", "montículo binario", "B-tree", "algoritmo de Dijkstra",
    "algoritmo A*", "quicksort", "mergesort", "programación dinámica", "memoización", "currying", "mónada",
    "programación funcional", "programación reactiva", "patrón observador", "patrón singleton", "patrón factory",
    "patrón MVC", "inyección de dependencias", "microservicios", "contenedor Docker", "Kubernetes", "integración continua",
    "expresión regular", "función hash", "blockchain", "cifrado asimétrico", "OAuth", "JWT", "WebSocket", "GraphQL", "ORM",
    "base de datos NoSQL", "índice de base de datos", "transacción ACID", "normalización de bases de datos", "red neuronal",
    "recolector de basura", "compilación JIT", "bytecode", "máquina virtual", "lenguaje ensamblador", "endianness", "UTF-8",
    "tipado estático", "tipado dinámico", "duck typing", "metaprogramación", "corrutina", "deadlock",
    "condición de carrera", "caché", "balanceo de carga", "CDN", "DNS", "proxy inverso", "principios SOLID",
    "desarrollo guiado por pruebas", "DevOps", "tabla de símbolos", "gramática libre de contexto", "autómata finito",
]

APIS = {
    "pandas": "read_csv merge groupby pivot_table fillna dropna concat apply iloc loc to_csv value_counts sort_values drop_duplicates rename describe isnull astype set_index".split(),
    "numpy": "reshape concatenate linspace arange argmax dot zeros where mean std transpose unique".split(),
    "requests": "get post Session raise_for_status headers".split(),
    "Python": "zip enumerate sorted map filter isinstance sum range lru_cache dataclass".split(),
    "os.path": ["join", "exists", "basename"],
    "json": ["loads", "dumps"],
    "re": ["sub", "findall", "compile"],
    "datetime": ["strptime", "strftime", "timedelta"],
    "collections": ["Counter", "defaultdict", "deque", "namedtuple"],
    "itertools": ["chain", "product", "permutations"],
    "pathlib": ["Path"],
    "random": ["choice", "shuffle"],
    "functools": ["reduce", "partial"],
    "argparse": ["ArgumentParser"],
    "logging": ["basicConfig"],
    "unittest": ["TestCase"],
    "sqlite3": ["connect"],
    "csv": ["DictReader"],
    "subprocess": ["run"],
    "threading": ["Thread"],
    "asyncio": ["gather", "run"],
    "enum": ["Enum"],
    "abc": ["ABC"],
    "contextlib": ["contextmanager"],
    "Flask": ["route", "jsonify"],
    "Django": ["QuerySet", "ForeignKey"],
    "FastAPI": ["Depends"],
    "pytest": ["fixture", "parametrize"],
    "Angular": "ngFor ngIf ngModel ngClass routerLink HttpClient Observable subscribe @Component @Input @Output EventEmitter FormBuilder ngOnInit @Injectable ActivatedRoute ngSwitch @ViewChild".split(),
    "React": "useState useEffect useRef useContext useMemo useReducer props JSX".split(),
    "JavaScript": ["map", "filter", "reduce", "forEach", "fetch", "Promise.all", "async await", "addEventListener", "localStorage",
                   "setTimeout", "JSON.parse", "spread operator", "destructuring", "querySelector", "includes", "splice"],
    "TypeScript": ["interface", "generics", "enum", "type alias"],
    "Node.js": ["require", "express.Router", "fs.readFile", "npm install"],
    "SQL": ["JOIN", "GROUP BY", "HAVING", "LEFT JOIN", "INSERT INTO", "UPDATE", "DISTINCT", "ORDER BY", "CREATE INDEX", "subconsulta"],
    "git": "rebase stash cherry-pick merge reset checkout branch clone".split(),
    "Docker": ["docker run", "Dockerfile", "docker-compose"],
    "bash": ["grep", "chmod", "ls", "find"],
    "CSS": ["flexbox", "grid", "media query", "position absolute"],
    "Java": ["ArrayList", "HashMap", "Stream", "Optional"],
    "C#": ["LINQ", "async Task"],
    "Go": ["goroutine", "channel"],
}

_VERBOS = ["calcular", "ordenar", "fusionar", "mapear", "filtrar", "limpiar", "convertir", "validar", "procesar", "generar", "extraer", "normalizar"]
_SUST = ["magia", "nubes", "cuantico", "ultra", "fantasma", "turbo", "espejo", "titan", "neon", "prisma", "vortice", "zafiro"]


def api_falsa(lib, rng):
    """Nombre inventado con el estilo de la biblioteca (snake_case o camelCase)."""
    v, s = rng.choice(_VERBOS), rng.choice(_SUST)
    if lib in ("Angular", "React", "JavaScript", "TypeScript", "Node.js", "Java", "C#"):
        return v + s.capitalize()
    return f"{v}_{s}"


def es_eval(nombre):
    """~20 % de las APIs y conceptos se reservan para evaluar (partición estable por hash)."""
    return int(hashlib.md5(nombre.encode()).hexdigest(), 16) % 5 == 0


def lista_apis():
    return [(lib, item) for lib, items in APIS.items() for item in items]


if __name__ == "__main__":
    print(f"{len(FICHAS)} fichas ({sum(1 for f in FICHAS if f[3])} con ejemplo), {len(COLA)} conceptos de cola, {len(lista_apis())} APIs")
    print("reservados para evaluar:", sum(es_eval(f[0]) for f in FICHAS), "fichas,", sum(es_eval(c) for c in COLA), "de cola,",
          sum(es_eval(f'{a} {b}') for a, b in lista_apis()), "APIs")

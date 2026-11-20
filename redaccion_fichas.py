"""Contenido del experto de redacción: fichas gramaticales y de ortografía (base local, Opción B) y lista de temas de cola.

FICHAS_GRAMATICA: reglas estables del español. (nombre, forma con artículo, regla corta, ejemplo). El experto NO las memoriza:
las lee de la base local (`buscar_ficha_gramatica`, < 1 ms) igual que el experto de código lee `FICHAS`.
COLA_GRAMATICA: temas menos comunes o más discutidos; el experto debe BUSCARLOS en ddgs (o abstenerse), no inventarlos.
"""
import hashlib
import re
import unicodedata

FICHAS_GRAMATICA = [
    # --- acentuación ---
    ("palabra aguda", "una palabra aguda", "Una palabra aguda es la que lleva la fuerza de voz en la última sílaba, y lleva tilde si termina en n, s o vocal.", "canción, café, papel"),
    ("palabra llana", "una palabra llana", "Una palabra llana tiene la fuerza de voz en la penúltima sílaba y lleva tilde cuando no termina en n, s ni vocal.", "árbol, lápiz, casa"),
    ("palabra esdrújula", "una palabra esdrújula", "Una palabra esdrújula tiene la fuerza de voz en la antepenúltima sílaba y siempre lleva tilde.", "teléfono, música, rápido"),
    ("diptongo", "un diptongo", "Un diptongo es la unión de dos vocales en una misma sílaba, una abierta y una cerrada o dos cerradas distintas.", "cuidado, aire, ciudad"),
    ("hiato", "un hiato", "Un hiato es la separación de dos vocales en sílabas distintas; si la vocal cerrada es la tónica, lleva tilde.", "país, día, río"),
    ("tilde diacrítica", "una tilde diacrítica", "La tilde diacrítica distingue palabras que se escriben igual pero cumplen funciones distintas.", "tú (pronombre) y tu (posesivo); él y el; sí y si"),
    ("tilde en interrogativos", "la tilde en interrogativos", "Los pronombres y adverbios interrogativos y exclamativos llevan tilde: qué, quién, cómo, cuándo, dónde, cuánto.", "¿Dónde vives? Dime dónde vives."),
    ("tilde en mayúsculas", "la tilde en mayúsculas", "Las mayúsculas llevan tilde igual que las minúsculas cuando la regla de acentuación lo exige.", "África, Álvaro, ÁRBOL"),
    ("tilde en monosílabos", "la tilde en monosílabos", "Los monosílabos no llevan tilde, salvo cuando es diacrítica, como en té, más, sé o dé.", "fue, dio, vio, pero más y té"),
    ("solo y este sin tilde", "la tilde en solo y los demostrativos", "Solo, este, ese y aquel no llevan tilde, ni siquiera cuando pueden confundirse.", "Vive solo. Este libro es mío."),
    # --- ortografía y homófonos ---
    ("haber y a ver", "la diferencia entre haber y a ver", "Haber es un verbo; a ver es la preposición a más el verbo ver, y se usa para pedir que algo se muestre o se compruebe.", "Debe haber pan. A ver qué pasa."),
    ("hay, ahí y ay", "la diferencia entre hay, ahí y ay", "Hay es del verbo haber, ahí indica lugar y ay es una interjección de dolor o sorpresa.", "Hay un libro ahí. ¡Ay, me dolió!"),
    ("porque, por qué, porqué y por que", "la diferencia entre porque, por qué, porqué y por que", "Porque introduce una causa; por qué es interrogativo; porqué es un sustantivo que significa motivo; por que es la preposición por más el relativo que.", "¿Por qué vienes? Vengo porque quiero."),
    ("sino y si no", "la diferencia entre sino y si no", "Sino expresa contraste después de una negación; si no es la condición si más la negación no.", "No es azul, sino verde. Si no llueve, saldremos."),
    ("también y tan bien", "la diferencia entre también y tan bien", "También equivale a además o igualmente; tan bien es el adverbio tan más bien, y se opone a tan mal.", "Yo también voy. Cantas tan bien."),
    ("tampoco y tan poco", "la diferencia entre tampoco y tan poco", "Tampoco niega algo que se suma a otra negación; tan poco es tan más poco, y se opone a tanto.", "Yo tampoco fui. Comió tan poco."),
    ("asimismo, así mismo y a sí mismo", "la diferencia entre asimismo, así mismo y a sí mismo", "Asimismo significa además; así mismo significa de esa misma manera; a sí mismo es el reflexivo de él mismo.", "Asimismo, se aprobó la ley. Se miró a sí mismo."),
    ("ha, a y ah", "la diferencia entre ha, a y ah", "Ha es del verbo haber; a es una preposición; ah es una interjección.", "Ha llegado a casa. ¡Ah, qué bien!"),
    ("echo y hecho", "la diferencia entre echo y hecho", "Echo viene del verbo echar; hecho viene del verbo hacer o es un sustantivo que significa suceso.", "Echo sal al guiso. Es un hecho conocido."),
    ("b y v", "el uso de b y v", "Los verbos terminados en -bir, como escribir, se escriben con b, salvo hervir, servir y vivir; el pretérito imperfecto en -aba también lleva b.", "escribir, cantaba, hervir"),
    ("g y j", "el uso de g y j", "Los verbos terminados en -ger y -gir se escriben con g, salvo tejer y crujir; antes de e o i, la g suena como j.", "coger, elegir, tejer"),
    ("h", "el uso de la h", "La h no suena en español; se escribe en las palabras que empiezan por hue-, hie-, hia- y en las formas del verbo haber.", "huevo, hielo, hacer"),
    ("ll y y", "la diferencia entre ll y y", "La ll y la y representan sonidos que hoy suelen pronunciarse igual en muchas zonas, por eso hay que fijarse en cada palabra.", "calló (callar) y cayó (caer)"),
    ("c, s y z", "el uso de c, s y z", "Los sustantivos terminados en -ción se escriben con c, y los terminados en -sión se escriben con s.", "canción, pasión, lápiz"),
    ("r y rr", "el uso de r y rr", "La rr se escribe entre vocales para el sonido fuerte; al inicio de palabra el sonido fuerte se escribe con una sola r.", "perro, rosa, honra"),
    ("m antes de p y b", "la m antes de p y b", "Antes de p y b se escribe siempre m y nunca n.", "campo, también, ambos"),
    # --- puntuación y mayúsculas ---
    ("coma enumerativa", "la coma enumerativa", "La coma separa los elementos de una enumeración, y no se pone antes de la última cuando va precedida de y, e, o, u o ni.", "Compré pan, leche y huevos."),
    ("coma vocativa", "la coma vocativa", "El vocativo, que es la palabra con la que se llama a alguien, se separa con comas del resto de la oración.", "Ana, ven aquí. Ven aquí, Ana."),
    ("coma explicativa", "la coma explicativa", "Los incisos o aclaraciones intercaladas se escriben entre comas.", "Mi hermano, que vive en Chile, llega hoy."),
    ("coma antes de pero", "la coma antes de pero", "Se escribe coma delante de pero cuando introduce una oposición.", "Quiero ir, pero no puedo."),
    ("coma entre sujeto y verbo", "la coma entre sujeto y verbo", "No se escribe coma entre el sujeto y el verbo, salvo que haya un inciso entre ambos.", "Los niños juegan en el parque."),
    ("punto y coma", "el punto y coma", "El punto y coma separa elementos más largos que los de una coma o oraciones relacionadas entre sí cuando ya hay comas.", "Ana, mi hermana, canta; Luis, mi primo, baila."),
    ("dos puntos", "los dos puntos", "Los dos puntos anuncian una enumeración, una cita o una explicación, y después se escribe minúscula salvo que siga una cita o un nombre propio.", "Trae tres cosas: pan, sal y agua."),
    ("puntos suspensivos", "los puntos suspensivos", "Los puntos suspensivos son siempre tres e indican una pausa o una oración que queda inconclusa.", "No sé qué decirte..."),
    ("signos de interrogación y exclamación", "los signos de interrogación y exclamación", "En español los signos de interrogación y exclamación se escriben al principio y al final de la frase: ¿ ? y ¡ !.", "¿Cómo estás? ¡Qué bien!"),
    ("raya", "la raya", "La raya es un guion largo que se usa en diálogos y para intercalar aclaraciones.", "—Hola —dijo Ana."),
    ("comillas", "las comillas", "Las comillas encierran citas textuales, títulos de artículos y palabras usadas con un sentido especial; en español se prefieren las angulares «».", "Dijo: «Volveré mañana»."),
    ("mayúscula inicial", "la mayúscula inicial", "Se escribe con mayúscula la primera palabra de un texto y la que sigue a un punto.", "Llegué tarde. Me dormí."),
    ("mayúscula en nombres propios", "la mayúscula en nombres propios", "Los nombres propios de personas, lugares e instituciones se escriben con mayúscula inicial.", "María, Chile, Universidad de Chile"),
    ("minúscula en días y meses", "la minúscula en días, meses y gentilicios", "Los días de la semana, los meses, las estaciones y los gentilicios se escriben con minúscula.", "lunes, marzo, otoño, chileno"),
    ("punto y comillas", "el punto con comillas y paréntesis", "En español el punto va después de las comillas o del paréntesis de cierre.", "Dijo «adiós»."),
    # --- gramática ---
    ("concordancia de género y número", "la concordancia de género y número", "El artículo y el adjetivo concuerdan en género y número con el sustantivo al que acompañan.", "las casas blancas"),
    ("concordancia entre sujeto y verbo", "la concordancia entre sujeto y verbo", "El verbo concuerda con su sujeto en número y persona.", "Los niños juegan. El niño juega."),
    ("dequeísmo", "el dequeísmo", "El dequeísmo es el uso incorrecto de de delante de que cuando el verbo no lo pide.", "Pienso que vendrá, no «pienso de que vendrá»."),
    ("queísmo", "el queísmo", "El queísmo es suprimir de delante de que cuando el verbo o el nombre sí lo exigen.", "Me alegro de que vengas, no «me alegro que vengas»."),
    ("laísmo", "el laísmo", "El laísmo es usar la o las como complemento indirecto en lugar de le o les.", "Le di un regalo a ella, no «la di un regalo»."),
    ("leísmo", "el leísmo", "El leísmo es usar le como complemento directo; solo se admite con personas masculinas singulares.", "Lo vi a Juan o Le vi a Juan; la vi a María."),
    ("gerundio", "el gerundio", "El gerundio expresa una acción en desarrollo o simultánea; no se usa para indicar una acción posterior ni como adjetivo.", "Llegó corriendo. No: «una caja conteniendo libros»."),
    ("pretérito perfecto simple y compuesto", "la diferencia entre pretérito perfecto simple y compuesto", "El perfecto simple, como canté, presenta la acción como terminada; el compuesto, como he cantado, la vincula con el presente.", "Ayer canté. Hoy he cantado."),
    ("pretérito imperfecto", "el pretérito imperfecto", "El pretérito imperfecto describe acciones pasadas en desarrollo o habituales, sin precisar su inicio ni su fin.", "Antes vivía en Lima y caminaba al trabajo."),
    ("modo subjuntivo", "el modo subjuntivo", "El modo subjuntivo expresa deseo, duda o hipótesis, y aparece con verbos como querer, esperar o dudar seguidos de que.", "Espero que llegues pronto."),
    ("imperativo", "el imperativo", "El imperativo expresa órdenes o ruegos; la forma afirmativa de tú y la negativa son distintas.", "Ven aquí. No vengas."),
    ("condicional", "el condicional", "El condicional expresa una acción posible o una cortesía y nunca debe usarse después de si en la condición.", "Si tuviera tiempo, iría. No: «si tendría tiempo»."),
    ("verbos irregulares", "los verbos irregulares", "Un verbo irregular cambia su raíz o sus terminaciones respecto del modelo de su conjugación.", "pedir: pido; tener: tuve; ir: voy"),
    ("voz pasiva", "la voz pasiva", "En la voz pasiva el sujeto recibe la acción y se forma con el verbo ser más el participio.", "La carta fue escrita por Ana."),
    ("oración simple y compuesta", "la diferencia entre oración simple y compuesta", "Una oración simple tiene un solo verbo conjugado; una compuesta tiene dos o más.", "Ana canta. Ana canta y Luis baila."),
    ("sujeto y predicado", "el sujeto y el predicado", "El sujeto es quien realiza la acción o de quien se dice algo, y el predicado es todo lo que se dice del sujeto.", "Mi hermana (sujeto) estudia medicina (predicado)."),
    ("complemento directo", "el complemento directo", "El complemento directo recibe la acción del verbo, y se reconoce porque se puede sustituir por lo, la, los o las.", "Compré pan. Lo compré."),
    ("complemento indirecto", "el complemento indirecto", "El complemento indirecto indica el destinatario de la acción y se sustituye por le o les.", "Di un libro a Ana. Le di un libro."),
    ("artículo el ante sustantivo femenino", "el artículo el ante sustantivo femenino", "Los sustantivos femeninos que empiezan por a o ha tónicas llevan el artículo el en singular, pero los adjetivos siguen en femenino.", "el agua fría, las aguas"),
    ("adjetivos y adverbios", "la diferencia entre adjetivo y adverbio", "El adjetivo acompaña a un sustantivo y concuerda con él; el adverbio modifica a un verbo, a un adjetivo o a otro adverbio y no cambia.", "Una niña rápida corre rápido."),
    ("pronombres relativos", "los pronombres relativos", "Los relativos que, quien, cual y cuyo introducen una oración que complementa a un sustantivo.", "El libro que leí es largo."),
    ("preposiciones", "las preposiciones", "Las preposiciones son palabras invariables que relacionan los elementos de una oración: a, ante, bajo, con, contra, de, desde, en, entre, hacia, hasta, para, por, según, sin, sobre y tras.", "Voy a casa con Ana."),
    ("conjunciones", "las conjunciones", "Las conjunciones unen palabras u oraciones; y, e, o, u, ni, pero y que son las más frecuentes.", "Pan y leche; té o café."),
    ("y se cambia por e", "el cambio de y por e", "La conjunción y se transforma en e delante de palabras que empiezan por i o hi, salvo hie.", "Padres e hijos; agua y hielo."),
    ("o se cambia por u", "el cambio de o por u", "La conjunción o se transforma en u delante de palabras que empiezan por o u ho.", "Siete u ocho; mujer u hombre."),
    ("sílaba tónica", "la sílaba tónica", "La sílaba tónica es la que se pronuncia con más fuerza en una palabra.", "can-CIÓN, CÁ-ma-ra"),
    ("sinónimo y antónimo", "la diferencia entre sinónimo y antónimo", "Los sinónimos son palabras de significado parecido, y los antónimos son palabras de significado opuesto.", "feliz y contento; frío y caliente"),
    ("estilo formal", "el estilo formal", "El estilo formal usa usted o fórmulas de cortesía, evita coloquialismos y abreviaturas y prefiere oraciones completas.", "Le agradezco su atención."),
    ("redacción clara", "la redacción clara", "La redacción clara usa oraciones cortas, palabras comunes y un solo mensaje principal por oración.", "El plazo termina el viernes."),
    ("redacción concisa", "la redacción concisa", "La redacción concisa elimina muletillas y repeticiones sin cambiar el sentido de lo que se dice.", "En vez de «la verdad es que, básicamente, llegué tarde» se escribe «llegué tarde»."),
]

COLA_GRAMATICA = [
    "perífrasis verbal", "complemento de régimen", "oración subordinada sustantiva", "oración subordinada adverbial", "oración yuxtapuesta",
    "voseo", "ultracorrección", "solecismo", "anacoluto", "elipsis", "hipérbaton", "zeugma", "pleonasmo", "concordancia ad sensum",
    "se impersonal y se pasivo", "complemento circunstancial", "atributo y complemento predicativo", "oración copulativa", "oración impersonal",
    "tiempos verbales compuestos", "acento prosódico", "diéresis", "prefijos y sufijos", "locución adverbial", "frase hecha", "polisemia",
    "adjetivo calificativo", "adverbio de modo", "pronombre enclítico", "oración subordinada causal", "complemento agente", "nombre colectivo",
    "verbo copulativo", "pretérito pluscuamperfecto", "futuro perfecto", "sílaba átona", "palabra compuesta", "plural de las palabras terminadas en z",
    "abreviatura", "siglas y acrónimos", "números romanos", "uso del guion", "uso del paréntesis", "uso de la barra", "adjetivo gentilicio",
    "determinantes demostrativos", "pronombres posesivos", "oración exclamativa", "oración desiderativa", "oración interrogativa indirecta",
    "verbo transitivo e intransitivo", "verbo reflexivo", "participio irregular", "infinitivo", "gerundio compuesto", "apócope", "diminutivo", "aumentativo",
    "sufijo -mente", "prefijo des-", "palabra sobresdrújula", "monosílabo", "triptongo", "grafía de los números", "uso de la cursiva", "uso del asterisco",
    "homonimia", "paronimia", "falso amigo", "neologismo", "arcaísmo", "préstamo lingüístico", "calco semántico", "modo potencial",
    "futuro de subjuntivo", "pretérito anterior", "voz media", "verbo defectivo", "verbo pronominal", "oración de relativo",
]

FRASES_ANTI_RELLENO = [
    "la verdad es que", "en realidad", "básicamente", "por así decirlo", "la verdad", "como que", "o sea", "digamos", "es decir que", "pues bien",
    "en cierto modo", "por lo general", "a decir verdad", "en todo caso", "como quien dice",
]

# (complicado, simple): cambios que dejan la oración igual de correcta y más clara
SIMPLIFICACIONES = [
    ("sin embargo", "pero"), ("no obstante", "pero"), ("debido a que", "porque"), ("a pesar de que", "aunque"),
    ("con el fin de", "para"), ("con la finalidad de", "para"), ("en la actualidad", "hoy"), ("actualmente", "hoy"),
    ("a fin de", "para"), ("con respecto a", "sobre"), ("en lo que respecta a", "sobre"), ("llevar a cabo", "hacer"),
    ("en el caso de que", "si"), ("a causa de", "por"), ("posteriormente", "después"), ("anteriormente", "antes"),
    ("por consiguiente", "por eso"), ("en virtud de", "por"),
]


def _norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"\b(gramatica|ortografia|espanol|regla|reglas|el uso de|la diferencia entre|el|la|los|las|un|una)\b", " ", t)
    return " ".join(re.sub(r"[^a-z0-9ñ ]", " ", t).split())


def linea_ficha_gramatica(ficha, con_ejemplo=True):
    """Formato único (entrenamiento e inferencia) de un resultado de la base local de gramática."""
    nombre, _, regla, ejemplo = ficha
    return f"{nombre} - base local: {regla}" + (f" Ejemplo: {ejemplo}" if (ejemplo and con_ejemplo) else "")


def buscar_ficha_gramatica(consulta):
    """Base local de gramática y ortografía: consulta instantánea ANTES de internet. «1. nombre - base local: regla Ejemplo: …» o None."""
    q = _norm(consulta)
    if not q:
        return None
    mejor = None
    for f in FICHAS_GRAMATICA:
        claves = {_norm(f[0]), _norm(f[1])}
        if q in claves:
            return "1. " + linea_ficha_gramatica(f)
        # coincidencia por contención de todas las palabras del nombre (p. ej. «porque» dentro de «porque, por qué, porqué y por que»)
        if any(set(q.split()) and set(q.split()) <= set(c.split()) and len(q) >= 4 for c in claves):
            mejor = mejor or f
    return ("1. " + linea_ficha_gramatica(mejor)) if mejor else None


def es_eval(nombre):
    """~20 % de las fichas y temas se reservan para evaluar (partición estable por hash, igual que en el experto de código)."""
    return int(hashlib.md5(nombre.encode()).hexdigest(), 16) % 5 == 0


if __name__ == "__main__":
    print(f"{len(FICHAS_GRAMATICA)} fichas gramaticales ({sum(1 for f in FICHAS_GRAMATICA if f[3])} con ejemplo), {len(COLA_GRAMATICA)} temas de cola")
    print("reservadas para evaluar:", sum(es_eval(f[0]) for f in FICHAS_GRAMATICA), "fichas,", sum(es_eval(c) for c in COLA_GRAMATICA), "de cola")
    for q in ("porque", "diptongo", "hiato", "haber y a ver", "capital de Chile"):
        print(q, "->", (buscar_ficha_gramatica(q) or "None")[:90])

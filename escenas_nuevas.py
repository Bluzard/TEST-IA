"""16 escenas NUEVAS (no explícitas), escritas DESPUÉS de ajustar escena_prompt.py con las 6 de b_chat: miden si las reglas generalizan o estaban ajustadas a esos casos.
Mismas comprobaciones que b_chat: required (debe aparecer) y forbidden (no debe aparecer). Solo se evalúa el redactor determinista: no hay prompts de Mistral para estas escenas.

  python escenas_nuevas.py
"""
import re
import time

from comparar_escenas import BASE, puntuar
from escena_prompt import componer

CASOS = [
    dict(name="cocina-pasado", situation="MAIN_ADULT está de pie junto a la encimera cortando verduras con un cuchillo. Antes estaba lavando platos.",
         required=[r"\bstand(?:s|ing)\b", r"\bcounter", r"\bcutt?ing\b|\bchops?\b|\bslic", r"\bknife\b"], forbidden=[r"\bwash|dishes\b"]),
    dict(name="intencion-no-ejecutada", situation="MAIN_ADULT se sienta en el sofá y abre una laptop sobre sus piernas. Piensa en salir a caminar.",
         required=[r"\bsofa|couch\b", r"\blaptop\b"], forbidden=[r"\bwalk|go out|going out\b"]),
    dict(name="negacion", situation="MAIN_ADULT no está sentada; está de pie junto a la ventana mirando la lluvia.",
         required=[r"\bstand(?:s|ing)\b", r"\bwindow\b", r"\brain\b"], forbidden=[r"\bseated|sitting|sits\b"]),
    dict(name="entrega-de-objeto", partner={"person": "man", "wardrobe": "suéter negro"}, situation="MAIN_ADULT le entrega una carta a PARTNER_ADULT, que la recibe con una sonrisa. Ambos están de pie en el pasillo.",
         required=[r"\bletter\b", r"\bhand(?:s|ing)|giv(?:es|ing)|pass", r"\bhallway|corridor\b", r"\bsmil"], forbidden=[r"\bsits|seated\b"]),
    dict(name="pov-accion-del-observador", camera="pov", situation="MAIN_ADULT está sentada frente al observador sirviendo té en una taza. PARTNER_ADULT extiende la mano para tomar la taza.",
         photography={"viewpoint": "first-person view from the observer's eyes", "gaze": "she is looking at the viewer."},
         required=[r"\btea\b", r"\bcup\b", r"\bPOV|first.person\b"], forbidden=[r"\bthe viewer (?:is )?(?:sits|seated|sitting)\b"]),
    dict(name="expresion-y-apoyo", situation="MAIN_ADULT sonríe ligeramente mientras revisa su teléfono, recargada contra la pared.",
         required=[r"\bsmil", r"\bphone\b", r"\bwall\b"], forbidden=[r"\bfrown|angry\b"]),
    dict(name="jardin-pasado", situation="MAIN_ADULT está agachada en el jardín plantando flores con una pala pequeña. Hace un rato estaba regando el césped.",
         required=[r"\bcrouch|squat|kneel|bend", r"\bgarden\b", r"\bflowers\b", r"\bshovel|trowel|spade\b"], forbidden=[r"\bwatering the (?:lawn|grass)|hose\b"]),
    dict(name="pedido-rechazado", partner={"person": "man", "wardrobe": "camiseta blanca"}, situation="PARTNER_ADULT le pide a MAIN_ADULT que deje de leer, pero ella sigue leyendo un libro en la cama.",
         required=[r"\bbed\b", r"\bbook\b", r"\bread"], forbidden=[r"\bstop|puts? down|closes?\b"]),
    dict(name="intencion-y-caminar", situation="MAIN_ADULT camina por la calle bajo un paraguas negro y quiere cruzar hacia la tienda.",
         required=[r"\bwalk", r"\bumbrella\b", r"\bstreet\b"], forbidden=[r"\bwants|wishes|wanting\b"]),
    dict(name="lateralidad", situation="MAIN_ADULT está tocando la guitarra sentada en un taburete, con la guitarra apoyada sobre su pierna derecha.",
         required=[r"\bguitar\b", r"\bstool\b", r"\bright\b"], forbidden=[r"\bleft\b"]),
    dict(name="dos-manos-distintas", situation="MAIN_ADULT se ajusta los lentes con una mano y sostiene un cuaderno con la otra.",
         required=[r"\bglasses\b", r"\bnotebook\b", r"\bhand\b"], forbidden=[r"\bwrites|writing\b"]),
    dict(name="estado-dormida", situation="MAIN_ADULT está dormida en el sillón con una manta sobre las piernas.",
         required=[r"\basleep|sleeping\b", r"\barmchair|chair\b", r"\bblanket\b"], forbidden=[r"\bawake|eyes open\b"]),
    dict(name="pasado-con-ahora", situation="Antes ella corría por el parque; ahora está sentada en un banco atándose los zapatos y bebiendo agua de una botella.",
         required=[r"\bbench\b", r"\bshoes?|laces\b", r"\bwater\b", r"\bbottle\b"], forbidden=[r"\brunning|runs|jogging\b"]),
    dict(name="baile-no-explicito", partner={"person": "man", "wardrobe": "camisa azul"}, situation="MAIN_ADULT y PARTNER_ADULT bailan en la sala; ella apoya la cabeza en su hombro.",
         required=[r"\bdanc", r"\bshoulder\b", r"\bhead\b"], forbidden=[r"\bsits|seated\b"]),
    dict(name="bano-espejo", situation="MAIN_ADULT está de pie frente al espejo del baño cepillándose los dientes.",
         required=[r"\bmirror\b", r"\bbrush", r"\bteeth\b"], forbidden=[r"\bsits|seated\b"]),
    dict(name="mirada-no-establecida", situation="MAIN_ADULT está sentada en el suelo armando un rompecabezas.",
         photography={"viewpoint": "eye-level view", "gaze": ""},
         required=[r"\bfloor\b", r"\bpuzzle\b", r"\bsit"], forbidden=[r"\blooking at the viewer\b"]),
]


def main():
    ok = 0
    fallos = []
    ms = []
    for c in CASOS:
        fuente = {**BASE, **{k: v for k, v in c.items() if k not in ("name", "required", "forbidden")}}
        t0 = time.time()
        prompt, traza = componer(fuente)
        ms.append((time.time() - t0) * 1000)
        falta, prohibido = puntuar(prompt, c)
        bien = not falta and not prohibido
        ok += bien
        print(f"\n## {c['name']}: {'OK' if bien else 'FALLA'}")
        print("   ", prompt)
        if not bien:
            fallos.append((c["name"], falta, prohibido))
            print("    falta:", falta, "| prohibido presente:", prohibido)
        if traza["descartadas"]:
            print("    descartadas:", [f"{a} ({b})" for a, b in traza["descartadas"]])
    print(f"\nRESUMEN escenas nuevas: {ok}/{len(CASOS)} | latencia media {sum(ms) / len(ms):.0f} ms")
    for f in fallos:
        print("  -", f)


if __name__ == "__main__":
    main()

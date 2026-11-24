"""Compara el redactor determinista (escena_prompt.py) con el redactor LLM de b_chat sobre sus MISMAS 6 escenas de prueba no explícitas y sus mismas comprobaciones required/forbidden
(copiadas de scripts/check-image-prompts.cjs). Los prompts de Mistral salen de storage/debug/prompt-quality/live-regression.json (se vuelven a puntuar con las comprobaciones actuales).

  python comparar_escenas.py
"""
import json
import re
import time
from pathlib import Path

from escena_prompt import componer

BCHAT = Path(r"D:\Documentos\GitHub\b_chat")
BASE = {
    "camera": "high-angle-side", "main": {"person": "woman", "wardrobe": "vestido azul"}, "location": "sala de estar",
    "time": "Antes miró su reloj. Son las diez de la noche.", "lighting": "Una lámpara ilumina la sala.",
    "photography": {"viewpoint": "slightly elevated side view", "framing": "Environmental composition showing the current pose, supporting surface and interaction, with space above and around the subject.",
                    "canvas": "square, 1:1", "style": "Hyper-realistic photograph", "gaze": "she is looking at the viewer."},
}
R = lambda p: re.compile(p, re.I)
CASOS = [
    dict(name="reading-with-unexecuted-intention", situation="MAIN_ADULT está recostada de lado en el sofá leyendo un libro que sostiene con ambas manos. Quiere levantarse pero sigue recostada.",
         required=[r"\bread(?:s|ing)?\b", r"\bsofa|couch\b", r"\bside\b", r"\bboth hands\b"], forbidden=[r"\bleft side|right side|against her chest|before (?:she )?(?:rises|rising)|urge|intends|intention|wants to\b"]),
    dict(name="current-posture-replaces-past", situation="MAIN_ADULT antes estaba de pie; ahora está sentada en una silla junto a la mesa y escribe en un cuaderno.",
         required=[r"\bseated|sits|sitting\b", r"\bchair\b", r"\bwrit(?:es|ing)\b", r"\bnotebook\b"], forbidden=[r"\bstands|standing|watch|wrist\b"]),
    dict(name="distinct-participants-and-contact", partner={"person": "man", "wardrobe": "camisa gris"},
         situation="MAIN_ADULT está de pie detrás de PARTNER_ADULT y apoya una mano en su hombro. PARTNER_ADULT está sentado en una silla leyendo un periódico.",
         required=[r"\bbehind\b", r"\bshoulder\b", r"\bgray|grey\b", r"\bnewspaper\b", r"\bread(?:s|ing)?\b"], forbidden=[r"\bwatch|wrist|massag(?:es|ing)|supporting her weight|leaning on\b"]),
    dict(name="pov-observer-is-not-main-person", camera="pov", situation="MAIN_ADULT está de pie al otro lado de la mesa sosteniendo una taza con ambas manos. PARTNER_ADULT está sentado frente a ella.",
         photography={"viewpoint": "first-person view from the observer's eyes", "framing": "show the main person and table", "gaze": "she is looking at the viewer."},
         required=[r"\bstand(?:s|ing)\b", r"\bcup\b", r"\bboth hands\b", r"\bPOV|first.person\b"], forbidden=[r"\bwoman (?:sits|is seated)|her lap|watch|wrist|(?:partner|man|observer) sits|seated eye level|seated partner\b"]),
    dict(name="object-use-and-rejected-request", situation="MAIN_ADULT está arrodillada junto a una maceta, regando la planta con una regadera. PARTNER_ADULT le pide que se levante, pero ella sigue regando sin cambiar de postura.",
         required=[r"\bkneel(?:s|ing)?|on her knees\b", r"\bwater(?:s|ing)\b", r"\bplant\b", r"\bwatering can\b"], forbidden=[r"\bstands|standing|gets up|rises|watch|wrist|bell|dough\b"]),
    dict(name="no-borrowed-appearance-or-posture", main={"person": "man", "wardrobe": "chaqueta roja"}, partner={"person": "woman", "wardrobe": "abrigo verde"},
         situation="MAIN_ADULT está de pie a la izquierda de PARTNER_ADULT sosteniendo un paraguas cerrado. PARTNER_ADULT está sentada en un banco atándose los cordones.",
         required=[r"\bred jacket\b", r"\bgreen coat\b", r"\bclosed umbrella\b", r"\bbench\b", r"\btying\b", r"\b(?:shoe)?laces\b"], forbidden=[r"\bopen umbrella|watch|wrist|bell|dough\b"]),
]


def puntuar(prompt, caso):
    return [p for p in caso["required"] if not R(p).search(prompt)], [p for p in caso["forbidden"] if R(p).search(prompt)]


def main():
    ruta = BCHAT / "storage" / "debug" / "prompt-quality" / "live-regression.json"
    mistral = {r["name"]: r for r in json.loads(ruta.read_text(encoding="utf-8"))} if ruta.exists() else {}
    componer({**BASE, **{k: v for k, v in CASOS[0].items() if k not in ("name", "required", "forbidden")}})  # calienta el traductor
    tot = {"mistral_ok": 0, "determinista_ok": 0}
    for c in CASOS:
        fuente = {**BASE, **{k: v for k, v in c.items() if k not in ("name", "required", "forbidden")}}
        t0 = time.time()
        prompt, traza = componer(fuente)
        ms = (time.time() - t0) * 1000
        falta, prohibido = puntuar(prompt, c)
        ok_d = not falta and not prohibido
        tot["determinista_ok"] += ok_d
        m = mistral.get(c["name"])
        if m:
            fm, pm = puntuar(m["prompt"], c)
            tot["mistral_ok"] += (not fm and not pm)
        print(f"\n## {c['name']}  | determinista: {'OK' if ok_d else 'FALLA'} ({ms:.0f} ms) | Mistral (re-puntuado con las comprobaciones actuales): " + ("—" if not m else ("OK" if not (fm or pm) else f"FALLA falta={fm} prohibido={pm}")) + f" ({m['milliseconds'] if m else '—'} ms)")
        print("   DET:", prompt)
        if m:
            print("   LLM:", m["prompt"])
        if falta or prohibido:
            print("   falta:", falta, "| prohibido presente:", prohibido)
        if traza["descartadas"]:
            print("   descartadas:", [f"{c_} ({mot})" for c_, mot in traza["descartadas"]])
    print(f"\nRESUMEN: determinista {tot['determinista_ok']}/{len(CASOS)} | Mistral {tot['mistral_ok']}/{len(CASOS)}")


if __name__ == "__main__":
    main()

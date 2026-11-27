"""Experimento pareado A/B/C y transferencia D; biblioteca estándar solamente."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics

from conocimiento_relacional import ASPIRACION, Interprete, MemoriaRelacional, deficit, serial
from entorno_regulacion import Camara


def vivir(memoria, semilla, pasos, documentos=None, destino=False, permutar=False, aprender=True):
    mundo = Camara(semilla, pasos, destino, permutar)
    memoria.importar(documentos or [])
    memoria.hecho(dict(catalogo=[dict(id=a.id, entidad=a.entidad, operacion=a.operacion, coste=a.coste)
                                for a in mundo.acciones], necesidades=mundo.necesidades))
    sujeto = Interprete(memoria, 30_000 + semilla)
    satisfaccion, vistos, usos = [], set(), {'externo': 0, 'empirico': 0, 'exploracion': 0, 'espera': 0}
    coste = exploraciones = contradicciones = contrastes = 0
    errores = []
    errores_empiricos = []
    contradicciones_empiricas = contrastes_empiricos = 0
    traza = []
    for t in range(pasos):
        antes = dict(mundo.estado)
        contexto, fondo = mundo.contexto(t), mundo.fondo(t)
        accion, info = sujeto.proponer(antes, mundo.necesidades, mundo.acciones, contexto, fondo, 1.0)
        despues = mundo.paso(accion, t)
        usos[info['origen']] += 1
        exploraciones += int(info['exploracion'])
        if accion is not None:
            vistos.add(accion.id)
            coste += accion.coste
            resultados = sujeto.observar(accion, antes, despues, contexto, fondo, aprender)
            externos = [r for r in resultados if r['tipo'] == 'externo']
            empiricos = [r for r in resultados if r['tipo'] == 'empirico']
            contrastes += len(externos)
            contradicciones += sum(r['contradice'] for r in externos)
            errores.extend(r['error'] for r in externos)
            contrastes_empiricos += len(empiricos)
            contradicciones_empiricas += sum(r['contradice'] for r in empiricos)
            errores_empiricos.extend(r['error'] for r in empiricos)
        satisfaccion.append(int(deficit(despues, mundo.necesidades) == 0))
        traza.append(dict(t=t, accion=accion.id if accion else None, origen=info['origen'], estado=despues))
    tasa = statistics.mean(satisfaccion)
    return dict(semilla=semilla, satisfaccion=tasa, inicial=statistics.mean(satisfaccion[:20]),
                final=statistics.mean(satisfaccion[-40:]), aspiracion=tasa >= ASPIRACION,
                exploraciones=exploraciones, acciones_ineditas=len(vistos), coste=coste, usos=usos,
                contrastes=contrastes, contradicciones=contradicciones,
                tasa_contradiccion=contradicciones / contrastes if contrastes else None,
                error_prediccion=statistics.mean(errores) if errores else None,
                hipotesis=len(memoria.empiricas()),
                contrastes_empiricos=contrastes_empiricos, contradicciones_empiricas=contradicciones_empiricas,
                error_empirico=statistics.mean(errores_empiricos) if errores_empiricos else None,
                evidencia_externa=[dict(relacion=i, contexto=json.loads(c), favor=f, contra=z,
                                        cuestionada=z > f)
                                   for i, c, f, z in memoria.db.execute(
                                       'SELECT relacion,contexto,favor,contra FROM evidencia ORDER BY relacion,contexto')],
                huella_traza=hashlib.sha256(serial(traza).encode()).hexdigest())


METRICAS = ('satisfaccion', 'inicial', 'final', 'exploraciones', 'acciones_ineditas', 'coste', 'aspiracion')


def intervalo_pareado(deltas):
    rng = random.Random(90_000)
    medias = sorted(statistics.mean(rng.choices(deltas, k=len(deltas))) for _ in range(2000))
    return dict(media=statistics.mean(deltas), ic95_bootstrap=[medias[49], medias[1949]])


def comparar(rep, pasos, semilla):
    vidas = []
    for seed in range(semilla, semilla + rep):
        docs = Camara(seed, pasos).documentos()
        falsos = Camara(seed, pasos).documentos(True)
        for nombre, documentos, aprende in [('A', [], True), ('B', docs, True), ('C', falsos, True),
                                            ('B_fijo', docs, False), ('C_fijo', falsos, False)]:
            with MemoriaRelacional() as m:
                fila = vivir(m, seed, pasos, documentos, aprender=aprende)
                fila['condicion'] = nombre
                vidas.append(fila)
        # Fuente independiente de B/C, sin testimonio: transferencia de experiencia A.
        with MemoriaRelacional() as fuente:
            entrenamiento = vivir(fuente, seed, pasos)
            for nombre, transferir, permutar in [('D', True, False), ('D_vacio', False, False),
                                                ('D_roles_permutados', True, True)]:
                with MemoriaRelacional() as m:
                    if transferir:
                        fuente.transferir(m)
                    fila = vivir(m, seed, pasos, destino=True, permutar=permutar)
                    fila.update(condicion=nombre, coste_fuente=entrenamiento['coste'],
                                exploraciones_fuente=entrenamiento['exploraciones'])
                    vidas.append(fila)
    condiciones = list(dict.fromkeys(f['condicion'] for f in vidas))
    resumen = {c: {k: statistics.mean(f[k] for f in vidas if f['condicion'] == c) for k in METRICAS}
               for c in condiciones}
    contrastes = {}
    for a, b in [('B', 'A'), ('C', 'A'), ('C', 'C_fijo'), ('B', 'B_fijo'), ('D', 'D_vacio'), ('D', 'D_roles_permutados')]:
        left = {f['semilla']: f for f in vidas if f['condicion'] == a}
        right = {f['semilla']: f for f in vidas if f['condicion'] == b}
        contrastes[f'{a}-{b}'] = {k: intervalo_pareado([left[s][k] - right[s][k] for s in left])
                                 for k in ('satisfaccion', 'inicial', 'coste', 'exploraciones')}
    archivos = ['conocimiento_relacional.py', 'entorno_regulacion.py', 'experimento_conocimiento.py']
    return dict(protocolo=dict(rep=rep, pasos=pasos, semilla=semilla, aspiracion=ASPIRACION,
                               exploracion=0.15, bootstrap=2000, ventana_inicial=20, ventana_final=40),
                codigo_sha256={f: hashlib.sha256(Path(__file__).with_name(f).read_bytes()).hexdigest() for f in archivos},
                resumen=resumen, contrastes_pareados=contrastes, vidas=vidas,
                limites=['Efectos aditivos, observables, horizonte de un paso y roles públicos impuestos.',
                         'D transfiere hipótesis por rol y contexto; no descubre la ontología.',
                         'Intervalos descriptivos por semilla, sin corrección por comparaciones múltiples.',
                         'Prototipo separado: pendiente conexión al controlador continuo W/P.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rep', type=int, default=40)
    parser.add_argument('--pasos', type=int, default=160)
    parser.add_argument('--semilla', type=int, default=0)
    parser.add_argument('--salida', type=Path, required=True)
    parser.add_argument('--importar', type=Path, help='JSON externo para una vida persistente')
    parser.add_argument('--db', type=Path, help='Una vida B/archivo; fuera de la comparación aislada')
    args = parser.parse_args()
    if args.rep < 2 or args.pasos < 40 or args.semilla < 0:
        parser.error('rep >= 2, pasos >= 40 y semilla >= 0')
    if args.importar and not args.db:
        parser.error('--importar requiere --db')
    if args.db:
        args.db.parent.mkdir(parents=True, exist_ok=True)
        documentos = json.loads(args.importar.read_text(encoding='utf-8')) if args.importar else []
        with MemoriaRelacional(args.db) as m:
            resultado = vivir(m, args.semilla, args.pasos, documentos)
    else:
        resultado = comparar(args.rep, args.pasos, args.semilla)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(resultado, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(resultado.get('resumen', resultado), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

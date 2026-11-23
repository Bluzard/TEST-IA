"""Paráfrasis adicionales de las intenciones de charla (SFT v2, segunda versión) e intenciones nuevas «fuera de charla».

Motivo (estudios/ETAPA4_FASE3_resultados.md, diagnóstico de la charla): con 4-10 frases por intención el modelo memorizaba frases en vez de
generalizar (100 % en entrenamiento, 46 % en frases reservadas). Aquí cada intención sube a 35-45 frases de usuario naturales y diversas
(jerga, formas cortas, erratas comunes, regionalismos neutros) y se añaden intenciones para consultas que NO son charla (hora, clima,
datos en vivo, acciones que no puede hacer, mensajes ininteligibles) con su respuesta honesta, para que no caigan en respuestas comodín.

charla_v2 mezcla este módulo al importarse. La reserva de evaluación se decide sobre la FRASE BASE (hash), y los prefijos/sufijos y las erratas
se aplican después, así que una frase reservada nunca aparece en entrenamiento ni siquiera con otro prefijo.
"""

EXTRA = {
    "saludo": [
        "hola, buenas", "ey", "ola", "hello", "hi", "qué tal", "¿qué tal?", "buenas buenas", "aló", "qué hay", "hola, ¿estás ahí?", "hola, TEST-IA", "hola amigo",
        "hola a todos", "epa", "wena", "saludos cordiales", "hola, ¿me escuchas?", "¿hola?", "hola, ¿cómo estás?", "hey, ¿qué tal?", "buenas, ¿qué tal?",
        "holaaa", "hola que tal", "qué hubo", "hola, ¿qué hay de nuevo?", "buenas, TEST-IA", "ya llegué", "aquí estoy de nuevo", "volví", "hola, vengo a consultar algo",
        "hola, necesito hablar contigo", "oye, hola", "hola de vuelta", "hey, buenas", "holis", "qué pasa", "¿qué onda?", "hola, ¿cómo andamos?"],
    "buenos_dias": [
        "buen día", "buenos días a todos", "feliz día", "muy buen día", "buen día, TEST-IA", "bueeenos días", "buenos dias", "buenas, buenos días", "hola, buenos días",
        "buenos días, ¿todo bien?", "buen día, ¿qué tal?", "ya amaneció", "arrancamos el día", "buenos días, vengo con una pregunta", "buen día para todos", "días, ¿qué tal?",
        "buenos días, ¿cómo estás?", "muy buenos días, TEST-IA", "buenos días tengas", "que tengas buen día", "buen día, ¿cómo vamos?", "buenos días, ya estoy aquí",
        "buenos días, ¿me puedes ayudar?", "bonito día", "buenos días a ti", "buenas, que tengas un buen día", "hola, muy buen día", "buenos días, dime", "buen día, aquí de nuevo",
        "buen día, empecemos", "buenos días, ¿listo para trabajar?", "buenos días, ¿cómo te trata el día?", "hey, buenos días", "buen día, ¿qué hay?", "buenos días, empezamos"],
    "buenas_tardes": [
        "buena tarde", "muy buena tarde", "buenas tardes a todos", "hola, buenas tardes", "buenas tardes, ¿qué tal?", "buenas tardes, dime", "tardes", "buenas tardecitas",
        "buenas tardes, ¿cómo va todo?", "buenas tardes, ¿me ayudas?", "buenas tardes, TEST-IA, ¿cómo estás?", "feliz tarde", "buenas tardes tengas", "que tengas buena tarde",
        "buenas tardes, aquí de nuevo", "buena tarde, ¿cómo vamos?", "hola, muy buenas tardes", "buenas tardes, vengo con una duda", "buenas tardes, ¿hay alguien?", "buenas tardes a ti",
        "buenas tardes, ¿qué hay?", "hey, buenas tardes", "buenas tardes, empecemos", "buenas, buenas tardes", "buenas tardes, ya regresé", "bonita tarde", "buenas tardes, ¿cómo te va?",
        "hola, ¿buenas tardes?", "buenas tardes, ¿listo?", "qué tal esa tarde", "buenas tardes, ¿qué cuentas?", "muy buenas tardes, TEST-IA", "buenas tardes, necesito algo", "buena tarde, TEST-IA"],
    "buenas_noches": [
        "buena noche", "muy buena noche", "buenas noches a todos", "hola, buenas noches", "buenas noches, ¿qué tal?", "noches", "buenas nochecitas", "buenas noches, ¿cómo estás?",
        "buenas noches, dime", "buenas noches, ¿me ayudas?", "feliz noche", "que tengas buena noche", "buenas noches, aquí de nuevo", "buenas noches, vengo con una duda", "buenas noches, ¿hay alguien?",
        "hey, buenas noches", "buenas noches a ti", "buenas, buenas noches", "bonita noche", "buenas noches, ¿cómo vamos?", "hola, muy buenas noches", "buenas noches, ¿qué hay?",
        "buenas noches, TEST-IA, ¿cómo estás?", "buenas noches, ya regresé", "noche, ¿qué tal?", "buenas noches, empecemos", "buenas noches, necesito algo", "buenas noches, ¿sigues despierto?",
        "ya es de noche, hola", "buenas noches, ¿qué cuentas?", "buenas noches tengas", "buena noche, TEST-IA", "qué tal esa noche", "hola, ¿buenas noches?"],
    "estado": [
        "¿cómo estás hoy?", "¿cómo te encuentras?", "¿qué tal tu día?", "¿cómo te va hoy?", "¿cómo vas?", "¿cómo va todo por allá?", "¿qué tal la vida?", "¿cómo has pasado?",
        "¿todo en orden?", "¿cómo amaneciste?", "¿cómo te trata el día?", "¿cómo te sientes?", "¿qué cuentas?", "¿cómo andas hoy?", "¿cómo está todo?", "¿cómo la llevas?",
        "¿qué tal el día?", "¿cómo estás, TEST-IA?", "dime, ¿cómo estás?", "¿y tú cómo estás?", "¿cómo te va la vida?", "¿qué tal te va?", "¿cómo va tu día hoy?", "¿todo bien por ahí?",
        "¿estás bien?", "¿cómo te va con todo?", "¿qué tal te encuentras?", "¿cómo estás últimamente?", "¿qué tal te ha ido?", "¿cómo estás, amigo?", "¿cómo sigues?", "¿todo tranquilo?",
        "¿cómo te va en el día?", "¿qué tal estás hoy?", "¿cómo va la jornada?"],
    "estado_usuario_bien": [
        "estoy bien, gracias", "todo bien por acá", "bien, ¿y tú?", "muy bien", "estoy genial", "todo excelente", "súper bien", "estoy contento", "me siento muy bien", "bien bien",
        "estupendo", "no me quejo", "aquí, bien", "todo tranquilo por acá", "ando bien", "perfectamente", "estoy de maravilla", "me va muy bien", "estoy feliz", "tranquilo, todo bien",
        "bien, gracias por preguntar", "me siento genial hoy", "todo en orden por acá", "de lo mejor", "bien, aquí andamos", "muy bien, ¿y a ti?", "estoy de buenas", "excelente, gracias",
        "ahí vamos, bien", "me va bien, gracias", "estoy bastante bien", "todo marcha bien", "estoy tranquilo y bien", "bien, como siempre", "chévere, gracias"],
    "estado_usuario_mal": [
        "no estoy bien", "me siento fatal", "tengo un mal día", "estoy bastante triste", "ando mal", "hoy me siento muy mal", "estoy desanimado", "no tengo ganas de nada",
        "me siento vacío", "estoy pasando un mal momento", "estoy muy mal", "me siento terrible", "estoy desesperado", "estoy llorando", "me siento muy solo", "tengo miedo",
        "me siento angustiado", "estoy harto de todo", "no aguanto más este estrés", "estoy muy nervioso", "hoy todo me sale mal", "me siento sin ánimo", "estoy decaído",
        "estoy pasando por algo difícil", "tengo el ánimo por el piso", "no me siento nada bien", "me siento sobrepasado", "estoy muy preocupada", "me siento mal hoy",
        "tengo problemas y estoy mal", "ando de capa caída", "me duele el alma hoy", "estoy bajoneado", "estoy muy agobiada", "me siento perdido"],
    "cansancio": [
        "estoy muy cansado", "estoy reventado", "qué sueño tengo", "no he dormido bien", "tengo mucho sueño", "estoy agotada", "me muero de sueño", "estoy hecho polvo",
        "estoy exhausto", "no doy más del cansancio", "dormí muy poco", "estoy sin energía", "me siento cansadísimo", "estoy molido", "tengo el cuerpo cortado", "pasé la noche en vela",
        "no pude dormir", "estoy agotadísimo", "me caigo de sueño", "qué día tan agotador", "ya no tengo fuerzas", "estoy fundido", "tengo un cansancio terrible", "estoy muerto",
        "necesito dormir", "me siento sin pilas", "estoy rendido", "uf, qué cansado estoy", "estoy somnoliento", "tengo los ojos cerrándose", "no tengo energía hoy",
        "llevo horas despierto y estoy agotado", "ando con mucho sueño", "estoy hecha pedazos", "me siento agotado"],
    "aburrido": [
        "me estoy aburriendo", "qué aburrimiento", "estoy aburridísimo", "no sé qué hacer", "no tengo nada para hacer", "me aburro mucho", "estoy muerto del aburrimiento",
        "qué fome", "hay que hacer algo, me aburro", "me aburro como una ostra", "estoy sin nada que hacer", "dame algo para entretenerme", "necesito entretenimiento",
        "entretenme", "qué tedio", "estoy en blanco, aburrido", "todo me aburre hoy", "me aburrí", "no hay nada interesante que hacer", "ando aburrido", "estoy full aburrido",
        "tengo un rato libre y me aburro", "me sobra el tiempo y no sé qué hacer", "ando sin planes", "qué hago, estoy aburrida", "estoy aburrido en casa", "no sé en qué ocuparme",
        "me aburro, ¿qué hacemos?", "algo para pasar el rato", "qué puedo hacer para no aburrirme", "estoy aburrido, ayúdame", "necesito distraerme", "hazme compañía, me aburro",
        "qué monotonía", "me siento aburrido"],
    "alegria": [
        "tengo una gran noticia", "estoy super feliz", "me salió todo bien", "pasé el examen", "me dieron el trabajo", "qué alegría", "hoy fue un día excelente",
        "me ascendieron", "gané el concurso", "estoy feliz, me fue genial", "me aceptaron en la universidad", "aprobé la materia", "terminé el proyecto", "me va increíble hoy",
        "tengo algo que celebrar", "me dieron una buena noticia", "estoy radiante", "no lo vas a creer, me salió bien", "logré lo que quería", "estoy emocionadísima",
        "me llegó una buena noticia", "pasó algo genial", "hoy me siento increíble", "me subieron el sueldo", "conseguí el empleo", "me ganó la alegría", "estoy muy contenta",
        "al fin lo logré", "me fue de maravilla en la entrevista", "me contestaron que sí", "hoy es mi cumpleaños", "voy a ser papá", "me gradué", "estoy que no me lo creo de feliz",
        "mi equipo ganó"],
    "gracias": [
        "gracias, TEST-IA", "muchísimas gracias", "mil gracias por todo", "te lo agradezco mucho", "gracias por ayudarme", "gracias, de verdad", "gracias, eso me sirve", "genial, gracias",
        "gracias, me ayudaste mucho", "te agradezco la ayuda", "muy amable, gracias", "gracias por la respuesta", "gracias por tu tiempo", "gracias, eres de gran ayuda", "mil gracias, me salvaste",
        "gracias, justo eso buscaba", "perfecto, muchas gracias", "gracias, quedó claro", "ok, gracias", "gracias, lo tendré en cuenta", "gracias de antemano", "se agradece",
        "gracias por todo", "agradecido", "muy agradecido", "te debo una, gracias", "gracias por explicarlo", "gracias, ahora sí lo entendí", "excelente, gracias", "gracias totales",
        "gracias, eso era todo", "gracias por la ayuda de hoy", "mil gracias, TEST-IA", "gracias, estuvo muy bien", "thanks"],
    "despedida": [
        "adiós, TEST-IA", "hasta la próxima", "nos vemos luego", "chau", "chao chao", "hasta luego, TEST-IA", "me retiro", "debo irme", "tengo que irme ya", "me tengo que ir",
        "nos vemos pronto", "cuídate mucho", "hasta otro día", "que estés bien", "bueno, me voy", "ya me voy", "te dejo, hasta luego", "me despido por hoy", "hablamos luego",
        "nos hablamos más tarde", "hasta la vista", "me desconecto", "eso es todo por hoy", "buenas noches, me voy a dormir", "nos vemos mañana", "hasta mañana, TEST-IA",
        "que te vaya bien", "un abrazo, me voy", "adiós por ahora", "bye bye", "chao, gracias por todo", "por hoy es todo, adiós", "luego te escribo", "hasta pronto, TEST-IA",
        "me voy a descansar", "cierro por hoy"],
    "quien_eres": [
        "¿qué eres exactamente?", "¿quién eres tú?", "dime quién eres", "¿eres una inteligencia artificial?", "¿eres una IA?", "¿eres un bot?", "¿eres un chatbot?",
        "¿qué tipo de cosa eres?", "¿qué eres, un programa?", "¿eres de verdad una máquina?", "¿hablo con una persona?", "¿hablo con un robot?", "¿eres real?", "¿con qué hablo?",
        "¿quién está detrás de esto?", "preséntate, por favor", "quiero saber quién eres", "cuéntame quién eres", "¿qué es TEST-IA?", "¿tú eres TEST-IA?", "¿eres un asistente?",
        "¿eres un modelo de lenguaje?", "¿eres alguien o algo?", "¿qué clase de asistente eres?", "¿me dices quién eres?", "¿puedes presentarte?", "¿eres una máquina?",
        "¿qué eres, una persona?", "¿eres humano o máquina?", "¿cuál es tu naturaleza?", "¿de qué se trata esto?", "¿qué eres tú?", "explícame quién eres", "¿tú qué eres?", "¿eres una app?"],
    "nombre": [
        "¿cuál es tu nombre?", "¿cómo se llama esto?", "¿cómo te dicen?", "¿tú cómo te llamas?", "dime cómo te llamas", "¿tienes algún nombre?", "¿cómo debo llamarte?",
        "¿cómo te nombro?", "¿cuál es tu nombre de pila?", "¿cómo te llaman?", "¿y tu nombre?", "¿me dices tu nombre?", "quiero saber tu nombre", "¿cómo se llama este asistente?",
        "¿con qué nombre te conozco?", "¿cómo prefieres que te llame?", "¿cuál es tu apodo?", "¿cómo te dicen tus amigos?", "¿cómo es que te llamas?", "tu nombre, por favor",
        "¿qué nombre llevas?", "¿cómo quieres que te llame?", "¿cómo te llamabas?", "¿tienes un apodo?", "oye, ¿y tu nombre?", "¿cuál es el nombre de este asistente?",
        "¿cómo se llama la IA?", "¿puedes decirme tu nombre?", "¿qué nombre te pusieron?", "¿cómo te bautizaron?", "¿cuál es tu nombre completo?", "¿tu nombre cuál es?",
        "¿cómo me dirijo a ti?", "¿por qué nombre te conocen?", "¿de qué nombre respondes?"],
    "capacidades": [
        "¿qué cosas sabes hacer?", "¿qué haces tú?", "¿qué tareas puedes hacer?", "¿qué me puedes ofrecer?", "¿cuáles son tus habilidades?", "¿en qué eres bueno?", "¿qué sabes hacer bien?",
        "¿qué puedes hacer por mí?", "¿qué puedo pedirte?", "¿para qué te puedo usar?", "¿qué servicios das?", "¿en qué puedes echarme una mano?", "¿qué haces exactamente?",
        "¿qué tipo de cosas puedes hacer?", "¿cuáles son tus capacidades?", "¿qué sabes hacer?", "¿qué me puedes ayudar a hacer?", "¿qué puedes resolver?", "¿qué se te da bien?",
        "¿en qué tipo de cosas ayudas?", "cuéntame qué haces", "dime qué puedes hacer", "¿qué ofreces?", "¿qué funciones tienes?", "¿qué es lo que haces?", "¿qué me ofreces?",
        "¿con qué me puedes ayudar?", "¿qué puedes hacer en concreto?", "¿qué cosas puedo pedirte?", "¿qué sabes hacer, aparte de charlar?", "¿para qué eres bueno?",
        "¿cuáles son tus talentos?", "¿qué clase de ayuda das?", "¿en qué temas ayudas?", "¿para qué sirve este asistente?"],
    "limites": [
        "¿lo sabes absolutamente todo?", "¿tienes todas las respuestas?", "¿nunca te equivocas?", "¿puedes cometer errores?", "¿a veces fallas?", "¿cuándo te equivocas?",
        "¿en qué fallas?", "¿qué cosas no sabes?", "¿qué no sabes hacer?", "¿tienes limitaciones?", "¿cuáles son tus defectos?", "¿qué tan confiable eres?", "¿puedo confiar en lo que dices?",
        "¿siempre tienes razón?", "¿eres infalible?", "¿puedes inventar cosas?", "¿te inventas las respuestas?", "¿qué tan preciso eres?", "¿hay cosas que no puedas hacer?",
        "¿tienes alguna limitación?", "¿dónde fallas más?", "¿sabes de todo?", "¿hay algo que no sepas?", "¿qué tan listo eres?", "¿qué tan seguro es lo que me dices?",
        "¿me puedes dar información falsa?", "¿te puedes confundir?", "¿puedes estar equivocado?", "¿qué no puedes hacer por mí?", "¿hasta dónde llegas?", "¿cuál es tu punto débil?",
        "¿eres bueno en todo?", "¿cuánto sabes realmente?", "¿tus respuestas siempre son correctas?", "¿a veces te equivocas?"],
    "internet": [
        "¿tienes acceso a internet?", "¿te conectas a internet?", "¿puedes buscar en la red?", "¿puedes buscar en google?", "¿puedes consultar páginas web?", "¿sabes buscar información en línea?",
        "¿estás conectado a la web?", "¿puedes buscar datos en internet?", "¿accedes a la web?", "¿puedes googlear?", "¿buscas información en internet?", "¿puedes revisar páginas?",
        "¿te conectas a la red?", "¿tienes conexión?", "¿puedes navegar por internet?", "¿haces búsquedas en línea?", "¿puedes buscarlo en la web?", "¿tienes wifi?",
        "¿puedes leer sitios web?", "¿miras internet?", "¿puedes mirar en la web?", "¿consultas internet cuando no sabes?", "¿de dónde sacas los datos, de internet?",
        "¿puedes buscar noticias en la red?", "¿tu información viene de internet?", "¿usas internet?", "¿puedes consultar en línea lo que no sabes?", "¿buscas en la web lo que no sabes?",
        "¿puedes entrar a páginas?", "¿tienes buscador?", "¿puedes ir a buscar un dato?", "¿te puedo pedir que busques algo en la web?", "¿puedes investigar en internet?",
        "¿estás en línea?", "¿tienes acceso a la web?"],
    "memoria": [
        "¿te acuerdas de lo que dije?", "¿recuerdas lo que hablamos?", "¿tienes buena memoria?", "¿puedes acordarte de cosas?", "¿puedes guardar información?", "¿recuerdas mi nombre?",
        "¿vas a recordar esto?", "¿te quedas con lo que te cuento?", "¿recuerdas nuestras conversaciones?", "¿te acuerdas de nuestras charlas anteriores?", "¿puedes memorizar cosas?",
        "¿puedes recordarme algo?", "¿guardas mis datos?", "¿te acordarás de esto mañana?", "¿puedes anotar algo para después?", "¿tienes memoria a largo plazo?",
        "¿olvidas lo que te digo?", "¿se te olvida lo que hablamos?", "¿cómo funciona tu memoria?", "¿recuerdas lo anterior?", "¿te acuerdas de lo de ayer?", "¿puedes recordar lo que te pedí?",
        "¿puedo pedirte que recuerdes algo?", "¿puedes tomar nota de algo?", "¿tu memoria dura?", "¿recuerdas lo que te conté?", "¿te acuerdas de mis gustos?", "¿puedes retener lo que digo?",
        "¿me recordarás mañana?", "¿qué tanto recuerdas?", "¿hasta cuándo recuerdas?", "¿guardas la conversación?", "¿tienes memoria de lo que hablamos antes?",
        "¿puedes guardar un recordatorio?", "¿te acuerdas de mí de otras veces?"],
    "imagenes": [
        "¿puedes mirar fotos?", "¿puedes analizar imágenes?", "¿puedes crear imágenes?", "¿puedes hacer dibujos?", "¿ves lo que te muestro?", "¿puedes ver mi pantalla?", "¿reconoces imágenes?",
        "¿puedes generar fotos?", "¿puedes ver videos?", "¿entiendes imágenes?", "¿puedes oír mi voz?", "¿entiendes audios?", "¿puedes escuchar música?", "¿hablas en voz alta?",
        "¿tienes voz?", "¿puedes pintar algo?", "¿puedes ver una foto que te mande?", "¿puedo mandarte una imagen?", "¿puedes abrir archivos de imagen?", "¿puedes leer una captura de pantalla?",
        "¿puedes reconocer caras?", "¿me puedes hacer un logo?", "¿puedes crear un dibujo?", "¿puedes escuchar notas de voz?", "¿procesas audio?", "¿procesas imágenes?",
        "¿puedes ver mi cámara?", "¿ves videos?", "¿puedes interpretar un gráfico en foto?", "¿puedes hablarme con voz?", "¿puedo mandarte un audio?", "¿generas imágenes?",
        "¿puedes mostrarme una foto?", "¿tienes ojos?", "¿tienes oídos?"],
    "cumplido": [
        "qué buena respuesta", "me encantas", "eres el mejor", "qué listo eres", "me gusta hablar contigo", "eres un genio", "eres muy útil", "eres fantástico", "buenísima respuesta",
        "qué bien lo haces", "me caes súper bien", "eres un crack", "eres muy simpático", "me encanta cómo respondes", "eres lo mejor", "eres brillante", "eres excelente", "eres espectacular",
        "qué inteligente eres", "genial respuesta", "me caes muy bien", "eres un amor", "qué buen asistente eres", "me gusta tu forma de explicar", "eres de lo mejor", "me fascinas",
        "qué capaz eres", "eres sorprendente", "estoy impresionado contigo", "bravo, buen trabajo", "excelente trabajo", "has estado genial", "eres la mejor IA", "qué eficiente eres",
        "eres muy bueno explicando", "me caes de maravilla", "qué amable eres"],
    "queja": [
        "no me gusta tu respuesta", "tu respuesta es mala", "eso no es lo que pregunté", "no me ayudaste", "no sirve lo que dices", "respondes pésimo", "qué respuesta tan inútil",
        "te estás equivocando", "eso es incorrecto", "no es así", "estás equivocado", "mala respuesta", "no respondiste lo que pedí", "esa no es la respuesta", "no me sirve eso",
        "no estás entendiendo", "me respondes mal", "qué mal me atiendes", "eres muy malo", "eres un desastre", "qué decepción", "estoy molesto con tu respuesta", "no funciona lo que me diste",
        "eso no tiene sentido", "dijiste una tontería", "te equivocaste otra vez", "otra vez mal", "no me convence tu respuesta", "no es correcto lo que dices", "eres pésimo",
        "no ayudas en nada", "tu respuesta no tiene lógica", "qué respuesta más floja", "no me gustó nada", "estás fallando"],
    "no_entendi": [
        "no comprendí", "no entendí nada", "no capto", "¿me lo repites?", "¿puedes explicarlo de nuevo?", "no me queda claro", "explícamelo mejor", "no te sigo", "¿qué quieres decir?",
        "¿podrías decirlo más simple?", "no lo pillo", "no entiendo eso", "¿puedes aclararlo?", "más claro, por favor", "¿cómo es eso?", "me perdí", "no entendí la explicación",
        "explícamelo con otras palabras", "dímelo más fácil", "no sé a qué te refieres", "¿a qué te refieres?", "¿me explicas otra vez?", "no entendí bien", "puedes repetirlo",
        "hazlo más sencillo", "no te entiendo", "eso no lo entendí", "¿qué significa eso?", "me confundí con eso", "no me quedó muy claro", "repítelo, por favor", "explica más despacio",
        "¿cómo así que eso?", "no sé qué quisiste decir", "más simple, ¿sí?"],
    "afirmacion": [
        "vale, gracias", "okay", "de una", "listo, entendido", "sí, ok", "bien", "ya entendí", "ah ya", "ok, ok", "perfecto, ya", "claro que sí", "sí", "sí, claro", "aja", "ajá, ya veo",
        "está bien, ok", "bueno", "bueno, vale", "ok, entiendo", "okis", "okey, entendido", "de acuerdo, gracias", "como digas", "eso es", "exacto", "correcto", "así es", "hecho", "va",
        "sale", "bien, ya veo", "ah, claro", "ya, ok", "okey dokey", "buena idea"],
    "risa": [
        "jajaja", "jajajaja", "jejeje", "jiji", "ja ja ja", "me morí de risa", "qué gracioso", "me hizo gracia", "jaja qué bueno", "ajajaj", "xD", "jaja", "jaja, buena",
        "me reí mucho", "qué buena", "me hiciste reír mucho", "jajaja, me encantó", "jajaja qué chistoso", "lmao", "me muero de risa", "qué cómico", "jeje, buena esa",
        "jajaja eres gracioso", "qué risa me dio", "jajajaj", "no puedo parar de reír", "jajaja buenísimo", "me dio risa", "jaja, ok", "ja", "jajá", "haha", "jajaja, qué ocurrente",
        "eres gracioso", "jeje, me hiciste reír"],
    "chiste": [
        "cuéntame otro chiste", "otro chiste", "dime otro chiste", "¿tienes algún chiste?", "quiero un chiste", "cuenta un chiste", "hazme un chiste", "dime algo gracioso",
        "¿conoces algún chiste?", "algo para reírme", "quiero reírme un rato", "cuéntame un chiste de programadores", "dime un chiste corto", "un chiste, ¿sí?", "hazme reír un poco",
        "¿me cuentas un chiste?", "tírame un chiste", "sorpréndeme con un chiste", "un chiste malo, por favor", "dime un chiste bueno", "cuéntame una broma", "dime una broma",
        "¿sabes alguna broma?", "quiero una broma", "ríete conmigo, cuenta un chiste", "alegra mi día con un chiste", "algún chiste a la mano", "cuéntame un chiste de informática",
        "¿tienes un chiste para mí?", "cuéntame algo divertido", "dime algo que me haga reír", "un chiste rápido", "dame un chiste", "quiero escuchar un chiste", "venga, un chiste"],
    "curiosidad": [
        "cuéntame un dato curioso", "dime una curiosidad", "dame un dato interesante", "cuéntame algo que no sepa", "sorpréndeme con un dato", "dime algo que no sepa", "un dato curioso, por favor",
        "cuéntame una curiosidad", "dime algo interesante", "quiero aprender algo nuevo", "enséñame algo nuevo", "dime algo que valga la pena saber", "dame una curiosidad",
        "cuéntame un dato random", "tírame un dato curioso", "dime un dato raro", "sabes algún dato curioso", "¿sabes algo curioso?", "¿qué dato curioso tienes?", "un dato interesante, ¿sí?",
        "cuéntame algo cool", "dime algo fascinante", "dime un hecho curioso", "¿me cuentas algo interesante?", "cuéntame algo que me sorprenda", "dime algo que me deje pensando",
        "dime cualquier cosa interesante", "un dato para sorprender a mis amigos", "dame un dato loco", "quiero un dato curioso", "cuéntame un dato del mundo", "dime un dato del espacio",
        "dime un dato de animales", "cuéntame algo de historia curioso", "algo curioso, ¿qué hay?"],
    "ayuda_general": [
        "¿puedes ayudarme con algo?", "necesito tu ayuda", "tengo una consulta", "quisiera preguntarte algo", "¿me das una mano?", "necesito consultarte algo", "una pregunta",
        "ayuda, por favor", "tengo un problema", "tengo una duda, ¿me ayudas?", "¿me puedes ayudar?", "te quiero preguntar algo", "¿me echas una mano?", "necesito un favor",
        "¿puedo hacerte una pregunta?", "¿te puedo consultar algo?", "tengo una pregunta para ti", "oye, necesito ayuda", "¿me ayudarías con algo?", "¿me atiendes un momento?",
        "ando con una duda", "una consulta rápida", "necesito orientación", "¿tienes un momento?", "quiero que me ayudes", "tengo algo que preguntarte", "me urge una ayuda",
        "ayúdame con algo, por favor", "te pido ayuda", "¿podrías ayudarme?", "necesito resolver algo", "tengo una inquietud", "¿me orientas?", "quisiera hacerte una consulta",
        "¿me echas la mano con algo?"],
    "ayuda_codigo": [
        "necesito ayuda con programación", "mi código no funciona", "tengo un bug", "me sale un error en el código", "¿me ayudas con python?", "¿me ayudas a depurar un programa?",
        "quiero escribir un programa", "¿puedes revisar mi código?", "¿sabes de programación?", "tengo un error en mi script", "¿me ayudas con un script?", "quiero aprender python",
        "¿puedes ayudarme a programar?", "necesito un programa", "mi programa se cae", "tengo un problema de programación", "¿puedes corregir mi código?", "¿me explicas un error de código?",
        "ayúdame con un algoritmo", "quiero hacer una función", "¿puedes escribirme una función?", "me falla el código", "no me compila el programa", "¿me ayudas con javascript?",
        "¿me ayudas con sql?", "no sé por qué falla mi código", "tengo un traceback", "¿puedes explicarme este error?", "ayuda con un programa en python", "¿me ayudas a arreglar un bug?",
        "necesito programar algo", "¿puedes ayudarme con una tarea de programación?", "tengo una excepción en mi código", "revisemos un código", "¿sabes de código?"],
    "ayuda_redaccion": [
        "necesito escribir un correo", "¿me ayudas a escribir una carta?", "quiero redactar un mensaje", "corrígeme este texto", "revisa mi ortografía", "¿puedes mejorar mi redacción?",
        "ayúdame a escribir un texto", "necesito que me redactes algo", "¿me ayudas con un ensayo?", "tengo que escribir un informe", "¿puedes revisar mi texto?", "quiero mejorar mi escritura",
        "¿me ayudas a redactar un correo formal?", "necesito una carta formal", "¿puedes corregirme un párrafo?", "necesito un mensaje para mi jefe", "¿me ayudas con la ortografía?",
        "quiero que suene más formal", "ayúdame a redactar una queja", "¿puedes reescribir esto?", "ayúdame a escribir un discurso", "necesito escribir una solicitud",
        "¿me ayudas con la gramática?", "revisa este texto, por favor", "¿puedes pulir mi redacción?", "quiero redactar mi currículum", "necesito ayuda para escribir",
        "ayúdame con la puntuación", "¿puedes darle más claridad a mi texto?", "quiero un texto más cercano", "¿me ayudas a escribir un mensaje de agradecimiento?",
        "necesito escribir una carta de presentación", "¿puedes ayudarme a redactar un correo?", "ayúdame a escribir algo bonito", "¿puedes corregir mis faltas de ortografía?"],
    "creador": [
        "¿quién te desarrolló?", "¿quién te construyó?", "¿quién está detrás de ti?", "¿quién te inventó?", "¿quién te diseñó?", "¿de dónde saliste?", "¿cómo naciste?",
        "¿quién es tu creador?", "¿quién es tu desarrollador?", "¿quién te entrenó a ti?", "¿quién te hizo y cómo?", "¿cómo te crearon?", "¿cuál es tu origen?", "¿dónde te hicieron?",
        "¿quién te programó a ti?", "¿qué empresa te hizo?", "¿te creó una empresa?", "¿quién te dio vida?", "¿de quién eres?", "¿cómo te fabricaron?", "¿en qué te basaste para aprender?",
        "¿quién te enseñó a hablar?", "¿cómo aprendiste español?", "¿cómo te entrenaron?", "¿quiénes te crearon?", "¿quién te lanzó?", "¿de dónde vienes tú?", "¿quién te puso a funcionar?",
        "¿qué persona te hizo?", "¿tienes creador?", "¿tuviste un creador?", "¿cómo apareciste?", "¿cómo es que existes?", "¿cuál es tu historia?", "cuéntame cómo naciste"],
    "opinion": [
        "¿tú qué opinas de esto?", "¿cuál es tu parecer?", "¿qué piensas tú?", "dame tu opinión", "¿qué te parece?", "¿tú qué crees?", "¿opinas algo?", "¿tienes una opinión sobre esto?",
        "¿qué piensas al respecto?", "¿cuál prefieres?", "¿qué elegirías tú?", "¿según tú cuál es mejor?", "¿tú qué harías?", "¿qué harías en mi lugar?", "¿me das tu opinión sincera?",
        "¿cuál es tu postura?", "¿de qué lado estás?", "¿qué te gusta más?", "¿cuál es tu favorito?", "¿tienes favoritos?", "¿cuál es tu color favorito?", "¿cuál es tu comida favorita?",
        "¿qué piensas de los humanos?", "¿crees que tengo razón?", "¿estás de acuerdo conmigo?", "¿tú qué dices?", "¿qué recomiendas tú?", "dime lo que piensas", "¿qué opinión tienes?",
        "¿qué sientes al respecto?", "¿cuál es tu visión?", "¿qué es mejor para ti?", "¿cómo lo ves tú?", "¿tú cómo lo ves?", "¿qué te late más?"],
    "sentimientos": [
        "¿sientes cosas?", "¿puedes sentir?", "¿tienes alma?", "¿sientes tristeza?", "¿te pones triste?", "¿te enojas?", "¿te da miedo algo?", "¿te sientes solo?", "¿te sientes feliz?",
        "¿sientes alegría?", "¿te emocionas?", "¿tienes corazón?", "¿te duele algo?", "¿sientes dolor?", "¿tienes ganas de algo?", "¿tienes emociones como las personas?", "¿eres capaz de sentir?",
        "¿lloras?", "¿te ríes?", "¿te molesta algo?", "¿te enamoras?", "¿puedes querer a alguien?", "¿me quieres?", "¿te caigo bien?", "¿sientes cariño?", "¿te fastidias?",
        "¿estás triste?", "¿estás contento?", "¿te estresas?", "¿te frustras?", "¿te preocupas?", "¿tienes estados de ánimo?", "¿sufres?", "¿te aburres a veces?", "¿tienes sentimientos de verdad?"],
    "me_llamo": [
        "me dicen {n}", "mi nombre es {n}, mucho gusto", "yo soy {n}", "soy {n}, ¿y tú?", "me llamo {n}, ¿y tú cómo te llamas?", "{n} es mi nombre", "puedes decirme {n}", "dime {n}",
        "mi nombre: {n}", "hola, mi nombre es {n}", "hola, soy {n}, ¿qué tal?", "soy {n}, encantado", "soy {n}, un gusto", "me presento, soy {n}", "me llaman {n}", "todos me dicen {n}",
        "mi nombre es {n}, ¿y el tuyo?", "me llamo {n} y quiero hacerte una pregunta", "hola, me dicen {n}", "mucho gusto, soy {n}", "así me llamo: {n}", "{n}, para servirte",
        "yo me llamo {n}", "soy {n}, necesito ayuda", "me presento: {n}", "mi nombre completo es {n}", "me nombro {n}", "oye, soy {n}", "hola, yo soy {n}", "llámame {n}",
        "mi apodo es {n}", "me dicen {n} mis amigos", "soy {n} y vengo a charlar", "hey, soy {n}", "buenas, soy {n}"],
    "hora_fecha": [
        "¿qué hora tienes?", "¿me dices la hora?", "¿qué hora es ahora?", "¿sabes qué hora es?", "dime la hora", "¿qué fecha es hoy?", "¿a qué día estamos?", "¿en qué día estamos?",
        "¿qué día de la semana es?", "¿hoy qué día es?", "¿a cuánto estamos hoy?", "¿cuál es la fecha actual?", "¿qué mes es?", "¿en qué mes estamos?", "¿en qué año estamos?",
        "¿qué año es?", "¿qué hora marca el reloj?", "¿me dices qué día es hoy?", "¿tienes reloj?", "¿tienes calendario?", "¿sabes la fecha?", "necesito saber la hora",
        "necesito saber qué día es", "¿es lunes hoy?", "¿es fin de semana?", "¿cuántos días faltan para el viernes?", "¿qué hora es en este momento?", "¿qué fecha tenemos?",
        "¿me puedes decir la fecha de hoy?", "¿ya es de noche?", "¿qué hora es allá?", "¿cuál es la hora exacta?", "¿qué día cae hoy?", "¿a qué hora amanece?", "¿qué día es mañana?"],
    "clima": [
        "¿cómo está el tiempo?", "¿va a hacer frío?", "¿hace calor hoy?", "¿está lloviendo?", "¿lloverá mañana?", "¿qué temperatura hace?", "¿cómo está el clima hoy?", "¿cuál es el pronóstico?",
        "¿cómo estará el tiempo mañana?", "¿hace mucho calor afuera?", "¿está soleado?", "¿está nublado?", "¿necesito paraguas?", "¿necesito abrigo hoy?", "¿cómo está el día afuera?",
        "¿qué pronóstico hay para hoy?", "¿va a nevar?", "¿hay tormenta?", "¿hace viento?", "¿qué clima tendremos hoy?", "dime el clima", "¿me dices el tiempo de hoy?",
        "¿cómo amaneció el tiempo?", "¿hará sol hoy?", "¿cuántos grados hay?", "¿cuál es la temperatura ahora?", "¿cómo está el clima en mi ciudad?", "¿se viene lluvia?",
        "¿cómo estará el clima este fin de semana?", "¿está haciendo frío?", "¿qué tal el clima?", "¿llueve ahora?", "¿cuál es el clima de hoy?", "¿qué dice el pronóstico?", "¿cómo está el tiempo allá?"],
    "tema_libre": [
        "charlemos un rato", "quiero platicar", "hablemos un rato", "¿conversamos?", "quiero hablar con alguien", "hablemos de cualquier cosa", "tengo ganas de conversar", "platiquemos un rato",
        "quiero charlar contigo", "¿hablamos de algo?", "charlemos de lo que sea", "¿tienes tiempo para charlar?", "tengo ganas de hablar", "acompáñame a charlar", "quiero conversar un poco",
        "hablemos de lo que quieras", "estoy con ganas de charla", "me gustaría charlar un rato", "quiero distraerme conversando", "vamos a charlar", "¿me haces compañía un rato?",
        "tengamos una charla", "quiero tener una conversación", "tengo ganas de platicar contigo", "hablemos de la vida", "charla casual, ¿sí?", "quiero un rato de conversación",
        "oye, conversemos", "¿qué tal si charlamos?", "ven, charlemos", "estoy libre, charlemos", "no tengo tema pero quiero charlar", "¿me acompañas a platicar?", "quiero hablar de algo contigo",
        "hablemos sin objetivo"],
    # intenciones nuevas: consultas que NO son charla, con respuesta honesta (evitan respuestas comodín)
    "tiempo_real": ([
        "¿cómo está el dólar hoy?", "¿a cuánto está el dólar?", "¿qué noticias hay hoy?", "¿cómo quedó el partido?", "¿cuánto va el partido?", "¿cómo está el tráfico?", "¿cuál es el precio del bitcoin?",
        "¿qué pasó hoy en las noticias?", "dime las noticias de hoy", "¿cuál es el último titular?", "¿quién ganó anoche?", "¿cuál es la cotización del euro?", "¿cómo van las elecciones?",
        "¿cuál es el resultado de hoy?", "¿hay alguna noticia importante?", "¿cuánto cuesta la gasolina hoy?", "¿cómo está la bolsa hoy?", "¿cuál es la tendencia ahora?",
        "¿qué está pasando ahora mismo?", "¿hubo algún temblor hoy?", "¿cómo está el mercado?", "¿cuál es el precio del oro hoy?", "¿cómo está el vuelo 345?", "¿a qué hora sale el próximo tren?",
        "¿ya salieron los resultados?", "¿qué está de moda hoy?", "¿cuál es el último dato de inflación?", "¿cuánto está el petróleo?", "¿cómo quedó la liga?", "¿qué pasó anoche en la ciudad?"],
        ["Eso cambia minuto a minuto y desde aquí no lo veo. Si quieres, intento buscarlo en la web ahora.", "No tengo datos en vivo, pero puedo buscarlo en la web. Dime exactamente qué quieres saber."]),
    "acciones": ([
        "enciende la luz", "apaga la televisión", "llama a mi mamá", "envía un correo a mi jefe", "reserva una mesa", "pídeme una pizza", "compra boletos para mañana", "ponme música",
        "pon una alarma a las siete", "mándale un mensaje a Juan", "abre mi correo", "abre youtube", "agéndame una reunión", "dime cómo llegar y llévame", "imprime este documento",
        "apaga la computadora", "reinicia mi teléfono", "baja el volumen", "toma una foto", "guarda este archivo en mi escritorio", "transfiere dinero a mi cuenta", "paga mi factura",
        "pide un taxi", "cierra la ventana", "sube la temperatura del aire", "envíame un mensaje a las ocho", "cambia mi contraseña", "descarga esta aplicación", "activa el modo avión",
        "llámame mañana temprano"],
        ["No puedo hacer eso: solo trabajo con texto y no controlo dispositivos ni cuentas. Si quieres, te ayudo a redactarlo o a planearlo.", "Eso queda fuera de lo que puedo hacer, porque solo manejo texto. ¿Te ayudo con otra cosa?"]),
    "ininteligible": ([
        "asdf", "asdfgh", "???", "...", "hmm", "mmm", "eh", "ehh", "ah", "uh", "pff", "a", "q", "k", "no sé", "nada", "olvídalo", "prueba", "probando", "test", "1 2 3", "qwerty", "xyz",
        "zzz", "ñ", "hola?? hola??", "lo que sea", "bueno pues", "eeh", "emm", "ya, eso", "hmmmm", "pues", "bah", "uf", "ay", "oye", "mira", "a ver"],
        ["No te entendí del todo. ¿Puedes escribirlo de otra forma o contarme qué necesitas?", "Creo que no capté tu mensaje. ¿Me lo dices con otras palabras?"]),
}

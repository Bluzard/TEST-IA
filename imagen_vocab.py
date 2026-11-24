"""Vocabulario bilingüe (español, inglés) para generar escenas sintéticas de prompts de imagen: la entrada del usuario sale en español (o inglés/mezcla) y el prompt final en inglés.
Cada entrada es (español, inglés). Los sujetos llevan además un tipo («persona», «animal», «objeto», «lugar», «criatura») para elegir acciones y rasgos coherentes."""

SUJETOS = [  # (es, en, tipo, rasgos_es_en)
    ("un gato naranja", "an orange tabby cat", "animal", [("de ojos verdes", "with bright green eyes"), ("esponjoso", "with fluffy fur")]),
    ("un perro labrador", "a golden labrador", "animal", [("con una bufanda roja", "wearing a red scarf"), ("de pelo mojado", "with wet fur")]),
    ("un zorro", "a red fox", "animal", [("de pelaje brillante", "with glossy fur"), ("curioso", "with curious eyes")]),
    ("un búho", "a snowy owl", "animal", [("de plumas blancas", "with white feathers"), ("de ojos enormes", "with huge amber eyes")]),
    ("un lobo gris", "a grey wolf", "animal", [("con la mirada fija", "with an intense gaze"), ("cubierto de escarcha", "covered in frost")]),
    ("un caballo negro", "a black stallion", "animal", [("con la crin al viento", "with its mane flowing in the wind")]),
    ("un dragón", "a majestic dragon", "criatura", [("de escamas verdes", "with emerald scales"), ("de alas enormes", "with enormous wings")]),
    ("un robot antiguo", "an old rusty robot", "criatura", [("con un solo ojo luminoso", "with a single glowing eye"), ("cubierto de musgo", "covered in moss")]),
    ("una sirena", "a mermaid", "criatura", [("de cola iridiscente", "with an iridescent tail"), ("de pelo largo", "with long flowing hair")]),
    ("un hada", "a tiny fairy", "criatura", [("de alas transparentes", "with translucent wings")]),
    ("una anciana", "an elderly woman", "persona", [("de sonrisa amable", "with a kind smile"), ("con arrugas profundas", "with deep wrinkles"), ("con un chal tejido", "wearing a knitted shawl")]),
    ("un anciano pescador", "an elderly fisherman", "persona", [("de barba blanca", "with a thick white beard"), ("con impermeable amarillo", "in a yellow raincoat")]),
    ("una joven", "a young woman", "persona", [("de pelo rojo", "with red hair"), ("con pecas", "with freckles"), ("con chaqueta de cuero", "in a leather jacket")]),
    ("un niño", "a little boy", "persona", [("con un globo", "holding a balloon"), ("con botas de lluvia", "in rain boots")]),
    ("un astronauta", "an astronaut", "persona", [("con el casco reflejando la luna", "with the helmet reflecting the moon"), ("con traje desgastado", "in a worn spacesuit")]),
    ("un samurái", "a samurai", "persona", [("con armadura negra", "in black lacquered armor"), ("con una katana", "holding a katana")]),
    ("una bailarina", "a ballerina", "persona", [("con tutú blanco", "in a white tutu"), ("en puntas", "on pointe")]),
    ("un músico callejero", "a street musician", "persona", [("con una guitarra vieja", "playing an old guitar"), ("con sombrero de ala ancha", "in a wide-brimmed hat")]),
    ("un cocinero", "a chef", "persona", [("con delantal blanco", "in a white apron"), ("concentrado", "with a focused expression")]),
    ("una detective", "a detective", "persona", [("con gabardina", "in a trench coat"), ("con sombrero fedora", "wearing a fedora")]),
    ("un mago", "a wizard", "persona", [("de barba larga", "with a long beard"), ("con un bastón brillante", "holding a glowing staff")]),
    ("una guerrera elfa", "an elven warrior", "persona", [("con arco de madera", "with a wooden bow"), ("de ojos plateados", "with silver eyes")]),
    ("un faro", "a lighthouse", "lugar", [("de piedra blanca", "made of white stone"), ("sobre un acantilado", "on a rocky cliff")]),
    ("una casa de madera", "a small wooden cabin", "lugar", [("con chimenea humeante", "with smoke rising from the chimney")]),
    ("un castillo", "a medieval castle", "lugar", [("entre las nubes", "among the clouds"), ("en ruinas", "in ruins")]),
    ("una ciudad futurista", "a futuristic city", "lugar", [("con rascacielos de cristal", "with glass skyscrapers"), ("con coches voladores", "with flying cars")]),
    ("un mercado nocturno", "a night market", "lugar", [("lleno de faroles", "full of paper lanterns"), ("con puestos de comida", "with food stalls")]),
    ("un bosque", "a dense forest", "lugar", [("de árboles gigantes", "with giant ancient trees"), ("con luciérnagas", "full of fireflies")]),
    ("una montaña nevada", "a snow-covered mountain", "lugar", [("al amanecer", "at sunrise")]),
    ("un jardín japonés", "a Japanese garden", "lugar", [("con un puente de madera", "with a wooden bridge"), ("con cerezos en flor", "with cherry blossoms")]),
    ("una biblioteca", "an old library", "lugar", [("con estantes infinitos", "with endless shelves"), ("con escaleras de caracol", "with spiral staircases")]),
    ("una cafetería", "a cozy coffee shop", "lugar", [("con ventanales empañados", "with fogged windows")]),
    ("una nave espacial", "a spaceship", "objeto", [("de casco metálico", "with a sleek metal hull"), ("aterrizando", "landing")]),
    ("una taza de café", "a steaming cup of coffee", "objeto", [("sobre una mesa de madera", "on a wooden table"), ("con vapor", "with rising steam")]),
    ("un reloj antiguo", "an antique pocket watch", "objeto", [("de latón", "made of brass"), ("abierto", "opened to show the gears")]),
    ("una moto clásica", "a vintage motorcycle", "objeto", [("cromada", "with polished chrome"), ("cubierta de polvo", "covered in dust")]),
    ("un coche deportivo", "a sports car", "objeto", [("rojo", "in glossy red paint"), ("mojado por la lluvia", "wet from the rain")]),
    ("un ramo de flores", "a bouquet of wildflowers", "objeto", [("en un jarrón de cristal", "in a glass vase")]),
    ("un tazón de ramen", "a bowl of ramen", "objeto", [("con huevo y cebollín", "with a soft egg and scallions"), ("humeante", "steaming")]),
    ("una torta de chocolate", "a chocolate layer cake", "objeto", [("con frutillas", "topped with fresh strawberries")]),
    ("un violín", "a violin", "objeto", [("sobre un piano", "resting on a grand piano")]),
]

ACCIONES = {  # por tipo: (es, en)
    "animal": [("durmiendo", "sleeping peacefully"), ("corriendo", "running"), ("mirando por la ventana", "looking out of a window"), ("saltando", "leaping mid-air"), ("bebiendo agua", "drinking water"), ("sentado", "sitting calmly")],
    "criatura": [("volando", "flying"), ("rugiendo", "roaring"), ("descansando", "resting"), ("vigilando", "keeping watch"), ("emergiendo del agua", "emerging from the water")],
    "persona": [("leyendo un libro", "reading a book"), ("caminando", "walking"), ("mirando al horizonte", "gazing at the horizon"), ("riendo", "laughing"), ("sentado", "sitting"), ("corriendo", "running"), ("bailando", "dancing"), ("trabajando", "working"), ("escribiendo una carta", "writing a letter")],
    "objeto": [("sobre una mesa", "resting on a table"), ("flotando", "floating in mid-air"), ("bajo la lluvia", "standing in the rain"), ("iluminado desde atrás", "backlit"), ("en primer plano", "in extreme close-up")],
    "lugar": [("al atardecer", "at sunset"), ("bajo la lluvia", "under heavy rain"), ("cubierto de niebla", "wrapped in fog"), ("de noche", "at night"), ("en otoño", "in autumn"), ("en invierno", "in winter"), ("en primavera", "in spring")],
}

ENTORNOS = [("en un bosque encantado", "in an enchanted forest"), ("en la playa", "on a quiet beach"), ("en una calle lluviosa", "on a rainy city street"), ("en el desierto", "in a vast desert"),
            ("en una cueva de cristales", "in a crystal cave"), ("en el espacio", "in deep space"), ("en un campo de lavanda", "in a lavender field"), ("en una estación de tren", "in an old train station"),
            ("en una aldea medieval", "in a medieval village"), ("sobre un lago helado", "on a frozen lake"), ("en el fondo del mar", "on the ocean floor"), ("en un taller", "in a cluttered workshop"),
            ("en una azotea", "on a city rooftop"), ("en un invernadero", "inside a glass greenhouse"), ("en una cocina rústica", "in a rustic kitchen"), ("en un templo antiguo", "in an ancient temple"),
            ("en un pueblo costero", "in a seaside village"), ("entre montañas", "among tall mountains"), ("en la selva", "in a lush jungle"), ("en una ciudad cyberpunk", "in a neon-lit cyberpunk city"),
            ("junto a una fogata", "beside a campfire"), ("en un campo de trigo", "in a golden wheat field"), ("en un pasillo vacío", "in an empty corridor"), ("en un viejo teatro", "in an abandoned theater"),
            ("en una isla flotante", "on a floating island"), ("en un tren en movimiento", "on a moving train"), ("en un barrio de Tokio", "in a Tokyo back alley"), ("en un bazar", "in a busy bazaar")]

LUCES = [("luz dorada del atardecer", "warm golden hour light"), ("luz suave y difusa", "soft diffused light"), ("luz de neón", "colorful neon glow"), ("contraluz", "dramatic backlighting"),
         ("luz de luna", "cold moonlight"), ("niebla y rayos de luz", "volumetric light rays through fog"), ("luz de velas", "warm candlelight"), ("cielo nublado", "overcast sky"),
         ("luz de estudio", "soft studio lighting"), ("iluminación cinematográfica", "cinematic lighting"), ("luz del amanecer", "pale sunrise light"), ("sombras marcadas", "high contrast shadows")]

ESTILOS_FOTO = [("fotografía realista", "a photorealistic photograph"), ("foto de retrato", "a professional portrait photo"), ("foto analógica", "an analog film photograph"),
                ("fotografía documental", "a candid documentary photograph"), ("foto macro", "a macro photograph")]
ESTILOS_ARTE = [("acuarela", "a delicate watercolor painting"), ("óleo", "a rich oil painting"), ("ilustración digital", "a detailed digital illustration"), ("anime", "an anime-style illustration"),
                ("arte conceptual", "a concept art piece"), ("pixel art", "a pixel art scene"), ("render 3D", "a polished 3D render"), ("cómic", "a comic book illustration"),
                ("estilo Ghibli", "a hand-painted scene in the style of Studio Ghibli"), ("boceto a lápiz", "a pencil sketch"), ("arte vectorial plano", "a flat vector illustration"),
                ("cyberpunk", "a cyberpunk digital artwork"), ("fantasía épica", "an epic fantasy painting"), ("minimalista", "a minimalist illustration")]

CAMARAS = [("primer plano", "close-up shot"), ("plano general", "wide establishing shot"), ("desde abajo", "low angle shot"), ("vista aérea", "aerial view"), ("lente de 85mm", "85mm portrait lens, shallow depth of field"),
           ("gran angular", "wide-angle lens"), ("macro", "macro lens"), ("profundidad de campo corta", "shallow depth of field"), ("plano cenital", "top-down view")]
AMBIENTES = [("melancólico", "melancholic mood"), ("alegre", "joyful atmosphere"), ("misterioso", "mysterious atmosphere"), ("sereno", "serene and calm mood"), ("épico", "epic and grand mood"),
             ("nostálgico", "nostalgic feeling"), ("inquietante", "eerie atmosphere"), ("acogedor", "cozy and warm feeling"), ("onírico", "dreamlike atmosphere")]
PALETAS = [("tonos cálidos", "warm amber and orange tones"), ("tonos fríos", "cool blue and teal palette"), ("colores pastel", "soft pastel colors"), ("blanco y negro", "black and white, high contrast"),
           ("colores saturados", "vivid saturated colors"), ("tonos tierra", "earthy brown and green tones"), ("púrpura y rosa", "purple and pink hues"), ("paleta apagada", "muted desaturated palette")]
CALIDAD_NL = ["highly detailed", "sharp focus", "fine textures", "intricate details", "crisp details"]

TEXTOS = [("MORNING BREW", "Fresh roasted daily", "cartel de cafetería retro", "a vintage coffee shop poster"), ("OPEN", "24 hours", "letrero de neón de un local", "a neon sign above a shop door"),
          ("LA LUNA", "Pizzería artesanal", "fachada de pizzería", "the storefront of a small pizzeria"), ("SALE", "50% OFF", "cartel de rebajas", "a bright sale banner"),
          ("Happy Birthday Ana", "", "tarjeta de cumpleaños", "a birthday card"), ("STORM CHASERS", "Live tonight", "afiche de concierto", "a concert poster"),
          ("Café del Mar", "", "pizarra de un café", "a chalkboard menu sign"), ("BOOKS & TEA", "Since 1987", "portada de una librería", "a bookstore shopfront sign"),
          ("GALAXY RUN", "", "portada de un videojuego", "a video game cover"), ("Welcome Home", "", "cartel de bienvenida", "a handwritten welcome sign"),
          ("EL JARDÍN SECRETO", "", "portada de un libro infantil", "a children's book cover"), ("Zen Spa", "Relax & Renew", "cartel de un spa", "a minimalist spa poster")]

# plantillas de pedido (español informal): {x} = descripción, {m} = modelo
PEDIDOS_ES = ["prompt para {m}: {x}", "hazme un prompt para {m} de {x}", "necesito un prompt de {m}: {x}", "quiero generar con {m} {x}", "{m}: {x}", "genera un prompt para {m}. {x}",
              "ayudame con un prompt pa {m}, {x}", "para {m} -> {x}", "prompt {m} {x}", "me haces un prompt en {m} de {x}", "escribe el prompt para {m}: {x}", "creame un prompt {m}: {x}"]
PEDIDOS_EN = ["write a prompt for {m}: {x}", "{m} prompt: {x}", "make me a {m} prompt of {x}", "prompt for {m} -> {x}", "i need a prompt for {m}. {x}", "generate a {m} prompt: {x}"]
PEDIDOS_SIN_MODELO = ["prompt de {x}", "hazme un prompt: {x}", "quiero una imagen de {x}", "necesito un prompt para {x}", "genera un prompt de {x}", "dame un prompt para {x}", "write a prompt for {x}", "una imagen de {x}"]
PREGUNTA_MODELO = ["¿Para qué modelo lo quieres: Flux, Z-Image Turbo o Base, Qwen-Image, SDXL, SD 1.5, Pony o Illustrious? Cada uno se escribe distinto.",
                   "Dime para qué modelo es (Flux, Z-Image, Qwen-Image, SDXL, SD 1.5, Pony o Illustrious) y te lo escribo en su estilo.",
                   "¿Qué modelo vas a usar: Flux, Z-Image Turbo/Base, Qwen-Image, SDXL, SD 1.5, Pony o Illustrious? El formato cambia de uno a otro."]


# --- texto dentro de la imagen: variedad suficiente para que el experto aprenda a COPIAR lo que se pide, no a recordar 12 carteles ---
OBJETOS_TEXTO = [("cartel de neón", "a neon sign"), ("cartel de bienvenida", "a handwritten welcome sign"), ("afiche de concierto", "a concert poster"), ("portada de un libro", "a book cover"),
                 ("letrero de una tienda", "a shop sign"), ("pizarra de un café", "a chalkboard menu sign"), ("camiseta", "a t-shirt design"), ("taza de cerámica", "a ceramic mug print"),
                 ("cartel publicitario", "a roadside billboard"), ("etiqueta de un frasco", "a product label"), ("portada de un videojuego", "a video game cover"), ("tarjeta de invitación", "an invitation card"),
                 ("logo minimalista", "a minimalist logo"), ("fachada de un local", "a storefront facade"), ("cartel de película", "a movie poster"), ("menú de restaurante", "a restaurant menu"), ("pegatina", "a sticker design")]
PALABRAS_TEXTO = ["LUNA", "CAFÉ", "MORNING", "BREW", "ROCKET", "SOL", "MAR", "CASA", "STUDIO", "GALAXY", "DREAM", "FOREST", "JARDÍN", "NOCHE", "ROAD", "KITCHEN", "BOOKS", "TEA", "SPA", "PIZZA", "SUSHI", "BAKERY",
                  "FLORES", "TACOS", "RADIO", "CINE", "FIESTA", "WINTER", "SUMMER", "ARTE", "VINO", "TERRA", "AURORA", "NOVA", "PIXEL", "ZEN", "OCÉANO", "CIUDAD", "HARVEST", "ELECTRIC", "VELVET", "MONTAÑA", "DRAGÓN"]
SUBTITULOS = ["Fresh daily", "Open 24 hours", "Desde 1987", "Since 1987", "Live tonight", "Gran apertura", "Grand opening", "50% OFF", "Ven y descubre", "Handmade with love", "Hecho a mano", "Welcome", "Bienvenidos",
              "Est. 2010", "Tonight only", "Solo hoy", "New collection", "Nueva colección", "Free entry", "Entrada libre", "Best in town", "Tradición y sabor"]


def texto_aleatorio(rng):
    """(título, subtítulo, objeto es, objeto en): textos y objetos combinados al azar, con mayúsculas, títulos y nombres compuestos."""
    n = rng.choice([1, 1, 2, 2, 3])
    palabras = rng.sample(PALABRAS_TEXTO, n)
    titulo = " ".join(palabras) if rng.random() < 0.6 else " ".join(w.capitalize() for w in palabras)
    if rng.random() < 0.15:
        titulo = rng.choice(["Happy Birthday ", "Feliz cumpleaños ", "Welcome to ", "Bienvenidos a "]) + palabras[0].capitalize()
    sub = rng.choice(SUBTITULOS) if rng.random() < 0.55 else ""
    es, en = rng.choice(OBJETOS_TEXTO)
    return (titulo, sub, es, en)

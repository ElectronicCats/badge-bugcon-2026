# Herramientas de computadora para tu Badge · BugCON 2026

Esta guía explica cómo usar los **programas de computadora** del Badge de
**BugCON 2026**. Con ellos puedes personalizar tu Badge, guardar tu álbum,
cargar controles remotos y mucho más, todo desde tu computadora.

**No los necesitas para el uso diario.** Todo lo esencial del Badge se hace
con sus botones. Para lo básico de la computadora (tu estampa, tus imágenes
y tu álbum) también existe el **configurador**: una página que se abre en el
navegador y es más sencilla. Estas herramientas son para quien quiera ir un
paso más allá.

> ¿Primera vez con tu Badge? Empieza por la
> [guía de uso del Badge](../README.md).

## Contenido

1. [¿Qué puedes hacer?](#qué-puedes-hacer)
2. [Palabras que conviene conocer](#palabras-que-conviene-conocer)
3. [Antes de empezar (una sola vez)](#antes-de-empezar-una-sola-vez)
4. [Conecta tu Badge](#conecta-tu-badge)
5. [Tu primer comando: comprobar la conexión](#tu-primer-comando-comprobar-la-conexión)
6. [Poner la hora](#poner-la-hora)
7. [Personalizar tu estampa](#personalizar-tu-estampa)
8. [Imágenes para el Marco](#imágenes-para-el-marco)
9. [Guardar una copia de tu álbum](#guardar-una-copia-de-tu-álbum)
10. [Control remoto: archivos de Flipper Zero](#control-remoto-archivos-de-flipper-zero)
11. [Tomar una foto de la pantalla](#tomar-una-foto-de-la-pantalla)
12. [El Badge en tu escritorio](#el-badge-en-tu-escritorio)
13. [Entregar la flag de un reto](#entregar-la-flag-de-un-reto)
14. [Si algo no funciona](#si-algo-no-funciona)

---

## ¿Qué puedes hacer?

| Quiero… | Programa |
|---|---|
| Ver el dorsal y el avance de mi álbum | `badge_usb.py info` |
| Poner la hora en el Badge | `badge_usb.py time` |
| Cambiar mi apodo, villa, posición o estadísticas | `badge_usb.py nick` y `badge_usb.py card` |
| Poner una imagen en mi estampa | `badge_usb.py avatar` |
| Guardar imágenes para el Marco | `badge_usb.py upload` |
| Guardar una copia de mi álbum | `badge_usb.py album` |
| Cargar un control remoto de Flipper Zero | `ir_import.py import` |
| Guardar un control remoto en un archivo | `ir_import.py export` |
| Tomar una foto de la pantalla | `ui_shot.py` |
| Usar las luces como aviso en mi escritorio | `badge_usb.py led` |
| Ver mi consumo de inteligencia artificial | `ai_tokens.py` |
| Entregar la respuesta de un reto | `badge_usb.py raw "FLAG …"` |

Los demás programas de esta carpeta son para el equipo de organización y de
producción. No los necesitas.

## Palabras que conviene conocer

| Palabra | Significado |
|---|---|
| **Programa** o **script** | Un archivo con instrucciones que la computadora sigue por ti. Aquí terminan en `.py`. |
| **Python** | El lenguaje en que están escritos estos programas. Hay que instalarlo una vez para poder usarlos. |
| **Terminal** | Una ventana donde escribes órdenes a la computadora en lugar de usar el ratón. |
| **Comando** | Una orden que escribes en la terminal y confirmas con Enter. |
| **Puerto** | El nombre que la computadora le da al Badge cuando lo conectas, como el número de una puerta. |
| **Cable de datos** | Un cable USB que pasa información, no solo energía. Algunos cables de cargador solo dan energía y no sirven aquí. |

## Antes de empezar (una sola vez)

### 1. Instala Python

- **Windows y macOS:** descarga Python 3 desde
  [python.org/downloads](https://www.python.org/downloads/) e instálalo. Se
  necesita la versión 3.9 o una más reciente. En Windows, marca la casilla
  **"Add Python to PATH"** durante la instalación.
- **Linux:** casi siempre ya viene instalado.

### 2. Descarga las herramientas

1. Entra a
   [github.com/ElectronicCats/badge-bugcon-2026](https://github.com/ElectronicCats/badge-bugcon-2026).
2. Presiona el botón verde **"Code"** y luego **"Download ZIP"**.
3. Descomprime el archivo. Obtendrás una carpeta llamada
   `badge-bugcon-2026` (a veces termina en `-main`).

### 3. Abre una terminal en esa carpeta

- **Windows:** abre la carpeta `badge-bugcon-2026`, haz clic en la barra de
  dirección de arriba, escribe `cmd` y presiona Enter.
- **macOS:** clic derecho sobre la carpeta › **Servicios** › **Nueva
  terminal en la carpeta**.
- **Linux:** clic derecho dentro de la carpeta › **Abrir en una terminal**.

**Todos los comandos de esta guía se escriben en esa terminal**, dentro de la
carpeta `badge-bugcon-2026`.

### 4. Instala el complemento para hablar con el Badge

Los programas necesitan un complemento llamado **pyserial**. Escribe en la
terminal:

- **Windows:** `py -m pip install pyserial`
- **macOS y Linux:** `python3 -m pip install pyserial`

Si en Linux te dice que no puede instalarlo, usa el instalador de tu sistema,
por ejemplo `sudo apt install python3-serial`.

### 5. Solo en Linux: permiso para usar el Badge

Escribe esto una vez y luego cierra y vuelve a abrir tu sesión:

```
sudo usermod -aG dialout $USER
```

### Cómo leer los ejemplos

Los ejemplos de esta guía usan la forma de macOS y Linux:

```
python3 tools/badge_usb.py info
```

**En Windows**, cambia dos cosas: escribe `py` en lugar de `python3` y usa
`\` en lugar de `/`:

```
py tools\badge_usb.py -p COM3 info
```

El `-p COM3` es el puerto de tu Badge; en la siguiente sección se explica
cómo encontrarlo.

## Conecta tu Badge

1. **Enciende el Badge** con el interruptor **SW1**. Aunque esté conectado
   por USB, el interruptor debe estar encendido.
2. Conéctalo a la computadora con un **cable de datos**.
3. **Cierra el configurador** si lo tienes abierto en el navegador. Solo un
   programa a la vez puede hablar con el Badge.

### ¿Cuál es el puerto de mi Badge?

| Sistema | Cómo encontrarlo | Ejemplo |
|---|---|---|
| **Linux** | Casi siempre es el primero. No necesitas escribirlo. | `/dev/ttyACM0` |
| **Windows** | Abre el **Administrador de dispositivos** › **Puertos (COM y LPT)**. Busca el que aparece al conectar el Badge. | `COM3` |
| **macOS** | En la terminal escribe `ls /dev/cu.usbmodem*`. | `/dev/cu.usbmodem1101` |

Si tu puerto no es `/dev/ttyACM0`, agrégalo a cada comando con `-p`, justo
después del nombre del programa:

```
python3 tools/badge_usb.py -p /dev/cu.usbmodem1101 info
```

## Tu primer comando: comprobar la conexión

Escribe:

```
python3 tools/badge_usb.py info
```

Si todo va bien, verás algo parecido a esto:

```
fw=1.0.0
no=127
w=200
h=200
album=25
total=400
slots=4
current=-1
used=1000
```

Lo importante:

- **no** es tu **dorsal**, el número único de tu Badge.
- **album** y **total** son tu avance: en el ejemplo, 25 de 400 estampas.
- **used** dice qué espacios de imagen del Marco están ocupados: un `1` por
  espacio con imagen, empezando por el 0.
- **fw** es la versión del programa interno del Badge.

Las demás líneas puedes ignorarlas.

¿Salió un error? Revisa [Si algo no funciona](#si-algo-no-funciona).

## Poner la hora

El Badge olvida la hora cada vez que lo apagas con SW1. Sin hora, la Agenda
no puede marcar qué charla es la **"Próxima"** y el Reloj muestra `--:--`.
Para ponerle la hora de tu computadora:

```
python3 tools/badge_usb.py time
```

Verás `OK`. La hora aparece en la barra de arriba del Badge.

## Personalizar tu estampa

Es lo mismo que hacer en **Menú › Mi Estampa**, pero escribiendo desde tu
teclado. Los cambios se ven en tu gafete de inmediato.

### Tu apodo

```
python3 tools/badge_usb.py nick "Gol de Oro"
```

- Pon el apodo **entre comillas** si lleva espacios.
- Caben hasta 16 letras. Las letras con acento y la ñ ocupan el lugar de
  dos. Si te pasas, el Badge corta lo que sobra.

### Villa, posición, estadísticas y handle

Usa `card` y escribe **solo lo que quieras cambiar**. Lo demás se queda
igual.

```
python3 tools/badge_usb.py card --team 2 --pos 4
```

**`--team`: tu villa.** Escribe el número de la tabla.

| Número | Villa | Número | Villa |
|---|---|---|---|
| 0 | Hardware | 6 | WoSec |
| 1 | RF | 7 | APT |
| 2 | Rookie | 8 | Chaviza |
| 3 | OT | 9 | Nación Hacker |
| 4 | Payments | 10 | Live Hacking |
| 5 | BugBounty | -1 | Sin villa |

**`--pos`: tu posición.**

| Número | Posición |
|---|---|
| 0 | Portero |
| 1 | Defensa |
| 2 | Medio |
| 3 | Delantero |
| 4 | Pentester |
| -1 | Sin posición |

**`--stats`: tus estadísticas.** Son cuatro números separados por comas, sin
espacios, en este orden: ataque, defensa, hack y suerte.

```
python3 tools/badge_usb.py card --stats 60,40,70,30
```

Cada una va de 0 a 99 y entre las cuatro suman como máximo 200. Si te pasas,
el Badge no hace el cambio.

**`--handle`: tu usuario de redes sociales.** Caben hasta 20 letras.

```
python3 tools/badge_usb.py card --handle @mi_usuario
```

> **Importante:** si guardas tu handle de esta forma, **viaja con tu
> estampa** en cada intercambio. Para quitarlo, escribe
> `card --handle ""`.

### Tu imagen (avatar)

Tu estampa puede llevar una imagen en blanco y negro de **96 × 96** puntos.
Necesitas un archivo `.pbm` de ese tamaño (abajo se explica cómo hacerlo):

```
python3 tools/badge_usb.py avatar cara.pbm
```

Tu imagen solo se ve en tu Badge. No viaja a otros Badges al intercambiar.

## Imágenes para el Marco

En **Menú › Herramientas › Marco**, tu Badge muestra imágenes a pantalla
completa. Tiene **4 espacios** para guardarlas, numerados del **0 al 3**.

### Guardar una imagen

```
python3 tools/badge_usb.py upload 0 mi_foto.pbm
```

Esto guarda la imagen en el espacio 0 y la muestra en la pantalla. La imagen
debe medir **200 × 200** puntos.

Otras acciones:

| Comando | Qué hace |
|---|---|
| `show 1` | Muestra la imagen del espacio 1. |
| `read 1 -o copia.pbm` | Guarda en tu computadora una copia de la imagen del espacio 1. |

### Cómo preparar una imagen `.pbm`

Un archivo `.pbm` es una imagen de solo dos colores: blanco y negro. Puedes
crearlo gratis con **GIMP**:

1. Abre tu imagen en GIMP.
2. **Imagen › Escalar la imagen:** pon 200 × 200 (o 96 × 96 para el avatar).
3. **Imagen › Modo › Indexado:** elige **"Usar paleta en blanco y negro
   (1 bit)"**.
4. **Archivo › Exportar como:** ponle un nombre que termine en `.pbm`, por
   ejemplo `mi_foto.pbm`, y elige el formato **"Raw"**.

> **Más fácil:** el configurador del navegador convierte cualquier foto y te
> muestra cómo se verá antes de guardarla.

## Guardar una copia de tu álbum

Guarda en tu computadora tu estampa y todas las de tu álbum:

```
python3 tools/badge_usb.py album -o mi_album.json
```

Verás cuántas estampas se guardaron. Para verlas, abre la página del álbum
del configurador (`album/index.html`) y arrastra ahí el archivo. Desde esa
página también puedes descargar los contactos de quienes compartieron su
handle.

> **Cuida este archivo.** Tiene los apodos y los handles de las personas con
> quienes intercambiaste. No lo publiques.

## Control remoto: archivos de Flipper Zero

El **Flipper Zero** es un aparato muy popular entre aficionados a la
electrónica. Sus controles remotos se guardan en archivos `.ir`, y en
Internet hay colecciones con miles de ellos. Tu Badge puede usarlos en
**Menú › Infrarrojo › Control remoto**.

### Cargar un control

1. **Prueba primero, sin tocar el Badge.** Así ves qué botones se cargarían:

   ```
   python3 tools/ir_import.py import TV_Sala.ir --dry-run
   ```

2. **Cárgalo de verdad:**

   ```
   python3 tools/ir_import.py import TV_Sala.ir --brand "TV Sala"
   ```

   - `--brand` es el nombre con el que verás la marca en el Badge. Si no lo
     pones, se usa el nombre del archivo.
   - Al final verás el número de la marca, por ejemplo
     `Marca 'TV Sala' = 12`. Anótalo: sirve para exportarla después.

3. En el Badge, abre **Control remoto**. Tu marca nueva aparece en la lista.

El Badge tiene **16 botones** por control: Encender, Vol+, Vol-, Silencio,
Canal+, Canal-, Entrada, Menú, Arriba, Abajo, Izquierda, Derecha, OK, Atrás,
Inicio y Play/Pausa. El programa reconoce los nombres más comunes del
archivo, como "Power" o "Vol_up", y los pone en su lugar.

Junto a cada botón verás un resultado:

- **cargado:** el botón ya funciona en tu Badge.
- **omitido:** ese botón no tiene lugar en el Badge o su señal no es
  compatible. El resto sí se carga.
- **aviso:** el botón se cargó, pero quizá no funcione igual que con el
  control original.

Puedes tener hasta **8 marcas propias**. Para borrar una, hazlo desde el
Badge.

### Guardar un control en un archivo

Así puedes respaldar los botones que tu Badge aprendió o compartirlos con un
Flipper Zero:

```
python3 tools/ir_import.py export 12 -o tv_sala.ir
```

El número es el de la marca. Las 12 marcas que ya vienen en el Badge van del
**0 al 11**, en el orden de la lista. Tus marcas propias empiezan en el **12**.

## Tomar una foto de la pantalla

Guarda en tu computadora una imagen de lo que muestra la pantalla del Badge:

```
python3 tools/ui_shot.py -o mi_pantalla.png
```

También puede presionar botones por ti antes de tomar la foto. Escribe los
botones entre comillas, separados por espacios: `up`, `down`, `left`,
`right`, `a` y `b`.

```
python3 tools/ui_shot.py -o menu.png --keys "a right"
```

En el ejemplo, abre el menú, avanza una sección y toma la foto.

## El Badge en tu escritorio

Después de BugCON 2026, tu Badge puede acompañarte en tu escritorio,
conectado a la computadora. Abre **Menú › Herramientas** y cambia de vista
con **izquierda / derecha**.

### Luces de aviso

Pinta las 6 luces del Badge del color que quieras. Es útil como semáforo: por
ejemplo, rojo cuando estás en una llamada y verde cuando estás libre.

```
python3 tools/badge_usb.py led ff0000
```

El color se escribe con 6 caracteres:

| Color | Escribe |
|---|---|
| Rojo | `ff0000` |
| Verde | `00ff00` |
| Azul | `0000ff` |
| Amarillo | `ffff00` |
| Blanco | `ffffff` |
| Apagar | `000000` |

Las luces se apagan solas al desconectar el cable.

### Tokens de IA: tu consumo de inteligencia artificial

Los asistentes de inteligencia artificial miden su uso en **tokens**. Un
token es un pedacito de texto, más o menos una sílaba. Este programa cuenta
los tokens que usaste hoy en tu computadora y los muestra en el Badge.

Funciona con **Claude Code** y **opencode**, si los usas en esa computadora.

1. Conecta el Badge.
2. Escribe:

   ```
   python3 tools/ai_tokens.py
   ```

   En Windows y macOS agrega tu puerto: `--puerto COM3`.
3. En el Badge abre **Menú › Herramientas** y ve a la vista **Tokens**.
4. Deja la terminal abierta. Cada 30 segundos el programa revisa si hay
   cifras nuevas y las envía.
5. Para detenerlo, presiona **Ctrl + C** en la terminal.

En el Badge verás:

- Los tokens de hoy, en grande, y el total de los últimos 7 días.
- Una página por programa o por modelo de IA. Cámbialas con **arriba /
  abajo**.
- **"Sin actualizar"** si pasan 10 minutos sin cifras nuevas: revisa que el
  programa siga corriendo.

**Ponte una meta diaria.** Con `--meta`, las luces del Badge se llenan
conforme te acercas a ella y se ponen en rojo al llegar. Presiona **A** para
encender o apagar las luces.

```
python3 tools/ai_tokens.py --meta 5M
```

`5M` son 5 millones de tokens; también puedes escribir `800k` para 800 mil.

Cosas que conviene saber:

- **Tus conversaciones no salen de tu computadora.** El programa solo lee
  cuántos tokens se usaron.
- Al conectarse, el programa también le pone la hora al Badge.
- Mientras corre, ningún otro programa ni el configurador pueden hablar con
  el Badge. Detenlo antes de usar otro.

## Entregar la flag de un reto

En **Menú › Retos**, cada etapa que superas te da una estampa de reto. Cuando
encuentres la respuesta secreta (la **flag**), entrégala así:

```
python3 tools/badge_usb.py raw "FLAG tu_flag_aquí"
```

| Respuesta | Qué significa |
|---|---|
| `OK 1`, `OK 2`… | ¡Correcta! Superaste esa etapa y ganas su estampa. |
| `ERR wrong` | La flag no es correcta. Revísala e intenta de nuevo. |
| `ERR locked` | Primero tienes que superar la etapa anterior. |

## Si algo no funciona

| Problema | Qué hacer |
|---|---|
| `python3` o `py` "no se reconoce" | Python no está instalado. En Windows, reinstálalo y marca **"Add Python to PATH"**. |
| `No module named 'serial'` | Falta el complemento. Repite el paso 4 de [Antes de empezar](#antes-de-empezar-una-sola-vez). |
| No encuentra el puerto o "could not open port" | Revisa que el Badge esté encendido con SW1 y que el cable sea de datos. Prueba otro cable o puerto USB. Revisa el nombre del puerto con `-p`. |
| "Permission denied" en Linux | Haz el paso 5 de [Antes de empezar](#antes-de-empezar-una-sola-vez) y vuelve a iniciar sesión. |
| "Resource busy" o el puerto está ocupado | Otro programa está usando el Badge. Cierra el configurador, detén `ai_tokens.py` con Ctrl + C y vuelve a intentar. |
| `error: timeout` | El Badge puede estar dormido. Presiona un botón y repite el comando. |
| `ERR badstats` | Tus estadísticas pasan de 99 o suman más de 200. |
| `ERR badteam` o `ERR badpos` | El número de villa o de posición no está en la tabla. |
| `ERR full` en Tokens | El Badge ya tiene 8 páginas. Presiona **RESET** en el Badge y vuelve a correr el programa. |
| La imagen "mide…; el badge espera 200x200" | Cambia el tamaño de tu imagen a 200 × 200 (o 96 × 96 para el avatar). |
| Después de usar estos programas, el configurador no recibe respuesta (Linux) | Escribe `stty -F /dev/ttyACM0 min 1` en la terminal y vuelve a conectar desde el configurador. |
| Sigues con dudas | Acércate a la mesa de soporte de BugCON 2026. |

---

Badge diseñado por [Electronic Cats](https://electroniccats.com) para BugCON
2026. Estas herramientas son software libre bajo la licencia GPL-3.0
([LICENSE](../LICENSE)).

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
| Entregar la respuesta de un reto | `badge_usb.py flag` |

Los demás programas de esta carpeta son para el equipo de organización y de
producción. No los necesitas (están listados en [Para el equipo](#para-el-equipo)).

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

### 4. Instala los complementos

Los programas necesitan tres complementos: **pyserial** (hablar con el
Badge), **Rich** (mensajes claros en la terminal) y **Pillow** (convertir tus
imágenes). Una sola orden los instala:

- **Windows:** `py -m pip install -r tools\requirements.txt`
- **macOS y Linux:** `python3 -m pip install -r tools/requirements.txt`

Si en Linux te dice `externally-managed-environment`, usa el instalador de tu
sistema:

```
sudo apt install python3-serial python3-rich python3-pil
```

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
py tools\badge_usb.py info
```

## Conecta tu Badge

1. **Enciende el Badge** con el interruptor **SW1**. Aunque esté conectado
   por USB, el interruptor debe estar encendido.
2. Conéctalo a la computadora con un **cable de datos**.
3. **Cierra el configurador** si lo tienes abierto en el navegador. Solo un
   programa a la vez puede hablar con el Badge.

### ¿Necesito escribir el puerto?

**Normalmente no.** Los programas buscan solos tu Badge en cualquier sistema.
Solo si tienes **dos Badges conectados** a la vez, te mostrarán la lista y
tendrás que elegir uno con `-p`, justo después del nombre del programa:

| Sistema | Cómo se ve el puerto | Dónde verlo |
|---|---|---|
| **Linux** | `/dev/ttyACM0` | Aparece en la lista que te muestra el programa. |
| **Windows** | `COM3` | **Administrador de dispositivos** › **Puertos (COM y LPT)**. |
| **macOS** | `/dev/cu.usbmodem1101` | En la terminal, `ls /dev/cu.usbmodem*`. |

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
  Dorsal    127
  Álbum     25/400  █░░░░░░░░░░░░░░░
  Marco     0 ocupado · 1 libre · 2 libre · 3 libre
  Versión   0.1.0
```

Lo importante:

- **Dorsal** es el número único de tu Badge.
- **Álbum** es tu avance: en el ejemplo, 25 de 400 estampas.
- **Marco** dice cuáles de los 4 espacios de imagen tienen algo guardado.
- **Versión** es la del programa interno del Badge.

Si necesitas los datos "en crudo" (`clave=valor`), usa `info --crudo`.

¿Salió un error? Revisa [Si algo no funciona](#si-algo-no-funciona).

## Poner la hora

El Badge olvida la hora cada vez que lo apagas con SW1. Sin hora, la Agenda
no puede marcar qué charla es la **"Próxima"** y el Reloj muestra `--:--`.
Para ponerle la hora de tu computadora:

```
python3 tools/badge_usb.py time
```

Verás algo como `Hora puesta: mié 20 nov 10:42.` El Badge no permite leer la
hora de vuelta: compruébala en la barra de arriba del Badge.

## Personalizar tu estampa

Es lo mismo que hacer en **Menú › Mi Estampa**, pero escribiendo desde tu
teclado. Los cambios se ven en tu gafete de inmediato.

### Tu apodo

```
python3 tools/badge_usb.py nick "Gol de Oro"
```

- Pon el apodo **entre comillas** si lleva espacios.
- Caben hasta 16 bytes: las letras normales ocupan 1, y las letras con
  acento y la ñ ocupan 2 (ocho «ñ» llenan el apodo). Si te pasas, el programa
  te lo dice y no cambia nada.

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
| 2 | Rookie | 8 | Nación Hacker |
| 3 | OT | 9 | Live Hacking |
| 4 | Payments | -1 | Sin villa |
| 5 | BugBounty | | |

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
el programa te dice por cuánto y no hace el cambio.

**`--handle`: tu usuario de redes sociales.** Caben hasta 20 bytes (la ñ y los acentos cuentan doble).

```
python3 tools/badge_usb.py card --handle @mi_usuario
```

Al terminar, el programa te muestra un resumen de tu estampa.

> **Importante:** si guardas tu handle de esta forma, **viaja con tu
> estampa** en cada intercambio. Para quitarlo, escribe
> `card --handle ""`.

### Tu imagen (avatar)

Tu estampa puede llevar una imagen en blanco y negro de **96 × 96** puntos.
Pásale cualquier imagen (PNG, JPG, GIF, BMP o WebP); el programa la convierte
solo. Mira cómo se verá en [Convertir tus imágenes](#convertir-tus-imágenes).

```
python3 tools/badge_usb.py avatar cara.png
```

Tu imagen solo se ve en tu Badge. No viaja a otros Badges al intercambiar.

## Imágenes para el Marco

En **Menú › Herramientas › Marco**, tu Badge muestra imágenes a pantalla
completa. Tiene **4 espacios** para guardarlas, numerados del **0 al 3**.

### Guardar una imagen

```
python3 tools/badge_usb.py upload 0 mi_foto.jpg
```

Esto convierte la foto, la guarda en el espacio 0, la muestra en la pantalla
y comprueba que quedó igual. Sirve cualquier imagen (PNG, JPG, GIF, BMP,
WebP) y de cualquier tamaño; las fotos del teléfono se enderezan solas.

Si el espacio ya tiene una imagen, el programa te pregunta antes de
reemplazarla, porque **no se puede recuperar**. Con `--si` lo reemplaza sin
preguntar.

Otras acciones:

| Comando | Qué hace |
|---|---|
| `show 1` | Muestra la imagen del espacio 1. |
| `read 1 -o copia.pbm` | Guarda en tu computadora una copia de la imagen del espacio 1. |

### Convertir tus imágenes

El Badge solo muestra **blanco y negro**. Para que una foto se vea bien, el
programa la ajusta a la pantalla (200 × 200 en el Marco, 96 × 96 en el
avatar), sube el contraste y simula los grises con puntitos (tramado).

**Mira el resultado sin tocar el Badge:**

```
python3 tools/badge_usb.py upload 0 mi_foto.jpg --vista vista.png --solo-vista
```

Abre `vista.png` para ver cómo quedará (se guarda al doble de tamaño).
`--solo-vista` evita enviar la imagen; si quitas esa opción, `--vista` guarda
la vista y además envía la imagen al Badge.

Opciones para afinar el resultado (valen también para `avatar`):

| Opción | Qué hace |
|---|---|
| `--ajuste contener` | Por omisión: la imagen se ve entera, con bandas blancas si no es cuadrada. |
| `--ajuste cubrir` | Llena toda la pantalla y recorta los bordes. |
| `--tramado umbral --umbral 128` | Sin puntitos: cada punto es blanco o negro según su brillo (0 a 255). Bueno para logos y dibujos. |
| `--invertir` | Cambia blanco por negro. |
| `--ampliar` | Agranda una imagen más chica que la pantalla (por omisión se queda de su tamaño, centrada). |

> **Alternativa:** el configurador del navegador también convierte fotos y
> te muestra cómo se verán.

## Guardar una copia de tu álbum

Guarda en tu computadora tu estampa y todas las de tu álbum:

```
python3 tools/badge_usb.py album -o mi_album.json
```

Verás cuántas estampas se guardaron. (En el configurador, el mismo archivo
sale del botón **Guardar álbum (.json)**.) Para verlas, abre la página del
álbum (`album/index.html`), pulsa **Abrir álbum…** y elige el archivo, o
arrástralo ahí. Desde esa página también puedes descargar los contactos
(**Descargar contactos (.vcf)**) de quienes compartieron su handle.

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
python3 tools/badge_usb.py led rojo
```

Escribe el nombre del color, o cualquier color con 6 caracteres hex (con o
sin `#`):

| Color | Escribe |
|---|---|
| Rojo | `rojo` (o `ff0000`) |
| Verde | `verde` (o `00ff00`) |
| Azul | `azul` (o `0000ff`) |
| Amarillo | `amarillo` (o `ffff00`) |
| Blanco | `blanco` (o `ffffff`) |
| Apagar | `apagar` (o `000000`) |

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

   Si tienes dos Badges conectados, elige uno con `--puerto`.
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
python3 tools/badge_usb.py flag "tu_flag_aquí"
```

| El programa dice | Qué significa |
|---|---|
| "¡Correcta! Superaste la etapa N…" | Ganas la estampa de esa etapa. |
| "La flag no es correcta…" | Revísala e intenta de nuevo. |
| "Primero tienes que superar la etapa anterior." | Hazlas en orden. |

## Si algo no funciona

Los programas explican el problema en español y casi siempre dicen qué hacer.
Los códigos con los que terminan: `0` bien · `1` el Badge rechazó el comando ·
`2` algo está mal escrito · `3` no hay conexión con el Badge.

| Problema | Qué hacer |
|---|---|
| `python3` o `py` "no se reconoce" | Python no está instalado. En Windows, reinstálalo y marca **"Add Python to PATH"**. |
| `No module named 'serial'`, `'rich'` o `'PIL'` | Faltan complementos. Repite el paso 4 de [Antes de empezar](#antes-de-empezar-una-sola-vez). |
| "No encuentro tu Badge" | Revisa que esté encendido con SW1, que el cable sea de datos y que el configurador esté cerrado. Prueba otro cable o puerto USB. |
| "Hay más de un Badge conectado" | Elige uno con `-p` y el puerto de la lista. |
| "No tienes permiso para usar…" (Linux) | Haz el paso 5 de [Antes de empezar](#antes-de-empezar-una-sola-vez) y vuelve a iniciar sesión. |
| "…está ocupado por otro programa" | Cierra el configurador, detén `ai_tokens.py` con Ctrl + C y vuelve a intentar. |
| "Ese puerto no es un Badge BugCON 2026" | El `-p` apunta a otro aparato. Quítalo para que se busque solo. |
| "El Badge no contesta" | Puede estar dormido: presiona un botón y repite el comando. |
| "El Badge no reconoce esa versión de estampa" | Tus herramientas son de otra versión que tu Badge. Descárgalas de nuevo. |
| "Apodo no válido" / "Handle no válido" | El apodo no puede ir vacío; el handle cabe en 20 bytes. |
| "Villa no válida" / "Posición no válida" | El número no está en las tablas de arriba. |
| "Estadísticas no válidas" | Cada una va de 0 a 99 y la suma, hasta 200. |
| "Hora no válida" | El reloj de tu computadora está mal. |
| "Ese espacio del Marco no existe / está vacío" | Los espacios van del 0 al 3. Mira cuáles tienen imagen con `info`. |
| "El Badge ya no tiene espacio" en Tokens | El Badge ya tiene 8 páginas. Presiona **RESET** en el Badge y vuelve a correr el programa. |
| "El Badge no pudo guardarlo en su memoria" | Repite el comando. Si persiste, acércate a la mesa de soporte. |
| La imagen "no se puede convertir" | Prueba con un PNG o JPG. Si es un `.pbm`, debe medir exactamente 200 × 200 (o 96 × 96). |
| Después de usar estos programas, el configurador no recibe respuesta (Linux) | Escribe `stty -F /dev/ttyACM0 min 1` en la terminal (cambia el puerto si es otro) y vuelve a conectar desde el configurador. |
| Sigues con dudas | Acércate a la mesa de soporte de BugCON 2026. |

## Para el equipo

Estos programas son del equipo de organización y de producción. No los
necesitas para usar tu Badge.

**Producción y organización**

- `provision.py`: flashea cada Badge, le asigna dorsal y llave, corre la QA y registra en CSV. Con `--villa V` (0..9) provisiona el badge maestro de esa villa (uno por villa): dorsal 901 + V y en su estampa el nombre de la villa y su pedazo del reto de villas (handle, de `secrets.json` del `--vestidor`).
- `identity.py`: referencia de las cuentas HMAC (llave de dispositivo, firma, token, flag); necesita la llave maestra.
- `verify_album.py`: verifica sin conexión un álbum exportado, con la llave maestra. La línea `villas: n/10 verificadas` dice cuántos maestros de villa tienen firma y token válidos; la especial "Gira de villas" solo es válida con 10/10.
- `challenges/generate.py`: genera la cadena de retos (privada hasta el evento).

**Generadores del firmware** (convierten arte y datos en código; leen y escriben
en `firmware/`, que vive en el repositorio del firmware y no en este; estos
scripts, salvo `embed_page.py`, `embed_gfx.py` y `package_web.py`, tampoco están en la
copia pública de las herramientas)

- `img2bitmap.py`: arte de `firmware/art` a `icons.cpp`.
- `villa_logos.py`: logos de las villas a arte de 1 bit.
- `fontgen.py`: fuentes PCF/PSF a fuentes del firmware.
- `agenda.py`: `agenda.csv` a `agenda.cpp`.
- `ir_codes.py`: base TV-Gone a C++.
- `embed_page.py`: página del Wi-Fi a `wifi_page.h` comprimida.
- `embed_gfx.py`: fuentes, escudos y textos del gafete al configurador web, para que su plantilla "Copa BugCon" sea la pantalla del badge.
- `package_web.py`: empaqueta el configurador en un `.zip` (lo usa la CI).
- `pc_stubs/Arduino.h`: para compilar en la PC las pruebas de C++.

**Pruebas en vivo** (necesitan un Badge conectado; no son pruebas de la PC)

- `fs_powercut.py`: 200 cortes de energía durante escrituras de la memoria.
- `ir_aim.py`: aciertos de infrarrojo entre dos Badges.
- `ui_walk.py`: recorre las pantallas y captura cada una.
- `sdr/sdr_host_live.py`, `sdr/sdr_rx_live.py`, `sdr/sdr_viewer_live.py`: pruebas del SDR.
- `sdr/esdr_wire_live.py <puerto>`: muestra en hexadecimal, byte por byte, lo que el Badge
  envía y recibe en los modos host y captura de ráfaga del SDR, para revisar el formato de cada paquete.

**Pruebas de la PC** (sin Badge): los `test_*.py` de esta carpeta y los
`sdr/test_*.c` (con su `Makefile`). Los `test_*_badge.py` necesitan un Badge
conectado. Con el repositorio del firmware se corren con
`for t in tools/test_*.py; do case $t in *_badge.py) continue;; esac; python3 "$t" || break; done`;
solo con este repositorio, con
`python3 -m unittest tools/test_verify_album.py tools/test_configurator.py`.

**Qué necesita el repositorio del firmware:** los generadores de arriba, el
`Makefile` y las pruebas `sdr/test_*.c`, y las pruebas que compilan el código del firmware con
`pc_stubs/` (`test_agenda`, `test_battery`, `test_captive_dns`, `test_cup_link`,
`test_game_engine`, `test_home_slots`, `test_img2bitmap`, `test_ir_codes`,
`test_ir_import`, `test_ir_remote`, `test_theme_list`, `test_token_store`,
`test_villa_logos`, `test_villa_tour`) no corren sin la carpeta `firmware/` y
tampoco están en la copia pública de las herramientas.
`test_configurator.py` omite sus comparaciones con el firmware cuando no
la encuentra. Todo lo demás funciona con solo este repositorio.

---

Badge diseñado por [Electronic Cats](https://electroniccats.com) para BugCON
2026. Estas herramientas son software libre bajo la licencia GPL-3.0
([LICENSE](../LICENSE)).

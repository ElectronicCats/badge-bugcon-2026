# Componentes de terceros

El firmware, las páginas web y las herramientas de este repositorio se
distribuyen bajo la GPL-3.0 (`LICENSE`). Código fuente:
<https://github.com/ElectronicCats/badge-bugcon-2026>.

El firmware que se graba en el badge incluye además el código de terceros de
esta lista. Todas sus licencias son compatibles con la GPL-3.0. Antes de
agregar una biblioteca, revisa que su licencia también lo sea, fija su versión
en la sección `libraries:` del perfil `badge` de `sketch.yaml` (o vendorízala)
y agrégala aquí.

## En el firmware

| Componente | Versión | Licencia | Para qué |
|---|---|---|---|
| [arduino-esp32](https://github.com/espressif/arduino-esp32) | 3.3.12 | LGPL-2.1-or-later | Core de Arduino: `Serial`, `SPI`, `Wire`, arranque |
| [ESP-IDF](https://github.com/espressif/esp-idf) | v5.5.5 | Apache-2.0 | Drivers, NVS, particiones, sueño, `esp_http_server`, `esp_netif`, bootloader |
| Bibliotecas binarias de Wi-Fi y PHY de ESP-IDF (`libnet80211`, `libpp`, `libphy`…) | v5.5.5 | Apache-2.0, **solo binario** | Radio del SoftAP. Espressif no publica su código fuente |
| [FreeRTOS](https://www.freertos.org/) (incluido en ESP-IDF) | V10.5.1 (SMP de ESP-IDF) | MIT | Tareas, colas y semáforos |
| [lwIP](https://savannah.nongnu.org/projects/lwip/) (incluido en ESP-IDF) | v5.5.5 | BSD-3-Clause | TCP/IP del SoftAP, DNS del portal cautivo |
| [Mbed TLS](https://github.com/Mbed-TLS/mbedtls) (incluido en ESP-IDF) | v5.5.5 | Apache-2.0 | SHA-256 y HMAC (identidad, retos) |
| [newlib](https://sourceware.org/newlib/) (toolchain de Espressif) | — | BSD y licencias similares ([COPYING.NEWLIB](https://sourceware.org/git/?p=newlib-cygwin.git;a=blob;f=COPYING.NEWLIB)) | Biblioteca de C |
| [esp_littlefs](https://github.com/joltwallet/esp_littlefs) (`joltwallet__littlefs`) | 1.22.3 | MIT | Sistema de archivos de la partición `littlefs` |
| [littlefs](https://github.com/littlefs-project/littlefs) (dentro de esp_littlefs) | — | BSD-3-Clause | Idem |
| [esp_qrcode](https://components.espressif.com/components/espressif/qrcode) (`espressif__qrcode`) | 0.1.0~2 | Apache-2.0 | Códigos QR (`src/gfx/qr.cpp`) |
| [QR Code generator library](https://www.nayuki.io/page/qr-code-generator-library) (qrcodegen, dentro de esp_qrcode) | — | MIT (texto abajo) | Idem |
| [ESPARGOS esp-sdr](https://github.com/ESPARGOS/esp-sdr) vía [Minino](https://github.com/ElectronicCats/Minino) (commit `4b6fc6b9`) | — | GPL-3.0-or-later | Protocolo de ráfaga del visor web, osmosdr, espectro en chip y empaquetado de I/Q (`src/services/sdr/`, sin cambios; encabezados SPDX conservados). Pruebas de host en `tools/sdr/` |
| [ESPARGOS esp-sdr](https://github.com/ESPARGOS/esp-sdr) (commit `a8eaac1`) | — | GPL-3.0-or-later | Secuencia de captura del MAC dump del ESP32-S3 (`main/targets/esp32s3/receiver.c`), reescrita en `src/services/sdr/sdr_rx.cpp`. Usa registros sin documentar y símbolos de `libphy.a` del core `esp32:esp32 3.3.12`: otro core puede cambiarlos |
| [Terminus Font](https://terminus-font.sourceforge.net/) | console-setup 1.226 | OFL-1.1 | `FONT_6X12` y `FONT_8X16B` … `FONT_16X32B`, convertidas por `tools/fontgen.py`. Aviso y licencia en `firmware/badge_bugcon_2026/src/gfx/fonts/LICENSE-OFL.txt` |
| X11 misc-fixed (`xfonts-base`) | — | Dominio público | `FONT_5X8` y `FONT_6X10` |

Las versiones de ESP-IDF y de sus componentes son las que trae el core fijado
en `sketch.yaml` (`tools/esp32s3-libs/3.3.12/versions.txt`). Los textos
completos de LGPL-2.1, Apache-2.0 y BSD-3-Clause están en
<https://spdx.org/licenses/>.

**Sobre LGPL-2.1 del core:** el código fuente del core corresponde a la
etiqueta `3.3.12` de arduino-esp32, y este repositorio basta para recompilar y
volver a enlazar el firmware completo (`firmware/README.md`).

## Logos de las villas (marcas de terceros)

Los logos de las villas del evento que se graban en el firmware
(`firmware/art/sprites/logo_*.png` y las versiones derivadas en
`firmware/art/villas/`) son marcas de sus respectivas comunidades. **No están
bajo GPL-3.0** ni bajo ninguna otra licencia de este repositorio: son propiedad
de cada comunidad y se usan con su permiso y el del evento para identificar a
cada villa. No se pueden reutilizar fuera de ese contexto sin autorización de
la comunidad correspondiente.

## Páginas web y herramientas

Las páginas de `web/` no cargan nada de terceros: todo va en el propio HTML.
Las herramientas de `tools/` usan, sin distribuirlas, `pyserial`
(BSD-3-Clause) y `esptool` (GPL-2.0-or-later).

## Texto de la licencia MIT de qrcodegen

```
QR Code generator library
Copyright (c) Project Nayuki. (MIT License)
https://www.nayuki.io/page/qr-code-generator-library

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:
- The above copyright notice and this permission notice shall be included in
  all copies or substantial portions of the Software.
- The Software is provided "as is", without warranty of any kind, express or
  implied, including but not limited to the warranties of merchantability,
  fitness for a particular purpose and noninfringement. In no event shall the
  authors or copyright holders be liable for any claim, damages or other
  liability, whether in an action of contract, tort or otherwise, arising from,
  out of or in connection with the Software or the use or other dealings in the
  Software.
```

## Texto de la licencia MIT de esp_littlefs y FreeRTOS

Mismos términos que el bloque anterior, con estos avisos:

```
Copyright (c) 2020 Brian Pugh (esp_littlefs)
Copyright (C) 2021 Amazon.com, Inc. or its affiliates (FreeRTOS)
```

# Badge BugCon 2026

Badge electrónico de BugCon 2026, diseñado por Electronic Cats: ESP32-S3,
e-paper de 1.54" (200×200), 6 LEDs RGB, enlace infrarrojo, acelerómetro y
3 pilas AAA. Los asistentes intercambian estampas por IR para llenar su
álbum, juegan penales, la Copa BugCon y futbolito, y resuelven retos.

## Estructura

```
.
├── firmware/            Firmware del badge (arduino-cli, core esp32:esp32)
│   ├── README.md        Arquitectura, compilación, consola, protocolo USB y módulos
│   ├── Badge_Bugcon_2026_conexiones.md   Conexiones del esquema (fuente de los pines)
│   ├── docs/            Guías (bring-up de la PCB, control remoto y TV-Gone)
│   ├── art/             Iconos y sprites fuente de la UI
│   ├── scripts/         bootstrap.sh, compile.sh, flash.sh
│   └── badge_bugcon_2026/   Sketch
├── tools/               Herramientas de PC (Python): cliente USB, provisión,
│                        verificación del álbum, generadores y pruebas
├── web/                 Páginas sin servidor: configurador USB, álbum y la
│                        página del teléfono que sirve el badge por Wi-Fi
├── hardware/            Proyecto KiCad 9 (esquema, PCB, footprints, KiBot)
├── .github/workflows/   CI: pre-commit, archivos de fabricación y el .zip del configurador
├── LICENSE              GPL-3.0
└── THIRD_PARTY.md       Componentes de terceros y sus licencias
```

## Inicio rápido

Firmware (detalles en [firmware/README.md](firmware/README.md)):

```bash
cd firmware
./scripts/bootstrap.sh     # una vez: arduino-cli y el core esp32:esp32
./scripts/compile.sh       # compila → firmware/build/
./scripts/flash.sh         # compila, carga y abre el monitor serie
```

Pruebas de PC (desde la raíz; requieren Python 3, `pyserial` y `g++`):

```bash
python3 -m unittest discover -s tools -p 'test_*.py'
```

Archivos generados que no se editan a mano (se regeneran con su herramienta):

| Archivo | Fuente | Herramienta |
|---|---|---|
| `firmware/badge_bugcon_2026/src/ui/icons.cpp` | `firmware/art/` | `tools/img2bitmap.py --all` |
| `firmware/badge_bugcon_2026/src/services/ir_codes.cpp` | la tabla de `tools/ir_codes.py` | `tools/ir_codes.py --all` |
| `firmware/badge_bugcon_2026/src/services/wifi_page.h` | `web/phone/index.html` | `tools/embed_page.py` |
| `firmware/badge_bugcon_2026/src/gfx/fonts/*.cpp` | fuentes bitmap (Terminus, misc-fixed) | `tools/fontgen.py` |

Los datos del reto N3 (`tools/challenges/`) son privados y no viven en este
repositorio.

## Calidad y CI

- **pre-commit** ([.pre-commit-config.yaml](.pre-commit-config.yaml)):
  clang-format, espacios al final, fin de archivo y mensajes de commit con
  [Conventional Commits](https://www.conventionalcommits.org/). Excluye
  `hardware/`. Localmente: `pre-commit install --hook-type pre-commit
  --hook-type commit-msg`.
- **Hardware**: en cada `push` y `pull_request`, KiBot corre DRC y ERC sobre
  el primer `.kicad_pcb` de `hardware/` y su `.kicad_sch`. Para desactivarlos,
  cambiar `run_erc`/`run_drc` en
  [hardware/electroniccats_sch.kibot.yaml](hardware/electroniccats_sch.kibot.yaml).
- **Release publicado**: se generan los archivos de fabricación y se adjunta
  `bugcon26-configurador.zip` (`tools/package_web.py`).

## Licencia

GPL-3.0 ([LICENSE](LICENSE)). Componentes de terceros en
[THIRD_PARTY.md](THIRD_PARTY.md).

## Maintainer

<a href="https://github.com/sponsors/ElectronicCats">
<img src="https://electroniccats.com/wp-content/uploads/2020/07/Badge_GHS.png" height="104" />
</a>

Electronic Cats invests time and resources providing this open source design,
please support Electronic Cats and open-source hardware by purchasing products
from Electronic Cats!

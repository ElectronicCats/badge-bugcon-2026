#!/usr/bin/env node
/*
 * album_shots.cjs — Capturas del álbum web para revisión humana (no se comparan).
 *
 * Estados: vacío, error, típico en "Todas" y en la villa con más estampas,
 * detalle y vista rápida del QR. Medidas: 1280×800, 1024×768 al 200 %
 * (ventana de 512×384 con escala 2) y 360×740. Los archivos son los sintéticos
 * de test_album_page.cjs.
 *
 * Uso: NODE_PATH=<carpeta>/node_modules node tools/album_shots.cjs <carpeta de salida> [html]
 */
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer-core");
const { CASES } = require("./test_album_page.cjs");

const out = process.argv[2];
const html = path.resolve(process.argv[3] || path.join(__dirname, "../web/album/index.html"));
if (!out) { console.error("falta la carpeta de salida"); process.exit(2); }
fs.mkdirSync(out, { recursive: true });

const SIZES = { "1280x800": [1280, 800, 1], "1024x768-200": [512, 384, 2], "360x740": [360, 740, 1] };
const open = async (page, [[name, bytes]]) => {
  await page.evaluate(async (n, b64) => {
    await openFile(new File([Uint8Array.from(atob(b64), c => c.charCodeAt(0))], n));
  }, name, bytes.toString("base64"));
};

(async () => {
  const browser = await puppeteer.launch({ executablePath: process.env.BROWSER || "/usr/bin/brave-browser", headless: true });
  try {
    for (const [size, [w, h, f]] of Object.entries(SIZES)) {
      const shot = async (state, file, setup) => {
        const page = await browser.newPage();
        await page.setViewport({ width: w, height: h, deviceScaleFactor: f });
        await page.goto("file://" + html + (typeof file === "string" ? file : ""));
        if (Array.isArray(file)) await open(page, file);
        if (setup) await setup(page);
        await page.screenshot({ path: path.join(out, `${state}_${size}.png`), fullPage: true });
        await page.close();
      };
      // la villa con más estampas (sin contar "Todas")
      const villa = page => page.evaluate(() => {
        const n = sections().map(s => s.items.length);
        const i = n.indexOf(Math.max(...n.slice(1)), 1);
        document.querySelectorAll('#tabs [role="tab"]')[i].click();
      });
      await shot("vacio", null);
      await shot("error", CASES["JSON roto"]);
      await shot("tipico-todas", CASES["típico .json"]);
      await shot("tipico-villa", CASES["típico .json"], villa);
      await shot("detalle", CASES["típico .json"], async page => {
        await villa(page);
        await page.evaluate(() => document.querySelector("#grid button").click());
      });
      await shot("qr", CASES["QR (mi dorsal no viene en el bitmap)"]);
    }
  } finally {
    await browser.close();
  }
  console.log(fs.readdirSync(out).length + " capturas en " + out);
})().catch(e => { console.error(e.stack || e.message); process.exit(1); });

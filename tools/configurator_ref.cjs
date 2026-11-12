#!/usr/bin/env node
/*
 * configurator_ref.cjs — Huellas SHA-256 de lo que genera el configurador
 * (web/configurator/index.html) para una estampa e imágenes fijas, sin badge.
 * Sirve para comprobar que un cambio en la página no altera la plantilla
 * "Copa BugCon", el avatar (payload de AVTR) ni la imagen 200x200 del slot.
 *
 * Abre la página por file:// en Brave headless con puppeteer-core. Las
 * imágenes se generan píxel a píxel en la página (sin archivos ni fuentes del
 * sistema), así que el resultado solo depende de la página y del navegador.
 *
 * Uso (puppeteer-core instalado con npm en otra carpeta):
 *   NODE_PATH=<carpeta>/node_modules node tools/configurator_ref.cjs [html]
 *   git show <commit>:web/configurator/index.html > /tmp/old.html
 *   NODE_PATH=... node tools/configurator_ref.cjs /tmp/old.html
 * Imprime un JSON {nombre: sha256}; dos corridas iguales = mismos bytes.
 */
const crypto = require("crypto");
const path = require("path");
const puppeteer = require("puppeteer-core");

const html = path.resolve(process.argv[2] ||
  path.join(__dirname, "../web/configurator/index.html"));
const BROWSER = process.env.BROWSER || "/usr/bin/brave-browser";

// Corre dentro de la página: usa las funciones y variables globales del script.
function pageRun() {
  const synth = (w, h) => {
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const ctx = c.getContext("2d"), img = ctx.createImageData(w, h);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4;
        img.data[i] = x * 255 / (w - 1);
        img.data[i + 1] = y * 255 / (h - 1);
        img.data[i + 2] = (x ^ y) & 255;
        img.data[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return c;
  };
  const out = {};
  const grab = (name, bits, w, h) => { out[name] = Array.from(packBits(bits, w, h)); };

  $("nick").value = "Referencia";
  $("team").value = 3;
  $("pos").value = 2;
  [60, 50, 40, 30].forEach((v, i) => { $("st" + i).value = v; });
  $("handleOn").checked = true;
  $("handle").value = "@ref";
  onCardEdit();
  grab("tpl_sin_avatar", tplBits, panel.w, panel.h);

  setTarget("avatar");
  setSource(synth(300, 200));
  render();
  grab("avtr_payload", avatarBits, AVATAR_W, AVATAR_H);
  grab("tpl_con_avatar", tplBits, panel.w, panel.h);

  setTarget("slot");
  setSource(synth(400, 200));
  render();
  grab("slot_400x200", lastBits, panel.w, panel.h);
  setSource(synth(200, 400));
  render();
  grab("slot_200x400", lastBits, panel.w, panel.h);
  // editar en el slot no debe tocar la plantilla
  grab("tpl_tras_slot", tplBits, panel.w, panel.h);

  grab("patron", testPatternBits(panel.w, panel.h), panel.w, panel.h);
  return out;
}

(async () => {
  const browser = await puppeteer.launch({ executablePath: BROWSER, headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", e => errors.push(e.message));
    await page.goto("file://" + html);
    const out = await page.evaluate(pageRun);
    if (errors.length) throw new Error("errores en la página: " + errors.join("; "));
    const hashes = {};
    for (const [k, v] of Object.entries(out)) {
      hashes[k] = v.length + " B " +
        crypto.createHash("sha256").update(Buffer.from(v)).digest("hex");
    }
    console.log(JSON.stringify(hashes, null, 2));
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e.message); process.exit(1); });

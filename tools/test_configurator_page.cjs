#!/usr/bin/env node
/*
 * test_configurator_page.cjs — Prueba del configurador (web/configurator/index.html)
 * en Brave headless, sin badge: la plantilla y el avatar no cambian (huellas
 * fijas), el encuadre "Encajar" de la pestaña Pantalla completa, y el estado
 * al cambiar de pestaña.
 *
 * Las huellas dependen del navegador (canvas); se fijaron con Brave 1.98 /
 * Chromium 156 en Linux. Si cambian con otro navegador, compara contra el HTML
 * anterior con tools/configurator_ref.cjs antes de tocar la tabla.
 *
 * Uso (puppeteer-core instalado con npm en otra carpeta; sale 1 si algo falla):
 *   NODE_PATH=<carpeta>/node_modules node tools/test_configurator_page.cjs [html]
 */
const crypto = require("crypto");
const path = require("path");
const puppeteer = require("puppeteer-core");
const { pageRun: refRun } = require("./configurator_ref.cjs");

const html = path.resolve(process.argv[2] ||
  path.join(__dirname, "../web/configurator/index.html"));
const BROWSER = process.env.BROWSER || "/usr/bin/brave-browser";

const REF = {
  tpl_sin_avatar: "c0c9def543c77db936172550a458a75fa917fbaa66082110f4798bb1df619371",
  avtr_payload: "4919be4b874618ba45d0bc13f79c2b0af042bd294d5248591f4176bdc6428480",
  tpl_con_avatar: "a72569295e226a4b49e78e156de2af9a5a5d61cbc8d02d44e088f3aa7ab01a28",
  slot_400x200: "7a344c7d2604c7ab91855f8a8e435674a99dc6385dd3be4eea3cfd15fb4ac95d",
  slot_200x400: "3107ff371f21f171a6d23f73d08516b555c6bc477f23572b8b31f316a1c68e87",
  patron: "9e92452fd847c0e514951571702c6733422d3b8bd604b9be68db95686ec3c33b",
};

// Dentro de la página. Devuelve {nombre: booleano}.
function fitRun() {
  const flat = (w, h, color) => {
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const x = c.getContext("2d");
    x.fillStyle = color; x.fillRect(0, 0, w, h);
    return c;
  };
  const set = (id, v) => { $(id).value = v; $(id).dispatchEvent(new Event("change")); };
  // suma de bits (1 = blanco) en filas [y0,y1) / columnas [x0,x1)
  const rows = (y0, y1) => { let n = 0; for (let y = y0; y < y1; y++) for (let x = 0; x < W; x++) n += lastBits[y * W + x]; return n; };
  const cols = (x0, x1) => { let n = 0; for (let y = 0; y < H; y++) for (let x = x0; x < x1; x++) n += lastBits[y * W + x]; return n; };
  const ok = {};

  setTarget("slot");
  set("mode", "threshold");
  setSource(flat(400, 200, "#202020"));
  render();
  ok.fill_has_no_bands = rows(0, H) === 0;
  set("fit", "fit");
  // 400x200 en 200x200: imagen en las filas ~50-149, bandas blancas arriba y abajo
  ok.fit_bands_white = rows(0, 49) === 49 * W && rows(151, H) === 49 * W;
  ok.fit_image_whole = rows(51, 149) === 0;
  set("band", "black");
  ok.fit_bands_black = rows(0, 49) === 0 && rows(151, H) === 0;
  setSource(flat(400, 200, "#ffffff"));
  render();
  ok.black_bands_keep_white_image = rows(51, 149) === 98 * W && rows(0, 49) === 0;
  // 200x400: bandas a los lados, simétricas ±1 px
  set("band", "white");
  setSource(flat(200, 400, "#202020"));
  render();
  ok.side_bands = cols(0, 49) === 49 * H && cols(151, W) === 49 * H && cols(51, 149) === 0;
  // cuadrada: Rellenar y Encajar dan los mismos bits
  set("mode", "fs");
  setSource(flat(300, 300, "#808080"));
  render();
  const fitBits = lastBits.join();
  set("fit", "fill");
  ok.square_fill_eq_fit = fitBits === lastBits.join();
  // la plantilla siempre rellena y el control solo vive en Pantalla completa
  set("fit", "fit");
  setTarget("avatar");
  ok.template_never_fits = !fitting();
  setTarget("slot");
  ok.fit_kept_in_slot = fitting() && !$("bandWrap").hidden;
  ok.packed_5000 = packBits(lastBits, panel.w, panel.h).length === 5000;
  return ok;
}

function tabsRun() {
  const tab = t => document.querySelector(`#tabs [data-target="${t}"]`).click();
  const pack = b => packBits(b, W, H).join();
  const ok = {};
  ok.starts_in_template = target === "avatar" &&
    document.querySelector('#tabs [data-target="avatar"]').getAttribute("aria-selected") === "true";
  // sin imagen cargada, cambiar de pestaña no deja bits viejos que "Enviar" mande
  tab("slot"); tab("avatar");
  ok.no_stale_bits = lastBits === null;
  // estampa y avatar fijos: las idas y vueltas no tocan la plantilla
  refRun();
  tab("avatar"); // cada pestaña conserva su imagen: vuelve el avatar de refRun
  const tpl = tplBits.join(), av = avatarBits.join();
  for (let i = 0; i < 10; i++) { tab("slot"); tab("avatar"); }
  ok.round_trips_keep_template = tpl === tplBits.join() && av === avatarBits.join();
  // una imagen propia en Pantalla completa no se vuelve el avatar, y cada pestaña conserva la suya
  const c = document.createElement("canvas");
  c.width = 400; c.height = 200;
  c.getContext("2d").fillRect(0, 0, 400, 100);
  tab("slot"); setSource(c);
  const full = lastBits.join();
  tab("avatar");
  ok.full_image_not_avatar = tpl === tplBits.join() && av === avatarBits.join();
  tab("slot");
  ok.full_image_kept = baseImage === c && full === lastBits.join();
  // texto fuera de cuadro se recorta al cambiar de destino
  tab("slot");
  textRows[0].x.value = 150; textRows[0].y.value = 180;
  tab("avatar");
  ok.text_inside_avatar = +textRows[0].x.value <= 95 && +textRows[0].y.value <= 95 &&
    +textRows[0].x.max === 95;
  tab("slot");
  ok.slot_max_restored = +textRows[0].x.max === panel.w - 1;
  return ok;
}

(async () => {
  const browser = await puppeteer.launch({ executablePath: BROWSER, headless: true });
  let failed = 0;
  const check = (name, pass) => { if (!pass) failed++; console.log((pass ? "ok   " : "FALLA"), name); };
  try {
    const run = async (fn, ...args) => {
      const page = await browser.newPage();
      const errors = [];
      page.on("pageerror", e => errors.push(e.message));
      await page.goto("file://" + html);
      // la página no expone refRun: se inyecta como función global
      await page.evaluate(`window.refRun = ${refRun.toString()}`);
      const out = await page.evaluate(fn);
      await page.close();
      check("sin errores de página", errors.length === 0);
      errors.forEach(e => console.log("   ", e));
      return out;
    };

    const out = await run(refRun);
    for (const [name, hex] of Object.entries(REF)) {
      const got = crypto.createHash("sha256").update(Buffer.from(out[name])).digest("hex");
      check(`huella ${name} = referencia`, got === hex);
    }
    check("editar en Pantalla completa no toca la plantilla",
      out.tpl_tras_slot.join() === out.tpl_con_avatar.join());

    for (const [k, v] of Object.entries(await run(fitRun))) check("encuadre: " + k, v);
    for (const [k, v] of Object.entries(await run(tabsRun))) check("pestañas: " + k, v);
  } finally {
    await browser.close();
  }
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e.message); process.exit(1); });

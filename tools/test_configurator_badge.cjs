#!/usr/bin/env node
/*
 * test_configurator_badge.cjs — Con un badge conectado: la pestaña Pantalla
 * completa envía una imagen con UPLD y READ la devuelve byte por byte igual.
 * Usa Web Serial real (Brave headless con el puerto preautorizado para file://),
 * sin el selector de puertos. ESCRIBE el slot SLOT (por defecto 3) del badge.
 *
 * El puerto se busca en /dev/serial/by-id; el número de serie sale del nombre.
 * Si Python (pyserial) usó el puerto antes, en Linux hace falta VMIN=1: este
 * script lo restaura con stty.
 *
 * Uso: SLOT=3 NODE_PATH=<carpeta>/node_modules node tools/test_configurator_badge.cjs
 */
const { execFileSync } = require("child_process");
const fs = require("fs"), os = require("os"), path = require("path");
const puppeteer = require("puppeteer-core");

const html = path.resolve(__dirname, "../web/configurator/index.html");
const BROWSER = process.env.BROWSER || "/usr/bin/brave-browser";
const SLOT = +(process.env.SLOT || 3);

const byId = fs.readdirSync("/dev/serial/by-id").find(n => /Espressif.*_([0-9A-F:]{17})-if/.test(n));
if (!byId) { console.error("No hay badge en /dev/serial/by-id"); process.exit(1); }
const serial = byId.match(/_([0-9A-F:]{17})-if/)[1];
execFileSync("stty", ["-F", fs.realpathSync("/dev/serial/by-id/" + byId), "min", "1"]);

const wait = ms => new Promise(r => setTimeout(r, ms));
async function until(page, expr, what, ms = 15000) {
  for (let t = 0; t < ms; t += 250) {
    if (await page.evaluate(expr)) return;
    await wait(250);
  }
  throw new Error("tiempo agotado: " + what + " (estado: " + await page.evaluate(() => $("status").textContent + " busy=" + busy) + ")");
}

(async () => {
  const prof = fs.mkdtempSync(path.join(os.tmpdir(), "brave-"));
  fs.mkdirSync(path.join(prof, "Default"));
  fs.writeFileSync(path.join(prof, "Default/Preferences"), JSON.stringify({ profile: { content_settings: { exceptions: {
    serial_chooser_data: { "file:///*,*": { setting: { "chosen-objects": [
      { name: "USB JTAG/serial debug unit", vendor_id: 12346, product_id: 4097, serial_number: serial }] } } } } } } }));
  const browser = await puppeteer.launch({ executablePath: BROWSER, headless: "new", userDataDir: prof });
  let failed = 0;
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", e => errors.push(e.message));
    page.on("dialog", d => d.accept());   // «¿Reemplazar la imagen del slot?» si ya tenía una
    await page.evaluateOnNewDocument(() => {
      const real = navigator.serial;
      real.requestPort = async () => (await real.getPorts())[0];
    });
    await page.goto("file://" + html);
    await page.evaluate(() => $("connectBtn").click());
    await until(page, "!!port && !!info && !busy", "conectar");

    // Elegir un slot ocupado lo carga en el editor: se espera a que termine antes
    // de poner la imagen de la prueba
    await page.evaluate(n => {
      setTarget("slot");
      document.querySelector(`#slots input[value="${n}"]`).click();
    }, SLOT);
    await wait(500);
    await until(page, "!busy", "leer el slot elegido");
    // Imagen con diagonales y un recuadro: cualquier byte cambiado de lugar se nota
    await page.evaluate(() => {
      const c = document.createElement("canvas");
      c.width = 200; c.height = 200;
      const x = c.getContext("2d");
      x.fillStyle = "#fff"; x.fillRect(0, 0, 200, 200);
      x.strokeStyle = "#000"; x.lineWidth = 3;
      x.beginPath(); x.moveTo(0, 0); x.lineTo(200, 200); x.moveTo(200, 20); x.lineTo(20, 200); x.stroke();
      x.fillRect(10 + Math.floor(Math.random() * 150), 10, 30, 12); // distinta en cada corrida
      $("mode").value = "threshold"; $("mode").dispatchEvent(new Event("change"));
      setSource(c);
      setStatus("", "");
    });
    const sent = await page.evaluate(() => Array.from(packBits(lastBits, panel.w, panel.h)));
    await page.evaluate(() => $("sendBtn").click());
    await until(page, "!busy && /^Imagen en el slot \\d+\\. Se ve en la pantalla/.test($('status').textContent)", "UPLD", 45000);
    const back = await page.evaluate(() =>
      command("READ " + selectedSlot(), null, () => readPayloadReply(panelBytes()))
        .then(b => Array.from(b)));
    const same = sent.some(v => v !== 255) && sent.length === 5000 && back.length === 5000 && sent.every((v, i) => v === back[i]);
    console.log(same ? "ok   " : "FALLA", `UPLD ${SLOT} → READ ${SLOT}: ${back.length} B idénticos`);
    if (!same) failed++;
    if (errors.length) { failed++; console.log("FALLA errores de página:", errors.join("; ")); }
  } finally {
    await browser.close();
  }
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e.message); process.exit(1); });

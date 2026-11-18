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
    // «Compartir mi avatar por infrarrojo»: la casilla viaja en flags (0x04) dentro de CARD, el badge la
    // firma y guarda, y «Leer mi estampa» la devuelve; al terminar queda como estaba.
    const share = async on => {
      await page.evaluate(async on => {
        $("readCardBtn").click();
        for (let i = 0; i < 100 && busy; i++) await new Promise(r => setTimeout(r, 100));
        $("avatarShare").checked = on; $("avatarShare").dispatchEvent(new Event("input"));
        $("saveCardBtn").click();
        for (let i = 0; i < 100 && !/Estampa guardada/.test($("status").textContent); i++) await new Promise(r => setTimeout(r, 100));
      }, on);
      await until(page, "!busy", "guardar la estampa");
      return page.evaluate(() => ({ flags: myCard[27], box: $("avatarShare").checked, dirty: $("cardState").dataset.state }));
    };
    await page.evaluate(() => $("readCardBtn").click());
    await until(page, "!busy && !!myCard", "leer la estampa");
    const was = await page.evaluate(() => !($("avatarShare").checked === false));
    const off = await share(false), on = await share(true);
    const okShare = (off.flags & 4) === 4 && !off.box && on.flags === (off.flags & ~4) && on.box && on.dirty === "saved";
    console.log(okShare ? "ok   " : "FALLA", `casilla «Compartir mi avatar»: apagada flags=0x${off.flags.toString(16)}, encendida flags=0x${on.flags.toString(16)}`);
    if (!okShare) failed++;
    if (!was) await share(false);
    // "Guardar álbum (.json)": ALBM + ALAV reales -> .json v2. Cada avatar sale igual que en ALAV
    // (CRC-16 de ir_frame::crc16 y bytes) y el archivo tarda ≤ 5 s con el álbum que tenga el badge.
    // Con un badge sin avatares recibidos solo se comprueba que sale la v2 con 0.
    const json = await page.evaluate(async () => {
      let saved = null;
      HTMLAnchorElement.prototype.click = function () { saved = this.href; };
      const blobs = new Map(), create = URL.createObjectURL;
      URL.createObjectURL = b => { const u = create(b); blobs.set(u, b); return u; };
      const t0 = performance.now();
      $("jsonBtn").click();
      for (let i = 0; i < 200 && !saved; i++) await new Promise(r => setTimeout(r, 100));
      const ms = performance.now() - t0;
      const raw = await command("ALAV", null, () => readPayloadReply());
      return { ms, status: $("status").textContent, text: saved ? await blobs.get(saved).text() : null, raw: Array.from(raw) };
    });
    const crc16 = bytes => {
      let c = 0xffff;
      for (const b of bytes) { c ^= b << 8; for (let i = 0; i < 8; i++) c = c & 0x8000 ? ((c << 1) ^ 0x1021) & 0xffff : (c << 1) & 0xffff; }
      return c;
    };
    const doc = json.text && JSON.parse(json.text), raw = Buffer.from(json.raw);
    const records = Array.from({ length: raw.readUInt16LE(5) }, (_, i) => raw.subarray(7 + i * 516, 7 + (i + 1) * 516));
    const good = records.filter(r => r.readUInt16LE(2) !== 0);
    // los avatares de la prueba son los de asistentes del álbum (los de ALAV sin estampa no salen)
    const exported = doc ? Object.keys(doc.avatars || {}).length : -1;
    const sameBytes = doc && doc.version === 2 && good.every(r => {
      const no = r.readUInt16LE(0), img = r.subarray(4);
      return !(no in doc.avatars) || (Buffer.from(doc.avatars[no], "base64").equals(img) && crc16(img) === r.readUInt16LE(2));
    });
    const ok = doc && doc.version === 2 && doc.avatar_count === exported && exported <= good.length && sameBytes &&
      new RegExp(`\\(${doc.count} estampas, ${exported} avatares\\)`).test(json.status) && json.ms <= 5000;
    console.log(ok ? "ok   " : "FALLA", `Guardar álbum (.json): v2, ${exported} de ${good.length} avatares recibidos, ` +
      `${Math.round(json.ms)} ms, ${json.text ? Math.round(json.text.length / 1024) : 0} KB — ${json.status}`);
    if (!ok) failed++;
    if (errors.length) { failed++; console.log("FALLA errores de página:", errors.join("; ")); }
  } finally {
    await browser.close();
  }
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e.message); process.exit(1); });

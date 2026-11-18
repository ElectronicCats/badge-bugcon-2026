#!/usr/bin/env node
/*
 * test_album_axe.cjs — Revisión automática de accesibilidad del álbum web con
 * axe-core, inyectado solo aquí (la página no lo lleva). Recorre los estados
 * de la página con los archivos sintéticos de test_album_page.cjs, a 1280 y a
 * 360 px, y falla con cualquier violación seria o crítica. Las moderadas y
 * leves se imprimen sin fallar.
 *
 * Uso (axe-core y puppeteer-core en el NODE_PATH; sale 1 si hay serias/críticas):
 *   NODE_PATH=<carpeta>/node_modules[:<otra>/node_modules] node tools/test_album_axe.cjs [html]
 */
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer-core");
const { CASES, V2_CASES } = require("./test_album_page.cjs");

const html = path.resolve(process.argv[2] || path.join(__dirname, "../web/album/index.html"));
const BROWSER = process.env.BROWSER || "/usr/bin/brave-browser";
const axeSrc = fs.readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");

const open = (page, [[name, bytes]]) => page.evaluate(async (n, b64) => {
  await openFile(new File([Uint8Array.from(atob(b64), c => c.charCodeAt(0))], n));
}, name, bytes.toString("base64"));

const STATES = {
  "vacío": async () => {},
  "error al abrir": p => open(p, CASES["JSON roto"]),
  "típico, Todas": p => open(p, CASES["típico .json"]),
  "típico, villa": async p => { await open(p, CASES["típico .json"]); await p.evaluate(() => document.getElementById("tab3").click()); },
  "típico, filtro Tengo": async p => { await open(p, CASES["típico .json"]); await p.evaluate(() => document.querySelector("[data-f=got]").click()); },
  "típico, detalle con handle": async p => {
    await open(p, CASES["típico .json"]);
    await p.evaluate(() => document.querySelector('#grid button[aria-label^="#013"]').click());
  },
  "v2, detalle con avatar": async p => {
    await open(p, V2_CASES["v2 con avatares"]);
    await p.evaluate(() => document.querySelector('#grid button[aria-label^="#013"]').click());
  },
  "típico, tras descargar contactos": async p => {
    await open(p, CASES["típico .json"]);
    await p.evaluate(() => { HTMLAnchorElement.prototype.click = () => {}; document.getElementById("vcfBtn").click(); });
  },
  "lleno": p => open(p, CASES["lleno .json"]),
  "vista QR": async p => { await p.goto("file://" + html + CASES["QR (mi dorsal no viene en el bitmap)"]); },
};

(async () => {
  const browser = await puppeteer.launch({ executablePath: BROWSER, headless: true });
  let failed = 0, minor = 0;
  try {
    for (const [w, h] of [[1280, 800], [360, 740]]) {
      for (const [name, setup] of Object.entries(STATES)) {
        const page = await browser.newPage();
        await page.setViewport({ width: w, height: h });
        await page.goto("file://" + html);
        await setup(page);
        await page.evaluate(axeSrc);
        const { violations } = await page.evaluate(() => axe.run(document, { resultTypes: ["violations"] }));
        const bad = violations.filter(v => v.impact === "serious" || v.impact === "critical");
        const rest = violations.filter(v => !bad.includes(v));
        failed += bad.length; minor += rest.length;
        console.log(bad.length ? "FALLA" : "ok   ", `${w}×${h} ${name}` + (rest.length ? ` (${rest.length} menores)` : ""));
        for (const v of violations) {
          console.log(`       [${v.impact}] ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map(n => n.target.join(" ")).join(", ")}`);
        }
        await page.close();
      }
    }
  } finally {
    await browser.close();
  }
  console.log(`\n${failed} serias/críticas, ${minor} menores`);
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e.stack || e.message); process.exit(1); });

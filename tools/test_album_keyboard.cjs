#!/usr/bin/env node
/*
 * test_album_keyboard.cjs — Recorrido del álbum web (web/album/index.html) solo
 * con teclado: abrir un archivo con el botón, cambiar de pestaña, filtrar, ir a
 * un dorsal, abrir y cerrar el detalle y descargar contactos. Sin un solo clic.
 *
 * Imprime las paradas de Tab de cada pantalla (la lista se pega en el log del
 * plan) y falla si el recorrido no se puede hacer o si el foco se pierde.
 *
 * Uso: NODE_PATH=<carpeta>/node_modules node tools/test_album_keyboard.cjs [html]
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const puppeteer = require("puppeteer-core");
const { CASES } = require("./test_album_page.cjs");

const html = path.resolve(process.argv[2] || path.join(__dirname, "../web/album/index.html"));
const BROWSER = process.env.BROWSER || "/usr/bin/brave-browser";

// Descripción corta del elemento con el foco: lo que se vería/leería.
const focused = () => {
  const e = document.activeElement;
  if (!e || e === document.body) return "(nada)";
  const name = e.getAttribute("aria-label") || e.textContent.trim().replace(/\s+/g, " ") || e.id || e.name || "";
  const role = e.getAttribute("role") || e.tagName.toLowerCase();
  return `${role}${e.id ? "#" + e.id : ""} «${name.slice(0, 40)}»`;
};

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "album-kbd-"));
  const [[name, bytes]] = CASES["típico .json"];
  const file = path.join(dir, name);
  fs.writeFileSync(file, bytes);

  const browser = await puppeteer.launch({ executablePath: BROWSER, headless: true });
  const kb = (page) => page.keyboard;
  let failed = 0;
  const check = (n, pass, why) => {
    if (!pass) failed++;
    console.log(pass ? "ok   " : "FALLA", n + (pass || !why ? "" : " — " + why));
  };
  // Parte del primer elemento de la página (el enlace del encabezado) y pulsa Tab hasta que el
  // foco sale del documento (hacia la barra del navegador); devuelve las paradas en orden.
  const stops = async (page, max = 200) => {
    await page.evaluate(() => document.querySelector("header a").focus());
    const list = [await page.evaluate(focused)];
    for (let i = 0; i < max; i++) {
      await kb(page).press("Tab");
      const d = await page.evaluate(focused);
      if (d === "(nada)") break;
      list.push(d);
    }
    return list;
  };
  const show = (title, list) => {
    console.log(`\n## ${title}: ${list.length} paradas de Tab`);
    const head = list.slice(0, 12);
    head.forEach((s, i) => console.log(`  ${i + 1}. ${s}`));
    if (list.length > head.length) console.log(`  … (${list.length - head.length} más; última: ${list[list.length - 1]})`);
  };
  const ae = (page) => page.evaluate(focused);

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800 });
    const errors = [];
    page.on("pageerror", e => errors.push(e.message));
    await page.evaluateOnNewDocument(() => {
      const blobs = new Map(), create = URL.createObjectURL;
      URL.createObjectURL = b => { const u = create(b); blobs.set(u, b); return u; };
      window.__dl = [];
      HTMLAnchorElement.prototype.click = function () { if (this.download) window.__dl.push(this.download); };
    });
    await page.goto("file://" + html);

    // 1. Estado vacío: de Tab en Tab hasta el botón, Enter abre el selector
    const empty = await stops(page);
    show("Estado vacío", empty);
    check("vacío: configurador, botón «Abrir álbum…», enlace de la zona y privacidad son alcanzables",
      /Abrir el configurador/.test(empty[0]) && empty.some(s => /button#openBtn2/.test(s)) &&
      empty.some(s => /^a «configurador»/.test(s)) && empty.some(s => /Privacidad/.test(s)), empty.join(" | "));
    await page.evaluate(() => document.getElementById("openBtn2").focus());
    const [chooser] = await Promise.all([page.waitForFileChooser({ timeout: 5000 }), kb(page).press("Enter")]);
    await chooser.accept([file]);
    await page.waitForFunction(() => document.getElementById("view").hidden === false, { timeout: 5000 });
    const st = await page.$eval("#status", e => e.textContent);
    check("Enter en «Abrir álbum…» abre el selector y el álbum se muestra con ✓", /^✓/.test(st), st);

    // 2. Álbum abierto: paradas del resumen y las pestañas
    const all = await stops(page);
    show("Álbum abierto, pestaña «Todas»", all);
    check("álbum: el botón de contactos y las pestañas se alcanzan, y hay una sola pestaña con tabindex 0",
      all.some(s => /button#vcfBtn/.test(s)) && all.filter(s => /^tab#/.test(s)).length === 1, all.join(" | "));

    // 3. Pestañas: ← → Fin Inicio y Tab entra al panel
    await page.evaluate(() => document.querySelector('#tabs [aria-selected="true"]').focus());
    for (let i = 0; i < 3; i++) await kb(page).press("ArrowRight");
    const t3 = await page.evaluate(() => ({ ae: document.activeElement.id, sel: document.querySelector('#tabs [aria-selected="true"]').id }));
    check("3 × → : la cuarta pestaña queda activa y con el foco", t3.ae === t3.sel && t3.ae === "tab3", JSON.stringify(t3));
    await kb(page).press("Tab");
    check("Tab desde una pestaña de villa entra a la primera estampa del panel",
      /^button «#015, /.test(await ae(page)), await ae(page));
    const villa = await stops(page);
    show("Pestaña de villa", villa);
    await page.evaluate(() => document.getElementById("tab0").focus());
    await kb(page).press("Home");
    check("Inicio vuelve a «Todas»", (await ae(page)).startsWith("tab#tab0"), await ae(page));

    // 4. Filtro e «Ir al dorsal»
    await page.evaluate(() => document.querySelector("#filter [data-f=got]").focus());
    await kb(page).press("Enter");
    const pressed = await page.$eval("#filter [data-f=got]", e => e.getAttribute("aria-pressed"));
    const kept = await ae(page);
    check("«Tengo» con Enter: queda pulsado y conserva el foco", pressed === "true" && /Tengo/.test(kept), `${pressed} ${kept}`);
    await kb(page).press("Tab"); await kb(page).press("Tab");
    check("Tab desde el filtro llega al campo «Ir al dorsal»", /goNo/.test(await ae(page)) || /spinbutton/.test(await ae(page)) || (await page.evaluate(() => document.activeElement.id)) === "goNo", await ae(page));
    await kb(page).type("250");
    await kb(page).press("Enter");
    const go = await page.evaluate(() => ({ ae: document.activeElement.getAttribute("aria-label") || document.activeElement.textContent, tag: document.activeElement.parentElement && document.activeElement.parentElement.id }));
    check("«Ir al dorsal 250» + Enter enfoca el hueco 250", /250/.test(go.ae), JSON.stringify(go));

    // 5. Detalle: Enter abre, Tab queda dentro, Esc cierra y devuelve el foco
    await page.evaluate(() => document.getElementById("tab0").focus());
    await kb(page).press("Tab");           // primera estampa que sea botón
    await page.evaluate(() => { const b = document.querySelector("#grid button"); b && b.focus(); });
    const origin = await ae(page);
    await kb(page).press("Enter");
    const inDialog = await page.evaluate(() => document.getElementById("detail").open);
    // modal: el documento de fondo es inerte; Tab recorre solo el diálogo y luego sale a la barra del navegador
    const dlg = [await ae(page)];
    for (let i = 0; i < 12; i++) {
      await kb(page).press("Tab");
      const d = await ae(page);
      if (d === "(nada)") break;
      dlg.push(d);
    }
    show("Detalle (diálogo)", dlg);
    const inside = dlg.length > 0 && dlg.every(s => /Cerrar|Guardar contacto/.test(s));
    check("Enter abre el detalle y Tab no sale de él", inDialog && inside, dlg.join(" | "));
    await kb(page).press("Escape");
    check("Esc cierra y el foco vuelve a la estampa de origen", !(await page.evaluate(() => document.getElementById("detail").open)) && (await ae(page)) === origin, `${origin} → ${await ae(page)}`);

    // 6. Descargar contactos
    await page.evaluate(() => document.getElementById("vcfBtn").focus());
    await kb(page).press("Enter");
    const dl = await page.evaluate(() => window.__dl);
    const msg = await page.$eval("#vcfMsg", e => e.textContent);
    check("Enter en «Descargar contactos» descarga el .vcf y lo dice junto al botón",
      dl.length === 1 && /^contactos_bugcon_\d+\.vcf$/.test(dl[0]) && /^✓ Descargado/.test(msg), dl.join() + " | " + msg);
    check("sin errores de página", !errors.length, errors.join("; "));
  } finally {
    await browser.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e.stack || e.message); process.exit(1); });

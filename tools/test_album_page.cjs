#!/usr/bin/env node
/*
 * test_album_page.cjs — El álbum web (web/album/index.html) interpreta y
 * exporta lo mismo que una versión de referencia de la página.
 *
 * Arma en memoria álbumes sintéticos (.bin de ALBM y .json bb26-album, sin
 * badge ni datos reales), archivos inválidos y rutas del QR; abre cada uno en
 * las dos páginas (Brave headless, file://) y compara: las secciones y su
 * contenido, los dorsales que cuentan, los bytes y el nombre del .vcf de
 * contactos y de cada .vcf individual del detalle, y el motivo de cada error.
 * Los .vcf salen de pulsar los botones de la página (pestañas, estampas,
 * "Guardar contacto", "Descargar contactos"); la descarga se intercepta.
 *
 * Uso (puppeteer-core instalado con npm en otra carpeta; sale 1 si algo difiere):
 *   NODE_PATH=<carpeta>/node_modules node tools/test_album_page.cjs [html] [commit]
 * html: la página a probar (web/album/index.html); commit: la referencia (264d5f7).
 */
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const puppeteer = require("puppeteer-core");

const html = path.resolve(process.argv[2] || path.join(__dirname, "../web/album/index.html"));
const REF_COMMIT = process.argv[3] || "264d5f7";
const BROWSER = process.env.BROWSER || "/usr/bin/brave-browser";

/* ---------------- archivos de prueba ---------------- */

const ATTENDEE = 0, CHALLENGE = 1, SPECIAL = 2, NONE = 0xff, FLAG_HANDLE = 0x02;
const MASTER_FIRST = 901, VILLAS = 10;

// Pseudoaleatorio fijo (mulberry32): mismos archivos en cada corrida.
function rng(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Estampa v1 de 64 B (firmware services/card.h); la firma es relleno.
function card({ type = ATTENDEE, no, nick = "", team = NONE, pos = NONE, stats = [0, 0, 0, 0],
                rarity = 0, flags, handle = "" }) {
  const b = Buffer.alloc(64);
  b[0] = 1; b[1] = type; b.writeUInt16LE(no, 2);
  Buffer.from(nick, "utf8").copy(b, 4, 0, 16);
  b[20] = team; b[21] = pos;
  stats.forEach((s, i) => { b[22 + i] = s; });
  b[26] = rarity;
  b[27] = flags !== undefined ? flags : (handle ? FLAG_HANDLE : 0);
  Buffer.from(handle, "utf8").copy(b, 28, 0, 20);
  for (let i = 48; i < 64; i++) b[i] = (no * 7 + i) & 0xff;
  return b;
}

// Exportación de ALBM (services/usb_protocol.h): cabecera de 80 B y count × 80 B.
function albm(mine, entries, { provisioned = 1, mac = [0xf4, 0x12, 0xfa, 0x52, 0x03, 0xf8] } = {}) {
  const h = Buffer.alloc(80);
  h.write("ALBM", 0, "latin1"); h[4] = 1; h[5] = provisioned;
  Buffer.from(mac).copy(h, 6);
  h.writeUInt16LE(entries.length, 12);
  mine.copy(h, 16);
  return Buffer.concat([h, ...entries.map((c, i) => {
    const e = Buffer.alloc(80);
    c.copy(e, 0);
    for (let k = 64; k < 72; k++) e[k] = (i + k) & 0xff;   // token
    e.writeUInt16LE(i, 72);                                 // orden de llegada
    e.writeUInt32LE(0x1000 + i, 74);                        // nonce
    return e;
  })]);
}

// .json como lo guarda el configurador (albumJson en web/configurator).
function albumJson(data, extra = {}) {
  return Buffer.from(JSON.stringify({
    format: "bb26-album", version: 1,
    badge_no: data.readUInt16LE(18),
    mac: [...data.subarray(6, 12)].map(b => b.toString(16).padStart(2, "0").toUpperCase()).join(":"),
    provisioned: data[5] !== 0, count: data.readUInt16LE(12),
    fw: "1.0.0", exported_at: "2026-11-21T19:30:00Z", albm: data.toString("base64"), ...extra,
  }, null, 1));
}

const NICKS = ["Ana", "Beto", "Caro", "Dani", "Eli", "Fer", "Gabo", "Hugo", "Iris", "Juan",
  "Kari", "Leo", "Mau", "Nadia", "Oli", "Pau", "Quique", "Rosa", "Sofi", "Tono"];

function attendee(r, no, extra = {}) {
  return card({
    no, nick: NICKS[no % NICKS.length] + no, team: Math.floor(r() * VILLAS), pos: Math.floor(r() * 5),
    stats: [0, 1, 2, 3].map(() => Math.floor(r() * 100)), rarity: r() < 0.7 ? 0 : r() < 0.6 ? 1 : 2, ...extra,
  });
}

const MY_NO = 34;
const mine = card({ no: MY_NO, nick: "Yo Mismo", team: 0, pos: 3, stats: [60, 40, 99, 10], rarity: 2,
                    handle: "@yo_mismo" });

function typical() {
  const r = rng(1);
  const list = [];
  for (let i = 0; i < 40; i++) list.push(attendee(r, 3 + i * 9));   // dorsales 3..354, varias villas
  list.push(
    // compartieron su handle; textos que el .vcf escapa o dobla
    attendee(r, 7, { nick: "Zoë 🐛 Bug", handle: "@zoe,bug;mx\\", team: 9 }),
    attendee(r, 13, { nick: "a,b;c\\d", handle: "@abc", team: 4 }),
    attendee(r, 399, { nick: "ÑandúÑandúÑandú", handle: "🔒🔒🔒🔒🔒", team: 9, pos: 4 }),
    attendee(r, 250, { nick: "ctl\x01\x7fx", handle: "h\x02i", team: 2 }),
    // handle sin FLAG_HANDLE: no es contacto
    attendee(r, 15, { handle: "@sin_flag", flags: 0 }),
    attendee(r, 16, { team: NONE }),                                  // sin villa
    attendee(r, 3 + 9),                                               // repetida (dorsal 12 ya está)
    card({ no: MY_NO, nick: "Yo Mismo" }),                            // mi propia estampa recibida
    // maestro de villa con su pedazo (no es contacto ni cuenta en x/400)
    card({ no: MASTER_FIRST + 3, nick: "Maestra OT", team: 3, pos: 0, rarity: 2, handle: "A1B2C3D4E5F60718" }),
    card({ type: SPECIAL, no: 2, nick: "Mascota", handle: "Edición 2026", rarity: 2 }),
    card({ type: SPECIAL, no: 1, nick: "Staff", handle: "Gracias por venir" }),
    card({ type: CHALLENGE, no: 5, nick: "Reto CTF", handle: "Resuelve el reto" }),
    card({ no: 0, nick: "Sin provisión" }),                          // dorsal 0, fuera de rango
  );
  return albm(mine, list);
}

function full() {
  const r = rng(2), list = [];
  for (let no = 1; no <= 400; no++) {
    if (no !== MY_NO) list.push(attendee(r, no, no % 37 === 0 ? { handle: "@user" + no } : {}));
  }
  return albm(mine, list);
}

const empty = albm(card({ no: 400, nick: "" }), [], { provisioned: 0 });
const tiny = albm(mine, []);

// Base32 de RFC 4648 sin relleno (album::qrText)
function base32(bytes) {
  const A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = 0, buf = 0, out = "";
  for (const b of bytes) {
    buf = (buf << 8) | b; bits += 8;
    while (bits >= 5) { bits -= 5; out += A[(buf >> bits) & 31]; }
  }
  return bits ? out + A[(buf << (5 - bits)) & 31] : out;
}
function qr(no, numbers) {
  const bm = Buffer.alloc(50);
  for (const n of numbers) bm[(n - 1) >> 3] |= 0x80 >> ((n - 1) & 7);
  return `#/A/${no}/${base32(bm)}/${base32(Buffer.from("tag12345"))}`;
}

const T = typical(), F = full();
const badCount = Buffer.from(T); badCount.writeUInt16LE(5, 12);
const tj = JSON.parse(albumJson(T));

// Cada caso: archivos que se abren en orden ([nombre, bytes]) o un fragmento del QR.
const CASES = {
  "vacío .bin": [["vacio.bin", empty]],
  "vacío .json": [["vacio.json", albumJson(empty)]],
  "solo mi estampa .json": [["mia.json", albumJson(tiny)]],
  "típico .bin": [["tipico.bin", T]],
  "típico .json": [["tipico.json", albumJson(T)]],
  "típico .json sin exported_at": [["tipico2.json", albumJson(T, { exported_at: undefined, fw: null })]],
  "lleno .bin": [["lleno.bin", F]],
  "lleno .json": [["lleno.json", albumJson(F)]],
  "JSON roto": [["roto.json", Buffer.from('{"format": "bb26-album", ')]],
  "format equivocado": [["otro.json", albumJson(T, { format: "bb26-card" })]],
  "version equivocada": [["v2.json", albumJson(T, { version: 2 })]],
  "albm con base64 inválido": [["b64.json", Buffer.from(JSON.stringify({ ...tj, albm: "@@no base64@@" }))]],
  "albm no es texto": [["num.json", Buffer.from(JSON.stringify({ ...tj, albm: 5 }))]],
  "count no cuadra (.json)": [["count.json", albumJson(badCount)]],
  "count no cuadra (.bin)": [["count.bin", badCount]],
  "resumen editado (badge_no)": [["editado.json", albumJson(T, { badge_no: 35 })]],
  "resumen editado (mac en minúsculas)": [["mac.json", albumJson(T, { mac: "f4:12:fa:52:03:f8" })]],
  "300 KB": [["grande.json", Buffer.alloc(300 * 1024, 0x20)]],
  "archivo vacío": [["nada.json", Buffer.alloc(0)]],
  "JSON nulo": [["null.json", Buffer.from("null")]],
  "error con álbum abierto": [["tipico.json", albumJson(T)], ["roto.json", Buffer.from("{")]],
  "segundo álbum reemplaza": [["lleno.bin", F], ["tipico.bin", T]],
  "QR (mi dorsal no viene en el bitmap)": qr(123, [1, 2, 3, 50, 399, 400]),
  "QR con dorsal fuera de rango": qr(901, [10, 20]),
  "QR mal formado": "#/A/12/ABC/DEF",
};

module.exports = { CASES };

/* ---------------- dentro de la página ---------------- */

// Antes de cargar: las descargas se guardan en window.__dl en vez de bajarse.
function hookDownloads() {
  const blobs = new Map();
  const create = URL.createObjectURL;
  URL.createObjectURL = b => { const u = create(b); blobs.set(u, b); return u; };
  window.__dl = [];
  HTMLAnchorElement.prototype.click = function () {
    if (this.download) window.__dl.push({ name: this.download, blob: blobs.get(this.href) });
  };
}

// Estado del álbum abierto y todo lo que se puede descargar desde la interfaz.
async function snapshot() {
  const bytes = async b => Array.from(new Uint8Array(await b.arrayBuffer()));
  const out = { album: typeof album !== "undefined" && album !== null };
  if (!out.album) return out;
  out.sections = JSON.stringify(sections());
  out.numbers = [...album.numbers].sort((a, b) => a - b);
  out.no = album.no;
  out.contacts = vcard(contacts());
  window.__dl = [];
  const vcfBtn = document.getElementById("vcfBtn");
  out.vcfDisabled = vcfBtn.disabled;
  if (!vcfBtn.disabled) vcfBtn.click();
  // cada estampa de cada pestaña: abrir el detalle y pulsar "Guardar contacto" si está
  const dlg = document.getElementById("detail"), dVcf = document.getElementById("dVcf");
  const tabs = () => document.querySelectorAll('#tabs [role="tab"]');
  const visit = st => {
    st.click();
    if (!dlg.open) return;
    if (!dVcf.hidden) dVcf.click();
    dlg.close();
  };
  document.querySelectorAll("#mineSt button").forEach(visit);
  for (let i = 0; i < tabs().length; i++) {
    tabs()[i].click();
    document.querySelectorAll("#grid button").forEach(visit);
  }
  out.downloads = {};
  for (const d of window.__dl) {
    const b = await bytes(d.blob);
    if (d.name in out.downloads && out.downloads[d.name].join() !== b.join()) out.downloads[d.name] = "difiere";
    else out.downloads[d.name] = b;
  }
  return out;
}

async function openAll(files) {
  const status = [];
  for (const [name, b64] of files) {
    const bin = atob(b64), u8 = Uint8Array.from(bin, c => c.charCodeAt(0));
    await openFile(new File([u8], name));
    status.push(document.getElementById("status").textContent);
  }
  return status;
}

/* ---------------- comparación ---------------- */

async function runCase(browser, file, c) {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.evaluateOnNewDocument(hookDownloads);
  await page.goto("file://" + file + (typeof c === "string" ? c : ""));
  const status = typeof c === "string" ? [await page.$eval("#status", e => e.textContent)]
    : await page.evaluate(openAll, c.map(([n, b]) => [n, b.toString("base64")]));
  const snap = await page.evaluate(snapshot);
  await page.close();
  return { status, snap, errors };
}

// Motivo del error en la página de referencia: «<archivo> no se puede abrir: <motivo>.»
const reason = s => (s.match(/ no se puede abrir: (.*)\.$/) || [])[1];

// Apertura y errores (A1): lo que la página nueva añade y la referencia no tiene.
const NEXT_STEPS = ["Guardar álbum (.json)", "Vuelve a guardarlo", "se editó a mano", "unos 52 KB"];
async function checkA1(browser, check, refOut) {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.goto("file://" + html);
  const links = () => page.$$eval("a[href='../configurator/index.html']", l => l.length);
  const st = await page.evaluate(() => ({
    drop: !document.getElementById("drop").hidden, head: !document.getElementById("openBtn").hidden,
    btn: document.getElementById("openBtn2").textContent, status: document.getElementById("status").textContent }));
  check("A1 inicio: zona de apertura visible, botón del encabezado oculto",
    st.drop && !st.head && st.btn === "Abrir álbum…" && st.status === "", JSON.stringify(st));
  check("A1 inicio: enlace al configurador en el encabezado y en la zona", await links() === 2, await links());
  check("A1 inicio: la zona dice «Guardar álbum (.json)»",
    await page.$eval("#drop", e => e.textContent.includes("Guardar álbum (.json)")));
  // arrastre: entrar, pasar a un hijo (dragenter + dragleave del padre) y salir
  const over = await page.evaluate(() => {
    const ev = (type, files) => {
      const dt = new DataTransfer();
      if (files) dt.items.add(new File(["x"], "a.json"));
      return new DragEvent(type, { dataTransfer: dt, bubbles: true, cancelable: true });
    };
    const on = () => document.body.classList.contains("over"), r = [];
    document.dispatchEvent(ev("dragenter", false)); r.push(on());      // sin archivos: nada
    document.dispatchEvent(ev("dragenter", true)); r.push(on());
    document.dispatchEvent(ev("dragenter", true)); document.dispatchEvent(ev("dragleave", true)); r.push(on());
    document.dispatchEvent(ev("dragleave", true)); r.push(on());
    return r;
  });
  check("A1 arrastre: sin parpadeo y sin archivos no resalta", over.join() === "false,true,true,false", over);
  for (const [n, c] of Object.entries(CASES)) {
    if (!Array.isArray(c) || c.length !== 1) continue;
    const r = refOut[n];
    if (r.snap.album) continue;   // solo los inválidos
    const s = await page.evaluate(openAll, [[c[0][0], c[0][1].toString("base64")]]);
    check(`A1 error «${n}»: ⚠, motivo y siguiente paso`,
      s[0].startsWith("⚠ ") && NEXT_STEPS.some(t => s[0].includes(t)), s[0]);
  }
  const ok = await page.evaluate(openAll, CASES["típico .json"].map(([n, b]) => [n, b.toString("base64")]));
  check("A1 éxito: ✓", ok[0].startsWith("✓ "), ok[0]);
  const cnt = await page.evaluate(() => {
    const $ = id => document.getElementById(id), b = $("countBar");
    return { v: $("countV").textContent, n: $("countN").textContent, val: b.value,
             lab: b.getAttribute("aria-labelledby"), vt: b.getAttribute("aria-valuetext"), size: album.numbers.size, rec: album.entries.length };
  });
  check("A2 conteos: «N de 400 dorsales», recibidas aparte y barra con nombre y valor",
    cnt.v === `${cnt.size} de 400 dorsales` && cnt.n.startsWith(cnt.rec + " estampas recibidas") &&
    cnt.val === cnt.size && cnt.lab === "countV" && cnt.vt === `${cnt.size} de 400`, cnt);
  // A2.3: el botón de contactos y su aviso viven en el resumen y se ven sin desplazar con «Todas»
  for (const [w, h] of [[1280, 800], [360, 740]]) {
    await page.setViewport({ width: w, height: h });
    const r = await page.evaluate(() => {
      const b = document.getElementById("vcfBtn").getBoundingClientRect();
      return { inSummary: !!document.querySelector("#summary #vcfBtn"), hint: !!document.querySelector("#summary #actions .hint"),
               tab: document.querySelector("#tabs [aria-selected=true]").textContent, top: b.top, bottom: b.bottom,
               h: innerHeight, over: document.documentElement.scrollWidth > innerWidth };
    });
    check(`A2.3 ${w}×${h}: «Descargar contactos» y aviso en el resumen, visibles con «Todas», sin desborde`,
      r.inSummary && r.hint && r.tab.startsWith("Todas") && r.top >= 0 && r.bottom <= r.h && !r.over, r);
  }
  check("A1 con álbum: zona oculta, botón del encabezado y enlace visibles",
    await page.evaluate(() => document.getElementById("drop").hidden && !document.getElementById("openBtn").hidden) &&
    await links() >= 1);
  const bad = await page.evaluate(openAll, [["x.json", Buffer.from("{").toString("base64")]]);
  check("A1 error con álbum abierto: dice qué álbum se sigue viendo",
    /Sigues viendo el álbum de .+\.$/.test(bad[0]), bad[0]);
  // A2.4–A2.6: vista rápida del QR, origen y privacidad plegable
  const probe = pg => (pg || page).evaluate(() => {
    const $ = id => document.getElementById(id);
    return { tabs: [...document.querySelectorAll("#tabs [role=tab]")].map(t => t.textContent),
             note: !$("quickNote").hidden && $("quickNote").textContent.includes("solo dice qué dorsales"),
             why: !$("vcfWhy").hidden, dis: $("vcfBtn").disabled, source: $("source").textContent,
             title: $("source").title, priv: $("privacy").tagName + $("privacy").open,
             frases: ["no hay servidor ni almacenamiento central", "infrarrojo", "publiques", "borrar datos"]
               .every(f => $("privacy").textContent.toLowerCase().replace(/\s+/g, " ").includes(f)) };
  });
  const qp = await browser.newPage();   // el fragmento del QR se lee al cargar: página nueva
  await qp.goto("file://" + html + CASES["QR (mi dorsal no viene en el bitmap)"]);
  const q = await probe.call(null, qp);
  check("A2.4 vista QR: aviso, solo «Todas», botón deshabilitado con motivo",
    q.note && q.tabs.length === 1 && q.tabs[0].startsWith("Todas") && q.why && q.dis, JSON.stringify(q));
  await page.goto("file://" + html);
  await page.evaluate(openAll, CASES["típico .json"].map(([n, b]) => [n, b.toString("base64")]));
  await qp.close();
  const t = await probe();
  check("A2.4 álbum del .json: sin aviso, con todas las pestañas, sin motivo de deshabilitado",
    !t.note && t.tabs.length > 2 && !t.why, t);
  check("A2.5 origen: nombre y fecha de exportación en una línea, con título completo",
    /^Archivo .+, exportado .+\.$/.test(t.source) && t.title === t.source, t);
  check("A2.6 privacidad: <details> abierto y con las frases que vigila test_configurator",
    t.priv === "DETAILStrue" && t.frases, JSON.stringify(t));
  // A3.1–A3.3: foco estable, patrón de pestañas completo y etiquetas
  const ae = () => page.evaluate(() => document.activeElement.id);
  const sel = () => page.evaluate(() => [...document.querySelectorAll("#tabs [role=tab]")]
    .map(t => (t.getAttribute("aria-selected") === "true" ? "S" : "-") + t.tabIndex).join(" "));
  await page.focus("#tab2");
  await page.keyboard.press("Enter");
  check("A3.1 clic/Enter en una pestaña: el foco sigue en esa pestaña", await ae() === "tab2", await ae());
  await page.keyboard.press("ArrowRight");
  check("A3.2 → activa y enfoca la siguiente", await ae() === "tab3" && /^(-[-0-9]+ ){3}S0/.test(await sel()), await sel());
  await page.keyboard.press("End");
  const nTabs = await page.$$eval("#tabs [role=tab]", l => l.length);
  check("A3.2 Fin va a la última y → da la vuelta a la primera",
    await ae() === "tab" + (nTabs - 1) && (await page.keyboard.press("ArrowRight"), await ae()) === "tab0");
  await page.keyboard.press("ArrowLeft");
  check("A3.2 ← desde la primera da la vuelta; Inicio vuelve a la primera",
    await ae() === "tab" + (nTabs - 1) && (await page.keyboard.press("Home"), await ae()) === "tab0");
  const pn = await page.evaluate(() => {
    const g = document.getElementById("grid"), t = [...document.querySelectorAll("#tabs [role=tab]")];
    return { role: g.getAttribute("role"), lb: g.getAttribute("aria-labelledby"),
             ctl: t.every(b => b.getAttribute("aria-controls") === "grid"),
             tab0: t[0].getAttribute("aria-label"), lab0: t[0].textContent,
             lab1: t[1].textContent, al1: t[1].getAttribute("aria-label"),
             esp: t.map(b => b.textContent).filter(x => x.startsWith("Especiales")) };
  });
  check("A3.2 #grid es tabpanel enlazado a la pestaña activa, con aria-controls",
    pn.role === "tabpanel" && pn.lb === "tab0" && pn.ctl, JSON.stringify(pn));
  check("A3.3 etiquetas «Todas · n/400» y «Villa · n» con aria-label",
    /^Todas · \d+\/400$/.test(pn.lab0) && pn.tab0 === pn.lab0.replace(/ · (\d+)\/400/, ", $1 de 400") &&
    /^.+ · \d+$/.test(pn.lab1) && /^.+, \d+ estampas?$/.test(pn.al1), JSON.stringify(pn));
  await page.click("#tab1");   // en «Todas» el filtro va antes del panel (A3.4)
  await page.keyboard.press("Tab");
  check("A3.2 Tab desde una pestaña de villa entra a la primera estampa del panel",
    await page.evaluate(() => document.getElementById("grid").contains(document.activeElement) &&
                              document.activeElement.tagName === "BUTTON"));
  // A3.4: filtro de vista «Todas / Tengo / Me faltan» e «Ir al dorsal»
  const fv = () => page.evaluate(() => {
    const g = document.getElementById("grid");
    return { shown: !document.getElementById("filter").hidden, n: g.querySelectorAll("[data-no]").length,
             empty: g.querySelectorAll(".empty").length, size: album.numbers.size,
             pressed: [...document.querySelectorAll("#filter [aria-pressed=true]")].map(b => b.dataset.f).join(),
             ae: document.activeElement.dataset.f || document.activeElement.dataset.no || document.activeElement.id,
             data: JSON.stringify(sections()) + vcard(contacts()) };
  });
  check("A3.4 el filtro solo está en «Todas»", !(await fv()).shown && (await page.click("#tab0"), (await fv()).shown));
  const f0 = await fv();
  await page.click("#filter [data-f=got]");
  const fg = await fv();
  check("A3.4 «Tengo»: solo los dorsales que tengo, botón pulsado y con el foco",
    fg.n === fg.size && !fg.empty && fg.pressed === "got" && fg.ae === "got", JSON.stringify({ ...fg, data: 0 }));
  await page.click("#filter [data-f=missing]");
  const fm = await fv();
  check("A3.4 «Me faltan»: solo los huecos vacíos",
    fm.n === 400 - fm.size && fm.empty === fm.n && fm.pressed === "missing", JSON.stringify({ ...fm, data: 0 }));
  check("A3.4 el filtro no cambia sections() ni los contactos", f0.data === fg.data && fg.data === fm.data);
  const go = async n => {
    await page.click("#goNo", { clickCount: 3 });
    await page.type("#goNo", String(n));
    await page.keyboard.press("Enter");
    return page.evaluate(() => {
      const a = document.activeElement, r = a.getBoundingClientRect();
      return { no: a.dataset.no, tag: a.tagName, visible: r.top >= 0 && r.bottom <= innerHeight,
               pressed: document.querySelector("#filter [aria-pressed=true]").dataset.f };
    });
  };
  const g250 = await go(250);
  check("A3.4 «Ir al dorsal 250» con «Me faltan»: vuelve a «Todas», enfoca y muestra el 250",
    g250.no === "250" && g250.visible && g250.pressed === "all", JSON.stringify(g250));
  const g2 = await go(2);
  check("A3.4 «Ir al dorsal» enfoca también un hueco vacío", g2.no === "2" && g2.tag === "DIV" && g2.visible, JSON.stringify(g2));
  const g0 = await go(401);
  check("A3.4 «Ir al dorsal 401» no se acepta", g0.no === undefined, JSON.stringify(g0));
  // A3.5–A3.6: rareza con símbolo y nombre accesible de cada estampa
  const lab = sel => page.$eval(sel, e => e.getAttribute("aria-label"));
  const sts = await page.evaluate(() => [...document.querySelectorAll("#grid button.st, #mineSt button.st")].map(b => ({
    r: b.className.match(/r(\d)/)[1], rar: (b.querySelector(".rar") || {}).textContent || "",
    hidden: b.querySelector(".face").getAttribute("aria-hidden"), label: b.getAttribute("aria-label") })));
  check("A3.5 Plata ◆, Oro ★ y nada en las comunes, además del borde",
    sts.length > 40 && sts.every(s => s.rar === ["", "◆", "★"][s.r]) && sts.some(s => s.r === "1") && sts.some(s => s.r === "2"),
    JSON.stringify(sts.filter(s => s.rar !== ["", "◆", "★"][s.r])));
  check("A3.6 la inicial no se lee y todas las estampas tienen nombre accesible",
    sts.every(s => s.hidden === "true" && /^(Mi estampa, )?#\d{3}, /.test(s.label)));
  const mineLab = await lab("#mineSt button");
  check("A3.6 mi estampa: «Mi estampa, #034, Yo Mismo, Villa del Hardware, Oro»",
    mineLab === "Mi estampa, #034, Yo Mismo, Villa del Hardware, Oro", mineLab);
  const l13 = await lab('#grid [data-no="13"]');
  check("A3.6 el nick va como texto, con comas y barras tal cual", l13.startsWith("#013, a,b;c\\d, PaySec LATAM"), l13);
  check("A3.6 el nick completo en el title de los que se cortan",
    await page.$eval('#grid [data-no="399"] .nick', e =>
      e.title === album.entries.find(x => x.card.badgeNo === 399).card.nickname && e.title.startsWith("ÑandúÑandú")));
  await page.evaluate(() => [...document.querySelectorAll("#tabs [role=tab]")].find(t => t.textContent.startsWith("Especiales")).click());
  const esp = await page.$$eval("#grid button.st", l => l.map(b => b.getAttribute("aria-label")));
  check("A3.6 especiales y retos sin «Sin villa»: «Especial 2, Mascota, Oro»",
    esp.includes("Especial 2, Mascota, Oro") && esp.every(s => !s.includes("Sin villa")), JSON.stringify(esp));
  // A3.7–A3.9: huecos legibles, foco visible y vacío por pestaña
  await page.click("#tab0");
  const holes = await page.evaluate(() => {   // el típico no trae dorsales sin datos: uno armado con sticker()
    $("grid").append(sticker({ no: 401, got: true }));
    const r = [...document.querySelectorAll("#grid div.st")].map(d => ({ t: d.textContent, got: d.classList.contains("got"),
      tab: d.tabIndex, sr: getComputedStyle(d.querySelector(".sr")).clipPath }));
    $("grid").lastChild.remove();
    return r;
  });
  check("A3.7 cada hueco dice su estado en texto oculto y no es parada de Tab",
    holes.some(h => h.got) && holes.some(h => !h.got) && holes.every(h => h.tab < 0 && h.sr === "inset(50%)" &&
      h.t === h.t.slice(0, 4) + (h.got ? ", la tienes,sin datos" : ", vacío")),
    JSON.stringify({ got: holes.filter(h => h.got).length, n: holes.length, bad: holes.find(h => !(h.tab < 0 && h.sr === "inset(50%)" && h.t === h.t.slice(0, 4) + (h.got ? ", la tienes,sin datos" : ", vacío"))) }));
  await page.focus("#tab0");
  await page.keyboard.press("ArrowRight");
  const ring = sel => page.evaluate(s => {
    const a = s ? document.querySelector(s) : document.activeElement, c = getComputedStyle(a);
    const t = document.getElementById("tabs").getBoundingClientRect(), r = a.getBoundingClientRect();
    return { o: c.outlineStyle + " " + c.outlineWidth + " " + c.outlineOffset, color: c.outlineColor,
             inside: r.top - 4 >= t.top && r.left - 4 >= t.left };
  }, sel);
  const rt = await ring();
  check("A3.8 pestaña con teclado: contorno de 2px separado 2px, sin recortarse en #tabs",
    rt.o === "solid 2px 2px" && rt.color === "rgb(232, 234, 240)" && rt.inside, JSON.stringify(rt));
  await page.keyboard.press("Tab");
  const rs = await ring();
  check("A3.8 estampa con teclado: el mismo contorno", rs.o === "solid 2px 2px", JSON.stringify(rs));
  await page.evaluate(() => document.querySelector("#mineSt button").focus());
  const rm = await ring();
  check("A3.8 mi estampa: el contorno se aleja del anillo azul", rm.o === "solid 2px 4px", JSON.stringify(rm));
  await page.goto("file://" + html);
  await page.evaluate(openAll, CASES["solo mi estampa .json"].map(([n, b]) => [n, b.toString("base64")]));
  const empties = await page.evaluate(() => [...document.querySelectorAll("#tabs [role=tab]")].slice(1).map(t => {
    t.click();
    return [t.textContent, document.querySelector("#grid > p").textContent];
  }));
  check("A3.9 vacío por pestaña: la villa por su nombre y «Sin especiales todavía.»",
    empties.length === 11 && empties.at(-1)[1] === "Sin especiales todavía." && empties.slice(0, -1).every(([t, p]) =>
      p === "Todavía no tienes estampas de " + t.replace(/ · 0$/, "") + ". Intercambia por infrarrojo con alguien de esa villa."),
    JSON.stringify(empties));
  // A4: detalle de la estampa
  await page.setViewport({ width: 1280, height: 800 });
  await page.goto("file://" + html);
  await page.evaluate(hookDownloads);
  await page.evaluate(openAll, CASES["típico .json"].map(([n, b]) => [n, b.toString("base64")]));
  const dlg = () => page.evaluate(() => {
    const d = $("detail"), name = id => document.getElementById(d.getAttribute(id) || "").textContent;
    return { open: d.open, name: name("aria-labelledby"), desc: name("aria-describedby"),
             face: $("dNoFace").getAttribute("aria-hidden"), handle: $("dHandle").textContent, msg: $("dMsg").textContent,
             stats: [...document.querySelectorAll("#dStats .stat")].map(r => ({ sr: r.querySelector(".sr").textContent,
               hid: [...r.children].filter(c => !c.classList.contains("sr")).every(c => c.getAttribute("aria-hidden") === "true"),
               w: r.querySelector("i").style.width })),
             order: [...d.querySelectorAll("#dNick, #dMeta, #dStats, #dHandle, #dVcf")].map(e => e.id).join(),
             ae: document.activeElement.getAttribute("data-no") };
  });
  await page.focus('#grid [data-no="13"]');
  await page.keyboard.press("Enter");
  const d13 = await dlg(), c13 = await page.evaluate(() => album.entries.find(x => x.card.badgeNo === 13).card.stats);
  check("A4.1 el diálogo se nombra con el nick y se describe con los metadatos",
    d13.open && d13.name === "a,b;c\\d" && d13.desc.includes("PaySec LATAM"), JSON.stringify(d13));
  check("A4.2 la inicial no se lee", d13.face === "true");
  check("A4.3 cada estadística se lee «ATK n de 99», con la barra oculta y el mismo ancho",
    d13.stats.length === 4 && d13.stats.every((s, i) => s.hid && s.sr === ["ATK", "DEF", "HAX", "SUE"][i] + " " + c13[i] + " de 99" &&
      Math.abs(parseFloat(s.w) - Math.min(100, c13[i] * 100 / 99)) < 0.01), JSON.stringify(d13.stats));
  check("A4.6 orden de lectura: nick, metadatos, estadísticas, handle, acciones",
    d13.order === "dNick,dMeta,dStats,dHandle,dVcf", d13.order);
  await page.click("#dVcf");
  const m13 = await page.evaluate(() => ({ msg: $("dMsg").textContent, live: $("dMsg").getAttribute("role"),
    inDlg: $("detail").contains($("dMsg")), dl: window.__dl.map(d => d.name) }));
  check("A4.4 «Guardar contacto» confirma en el diálogo, en una región que se anuncia",
    m13.msg === "✓ Descargado bugcon_13.vcf." && m13.live === "status" && m13.inDlg && m13.dl.join() === "bugcon_13.vcf",
    JSON.stringify(m13));
  await page.keyboard.press("Escape");
  const e13 = await dlg();
  check("A4.5 Esc cierra y el foco vuelve a la estampa", !e13.open && e13.ae === "13", JSON.stringify(e13));
  await page.click('#grid [data-no="13"]');
  check("A4.4 al abrir otra vez el mensaje anterior ya no está", (await dlg()).msg === "");
  await page.click("#detail", { offset: { x: 5, y: 5 } });   // padding del diálogo: no cierra
  const inPad = (await dlg()).open;
  await page.mouse.click(5, 5);                                // fondo: cierra
  const f13 = await dlg();
  check("A4.5 clic en el fondo cierra, clic en el padding no; el foco vuelve a la estampa",
    inPad && !f13.open && f13.ae === "13", JSON.stringify({ inPad, f13 }));
  await page.evaluate(() => [...document.querySelectorAll("#tabs [role=tab]")].find(t => t.textContent.startsWith(TEAMS[3])).click());
  await page.click(`#grid [data-no="${MASTER_FIRST + 3}"]`);
  const dm = await dlg();
  check("A4.6 el maestro rotula su pedazo «Pedazo de la gira de villas»",
    dm.handle === "Pedazo de la gira de villas: A1B2 C3D4 E5F6 0718", dm.handle);
  await page.keyboard.press("Escape");
  await page.setViewport({ width: 360, height: 420 });
  await page.click(`#grid [data-no="${MASTER_FIRST + 3}"]`);
  const low = await page.evaluate(() => {
    const d = $("detail"), r = d.getBoundingClientRect();
    d.scrollTop = d.scrollHeight;
    const b = d.querySelector("form button").getBoundingClientRect();
    return { top: r.top, bottom: r.bottom, h: innerHeight, scrolls: d.scrollHeight > d.clientHeight, btn: b.bottom <= r.bottom };
  });
  check("A4.5 ventana baja: el diálogo cabe y se desplaza hasta «Cerrar»",
    low.top >= 0 && low.bottom <= low.h && low.scrolls && low.btn, JSON.stringify(low));
  await page.keyboard.press("Escape");
  await page.setViewport({ width: 1280, height: 800 });
  // A5: retroalimentación de «Descargar contactos»
  const vcf = () => page.evaluate(() => {
    const b = $("vcfBtn").getBoundingClientRect(), m = $("vcfMsg").getBoundingClientRect();
    return { msg: $("vcfMsg").textContent, live: $("vcfMsg").getAttribute("role"), gap: m.top - b.bottom,
             status: $("status").textContent, lives: document.querySelectorAll("[role=status]:not(:empty)").length,
             dis: $("vcfBtn").disabled, why: $("vcfWhy").hidden ? null : $("vcfWhy").textContent,
             who: $("vcfWho").hidden ? null : [...$("vcfWho").querySelectorAll("li")].map(l => l.textContent),
             dl: window.__dl.map(d => d.name), n: contacts().length };
  });
  await page.evaluate(() => { window.__dl = []; });
  const v0 = await vcf();
  check("A5.3–A5.4 con contactos: sin motivo y «Ver quiénes» con número, nick y handle como texto",
    !v0.dis && v0.why === null && v0.who && v0.who.length === v0.n && v0.n === 4 &&
    v0.who.includes("#013 a,b;c\\d · @abc") && v0.who.includes("#007 Zoë 🐛 Bug · @zoe,bug;mx\\"),
    JSON.stringify(v0));
  await page.click("#vcfBtn");
  const v1 = await vcf();
  check("A5.1–A5.2 «Descargado … con 4 contactos» junto al botón, en una sola región que se anuncia",
    v1.msg === "✓ Descargado contactos_bugcon_34.vcf con 4 contactos. Revisa cada handle antes de confiar en él." &&
    v1.live === "status" && v1.gap >= 0 && v1.gap < 100 && v1.status === "" && v1.lives === 1 &&
    v1.dl.join() === "contactos_bugcon_34.vcf", JSON.stringify(v1));
  await page.evaluate(openAll, CASES["solo mi estampa .json"].map(([n, b]) => [n, b.toString("base64")]));
  const v2 = await vcf();
  check("A5.3 sin contactos: deshabilitado con «Nadie de tu álbum compartió su handle.», sin lista ni mensaje viejo",
    v2.dis && v2.why === "Nadie de tu álbum compartió su handle." && v2.who === null && v2.msg === "", JSON.stringify(v2));
  const qv = await browser.newPage();
  await qv.goto("file://" + html + CASES["QR (mi dorsal no viene en el bitmap)"]);
  const why = await qv.$eval("#vcfWhy", e => e.hidden ? null : e.textContent);
  await qv.close();
  check("A5.3 vista QR: «Abre el .json para ver los contactos.»", why === "Abre el .json para ver los contactos.", why);
  // A6.1: los colores viven en :root; fuera solo var(--…)
  const css = fs.readFileSync(html, "utf8").match(/<style>([\s\S]*?)<\/style>/)[1].replace(/:root\s*\{[^}]*\}/, "");
  const loose = css.match(/#[0-9a-f]{3,8}\b|rgba?\(/gi);
  check("A6.1 sin colores sueltos fuera de :root", !loose, loose && loose.join(" "));
  // A6.2: contraste de los pares que usa la página (WCAG 2.x), leído de los tokens reales
  const ratios = await page.evaluate(() => {
    const v = n => getComputedStyle(document.documentElement).getPropertyValue("--" + n).trim();
    const rgba = h => { h = h.slice(1); if (h.length <= 4) h = [...h].map(c => c + c).join("");
      return [0, 2, 4, 6].map(i => parseInt(h.slice(i, i + 2) || "ff", 16)); };
    const over = (f, b) => f.slice(0, 3).map((c, i) => c * f[3] / 255 + b[i] * (1 - f[3] / 255));
    const lum = c => c.map(x => (x /= 255) <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4)
                      .reduce((s, x, i) => s + x * [0.2126, 0.7152, 0.0722][i], 0);
    const cr = (f, b) => { const bg = over(rgba(v(b)), [0, 0, 0]), fg = over(rgba(v(f)), bg);
      const [x, y] = [lum(fg), lum(bg)].sort((p, q) => q - p); return +((x + 0.05) / (y + 0.05)).toFixed(2); };
    const crOn = (f, bgRgb) => { const [x, y] = [lum(rgba(v(f)).slice(0, 3)), lum(bgRgb)].sort((p, q) => q - p);
      return +((x + 0.05) / (y + 0.05)).toFixed(2); };
    const out = {};
    for (const f of ["text", "muted", "accent", "ok", "err"]) for (const b of ["bg", "card", "card2"]) out[f + "/" + b] = [cr(f, b), 4.5];
    out["on-accent/accent"] = [cr("on-accent", "accent"), 4.5];
    for (const f of ["tag-text", "silver", "gold"]) out[f + "/tag-bg"] = [crOn(f, over(rgba(v("tag-bg")), rgba(v("card2")))), 4.5];
    for (const f of ["silver", "gold", "accent"]) for (const b of ["bg", "card"]) out[f + "/" + b + " (borde)"] = [cr(f, b), 3];
    for (const b of ["bg", "card"]) out["foco text/" + b] = [cr("text", b), 3];
    return out;
  });
  const weak = Object.entries(ratios).filter(([, [r, min]]) => r < min);
  check("A6.2 contraste ≥ 4.5:1 en texto y ≥ 3:1 en bordes de estado y foco", !weak.length, JSON.stringify(weak));
  // con el típico abierto (hay .sub de villa y etiquetas de dorsal) y un detalle
  await page.evaluate(openAll, CASES["típico .json"].map(([n, b]) => [n, b.toString("base64")]));
  const tiny = await page.evaluate(() => [...document.querySelectorAll("body *")]
    .filter(e => e.offsetParent && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) &&
                 parseFloat(getComputedStyle(e).fontSize) < 12)
    .map(e => e.className || e.tagName));
  check("A6.2 ningún texto visible de menos de 12 px", !tiny.length, tiny.join(" "));
  // A6.3: regiones
  const land = await page.evaluate(() => {
    const m = document.querySelectorAll("main");
    return { n: m.length, has: ["drop", "summary", "tabs", "grid"].every(id => m[0]?.contains($(id))),
             out: ["header", "footer", "#privacy", "#detail"].every(q => !m[0]?.contains(document.querySelector(q))),
             top: ["header", "footer"].every(q => document.querySelector(q).parentElement === document.body) };
  });
  check("A6.3 un <main> con zona, resumen, pestañas y cuadrícula; encabezado y pie fuera",
    land.n === 1 && land.has && land.out && land.top, JSON.stringify(land));
  // A6.4: sin desplazamiento horizontal en las tres medidas, ≥ 3 columnas a 360 px, pestañas con indicio
  const adapt = [];
  for (const [w, h, f] of [[1280, 800, 1], [512, 384, 2], [360, 740, 1]]) {
    await page.setViewport({ width: w, height: h, deviceScaleFactor: f });
    for (const c of ["típico .json", "lleno .json", "QR (mi dorsal no viene en el bitmap)"]) {
      const m = CASES[c];
      if (Array.isArray(m)) await page.evaluate(openAll, m.map(([n, b]) => [n, b.toString("base64")]));
      else { await page.goto("file://" + html + m); }
      adapt.push(await page.evaluate((w, c) => {
        const t = $("tabs"), more = t.scrollWidth > t.clientWidth;
        return { w, c, sw: document.documentElement.scrollWidth, iw: innerWidth,
          cols: getComputedStyle($("grid")).gridTemplateColumns.split(" ").length,
          more, fr: t.style.getPropertyValue("--fr"), fl: t.style.getPropertyValue("--fl"),
          mask: getComputedStyle(t).maskImage !== "none" };
      }, w, c));
    }
  }
  const badA = adapt.filter(a => a.sw > a.iw || a.cols < 3 || !a.mask || (a.more && a.fr !== "24px") || (!a.more && a.fr === "24px"));
  check("A6.4 sin desplazamiento horizontal a 1280, 1024 al 200 % y 360; ≥ 3 columnas; pestañas con borde desvanecido",
    !badA.length && adapt.some(a => a.more), JSON.stringify(badA));
  await page.setViewport({ width: 360, height: 740 });
  await page.evaluate(openAll, CASES["típico .json"].map(([n, b]) => [n, b.toString("base64")]));
  const sc = await page.evaluate(() => {
    const t = $("tabs"); t.scrollLeft = t.scrollWidth; t.dispatchEvent(new Event("scroll"));
    return { fl: t.style.getPropertyValue("--fl"), fr: t.style.getPropertyValue("--fr"),
             sub: [...document.querySelectorAll(".st .sub")].filter(e => e.title !== e.textContent) .length };
  });
  check("A6.4 al llegar al final de las pestañas se desvanece solo el borde izquierdo; la villa de cada estampa lleva title",
    sc.fl === "24px" && sc.fr === "0px" && sc.sub === 0, JSON.stringify(sc));
  await page.setViewport({ width: 1280, height: 800 });
  // los enlaces resuelven por file:// (relativos) y vuelven
  await page.goto("file://" + html);
  await page.click("a[href='../configurator/index.html']");
  await page.waitForFunction(() => document.title.includes("Configurador"));
  const back = await page.$$eval("a[href='../album/index.html']", l => l.length);
  check("A1 enlaces: álbum → configurador carga y el configurador enlaza al álbum", back >= 1, back);
  await page.click("header a[href='../album/index.html']");
  await page.waitForFunction(() => document.title.includes("Álbum"));
  check("A1 enlaces: configurador → álbum carga", true);
  check("A1 sin errores de página", !errors.length, errors.join("; "));
  await page.close();
}

if (require.main === module) (async () => {
  const ref = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "album-ref-")), "index.html");
  fs.writeFileSync(ref, execFileSync("git", ["show", REF_COMMIT + ":web/album/index.html"],
                                     { cwd: path.join(__dirname, "..") }));
  const browser = await puppeteer.launch({ executablePath: BROWSER, headless: true });
  let failed = 0;
  const check = (name, pass, why) => {
    if (!pass) failed++;
    console.log(pass ? "ok   " : "FALLA", name + (pass || !why ? "" : " — " + why));
  };
  try {
    const refOut = {};
    for (const [name, c] of Object.entries(CASES)) {
      const [a, b] = [await runCase(browser, ref, c), await runCase(browser, html, c)];
      refOut[name] = a;
      const why = [...a.errors, ...b.errors];
      // el texto alrededor del error puede cambiar; el motivo tiene que seguir ahí
      a.status.forEach((s, i) => {
        if (reason(s) && !b.status[i].includes(reason(s))) why.push(`falta «${reason(s)}» en «${b.status[i]}»`);
      });
      for (const k of ["album", "no", "numbers", "sections", "contacts", "vcfDisabled", "downloads"]) {
        if (JSON.stringify(a.snap[k]) !== JSON.stringify(b.snap[k])) why.push(k + " distinto");
      }
      check(name + " = " + REF_COMMIT, !why.length, why.join("; "));
    }
    // Que los casos sí prueben algo: lo que se espera de la referencia.
    const names = Object.keys(refOut["típico .json"].snap.downloads || {}).sort().join(" ");
    check("referencia: el típico baja contactos y .vcf individuales",
      names === "bugcon_13.vcf bugcon_250.vcf bugcon_399.vcf bugcon_7.vcf contactos_bugcon_34.vcf", names);
    const e = refOut["error con álbum abierto"];
    check("referencia: un error deja abierto el álbum anterior", e.snap.album && e.snap.no === MY_NO);
    for (const [n, r] of Object.entries(refOut)) {
      if (Array.isArray(CASES[n]) && CASES[n].length === 1 && !/^(vacío|típico|lleno|solo mi)/.test(n)) {
        check(`referencia: «${n}» se rechaza`, !r.snap.album && reason(r.status[0]), r.status[0]);
      }
    }
    await checkA1(browser, check, refOut);
  } finally {
    await browser.close();
    fs.rmSync(path.dirname(ref), { recursive: true, force: true });
  }
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e.stack || e.message); process.exit(1); });

#!/usr/bin/env node
/*
 * test_album_zip.cjs — Empaqueta el .zip (tools/package_web.py), lo descomprime en una carpeta
 * temporal y comprueba por file:// la ida y vuelta configurador → «Ver el álbum» → álbum →
 * «Abrir el configurador» → configurador, sin romper la ruta relativa.
 *
 * Uso: NODE_PATH=<carpeta>/node_modules node tools/test_album_zip.cjs
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");
const puppeteer = require("puppeteer-core");

const BROWSER = process.env.BROWSER || "/usr/bin/brave-browser";
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "album-zip-"));
const zip = path.join(dir, "web.zip");
execFileSync("python3", [path.join(__dirname, "package_web.py"), zip, "prueba"]);
execFileSync("python3", ["-I", "-c", "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])", zip, dir]);
const root = path.join(dir, "bugcon26-configurador");

(async () => {
  const browser = await puppeteer.launch({ executablePath: BROWSER, headless: true });
  let failed = 0;
  const check = (n, pass, why) => {
    if (!pass) failed++;
    console.log(pass ? "ok   " : "FALLA", n + (pass || !why ? "" : " — " + why));
  };
  const page = await browser.newPage();
  const tail = () => page.url().split("/").slice(-2).join("/");
  await page.goto("file://" + path.join(root, "configurator/index.html"));
  await page.click("header a");
  await page.waitForFunction(() => location.pathname.endsWith("album/index.html"));
  check("configurador → álbum", tail() === "album/index.html", tail());
  check("álbum con su página", !!(await page.$("#drop")));
  await page.click("header a");
  await page.waitForFunction(() => location.pathname.endsWith("configurator/index.html"));
  check("álbum → configurador", tail() === "configurator/index.html", tail());
  check("configurador con su página", !!(await page.$("#connectBtn")));
  await browser.close();
  fs.rmSync(dir, { recursive: true, force: true });
  process.exit(failed ? 1 : 0);
})();

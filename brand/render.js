// Renders the print designs to PDF (vector, for the printer) and PNG previews.
//   npm i playwright && npx playwright install chromium   (once)
//   node brand/render.js            -> brand/out/*.pdf, brand/out/*.png
const path = require("path");
const { chromium } = require("playwright");

const SRC = path.join(__dirname, "src");
const OUT = path.join(__dirname, "out");
const MM = 96 / 25.4; // CSS px per mm

// name, page width/height in mm (including bleed), preview scale
const DESIGNS = [
  ["rollup", 860, 2010, 0.3],
  ["brochure-outside", 303, 216, 1.2],
  ["brochure-inside", 303, 216, 1.2],
  ["identity", 297, 210, 1],
  ["logo", 297, 210, 4],
];

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
  const only = process.argv.slice(2);
  for (const [name, w, h, scale] of DESIGNS) {
    if (only.length && !only.includes(name)) continue;
    const page = await browser.newPage({ viewport: { width: Math.round(w * MM), height: Math.round(h * MM) }, deviceScaleFactor: scale });
    await page.goto("file://" + path.join(SRC, name + ".html"));
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(300);
    await page.pdf({ path: path.join(OUT, name + ".pdf"), preferCSSPageSize: true, printBackground: true });
    await page.screenshot({ path: path.join(OUT, name + ".png"), fullPage: true });
    // logo sheet: each marked block also becomes a transparent PNG in brand/logo
    for (const el of await page.$$(".export[data-name]")) {
      const file = (await el.getAttribute("data-name")) + ".png";
      await el.screenshot({ path: path.join(__dirname, "logo", file), omitBackground: true, scale: "device" });
    }
    await page.close();
    console.log("rendered", name);
  }
  await browser.close();
})();

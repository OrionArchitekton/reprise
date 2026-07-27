#!/usr/bin/env python3
"""Capture the Devpost gallery screenshots from a running deployment.

Reproducible so the gallery can be regenerated when the UI changes, rather
than being a folder of images nobody can re-derive. The shot list and the
captions live in docs/submission/SCREENSHOT_CAPTIONS.md; this script produces
the files that plan names.

Shot 05 costs a real generation (about $0.04), so it is opt-in with --spend.
Passing --spend twice in a day just spends twice: the prompt it uses is filed
in the library by the first run, and the second run would capture a REUSE card
under a filename that claims to be a generation. Use --generate-prompt with a
fresh novel prompt, checked with tools/band_probe.py first.

    python tools/capture_screenshots.py https://reprise-murex.vercel.app
    python tools/capture_screenshots.py <url> --spend --generate-prompt "..."
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs/screenshots"
DEFAULT_BASE = "https://reprise-murex.vercel.app"
DEFAULT_GENERATE_PROMPT = (
    "a brass sextant resting on an antique navigation chart, studio photograph"
)

# Driven through node because the capture pipeline this project already owns
# (agent-demo-video) carries the pinned Playwright, and installing a second
# browser stack for six images is not worth it.
DRIVER = Path(
    "/home/orion/src/orion-estate/personal-brand/oss-projects/agent-demo-video/agent-demo-video-oss"
)

SCRIPT = r"""
import { createRequire } from "node:module";
const require = createRequire(process.argv[2] + "/package.json");
const { chromium } = require("playwright");

const [, , , base, out, spend, genPrompt] = process.argv;
// 1200 tall, not 900: the result card measures ~1145px, so a 900 viewport
// cannot show a verdict headline and its evidence in one frame no matter where
// it is scrolled. Shrinking the asset with capture-only CSS would fit it, but
// then the gallery shows a UI the site does not render. A taller window is a
// real window.
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1440, height: 1200 } });
const shot = async (name, fn) => {
  const p = await ctx.newPage();
  await p.goto(base + "/", { waitUntil: "load" });
  await p.waitForTimeout(600);
  await fn(p);
  await p.screenshot({ path: `${out}/${name}.png`, fullPage: false });
  console.log("wrote", name);
  await p.close();
};
// Put the verdict card's top edge at the top of the frame, so the badge and
// headline are in shot along with the evidence underneath them.
const frameResult = async (p) => {
  const box = await p.locator("#result").boundingBox();
  await p.evaluate((y) => window.scrollTo({ top: y, behavior: "instant" }), box.y);
  await p.waitForTimeout(400);
};
const submit = async (p) => {
  await p.click("#go");
  await p.waitForSelector("#result .headline", { timeout: 60000 });
  await p.waitForTimeout(1500);
};

await shot("01-homepage", async () => {});

await shot("02-exact-reuse", async (p) => {
  await p.click("button[data-fill*='a red bicycle']");
  await submit(p);
  await frameResult(p);
});

await shot("03-review-card", async (p) => {
  await p.click("button[data-fill*='a crimson bicycle']");
  await submit(p);
  await frameResult(p);
});

await shot("04-proof-receipt", async (p) => {
  await p.click("button[data-fill*='a red bicycle']");
  await submit(p);
  await p.click(".receipt summary");
  await p.waitForTimeout(500);
  // Frame the receipt itself, with room under the manifest link: the caption
  // for this shot promises a reader can open the manifest, so the link cannot
  // be sitting on the bottom edge of the image.
  const box = await p.locator(".receipt").boundingBox();
  await p.evaluate((y) => window.scrollTo({ top: y, behavior: "instant" }), box.y - 220);
  await p.waitForTimeout(400);
});

if (spend === "spend") {
  await shot("05-generate", async (p) => {
    await p.fill("#prompt", genPrompt);
    await p.click("#go");
    await p.waitForSelector("#result .headline", { timeout: 180000 });
    await p.waitForTimeout(2000);
    await frameResult(p);
  });
} else {
  console.log("skipped 05-generate (needs --spend: it costs a real generation)");
}

// The eval report as a reader meets it, on GitHub, rather than a local render:
// the caption claims the published numbers are pinned in CI, and this is the
// page a judge would actually open to check that.
{
  const p = await ctx.newPage();
  await p.goto(
    "https://github.com/OrionArchitekton/reprise/blob/main/eval/report.md",
    { waitUntil: "domcontentloaded" },
  );
  await p.waitForSelector("article table", { timeout: 60000 });
  await p.waitForTimeout(1500);
  const box = await p.locator("article").boundingBox();
  await p.evaluate((y) => window.scrollTo({ top: y - 40, behavior: "instant" }), box.y);
  await p.waitForTimeout(500);
  await p.screenshot({ path: `${out}/06-evidence.png` });
  console.log("wrote 06-evidence");
  await p.close();
}

await b.close();
"""


def main() -> int:
    args = sys.argv[1:]
    base = next((a for a in args if a.startswith("http")), DEFAULT_BASE).rstrip("/")
    spend = "spend" if "--spend" in args else "dry"
    prompt = DEFAULT_GENERATE_PROMPT
    if "--generate-prompt" in args:
        prompt = args[args.index("--generate-prompt") + 1]

    OUT.mkdir(parents=True, exist_ok=True)
    driver = OUT.parent.parent / "tools" / "_capture.mjs"
    driver.write_text(SCRIPT)
    try:
        r = subprocess.run(
            ["node", str(driver), str(DRIVER), base, str(OUT), spend, prompt],
            cwd=DRIVER,
            check=False,
        )
    finally:
        driver.unlink(missing_ok=True)
    if r.returncode != 0:
        print("CAPTURE FAILED")
        return r.returncode
    print(f"\nwrote to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

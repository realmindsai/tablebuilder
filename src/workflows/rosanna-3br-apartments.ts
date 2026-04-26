import { writeFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { workflow, type LibrettoWorkflowContext } from "libretto";
import { log } from "../shared/utils.js";

type Input = {
  // Maximum number of result pages to walk. Safety cap.
  maxPages?: number;
  // Suburbs to keep. realestate.com.au broadens the search beyond Rosanna,
  // so we filter returned addresses by these suburb names (case-insensitive).
  allowedSuburbs?: string[];
  // Destination file for the scraped listings, relative to CWD.
  // Defaults to output/rosanna-3br-apartments-<ISO>.json.
  outputPath?: string;
};

type Listing = {
  address: string;
  suburb: string | null;
  price: string | null;
  propertyType: string | null;
  bedrooms: number | null;
  bathrooms: number | null;
  carSpaces: number | null;
  features: string | null;
  url: string;
};

type Output = {
  total: number;
  pagesWalked: number;
  outputPath: string;
  listings: Listing[];
};

const SEARCH_URL =
  "https://www.realestate.com.au/buy/property-apartment-with-3-bedrooms-in-rosanna,+vic+3084/list-";

const DEFAULT_ALLOWED_SUBURBS = [
  "Rosanna",
  "Ivanhoe",
  "Heidelberg",
  "Heidelberg Heights",
  "MacLeod",
];

export default workflow<Input, Output>(
  "rosanna-3br-apartments",
  async (ctx: LibrettoWorkflowContext, input): Promise<Output> => {
    const { page } = ctx;
    const maxPages = input?.maxPages ?? 10;
    const allowedSuburbs = (input?.allowedSuburbs ?? DEFAULT_ALLOWED_SUBURBS).map(
      (s) => s.toLowerCase(),
    );

    const listings: Listing[] = [];
    let pagesWalked = 0;

    // Clear any residual tab state (ad iframes, stale renders) before the
    // real navigation. Avoids the first goto landing on the wrong frame target.
    await page.goto("about:blank");

    // Walk /list-1, /list-2, ... until a page returns no result cards.
    for (let pageNum = 1; pageNum <= maxPages; pageNum++) {
      log(`Fetching results page ${pageNum}`);

      // Navigate, then retry once with a reload if the listing grid never
      // appears — REA occasionally serves an ad/prebid shell on first nav.
      let cardsReady = false;
      for (let attempt = 0; attempt < 2 && !cardsReady; attempt++) {
        if (attempt === 0) {
          await page.goto(`${SEARCH_URL}${pageNum}`, {
            waitUntil: "domcontentloaded",
          });
        } else {
          log(`Retrying page ${pageNum} via reload`);
          await page.reload({ waitUntil: "domcontentloaded" });
        }
        try {
          await page.waitForSelector('[data-testid="ResidentialCard"]', {
            timeout: 15000,
          });
          cardsReady = true;
        } catch {
          // fall through to retry or exit
        }
      }

      if (!cardsReady) {
        log(`No ResidentialCard on page ${pageNum} — stopping.`);
        break;
      }

      pagesWalked = pageNum;

      const cards = await page.locator('[data-testid="ResidentialCard"]').all();
      log(`Page ${pageNum}: ${cards.length} cards found`);
      if (cards.length === 0) break;

      // Extract per-card fields using Playwright locators.
      for (const card of cards) {
        const addressLink = card.locator(".residential-card__address-heading a").first();
        const address = (await addressLink.textContent())?.trim() ?? "";
        const href = await addressLink.getAttribute("href");
        if (!address || !href) continue;

        const url = new URL(href, "https://www.realestate.com.au/").toString();

        // Suburb is the last comma-separated segment in the displayed address.
        const addressParts = address.split(",").map((s) => s.trim());
        const suburb = addressParts.at(-1) ?? null;

        if (
          suburb &&
          !allowedSuburbs.includes(suburb.toLowerCase())
        ) {
          continue;
        }

        // Features come from the aria-label on the primary feature list,
        // e.g. "Apartment  with 3 bedrooms  2 bathrooms 2 car spaces".
        const features =
          (await card
            .locator("ul.residential-card__primary")
            .first()
            .getAttribute("aria-label")) ?? null;

        const propertyType = features?.trim().split(/\s+/)[0] ?? null;
        const bedrooms = matchInt(features, /(\d+)\s*bedroom/i);
        const bathrooms = matchInt(features, /(\d+)\s*bathroom/i);
        const carSpaces = matchInt(features, /(\d+)\s*car\s*space/i);

        // Two price shapes exist on REA:
        //   - standard listings:   <span class="property-price">$X - $Y</span>
        //   - off-the-plan / project cards: "Indicative price: $X - $Y" inline text
        let price: string | null = null;
        const priceNode = card.locator(".property-price").first();
        if ((await priceNode.count()) > 0) {
          price = (await priceNode.textContent())?.trim() ?? null;
        } else {
          const indicative = card.locator("text=/Indicative price[^\\n]*/i").first();
          if ((await indicative.count()) > 0) {
            price = (await indicative.textContent())?.trim() ?? null;
          }
        }

        listings.push({
          address,
          suburb,
          price,
          propertyType,
          bedrooms,
          bathrooms,
          carSpaces,
          features: features?.replace(/\s+/g, " ").trim() ?? null,
          url,
        });
      }
    }

    // Persist results to disk so `libretto run` produces a file, not just a
    // returned object. Default path lives under output/ with an ISO timestamp.
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const outputPath = resolve(
      input?.outputPath ?? `output/rosanna-3br-apartments-${stamp}.json`,
    );
    await mkdir(dirname(outputPath), { recursive: true });
    await writeFile(
      outputPath,
      JSON.stringify(
        { scrapedAt: new Date().toISOString(), pagesWalked, total: listings.length, listings },
        null,
        2,
      ),
    );

    log(
      `Done. Collected ${listings.length} listings across ${pagesWalked} page(s). Wrote ${outputPath}`,
    );
    return { total: listings.length, pagesWalked, outputPath, listings };
  },
);

function matchInt(text: string | null | undefined, re: RegExp): number | null {
  if (!text) return null;
  const m = text.match(re);
  return m ? Number.parseInt(m[1], 10) : null;
}

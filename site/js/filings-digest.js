import { fetchJSON, escapeHtml, renderFilingsSection, renderDisclaimerFooter } from "./shared.js";

async function main() {
  const content = document.getElementById("content");
  try {
    const doc = await fetchJSON("../data/filings_digest.json");
    content.innerHTML = render(doc);
  } catch (err) {
    content.innerHTML = `<p class="error">Could not load the filings digest (${escapeHtml(err.message)}). Has the pipeline run yet?</p>`;
  }
  renderDisclaimerFooter();
}

function render(doc) {
  const entries = doc.entries || [];
  if (!entries.length) {
    return `
      <section class="digest-intro">
        <p class="meta">Updated ${escapeHtml(doc.generated_at || "—")}</p>
      </section>
      <p class="status">No filing summaries yet - these are only generated for this week's per-sector finalists
      (see <a href="index.html">Top Performers</a>), and this week's run may not have produced any (or ran with
      --skip-ai).</p>
    `;
  }
  return `
    <section class="digest-intro">
      <p class="meta">Updated ${escapeHtml(doc.generated_at)} &middot; ${entries.length} of this week's
      finalists have an AI-summarized filing below. No new fetching happens for this page - it's the same
      10-K/10-Q/8-K summaries already generated for each finalist's own company page, gathered in one place.</p>
    </section>
    <div class="digest-entries">${entries.map(renderEntry).join("")}</div>
  `;
}

function renderEntry(entry) {
  const filings = entry.sec_filings || [];
  return `
    <section class="digest-entry">
      <h3><a href="company.html?ticker=${encodeURIComponent(entry.ticker)}">${escapeHtml(entry.ticker)} &mdash; ${escapeHtml(entry.name)}</a>
      <span class="meta">${escapeHtml(entry.sector || "—")}</span></h3>
      ${renderFilingsSection(filings, entry.qualitative)}
    </section>
  `;
}

main();

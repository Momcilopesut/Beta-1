import { escapeHtml, renderDisclaimerFooter } from "./shared.js";
import { METRIC_GLOSSARY } from "./metrics-glossary.js";

function render() {
  const cards = METRIC_GLOSSARY.map(
    (m) => `
      <article class="glossary-card">
        <h3>${escapeHtml(m.label)}</h3>
        <p><strong>What it is:</strong> ${escapeHtml(m.explanation)}</p>
        <p><strong>Why it matters:</strong> ${escapeHtml(m.significance)}</p>
        <p><strong>How it moves the business:</strong> ${escapeHtml(m.volatilityImpact)}</p>
      </article>
    `
  ).join("");

  return `
    <section class="glossary-intro">
      <h2>Metrics Glossary</h2>
      <p class="meta">Every metric this tool scores on - what it is, why it matters economically, and how swings in it
      actually affect the business, not just the number. Every company page also shows these values in context under
      "Key Metrics Reference," with the same explanations one click away.</p>
    </section>
    <div class="glossary-grid">${cards}</div>
  `;
}

function main() {
  document.getElementById("content").innerHTML = render();
  renderDisclaimerFooter();
}

main();

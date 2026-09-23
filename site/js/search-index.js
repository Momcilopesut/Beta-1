// A tiny, dependency-free search index over {ticker, name, sector} rows -
// this app's "database and indexing system" for ticker/company lookup. At
// the scale this app tracks (hundreds to low thousands of companies), a
// plain array scan is sub-millisecond in a browser; this module exists to
// give that scan one well-defined place and a consistent ranking - exact
// ticker match, then ticker-prefix, then ticker-substring, then
// name-starts-with, then name-substring - rather than scattering ad hoc
// filtering logic across pages.

export function buildSearchIndex(companies) {
  return companies.map((c) => ({
    ticker: c.ticker,
    name: c.name,
    sector: c.sector,
    tickerLower: c.ticker.toLowerCase(),
    nameLower: (c.name || "").toLowerCase(),
  }));
}

export function search(index, query, limit = 8) {
  const q = query.trim().toLowerCase();
  if (!q) return [];

  let exact = null;
  const tickerPrefix = [];
  const tickerSubstring = [];
  const nameStartsWith = [];
  const nameSubstring = [];

  for (const entry of index) {
    if (entry.tickerLower === q) {
      exact = entry;
    } else if (entry.tickerLower.startsWith(q)) {
      tickerPrefix.push(entry);
    } else if (entry.tickerLower.includes(q)) {
      tickerSubstring.push(entry);
    } else if (entry.nameLower.startsWith(q)) {
      nameStartsWith.push(entry);
    } else if (entry.nameLower.includes(q)) {
      nameSubstring.push(entry);
    }
  }

  return [exact, ...tickerPrefix, ...tickerSubstring, ...nameStartsWith, ...nameSubstring]
    .filter(Boolean)
    .slice(0, limit);
}

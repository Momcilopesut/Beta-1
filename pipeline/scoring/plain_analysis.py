"""Plain-language positives and things to worry about, computed straight
from this company's already-fetched metrics - no AI call, no jargon, one
short sentence per clear signal, written the way you'd explain it to
someone who has never read a balance sheet.

Replaces the earlier "Layered Analysis" section
(pipeline/scoring/aggregation.py, since removed), which combined the
quality checklist, the qualitative moat read, and the valuation gate into
one page section with a blended "overall" verdict. This module does
something narrower and simpler instead: it only looks at plain numbers
already sitting in the metrics dict and states what each one means in
everyday words - it never reads AI-generated text and never blends
multiple numbers into one judgment.

Each check below is independent, same philosophy as the rest of this
pipeline's scoring (see pipeline/scoring/value_investing.py): a metric
that's clearly good gets one positive sentence, a metric that's clearly
bad gets one worry sentence, and a metric with no data or an unclear,
in-between reading gets neither - a company doesn't have to be praised or
criticized on every single number just to fill out a list.

The 10th check (moat) is this pipeline's replacement for the old AI-read
moat classification: instead of asking Claude to read the 10-K and
classify the moat type, it checks whether the business earns more than
its own cost of capital (value_creation_pct - pipeline.scoring.
capital_efficiency.company_value_creation_pct), a quantitative proxy for
"does this business have a durable edge over its competitors" that costs
no AI call at all. It won't name what KIND of moat (network effects vs.
cost advantage vs. switching costs, etc.) - that classification genuinely
needs to read the business's own filing text, which is exactly what an
AI call is for - but it answers the more fundamental question this
pipeline actually cares about: is that edge, if it exists, still showing
up in the numbers.
"""


def build_plain_analysis(metrics: dict) -> dict:
    """Returns {"positives": [str, ...], "worries": [str, ...]}, both
    possibly empty (e.g. a company with too little data, or one that's
    simply unremarkable on every check below)."""
    positives: list[str] = []
    worries: list[str] = []

    def add_positive(text: str) -> None:
        positives.append(text)

    def add_worry(text: str) -> None:
        worries.append(text)

    # 1. Net worth - the single most basic question this whole tool is
    # built around: if the company sold everything it owns and paid off
    # everything it owes, would there be anything left over?
    shareholders_equity = metrics.get("shareholders_equity")
    if shareholders_equity is not None:
        if shareholders_equity > 0:
            add_positive(
                "If this company sold everything it owns and paid off everything it owes, there would be "
                "real money left over. It owns more than it owes."
            )
        else:
            add_worry(
                "If this company had to sell everything it owns and pay off everything it owes, there "
                "would be nothing left over - it actually owes more than it owns."
            )

    # 2. Debt load - money it has borrowed, compared to what the business
    # itself is actually worth. Debt has to be paid back no matter how
    # business is going, so a lot of it makes the company more fragile.
    debt_to_equity = metrics.get("debt_to_equity")
    if debt_to_equity is not None:
        if debt_to_equity <= 1.0:
            add_positive(
                "It hasn't borrowed too much money - what it owes is less than what the business itself "
                "is worth."
            )
        elif debt_to_equity > 2.0:
            add_worry(
                "It has borrowed a lot of money - what it owes is more than twice what the business "
                "itself is worth, which makes it riskier if things go wrong."
            )

    # 3. Can it pay its bills soon? Cash and other easy-to-sell things it
    # has, compared to the bills it needs to pay in the next year.
    current_ratio = metrics.get("current_ratio")
    if current_ratio is not None:
        if current_ratio >= 2.0:
            add_positive(
                "It has plenty of cash and other easy-to-sell things on hand - more than twice enough "
                "to cover the bills it owes over the next year."
            )
        elif current_ratio < 1.0:
            add_worry(
                "It might not have enough cash or easy-to-sell things on hand to cover the bills it "
                "owes soon."
            )

    # 4. Does the business actually make good money on everything it
    # uses to run itself, its own money and borrowed money together?
    roic_pct = metrics.get("roic_pct")
    if roic_pct is not None:
        if roic_pct >= 15:
            add_positive(
                "For every $100 it uses to run the business - its own money and borrowed money "
                "together - it makes back more than $15 in profit each year. That's a strong return."
            )
        elif roic_pct < 0:
            add_worry("Counting all the money it uses to run the business, it isn't making any profit right now.")

    # 5. Room to raise prices - how much of every sale is left after the
    # direct cost of making or providing what it sells.
    gross_margin_pct = metrics.get("gross_margin_pct")
    if gross_margin_pct is not None:
        if gross_margin_pct >= 40:
            add_positive(
                "It keeps a big chunk of every dollar it makes in sales, after paying the direct cost "
                "of making or providing what it sells - that gives it room to handle rising costs "
                "without hurting its profits much."
            )
        elif gross_margin_pct < 15:
            add_worry(
                "It keeps very little of each dollar it makes in sales after paying the direct cost of "
                "making or providing what it sells, so even a small rise in costs could hurt its "
                "profits a lot."
            )

    # 6. Growth - is the profit behind each share of stock actually
    # getting bigger over time, or smaller?
    eps_growth_cagr_3yr_pct = metrics.get("eps_growth_cagr_3yr_pct")
    if eps_growth_cagr_3yr_pct is not None:
        if eps_growth_cagr_3yr_pct >= 10:
            add_positive("The profit behind each share of stock has been growing at a healthy pace over the last few years.")
        elif eps_growth_cagr_3yr_pct < 0:
            add_worry("The profit behind each share of stock has actually been shrinking over the last few years, not growing.")

    # 7. Real cash left over - accounting profit can be flattered by
    # non-cash items, so this checks the cash the business actually has
    # left after paying for everything it needs to run and grow.
    fcf_margin_pct = metrics.get("fcf_margin_pct")
    if fcf_margin_pct is not None:
        if fcf_margin_pct >= 15:
            add_positive("After paying for everything it needs to run and grow the business, it still has real cash left over from its sales.")
        elif fcf_margin_pct < 0:
            add_worry("After paying for everything it needs to run and grow the business, it's actually spending more cash than it's bringing in.")

    # 8. Margin trend - is the share of each sale it keeps as profit
    # getting better or worse over the last few years? (20 = declining,
    # 60 = stable, 100 = improving - see fundamentals.py.)
    margin_trend_score = metrics.get("margin_trend_score")
    if margin_trend_score is not None:
        if margin_trend_score >= 100:
            add_positive("The share of each sale it gets to keep as profit has been getting better over the last few years.")
        elif margin_trend_score <= 20:
            add_worry("The share of each sale it gets to keep as profit has been getting worse over the last few years.")

    # 9. Is the price fair? A simple estimate of what the business is
    # roughly worth (from its profit and what it owns, no growth
    # projections), compared to what the stock actually costs today.
    graham_upside_pct = metrics.get("graham_upside_pct")
    if graham_upside_pct is not None:
        if graham_upside_pct >= 15:
            add_positive(
                "Using simple math based on its profit and what it owns, the stock looks priced well "
                "below what the business is roughly worth - a real discount."
            )
        elif graham_upside_pct < 0:
            add_worry(
                "Using simple math based on its profit and what it owns, the stock looks priced above "
                "what the business is roughly worth - you'd be paying more than the simple math says "
                "it's worth."
            )

    # 10. Moat: does this business earn more than its money actually costs
    # to raise (through debt or investors)? A business that doesn't have
    # some real edge over its competitors - a moat - usually sees them
    # copy what works until its profit gets competed down to roughly what
    # its capital costs. Earning meaningfully more than that, year after
    # year, is what a durable edge actually looks like in numbers - see
    # pipeline.scoring.capital_efficiency.company_value_creation_pct for
    # the ROIC-minus-cost-of-capital math behind this. A dead zone around
    # zero (+/-0.5 percentage points, matching the same market-wide read
    # on the macro page) reads as neither, rather than a hair-trigger flip.
    value_creation_pct = metrics.get("value_creation_pct")
    if value_creation_pct is not None:
        if value_creation_pct > 0.5:
            add_positive(
                "This business makes more profit on the money it uses than that money actually costs to "
                "raise, whether borrowed or put in by investors. That's a real edge over competitors - "
                "something people call a 'moat.'"
            )
        elif value_creation_pct < -0.5:
            add_worry(
                "This business makes less profit on the money it uses than that money actually costs to "
                "raise. That usually means competitors aren't held back from doing the same thing it "
                "does - no real moat protecting it."
            )

    return {"positives": positives, "worries": worries}

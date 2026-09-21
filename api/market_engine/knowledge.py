"""What is known about how this market works — principles, each with its
source and what it means for someone buying NIFTY options.

This is the research behind docs/MARKET_RESEARCH.md, in a form the engine
and the copilot can use. Every figure in it is a published one with its
source attached; nothing here is computed by this system, and nothing here
is a prediction. Where this system has measured something on its own data,
the measurement lives in the engine's studies, not here.
"""

KNOWLEDGE = [
    {
        "id": "prices_aggregate_information",
        "section": "How markets work",
        "title": "A price is a summary of what everyone knows",
        "principle": ("Prices move as traders act on information, so a market price aggregates knowledge no single "
                      "participant holds. In the strong form of the efficient-market view, price already reflects "
                      "all available information and no one can predict it from public data."),
        "for_you": ("If a pattern visible on a public chart reliably made money, the traders who can act fastest "
                    "would trade it until it stopped. That is the first reason every pattern here was rejected."),
        "sources": ["Hayek (1945), 'The Use of Knowledge in Society', American Economic Review",
                    "Fama (1970), 'Efficient Capital Markets: A Review of Theory and Empirical Work', Journal of Finance"],
    },
    {
        "id": "efficiency_is_never_complete",
        "section": "How markets work",
        "title": "Markets cannot be perfectly efficient — someone is paid to make them nearly so",
        "principle": ("If prices reflected everything, no one would pay to gather information, and then prices "
                      "could not reflect it. So markets settle where those with better information, faster "
                      "execution or more capital earn just enough to cover their costs."),
        "for_you": ("People do make money — but mostly by being paid for something: information, speed, capital, "
                    "or bearing a risk others will pay to be rid of. The question for any trade is which of those "
                    "you are being paid for."),
        "sources": ["Grossman & Stiglitz (1980), 'On the Impossibility of Informationally Efficient Markets', "
                    "American Economic Review", "Lo (2004), 'The Adaptive Markets Hypothesis', Journal of Portfolio "
                    "Management"],
    },
    {
        "id": "microstructure",
        "section": "How markets work",
        "title": "Every trade crosses a spread, and the spread pays for the risk of trading with someone who knows more",
        "principle": ("Market makers quote a price to buy and a higher one to sell. The gap compensates them for "
                      "the chance that the person trading with them knows something they do not. Informed traders "
                      "move prices gradually as they trade."),
        "for_you": ("Each round trip on an option pays that spread twice. This system charges 1.5% of premium a "
                    "side for it — often the largest single cost in a short option trade."),
        "sources": ["Kyle (1985), 'Continuous Auctions and Insider Trading', Econometrica",
                    "Glosten & Milgrom (1985), 'Bid, Ask and Transaction Prices in a Specialist Market with "
                    "Heterogeneously Informed Traders', Journal of Financial Economics"],
    },
    {
        "id": "noise_traders",
        "section": "How markets work",
        "title": "Most trading is noise, and noise is what pays those with an edge",
        "principle": ("Many trades are made on information that is not really information. That noise is what "
                      "makes markets liquid and what informed traders profit from — and noise can push prices "
                      "further from value than rational traders dare bet against."),
        "for_you": "Trading on a chart pattern with no demonstrated edge is, by this definition, noise trading.",
        "sources": ["Black (1986), 'Noise', Journal of Finance",
                    "De Long, Shleifer, Summers & Waldmann (1990), 'Noise Trader Risk in Financial Markets', "
                    "Journal of Political Economy"],
    },
    {
        "id": "behaviour",
        "section": "How markets work",
        "title": "People weigh losses more than gains and overpay for long shots",
        "principle": ("Losses hurt about twice as much as equal gains please, and small probabilities are "
                      "overweighted. Investors pay up for lottery-like payoffs; momentum and overreaction are "
                      "documented in prices."),
        "for_you": ("Cheap out-of-the-money options are lottery tickets, and the evidence is that buyers overpay "
                    "for them. Individual traders who trade more tend to earn less."),
        "sources": ["Kahneman & Tversky (1979), 'Prospect Theory', Econometrica",
                    "Barberis & Huang (2008), 'Stocks as Lotteries', American Economic Review",
                    "Jegadeesh & Titman (1993), 'Returns to Buying Winners and Selling Losers', Journal of Finance",
                    "Barber & Odean (2000), 'Trading Is Hazardous to Your Wealth', Journal of Finance"],
    },
    {
        "id": "who_makes_money",
        "section": "Who makes money",
        "title": "In Indian equity derivatives, individuals lose and institutions with algorithms win",
        "principle": ("SEBI measured it on client-level data. 93% of individual F&O traders lost money over FY22-FY24, "
                      "₹1.8 lakh crore in total. In FY24 proprietary traders made ₹33,000 crore and FPIs ₹28,000 "
                      "crore gross, 96% and 97% of it through algorithms. In FY26, 87.7% of individuals lost, "
                      "₹91,685 crore in total, 92% of it on options, and about 59% of index-options turnover was in "
                      "contracts expiring that day."),
        "for_you": ("The base rate for an individual buying index options is a loss. Any strategy has to explain "
                    "why it would be in the minority — this system's research has not found one that is."),
        "sources": ["SEBI (Sep 2024), study of individual traders in equity F&O, FY22-FY24",
                    "SEBI (Aug 2026), 'Profitability of Individual Traders in the Equity Derivatives Segment (FY25-FY26)'"],
    },
    {
        "id": "variance_risk_premium",
        "section": "Who makes money",
        "title": "Options are usually priced for more movement than arrives — sellers collect the difference",
        "principle": ("Implied volatility exceeds the volatility that follows most of the time, because buyers "
                      "pay for protection and for the chance of a big move. Selling options earns that premium "
                      "steadily and loses it violently in crashes. Buying at-the-money option pairs has lost money "
                      "on average in the US index."),
        "for_you": ("An option buyer starts each trade paying this premium, on top of the spread and costs. It is "
                    "measured on NIFTY in this engine's studies."),
        "sources": ["Carr & Wu (2009), 'Variance Risk Premiums', Review of Financial Studies",
                    "Bakshi & Kapadia (2003), 'Delta-Hedged Gains and the Negative Market Volatility Risk "
                    "Premium', Review of Financial Studies",
                    "Coval & Shumway (2001), 'Expected Option Returns', Journal of Finance"],
    },
    {
        "id": "what_moves_nifty",
        "section": "What moves NIFTY",
        "title": "Global cues, flows, policy, the rupee, oil and a handful of heavyweight stocks",
        "principle": ("NIFTY opens on the back of overnight US and Asian markets, moves with foreign and domestic "
                      "institutional flows, reacts to RBI policy and inflation, to the rupee and crude oil (India "
                      "imports most of its oil), and to results from its largest constituents. Expiry-day "
                      "positioning adds its own intraday flows."),
        "for_you": ("How much of a given day global cues account for is measured in this engine, and it is less "
                    "than headlines suggest: most daily movement is domestic, or noise."),
        "sources": ["See this engine's 'why it moved' attribution and its year-by-year fit"],
    },
    {
        "id": "the_law",
        "section": "Rules",
        "title": "What Indian law forbids: fraud, manipulation, insider trading",
        "principle": ("The SEBI Act 1992 (section 12A) prohibits manipulative and deceptive devices and insider "
                      "trading. The PFUTP Regulations 2003 list manipulative practices — trades that create a false "
                      "appearance of activity, that move prices to profit elsewhere, circular and synchronised "
                      "trades. The PIT Regulations 2015 govern insider trading. The Securities Contracts "
                      "(Regulation) Act 1956 governs exchanges and contracts."),
        "for_you": ("Trading on a rumour someone planted, or in a stock being pumped on social media, can leave "
                    "you holding the losses of someone else's violation — the law protects the market, not your "
                    "position."),
        "sources": ["SEBI Act 1992, s.11 and s.12A", "SEBI (Prohibition of Fraudulent and Unfair Trade Practices "
                    "relating to Securities Market) Regulations 2003", "SEBI (Prohibition of Insider Trading) "
                    "Regulations 2015"],
    },
    {
        "id": "cases",
        "section": "Rules",
        "title": "The cases that define the lines",
        "principle": ("SEBI v Rakhi Trading (Supreme Court, 2018): synchronised, reversed trades in NIFTY options "
                      "were held manipulative — reversing the tribunal's view that an index this large could not "
                      "be influenced — because they misuse the market mechanism, whatever their size. Sadhna "
                      "Broadcast (SEBI, 2023): misleading YouTube videos, paid promotion, then selling into the "
                      "buying they caused. Jane Street (SEBI interim order, July 2025): alleged manipulation of Bank "
                      "Nifty on 18 expiry days between January 2023 and March 2025 — buying constituents in the "
                      "morning, selling into the close while holding options that gained; ₹4,843.57 crore "
                      "impounded; contested before the Securities Appellate Tribunal."),
        "for_you": ("Manipulation happens at every scale, from a Telegram pump in a small stock to an "
                    "institutional expiry-day trade in an index. The Jane Street allegations are allegations; "
                    "the appeal was still being heard in 2026."),
        "sources": ["SEBI v Rakhi Trading Pvt Ltd, Supreme Court of India, 8 Feb 2018",
                    "SEBI interim order, Sadhna Broadcast Ltd, March 2023",
                    "SEBI interim order, Jane Street Group, 3 July 2025"],
    },
    {
        "id": "rule_changes",
        "section": "Rules",
        "title": "Since November 2024, index derivatives are harder to gamble on",
        "principle": ("SEBI circular of 1 October 2024: minimum contract size ₹15 lakh, one weekly expiry per "
                      "exchange (NSE kept NIFTY), option premium collected upfront from buyers, no calendar-spread "
                      "margin benefit on expiry day, intraday monitoring of position limits. NIFTY's weekly expiry "
                      "moved from Thursday to Tuesday from September 2025."),
        "for_you": "History before and after these changes is not one market. Evidence from 2018-2024 may not carry over.",
        "sources": ["SEBI circular SEBI/HO/MRD/TPD-1/P/CIR/2024/132, 1 October 2024"],
    },
    {
        "id": "philosophy",
        "section": "Philosophy",
        "title": "Speculation is useful to the market and usually costly to the speculator",
        "principle": ("Speculators supply liquidity and carry risk others want to shed, which is why markets "
                      "allow them. But a price set by traders guessing what other traders will think — Keynes's "
                      "beauty contest — can drift far from value, and returns have fatter tails than normal "
                      "models assume. Regulators aim for markets that are fair, efficient and transparent; "
                      "efficient is not the same as fair to every participant."),
        "for_you": ("A system that says 'no trade' most days is not failing. The market does not owe any "
                    "participant a return, and the honest default for an individual is no edge."),
        "sources": ["Keynes (1936), The General Theory, chapter 12",
                    "Mandelbrot (1963), 'The Variation of Certain Speculative Prices', Journal of Business",
                    "IOSCO, 'Objectives and Principles of Securities Regulation'"],
    },
    {
        "id": "manipulation_types",
        "section": "Manipulation",
        "title": "How manipulation works, and how it reaches you",
        "principle": ("Information-based: false news, pump-and-dump through social media. Trade-based: wash and "
                      "circular trades that fake activity; spoofing and layering (orders placed to be cancelled); "
                      "marking the close; moving an index or stock to profit on a larger derivatives position "
                      "elsewhere. Trade-based manipulation can be profitable even without false information."),
        "for_you": ("An index-options buyer meets it mainly on expiry day, when a large book can profit from "
                    "where the index settles. Red flags: a sharp move reversed into the close on expiry; heavy, "
                    "unusual volume in one strike; a close pinned at a big strike; any 'sure-shot' tip."),
        "sources": ["Allen & Gale (1992), 'Stock-Price Manipulation', Review of Financial Studies",
                    "Aggarwal & Wu (2006), 'Stock Market Manipulations', Journal of Business",
                    "Comerton-Forde & Putnins (2011), 'Measuring Closing Price Manipulation', Journal of "
                    "Financial Intermediation", "Ni, Pearson & Poteshman (2005), 'Stock Price Clustering on Option "
                    "Expiration Dates', Journal of Financial Economics"],
    },
]


def by_section() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for k in KNOWLEDGE:
        out.setdefault(k["section"], []).append(k)
    return out

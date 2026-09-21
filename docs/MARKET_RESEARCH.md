# How this market works — and who makes money in it

Research compiled 2026-09-22 for the question the pattern research left open: *every signal here
was rejected, yet people make money in this market — how?* Figures are either published (with
their source) or **measured on this system's own data** (marked as such, and reproducible with
`python scripts/market_research.py`). The engine built from this research lives in
`api/market_engine/` and the dashboard's **Market** tab.

## The short answer

In Indian equity derivatives, **individuals lose, and the money goes mainly to institutions that
trade with algorithms and to whoever sells options.** SEBI measured this on client-level data:

| | |
|---|---|
| FY22–FY24 | 93% of individual F&O traders lost money; ₹1.8 lakh crore in total; about 1% made more than ₹1 lakh after costs |
| FY24 | Proprietary traders made ₹33,000 crore gross, FPIs ₹28,000 crore — 96% and 97% of it through algorithms |
| FY25 | 91% of individuals lost; net losses ₹1,05,603 crore |
| FY26 | 87.7% lost; ₹91,685 crore in total, 92% of it on options; about 59% of index-options turnover was in contracts expiring that same day; about ₹25,000 crore paid in transaction costs |

People who make money are, broadly, **being paid for something**: bearing risk others want to shed
(option sellers), supplying liquidity (market makers, paid through the spread), speed and scale
(algorithmic desks), information, or — illegally — moving prices. Measured on this system's data:

- **Options are usually priced for more movement than arrives.** Over 2,126 days (2018–2026), 30-day
  implied volatility averaged 15.7% and the volatility that then arrived 14.5%; options were priced
  above what followed on **71% of days**, every year between 60% and 81%. That gap is what sellers
  collect and buyers pay. It is a premium for risk, not free money: in February–March 2020 options
  priced about 16–24% volatility and the market delivered about 80–88%, and across 2020 as a whole the
  premium disappeared (25.0% implied, 25.3% delivered).
- **Simply buying options lost money.** Buying each pattern's chosen option on a fixed schedule over
  2024–26, with no signal at all, lost a median ₹959 per lot after costs; 1 of 20 setups made money.
  That is the bar every pattern had to clear, and none did.

So the rejection of every pattern is not an accident of this system. It is the expected result for
someone *buying* index options on public information: the buyer starts every trade paying the
volatility premium, the spread twice, and costs — and competes with desks that are faster and
better informed.

## 1. How markets work — the principles

**A price summarises what everyone knows.** Traders acting on information move prices, so a price
aggregates knowledge no single participant holds (Hayek 1945). In its strongest form, the efficient-
market view says public information is already in the price (Fama 1970). *For you:* a pattern on a
public chart that reliably made money would be traded away by those who can act faster — the first
reason every pattern here was rejected.

**Efficiency is never complete — someone is paid to make it nearly so.** If prices reflected
everything, no one would pay to gather information, and then they could not reflect it (Grossman &
Stiglitz 1980). Markets settle where those with better information, speed or capital earn roughly
their costs, and the balance shifts as participants adapt (Lo 2004, the adaptive-markets view).
*For you:* the question for any trade is what you are being paid for.

**Every trade crosses a spread.** Market makers quote a bid and a higher ask; the gap compensates
them for trading with people who may know more (Glosten & Milgrom 1985), and informed traders move
prices gradually as they trade (Kyle 1985). *For you:* a round trip pays the spread twice. This
system charges 1.5% of premium a side for it — often the largest single cost of a short option trade.

**Most trading is noise, and noise pays the informed.** Trades made on information that is not really
information supply the liquidity others profit from (Black 1986), and can push prices further from
value than rational traders dare bet against (De Long, Shleifer, Summers & Waldmann 1990).

**Behaviour leaves marks in prices.** Losses hurt about twice as much as equal gains please, and small
probabilities are overweighted (Kahneman & Tversky 1979); investors overpay for lottery-like payoffs
(Barberis & Huang 2008); momentum is documented (Jegadeesh & Titman 1993); individuals who trade more
earn less (Barber & Odean 2000). *For you:* a cheap out-of-the-money option is a lottery ticket, and
the evidence is that buyers overpay for them.

**Option sellers earn a premium for crash risk.** Implied volatility usually exceeds what follows
(Carr & Wu 2009); delta-hedged option buyers lose on average (Bakshi & Kapadia 2003); buying
at-the-money option pairs has lost money in the US index (Coval & Shumway 2001). Measured on NIFTY
above.

## 2. What moves NIFTY

Overnight US and Asian markets set the open; foreign (FPI) and domestic (DII) institutional flows,
RBI policy and inflation, the rupee, crude oil (India imports most of its oil) and results from the
largest constituents move it through the day; expiry-day positioning adds its own flows.

**Measured on this system's data: global cues explain less than the headlines suggest.** A
regression of NIFTY's daily return on the S&P 500, USD/INR and Brent — each taken from the last
session that closed *before* India opened, since a same-date US session had not happened yet —
explains between 1% (2019) and 17% (2022) of NIFTY's day-to-day movement, depending on the year. Most
daily movement is domestic, or noise. The dashboard's "Why it moved" card does this attribution for
the latest session, fitted only on the year before it.

**Who holds what (measured: NSE participant-wise open interest, 1,913 sessions, 2019–2026).** Every
contract held long is held short by someone — the file balances to within 2 contracts out of millions
on every day, the remainder being NSE's rounding. Retail ("Client") has been net long index futures
on 74% of days; FIIs on 41%; proprietary desks on 39%. **One caution:** open interest is what is held
at the close. Most retail option buying is intraday — the 59% of turnover in same-day contracts never
reaches the close — so this data shows who carries risk overnight, not who wins. The evidence on who
wins is SEBI's.

## 3. Jurisprudence — what the law forbids, and the cases that draw the lines

**The statutes.** The SEBI Act 1992 (s.11 on SEBI's powers, s.12A prohibiting manipulative and
deceptive devices and insider trading); the Securities Contracts (Regulation) Act 1956 governing
exchanges and contracts; the **PFUTP Regulations 2003** (Prohibition of Fraudulent and Unfair Trade
Practices), whose regulation 4 lists manipulative practices — trades creating a false appearance of
activity, circular and synchronised trades, moving prices to profit elsewhere; and the **PIT
Regulations 2015** on insider trading.

**The cases.**

- **SEBI v Rakhi Trading (Supreme Court, 8 February 2018).** Synchronised trades in NIFTY options,
  reversed to shift profits between parties, were held manipulative. The Securities Appellate
  Tribunal had reasoned that NIFTY is too large and diversified to be influenced; the Court held that
  such trades misuse the market mechanism and harm market integrity whatever their size, and that
  SEBI's role is market integrity, not only preventing price manipulation.
- **Sadhna Broadcast (SEBI, March 2023; confirmed July 2023).** Misleading YouTube videos promoted a
  small stock with paid advertising; the promoters sold into the buying the videos caused. About ₹42
  crore of alleged unlawful gains; 31 entities initially barred. The template of the social-media
  pump-and-dump.
- **Jane Street (SEBI interim order, 3 July 2025).** Alleged manipulation of **Bank Nifty** on 18
  expiry days between January 2023 and March 2025: buying index constituents and futures heavily in
  the morning, then selling aggressively into the close while holding options that gained from the
  fall. ₹4,843.57 crore was impounded and deposited; the firm was barred pending proceedings and has
  contested the order before the Securities Appellate Tribunal — hearings were being adjourned in
  February 2026. **These are allegations, not findings on appeal.**

**The 2024 rule changes.** SEBI's circular of 1 October 2024 raised the minimum contract size to
₹15 lakh, allowed one weekly expiry per exchange (NSE kept NIFTY), required option premium to be
collected upfront from buyers, removed the calendar-spread margin benefit on expiry day, and added
intraday monitoring of position limits. NIFTY's weekly expiry moved from Thursday to Tuesday from
September 2025. *For you:* the market before and after November 2024 is not one market; evidence from
2018–2024 may not carry over.

## 4. Philosophy — why markets allow speculation, and what "fair" means

Speculators supply liquidity and carry risk others want to shed — which is why regulators permit
them — and it is how prices come to aggregate information. But a price set by traders guessing what
other traders will think can drift far from value (Keynes's beauty contest, *General Theory* ch. 12),
and returns have fatter tails than normal models assume (Mandelbrot 1963). Securities regulation aims
at three things (IOSCO): protecting investors; markets that are fair, efficient and transparent; and
reducing systemic risk. **Efficient is not the same as fair to every participant**: an efficient
market can transfer money steadily from the less informed to the better informed, which is what the
SEBI studies describe. *For you:* the market owes no participant a return. A system that says "no
trade" most days is not failing; the honest default for an individual is no edge.

## 5. Manipulation — how it works, how it reaches you, how to spot it

**Kinds.** *Information-based:* false news and rumours; pump-and-dump through social media (Sadhna
Broadcast). *Trade-based:* wash and circular trades that fake activity; spoofing and layering (orders
placed in order to be cancelled); marking the close; moving an index or stock to profit on a larger
derivatives position elsewhere (the Jane Street allegation). Trade-based manipulation can be
profitable even without any false information (Allen & Gale 1992); manipulators tend to target
illiquid stocks and periods of low scrutiny (Aggarwal & Wu 2006).

**How it reaches an index-options buyer.** Mainly on expiry day, when a large options book can profit
from where the index settles. The settlement price is the average of the last 30 minutes, which makes
that window valuable to push (the closing-price manipulation Comerton-Forde & Putnins 2011 measure),
and prices tend to cluster at strikes on expiry (Ni, Pearson & Poteshman 2005) — through lawful
hedging as well as manipulation.

**What this system can and cannot see.** Detecting manipulation properly needs order- and client-level
data, which only exchanges and SEBI have. With index bars and end-of-day option data, the engine
measures the *footprints* manipulation would leave, and treats them as statistics about the market,
never evidence against anyone. **Measured on NIFTY (2018–2026, 413 expiry sessions against 1,718
others):**

| Footprint | Expiry days | Other days | Test |
|---|---|---|---|
| A morning move of 0.4%+ largely reversed in the afternoon | 5.1% | 5.8% | z = −0.58 |
| Size of the last-30-minute move | 0.167% | 0.158% | t = 1.12 |
| Close within 5 points of a 50-point strike (chance: 20%) | 22.5% | 18.4% | z = 1.91 |

In January 2023–March 2025, the window SEBI's Jane Street order covers, NIFTY showed no reversal
footprint on expiry days (z = 0.47). The only comparison reaching 2 in twelve is the last-30-minute
move after March 2025 (t = 2.07), about what twelve comparisons produce by chance. **Honest summary:
NIFTY's index-level data shows at most a mild tendency to close near strikes on expiry — the direction
the literature reports — and no clear manipulation footprint.** The Jane Street case concerned Bank
Nifty, which this archive does not cover.

**Red flags for you.** A "sure-shot" tip or a paid group; a stock promoted on social media with
comments switched off; a sharp move reversed into the close on expiry day; heavy, unusual volume
concentrated in one strike; any strategy whose explanation is that someone else will move the price
for you. The engine's unusual-activity monitor compares each strike's share of volume with the same
point before expiry in the previous 20 expiries — its first version compared strikes with their own
earlier days and flagged everything the day before expiry, because volume always floods into the
nearest strikes then.

## Sources

**Regulators and courts**
- SEBI, [updated study of individual traders in equity F&O, FY22–FY24](https://www.sebi.gov.in/media-and-notifications/press-releases/sep-2024/updated-sebi-study-reveals-93-of-individual-traders-incurred-losses-in-equity-fando-between-fy22-and-fy24-aggregate-losses-exceed-1-8-lakh-crores-over-three-years_86906.html) (Sep 2024); FY24 proprietary/FPI profits as reported by [Wright Research](https://www.wrightresearch.in/blog/sebi-futures-and-option-report-individual-traders-in-fandos-incur-rs-18-lakh-crore-loss-over-3-years/)
- SEBI, [Profitability of Individual Traders in the Equity Derivatives Segment (FY25–FY26)](https://www.sebi.gov.in/reports-and-statistics/research/aug-2026/study-profitability-of-individual-traders-in-the-equity-derivatives-segment-fy25-fy26-_103835.html) (Aug 2026); FY25 figures via [Business Standard](https://www.business-standard.com/markets/news/net-losses-of-traders-in-fo-widens-in-fy25-sebi-study-125070701221_1.html)
- SEBI, [circular SEBI/HO/MRD/TPD-1/P/CIR/2024/132](https://www.cse-india.com/upload/upload/Oct_011024.pdf), 1 Oct 2024; NSE expiry-day change, [NSE circular](https://nsearchives.nseindia.com/content/circulars/FAOP68747.pdf)
- SEBI, [interim order in the matter of index manipulation by Jane Street Group](https://www.sebi.gov.in/enforcement/orders/jul-2025/interim-order-in-the-matter-of-index-manipulation-by-jane-street-group_95040.html), 3 Jul 2025; appeal status: [Business Today](https://www.businesstoday.in/markets/story/jane-street-vs-sebi-sat-adjourns-hearing-in-market-manipulation-case-517925-2026-02-25), Feb 2026
- SEBI, [interim order, Sadhna Broadcast Ltd](https://www.sebi.gov.in/enforcement/orders/mar-2023/interim-order-in-the-matter-of-stock-recommendations-using-youtube-in-the-scrip-of-sadhna-broadcast-limited_68595.html) (Mar 2023) and [confirmatory order](https://www.sebi.gov.in/enforcement/orders/jul-2023/confirmatory-order-in-the-matter-of-stock-recommendations-using-youtube-in-the-scrip-of-sadhna-broadcast-limited_74217.html) (Jul 2023)
- Supreme Court of India, [SEBI v Rakhi Trading Pvt Ltd](https://indiankanoon.org/doc/63300860/), 8 Feb 2018
- IOSCO, *Objectives and Principles of Securities Regulation*

**Academic**
- Aggarwal, R. & Wu, G. (2006). Stock market manipulations. *Journal of Business*.
- Allen, F. & Gale, D. (1992). Stock-price manipulation. *Review of Financial Studies*.
- Bakshi, G. & Kapadia, N. (2003). Delta-hedged gains and the negative market volatility risk premium. *Review of Financial Studies*.
- Barber, B. & Odean, T. (2000). Trading is hazardous to your wealth. *Journal of Finance*.
- Barberis, N. & Huang, M. (2008). Stocks as lotteries. *American Economic Review*.
- Black, F. (1986). Noise. *Journal of Finance*.
- Carr, P. & Wu, L. (2009). [Variance risk premiums](https://engineering.nyu.edu/sites/default/files/2019-01/CarrReviewofFinStudiesMarch2009-a.pdf). *Review of Financial Studies*.
- Comerton-Forde, C. & Putnins, T. (2011). Measuring closing price manipulation. *Journal of Financial Intermediation*.
- Coval, J. & Shumway, T. (2001). Expected option returns. *Journal of Finance*.
- De Long, J. B., Shleifer, A., Summers, L. & Waldmann, R. (1990). Noise trader risk in financial markets. *Journal of Political Economy*.
- Fama, E. (1970). Efficient capital markets: a review of theory and empirical work. *Journal of Finance*.
- Glosten, L. & Milgrom, P. (1985). Bid, ask and transaction prices in a specialist market with heterogeneously informed traders. *Journal of Financial Economics*.
- Grossman, S. & Stiglitz, J. (1980). On the impossibility of informationally efficient markets. *American Economic Review*.
- Hayek, F. (1945). The use of knowledge in society. *American Economic Review*.
- Jegadeesh, N. & Titman, S. (1993). Returns to buying winners and selling losers. *Journal of Finance*.
- Kahneman, D. & Tversky, A. (1979). Prospect theory. *Econometrica*.
- Keynes, J. M. (1936). *The General Theory of Employment, Interest and Money*, ch. 12.
- Kyle, A. (1985). Continuous auctions and insider trading. *Econometrica*.
- Lo, A. (2004). The adaptive markets hypothesis. *Journal of Portfolio Management*.
- Mandelbrot, B. (1963). The variation of certain speculative prices. *Journal of Business*.
- Ni, S., Pearson, N. & Poteshman, A. (2005). Stock price clustering on option expiration dates. *Journal of Financial Economics*.

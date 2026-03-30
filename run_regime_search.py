#!/usr/bin/env python3
"""
Regime-Aware Deep Strategy Search
Goal: Find conditions with WR >= 80% in BOTH bull and bear markets.
Data: 5 years (2021-2026), ~5M rows, TOPIX-based regime classification.

Phases:
  1. Singles: evaluate each filter in bull/bear separately
  2. Pairs: combine top singles from different groups
  3. Triples: add 3rd filter to top pairs
  4. Quads: add 4th filter to top triples
  5. Quints: add 5th filter to top quads
  6. Sort by min(bull_wr, bear_wr) descending — balanced winners first
"""
import sys, logging, time, json, pickle, gc, os
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stderr)
log = logging.getLogger("regime")
T0 = time.time()
SAVE_DIR = "quant_research/data"
TIME_LIMIT = 8 * 3600

HOLD_PERIODS = [20, 60, 120]

# ═══════════════════════════════════════════════════════════════
# LOAD DATA
# ═══════════════════════════════════════════════════════════════
log.info("Loading 5-year data...")
df = pd.read_pickle(f"{SAVE_DIR}/_intermediate_df_features.pkl")
N = len(df)
log.info(f"N={N:,} stocks={df['Code'].nunique()} date={df['Date'].min().date()}~{df['Date'].max().date()}")

# Load TOPIX for regime
topix = pd.read_parquet(f"{SAVE_DIR}/index_topix.parquet")
topix['Date'] = pd.to_datetime(topix['Date'])
topix = topix.sort_values('Date').reset_index(drop=True)
topix['topix_close'] = pd.to_numeric(topix['C'], errors='coerce')
topix['topix_ma200'] = topix['topix_close'].rolling(200).mean()
topix['regime'] = np.where(topix['topix_close'] >= topix['topix_ma200'], 'bull', 'bear')
df = df.merge(topix[['Date', 'regime']].dropna(), on='Date', how='left')
df['regime'] = df['regime'].fillna('unknown')

IS_BULL = (df["regime"] == "bull").values
IS_BEAR = (df["regime"] == "bear").values
log.info(f"Bull: {IS_BULL.sum():,}, Bear: {IS_BEAR.sum():,}")

# Train/Test split: train ~2024-07, test 2024-07~
split_date = pd.Timestamp("2024-07-01")
IS_TR = (df["Date"] <= split_date).values
IS_TE = (df["Date"] > split_date).values
log.info(f"Train: {IS_TR.sum():,}, Test: {IS_TE.sum():,}")

# Forward returns
for hd in HOLD_PERIODS:
    c = f"fwd_{hd}d_return"
    if c not in df.columns:
        df[c] = df.groupby("Code")["Close"].transform(lambda x: x.shift(-hd) / x - 1)

RET = {}
for hd in HOLD_PERIODS:
    v = df[f"fwd_{hd}d_return"].values
    RET[hd] = v
    RET[f"{hd}v"] = ~np.isnan(v)

# ═══════════════════════════════════════════════════════════════
# BUILD FILTER UNIVERSE (~300 filters)
# ═══════════════════════════════════════════════════════════════
log.info("Building filter universe...")

def mk(a, op, val):
    if op == ">=": return np.where(np.isnan(a), False, a >= val)
    if op == "<=": return np.where(np.isnan(a), False, a <= val)
    return a == val

def mkr(a, lo, hi):
    m = np.ones(N, dtype=bool)
    if lo is not None: m &= np.where(np.isnan(a), False, a >= lo)
    if hi is not None: m &= np.where(np.isnan(a), False, a <= hi)
    return m

AM = {}
GRP = {}

def add_filters(group_name, filters):
    keys = []
    for label, mask in filters:
        AM[label] = mask
        keys.append(label)
    GRP[group_name] = keys

# G1: Volume Ratio
vr = df["vol_ratio"].values
add_filters("VB", [
    (l, mkr(vr, lo, hi)) for lo, hi, l in [
        (None, 1.0, "VB<=1.0"), (None, 1.2, "VB<=1.2"), (None, 1.5, "VB<=1.5"),
        (0.5, 1.0, "VB0.5-1.0"), (0.5, 1.5, "VB0.5-1.5"),
        (1.0, 1.5, "VB1.0-1.5"), (1.0, 2.0, "VB1.0-2.0"),
        (1.2, 2.0, "VB1.2-2.0"), (1.3, 2.5, "VB1.3-2.5"),
        (1.5, 3.0, "VB1.5-3.0"), (1.5, None, "VB>=1.5"),
        (2.0, None, "VB>=2.0"),
    ]
])

# G2: RSI
rsi = df["rsi"].values
add_filters("RSI", [
    (l, mkr(rsi, lo, hi)) for lo, hi, l in [
        (20, 40, "RSI20-40"), (20, 50, "RSI20-50"), (20, 60, "RSI20-60"),
        (30, 50, "RSI30-50"), (30, 55, "RSI30-55"), (30, 60, "RSI30-60"),
        (30, 65, "RSI30-65"), (30, 70, "RSI30-70"),
        (40, 55, "RSI40-55"), (40, 60, "RSI40-60"), (40, 65, "RSI40-65"),
        (45, 55, "RSI45-55"), (50, 70, "RSI50-70"),
        (None, 40, "RSI<=40"), (None, 50, "RSI<=50"),
        (None, 55, "RSI<=55"), (None, 60, "RSI<=60"),
    ]
])

# G3: MA25 deviation
ma25 = df["ma25_dev"].values
add_filters("MA25", [
    (l, mkr(ma25, lo, hi)) for lo, hi, l in [
        (-0.05, 0.05, "MA25-5~5%"), (-0.05, 0.10, "MA25-5~10%"),
        (-0.03, 0.03, "MA25-3~3%"), (-0.03, 0.05, "MA25-3~5%"),
        (-0.03, 0.08, "MA25-3~8%"),
        (0.0, 0.03, "MA25_0~3%"), (0.0, 0.05, "MA25_0~5%"),
        (0.0, 0.08, "MA25_0~8%"), (0.0, 0.10, "MA25_0~10%"),
        (None, 0.05, "MA25<=5%"), (None, 0.10, "MA25<=10%"),
        (0.0, None, "MA25>=0%"),
    ]
])

# G4: PER
per = df["per"].fillna(9999).values
add_filters("PER", [
    (f"PER<={t}", (per > 0) & (per <= t)) for t in [3, 5, 7, 8, 10, 12, 15, 18, 20, 25, 30]
] + [
    (l, (per >= lo) & (per <= hi)) for lo, hi, l in [
        (3, 7, "PER3-7"), (5, 10, "PER5-10"), (5, 15, "PER5-15"),
        (8, 12, "PER8-12"), (8, 15, "PER8-15"), (8, 20, "PER8-20"),
        (10, 20, "PER10-20"), (10, 25, "PER10-25"),
    ]
])

# G5: PBR
pbr = df["pbr"].fillna(9999).values
add_filters("PBR", [
    (f"PBR<={t}", (pbr > 0) & (pbr <= t)) for t in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5, 2.0]
] + [
    (l, (pbr >= lo) & (pbr <= hi)) for lo, hi, l in [
        (0.3, 0.6, "PBR0.3-0.6"), (0.5, 1.0, "PBR0.5-1.0"),
        (0.5, 1.5, "PBR0.5-1.5"), (0.8, 1.5, "PBR0.8-1.5"),
    ]
])

# G6: Market Cap
mc = df["market_cap"].fillna(0).values
add_filters("MC", [
    (l, mkr(mc, lo, hi)) for lo, hi, l in [
        (5e9, None, "MC>=50億"), (10e9, None, "MC>=100億"),
        (20e9, None, "MC>=200億"), (50e9, None, "MC>=500億"),
        (100e9, None, "MC>=1000億"), (200e9, None, "MC>=2000億"),
        (500e9, None, "MC>=5000億"), (1e12, None, "MC>=1兆"),
        (5e9, 50e9, "MC50-500億"), (10e9, 100e9, "MC100-1000億"),
        (50e9, 500e9, "MC500-5000億"), (100e9, 1e12, "MC1000-1兆"),
        (None, 50e9, "MC<=500億"), (None, 100e9, "MC<=1000億"),
    ]
])

# G7: EPS growth
eps_v = df["eps_growth"].values
add_filters("EPS", [
    (f"EPS>={int(t*100)}%", mk(eps_v, ">=", t)) for t in [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 1.0]
])

# G8: OP growth
og = df["op_growth"].values
add_filters("OG", [
    (f"OG>={int(t*100)}%", mk(og, ">=", t)) for t in [0.0, 0.05, 0.10, 0.20, 0.30, 0.50]
])

# G9: ROE
roe_a = df["roe"].values
add_filters("ROE", [
    (f"ROE>={int(t*100)}%", mk(roe_a, ">=", t)) for t in [0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20]
])

# G10: ATR
atr_a = df["atr_pct"].values
add_filters("ATR", [
    (f"ATR<={t}", mk(atr_a, "<=", t)) for t in [0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05]
])

# G11: Volatility
vol = df["volatility"].values
add_filters("Vol", [
    (f"Vol<={t}", mk(vol, "<=", t)) for t in [0.01, 0.015, 0.02, 0.025, 0.03, 0.04]
])

# G12: OP Margin
opm = df["op_margin"].values
add_filters("OPM", [
    (f"OPM>={int(t*100)}%", mk(opm, ">=", t)) for t in [0.03, 0.05, 0.08, 0.10, 0.15, 0.20]
])

# G13: Equity/Debt
eq = df["equity_ratio"].values
dr = df["debt_ratio"].values
add_filters("FIN", [
    (f"EqR>={int(t*100)}%", mk(eq, ">=", t)) for t in [0.30, 0.40, 0.50, 0.60, 0.70]
] + [
    (f"DebtR<={int(t*100)}%", mk(dr, "<=", t)) for t in [0.30, 0.40, 0.50, 0.60]
])

# G14: Revenue growth
rg = df["revenue_growth"].values
add_filters("RevG", [
    (f"RevG>={int(t*100)}%", mk(rg, ">=", t)) for t in [0.0, 0.05, 0.10, 0.20]
])

# G15: Trend
add_filters("TREND", [
    ("Uptrend", df["full_uptrend"].values == 1),
    ("Brk50", df["breakout_50d"].values == 1),
    ("MA25>75", df["ma25_above_ma75"].values == 1),
    ("MA5>25", df["ma5_above_ma25"].values == 1),
    ("MACD>0", df["macd_hist"].fillna(0).values > 0),
    ("Mom5>0", df["mom_5d"].fillna(0).values > 0),
    ("Mom20>0", df["mom_20d"].fillna(0).values > 0),
])

# G16: 52w high proximity
pfh = df["pct_from_52w_high"].values
add_filters("52W", [
    (l, mkr(pfh, lo, hi)) for lo, hi, l in [
        (-0.05, 0.0, "52wH-5~0%"), (-0.10, 0.0, "52wH-10~0%"),
        (-0.15, 0.0, "52wH-15~0%"), (-0.20, 0.0, "52wH-20~0%"),
    ]
])

# G17: MA75 deviation
ma75 = df["ma75_dev"].values
add_filters("MA75", [
    (l, mkr(ma75, lo, hi)) for lo, hi, l in [
        (0.0, 0.05, "MA75_0~5%"), (0.0, 0.10, "MA75_0~10%"),
        (0.0, None, "MA75>=0%"), (None, 0.10, "MA75<=10%"),
        (-0.05, 0.05, "MA75-5~5%"),
    ]
])

# G18: Turnover
tr = df["turnover_ratio"].values
add_filters("TR", [
    (f"TR>={t}", mk(tr, ">=", t)) for t in [0.3, 0.5, 0.8, 1.0, 1.5]
])

# G19: Price level
cl = df["Close"].values
add_filters("Price", [
    (f"Price>={t}", cl >= t) for t in [100, 300, 500, 1000, 2000, 3000, 5000]
] + [
    (f"Price<={t}", cl <= t) for t in [1000, 2000, 3000, 5000, 10000]
])

# G20: Volume zscore
vz = df["vol_zscore"].values
add_filters("VZ", [
    (f"VZ>={t}", mk(vz, ">=", t)) for t in [0.5, 1.0, 1.5, 2.0]
] + [("VZ<=0", mk(vz, "<=", 0))])

# G21: Momentum ranges
m5d = df["mom_5d"].values
m20d = df["mom_20d"].values
m60d = df["mom_60d"].values
add_filters("MOM", [
    ("Mom5_0~3%", mkr(m5d, 0.0, 0.03)),
    ("Mom5_0~5%", mkr(m5d, 0.0, 0.05)),
    ("Mom5-3~3%", mkr(m5d, -0.03, 0.03)),
    ("Mom20_0~5%", mkr(m20d, 0.0, 0.05)),
    ("Mom20_0~10%", mkr(m20d, 0.0, 0.10)),
    ("Mom60_0~10%", mkr(m60d, 0.0, 0.10)),
    ("Mom60_0~20%", mkr(m60d, 0.0, 0.20)),
])

# G22: MA5 deviation
ma5d = df["ma5_dev"].values
add_filters("MA5", [
    (l, mkr(ma5d, lo, hi)) for lo, hi, l in [
        (None, 0.01, "MA5<=1%"), (None, 0.02, "MA5<=2%"),
        (-0.01, 0.01, "MA5-1~1%"), (-0.02, 0.02, "MA5-2~2%"),
    ]
])

del df
gc.collect()

FILTER_KEYS = list(AM.keys())
GROUP_OF = {}
for gn, keys in GRP.items():
    for k in keys:
        GROUP_OF[k] = gn

log.info(f"Total filters: {len(FILTER_KEYS)}, Groups: {len(GRP)}")

# ═══════════════════════════════════════════════════════════════
# EVALUATION FUNCTION
# ═══════════════════════════════════════════════════════════════

def eval_regime(mask, hd):
    """Evaluate mask across all regimes. Returns dict or None if insufficient data."""
    v = RET[f"{hd}v"]

    def _m(sub):
        r = RET[hd][sub]
        n = len(r)
        if n < 10:
            return {"n": 0, "wr": 0, "avg": 0, "pf": 0, "dd": 0}
        w = r[r > 0]; lo = r[r <= 0]
        wr = len(w) / n
        pf = w.sum() / max(abs(lo.sum()), 1e-10) if len(w) > 0 else 0
        c = np.cumsum(r)
        dd = float((c - np.maximum.accumulate(c)).min()) if len(c) else 0
        return {"n": int(n), "wr": round(wr, 4),
                "avg": round(float(r.mean()), 5),
                "pf": round(min(pf, 9999), 2),
                "dd": round(dd, 4)}

    all_m = mask & v
    bull_m = mask & v & IS_BULL
    bear_m = mask & v & IS_BEAR
    tr_m = mask & v & IS_TR
    te_m = mask & v & IS_TE
    te_bull = mask & v & IS_TE & IS_BULL
    te_bear = mask & v & IS_TE & IS_BEAR

    bull_n = int(bull_m.sum())
    bear_n = int(bear_m.sum())
    if bull_n < 30 or bear_n < 30:
        return None

    return {
        "all": _m(all_m), "bull": _m(bull_m), "bear": _m(bear_m),
        "train": _m(tr_m), "test": _m(te_m),
        "test_bull": _m(te_bull), "test_bear": _m(te_bear),
    }


def score(res):
    """Score = min(bull_wr, bear_wr) — we want BOTH to be high."""
    if res is None:
        return -1
    bw = res["bull"]["wr"]
    brw = res["bear"]["wr"]
    if res["bear"]["n"] < 30:
        return -1
    return min(bw, brw)


# ═══════════════════════════════════════════════════════════════
# PHASE 1: Singles
# ═══════════════════════════════════════════════════════════════
log.info("=" * 70)
log.info("PHASE 1: Singles")
log.info("=" * 70)

P1 = []
for hd in HOLD_PERIODS:
    for k in FILTER_KEYS:
        res = eval_regime(AM[k], hd)
        if res is None:
            continue
        s = score(res)
        if s > 0.50:
            P1.append((k, hd, s, res))

P1.sort(key=lambda x: x[2], reverse=True)
log.info(f"Phase 1: {len(P1)} candidates (min_both_wr > 50%)")
for k, hd, s, r in P1[:15]:
    hdl = {20:'20d', 60:'3m', 120:'6m'}[hd]
    log.info(f"  {s:.1%} | {hdl} | bull={r['bull']['wr']:.1%}({r['bull']['n']}) "
             f"bear={r['bear']['wr']:.1%}({r['bear']['n']}) | {k}")

# Top singles per group for pairing
TOP_PER_GROUP = {}
for k, hd, s, r in P1:
    g = GROUP_OF.get(k, k)
    key = (g, hd)
    if key not in TOP_PER_GROUP:
        TOP_PER_GROUP[key] = []
    if len(TOP_PER_GROUP[key]) < 5:
        TOP_PER_GROUP[key].append(k)

# ═══════════════════════════════════════════════════════════════
# PHASE 2: Pairs (combine top singles from different groups)
# ═══════════════════════════════════════════════════════════════
log.info("=" * 70)
log.info("PHASE 2: Pairs")
log.info("=" * 70)

p1_keys_by_hd = {}
for k, hd, s, r in P1:
    if hd not in p1_keys_by_hd:
        p1_keys_by_hd[hd] = []
    if s > 0.52:
        p1_keys_by_hd[hd].append(k)

P2 = []
checked2 = 0
for hd in HOLD_PERIODS:
    if time.time() - T0 > TIME_LIMIT:
        log.info("TIME LIMIT reached in Phase 2")
        break
    keys = list(dict.fromkeys(p1_keys_by_hd.get(hd, [])))[:120]
    for i, k1 in enumerate(keys):
        g1 = GROUP_OF.get(k1, k1)
        for k2 in keys[i+1:]:
            g2 = GROUP_OF.get(k2, k2)
            if g1 == g2:
                continue
            mask = AM[k1] & AM[k2]
            res = eval_regime(mask, hd)
            checked2 += 1
            if res is None:
                continue
            s = score(res)
            if s > 0.55:
                label = f"{k1} & {k2}"
                P2.append((label, hd, s, res))
    log.info(f"  hd={hd}: checked {checked2}, found {len(P2)}")

P2.sort(key=lambda x: x[2], reverse=True)
log.info(f"Phase 2: {len(P2)} candidates (min_both_wr > 55%)")
for k, hd, s, r in P2[:15]:
    hdl = {20:'20d', 60:'3m', 120:'6m'}[hd]
    log.info(f"  {s:.1%} | {hdl} | bull={r['bull']['wr']:.1%}({r['bull']['n']}) "
             f"bear={r['bear']['wr']:.1%}({r['bear']['n']}) | {k}")

# ═══════════════════════════════════════════════════════════════
# PHASE 3: Triples
# ═══════════════════════════════════════════════════════════════
log.info("=" * 70)
log.info("PHASE 3: Triples")
log.info("=" * 70)

p2_top = [(l, hd, s, r) for l, hd, s, r in P2 if s >= 0.57]
p2_top = p2_top[:300]
log.info(f"  Using top {len(p2_top)} pairs as base")

P3 = []
checked3 = 0
for base_label, hd, base_s, base_r in p2_top:
    if time.time() - T0 > TIME_LIMIT:
        log.info("TIME LIMIT reached in Phase 3")
        break
    base_keys = base_label.split(" & ")
    base_groups = {GROUP_OF.get(k, k) for k in base_keys}
    base_mask = np.ones(N, dtype=bool)
    for k in base_keys:
        base_mask &= AM[k]

    for k3 in FILTER_KEYS:
        g3 = GROUP_OF.get(k3, k3)
        if g3 in base_groups:
            continue
        mask = base_mask & AM[k3]
        res = eval_regime(mask, hd)
        checked3 += 1
        if res is None:
            continue
        s = score(res)
        if s > 0.60:
            label = f"{base_label} & {k3}"
            P3.append((label, hd, s, res))

    if checked3 % 10000 == 0:
        log.info(f"  Phase 3: checked {checked3:,}, found {len(P3)}")

P3.sort(key=lambda x: x[2], reverse=True)
log.info(f"Phase 3: {len(P3)} candidates (min_both_wr > 60%)")
for k, hd, s, r in P3[:15]:
    hdl = {20:'20d', 60:'3m', 120:'6m'}[hd]
    log.info(f"  {s:.1%} | {hdl} | bull={r['bull']['wr']:.1%}({r['bull']['n']}) "
             f"bear={r['bear']['wr']:.1%}({r['bear']['n']}) all_n={r['all']['n']} | {k}")

# Save intermediate
def save_results(final_list, phase_name):
    final_list.sort(key=lambda x: x[2], reverse=True)
    out = []
    for label, hd, s, res in final_list[:2000]:
        out.append({
            "params": {"base": label, "hd": hd},
            "score": round(s, 4),
            "all": res["all"], "bull": res["bull"], "bear": res["bear"],
            "train": res["train"], "test": res["test"],
            "test_bull": res.get("test_bull", {}),
            "test_bear": res.get("test_bear", {}),
        })

    wr_bins = {}
    for o in out:
        mn = min(o["bull"]["wr"], o["bear"]["wr"])
        if mn >= 0.80: wr_bins["both80+"] = wr_bins.get("both80+", 0) + 1
        elif mn >= 0.70: wr_bins["both70+"] = wr_bins.get("both70+", 0) + 1
        elif mn >= 0.60: wr_bins["both60+"] = wr_bins.get("both60+", 0) + 1

    data = {
        "generated_at": str(pd.Timestamp.now()),
        "phase": phase_name,
        "summary": wr_bins,
        "train_end": str(split_date.date()),
        "data_range": f"2021-03-30 ~ 2026-03-27",
        "regime_info": {"bull_rows": int(IS_BULL.sum()), "bear_rows": int(IS_BEAR.sum())},
        "high_n_strategies": out[:20],
    }
    with open(f"{SAVE_DIR}/regime_search_results.json", "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    with open(f"{SAVE_DIR}/_results_regime_search.pkl", "wb") as f:
        pickle.dump(out, f)
    log.info(f"Saved {len(out)} results ({phase_name}). Bins: {wr_bins}")

save_results(P3, "phase3")

# ═══════════════════════════════════════════════════════════════
# PHASE 4: Quads
# ═══════════════════════════════════════════════════════════════
log.info("=" * 70)
log.info("PHASE 4: Quads")
log.info("=" * 70)

p3_top = [(l, hd, s, r) for l, hd, s, r in P3 if s >= 0.62]
p3_top = p3_top[:400]
log.info(f"  Using top {len(p3_top)} triples as base")

P4 = []
checked4 = 0
for base_label, hd, base_s, base_r in p3_top:
    if time.time() - T0 > TIME_LIMIT:
        log.info("TIME LIMIT reached in Phase 4")
        break
    base_keys = base_label.split(" & ")
    base_groups = {GROUP_OF.get(k, k) for k in base_keys}
    base_mask = np.ones(N, dtype=bool)
    for k in base_keys:
        base_mask &= AM[k]

    for k4 in FILTER_KEYS:
        g4 = GROUP_OF.get(k4, k4)
        if g4 in base_groups:
            continue
        mask = base_mask & AM[k4]
        res = eval_regime(mask, hd)
        checked4 += 1
        if res is None:
            continue
        s = score(res)
        if s > 0.65:
            label = f"{base_label} & {k4}"
            P4.append((label, hd, s, res))

    if checked4 % 20000 == 0:
        elapsed = time.time() - T0
        log.info(f"  Phase 4: checked {checked4:,}, found {len(P4)}, elapsed {elapsed/60:.0f}min")

P4.sort(key=lambda x: x[2], reverse=True)
log.info(f"Phase 4: {len(P4)} candidates (min_both_wr > 65%)")
for k, hd, s, r in P4[:15]:
    hdl = {20:'20d', 60:'3m', 120:'6m'}[hd]
    log.info(f"  {s:.1%} | {hdl} | bull={r['bull']['wr']:.1%}({r['bull']['n']}) "
             f"bear={r['bear']['wr']:.1%}({r['bear']['n']}) all_n={r['all']['n']} | {k}")

ALL_RESULTS = P3 + P4
save_results(ALL_RESULTS, "phase4")

# ═══════════════════════════════════════════════════════════════
# PHASE 5: Quints
# ═══════════════════════════════════════════════════════════════
log.info("=" * 70)
log.info("PHASE 5: Quints")
log.info("=" * 70)

p4_top = [(l, hd, s, r) for l, hd, s, r in P4 if s >= 0.67]
p4_top = p4_top[:300]
log.info(f"  Using top {len(p4_top)} quads as base")

P5 = []
checked5 = 0
for base_label, hd, base_s, base_r in p4_top:
    if time.time() - T0 > TIME_LIMIT:
        log.info("TIME LIMIT reached in Phase 5")
        break
    base_keys = base_label.split(" & ")
    base_groups = {GROUP_OF.get(k, k) for k in base_keys}
    base_mask = np.ones(N, dtype=bool)
    for k in base_keys:
        base_mask &= AM[k]

    for k5 in FILTER_KEYS:
        g5 = GROUP_OF.get(k5, k5)
        if g5 in base_groups:
            continue
        mask = base_mask & AM[k5]
        res = eval_regime(mask, hd)
        checked5 += 1
        if res is None:
            continue
        s = score(res)
        if s > 0.70:
            label = f"{base_label} & {k5}"
            P5.append((label, hd, s, res))

    if checked5 % 20000 == 0:
        elapsed = time.time() - T0
        log.info(f"  Phase 5: checked {checked5:,}, found {len(P5)}, elapsed {elapsed/60:.0f}min")

P5.sort(key=lambda x: x[2], reverse=True)
log.info(f"Phase 5: {len(P5)} candidates (min_both_wr > 70%)")
for k, hd, s, r in P5[:15]:
    hdl = {20:'20d', 60:'3m', 120:'6m'}[hd]
    log.info(f"  {s:.1%} | {hdl} | bull={r['bull']['wr']:.1%}({r['bull']['n']}) "
             f"bear={r['bear']['wr']:.1%}({r['bear']['n']}) all_n={r['all']['n']} | {k}")

ALL_RESULTS = P3 + P4 + P5
save_results(ALL_RESULTS, "phase5")

# ═══════════════════════════════════════════════════════════════
# PHASE 6: Sextets (if time remains)
# ═══════════════════════════════════════════════════════════════
elapsed = time.time() - T0
if elapsed < TIME_LIMIT - 1800:
    log.info("=" * 70)
    log.info("PHASE 6: Sextets")
    log.info("=" * 70)

    p5_top = [(l, hd, s, r) for l, hd, s, r in P5 if s >= 0.72]
    p5_top = p5_top[:200]
    log.info(f"  Using top {len(p5_top)} quints as base")

    P6 = []
    checked6 = 0
    for base_label, hd, base_s, base_r in p5_top:
        if time.time() - T0 > TIME_LIMIT:
            log.info("TIME LIMIT reached in Phase 6")
            break
        base_keys = base_label.split(" & ")
        base_groups = {GROUP_OF.get(k, k) for k in base_keys}
        base_mask = np.ones(N, dtype=bool)
        for k in base_keys:
            base_mask &= AM[k]

        for k6 in FILTER_KEYS:
            g6 = GROUP_OF.get(k6, k6)
            if g6 in base_groups:
                continue
            mask = base_mask & AM[k6]
            res = eval_regime(mask, hd)
            checked6 += 1
            if res is None:
                continue
            s = score(res)
            if s > 0.73:
                label = f"{base_label} & {k6}"
                P6.append((label, hd, s, res))

        if checked6 % 20000 == 0:
            elapsed = time.time() - T0
            log.info(f"  Phase 6: checked {checked6:,}, found {len(P6)}, elapsed {elapsed/60:.0f}min")

    P6.sort(key=lambda x: x[2], reverse=True)
    log.info(f"Phase 6: {len(P6)} candidates")
    for k, hd, s, r in P6[:10]:
        hdl = {20:'20d', 60:'3m', 120:'6m'}[hd]
        log.info(f"  {s:.1%} | {hdl} | bull={r['bull']['wr']:.1%}({r['bull']['n']}) "
                 f"bear={r['bear']['wr']:.1%}({r['bear']['n']}) all_n={r['all']['n']} | {k}")

    ALL_RESULTS = P3 + P4 + P5 + P6
    save_results(ALL_RESULTS, "phase6")
else:
    log.info(f"Skipping Phase 6 (elapsed {elapsed/60:.0f}min)")

# ═══════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════
elapsed = time.time() - T0
log.info("=" * 70)
log.info(f"SEARCH COMPLETE in {elapsed/60:.1f} min")
log.info("=" * 70)

ALL = P3 + P4 + (P5 if P5 else []) + (P6 if 'P6' in dir() and P6 else [])
ALL.sort(key=lambda x: x[2], reverse=True)

log.info(f"\n{'='*130}")
log.info(f"TOP 30 STRATEGIES (sorted by min(bull_wr, bear_wr)):")
log.info(f"{'='*130}")
log.info(f"{'Score':>6} {'Hold':>4} {'BullWR':>7} {'BullN':>6} {'BearWR':>7} {'BearN':>6} {'AllWR':>6} {'AllN':>7} {'PF':>6} | Conditions")
log.info(f"{'-'*130}")
for label, hd, s, r in ALL[:30]:
    hdl = {20:'20d', 60:'3m', 120:'6m'}[hd]
    log.info(f"{s:>5.1%} {hdl:>4} {r['bull']['wr']:>6.1%} {r['bull']['n']:>6} "
             f"{r['bear']['wr']:>6.1%} {r['bear']['n']:>6} "
             f"{r['all']['wr']:>5.1%} {r['all']['n']:>7} {r['all']['pf']:>6.2f} | {label}")

save_results(ALL, "final")
log.info("ALL DONE.")

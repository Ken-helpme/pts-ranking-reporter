#!/usr/bin/env python3
"""
Deep Strategy Search Round 2: Deeper refinement on top strategies
- Finer PBR/PER/ATR/Vol grids
- 7-8 filter combos from best 6-filter bases
- More exit combos (finer TP/SL grid)
- Wider holding period exploration (10d, 20d, 60d, 120d)
- Time limit: 12 hours
"""
import sys, logging, time, json, pickle, gc, os
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stderr)
log = logging.getLogger("r2")
T0 = time.time()
SAVE_DIR = "quant_research/data"
TIME_LIMIT = 12 * 3600

HOLD_PERIODS = [10, 20, 60, 120]

log.info("Round 2: Loading...")
df = pd.read_pickle(f"{SAVE_DIR}/_intermediate_df_features.pkl")
N = len(df)

for hd in HOLD_PERIODS:
    c = f"fwd_{hd}d_return"
    if c not in df.columns:
        df[c] = df.groupby("Code")["Close"].transform(lambda x: x.shift(-hd) / x - 1)

dates = sorted(df["Date"].unique())
split = pd.Timestamp(dates[int(len(dates) * 0.4)])
IS_TR = (df["Date"] <= split).values
IS_TE = (df["Date"] > split).values
log.info(f"N={N:,} split={split.date()}")

RET = {}
for hd in HOLD_PERIODS:
    v = df[f"fwd_{hd}d_return"].values
    RET[hd] = v
    RET[f"{hd}v"] = ~np.isnan(v)
    RET[f"{hd}p"] = np.where(np.isnan(v), False, v > 0)
    te_n = int((IS_TE & RET[f"{hd}v"]).sum())
    log.info(f"  {hd}d: test={te_n:,}")

log.info("Building extended filter universe...")

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

# ── G0: Vol ratio (finer grid) ──
vr = df["vol_ratio"].values
for lo, hi, label in [
    (0.3, 0.7, "VB0.3-0.7"), (0.3, 0.8, "VB0.3-0.8"), (0.3, 1.0, "VB0.3-1.0"),
    (0.5, 0.8, "VB0.5-0.8"), (0.5, 1.0, "VB0.5-1.0"), (0.5, 1.2, "VB0.5-1.2"),
    (0.5, 1.5, "VB0.5-1.5"), (0.6, 1.0, "VB0.6-1.0"), (0.7, 1.0, "VB0.7-1.0"),
    (0.7, 1.3, "VB0.7-1.3"), (0.8, 1.2, "VB0.8-1.2"), (0.8, 1.5, "VB0.8-1.5"),
    (1.0, 1.5, "VB1.0-1.5"), (1.0, 2.0, "VB1.0-2.0"), (1.0, 3.0, "VB1.0-3.0"),
    (1.2, 2.0, "VB1.2-2.0"), (1.3, 2.5, "VB1.3-2.5"), (1.5, 3.0, "VB1.5-3.0"),
    (None, 0.8, "VB<=0.8"), (None, 1.0, "VB<=1.0"), (None, 1.2, "VB<=1.2"),
    (1.0, None, "VB>=1.0"), (1.3, None, "VB>=1.3"), (1.5, None, "VB>=1.5"),
]:
    AM[label] = mkr(vr, lo, hi)

# ── G1: RSI (finer) ──
rsi = df["rsi"].values
for lo, hi, label in [
    (20, 40, "RSI20-40"), (20, 50, "RSI20-50"), (20, 60, "RSI20-60"),
    (20, 70, "RSI20-70"), (25, 55, "RSI25-55"), (30, 50, "RSI30-50"),
    (30, 55, "RSI30-55"), (30, 60, "RSI30-60"), (30, 65, "RSI30-65"),
    (30, 70, "RSI30-70"), (35, 55, "RSI35-55"), (35, 60, "RSI35-60"),
    (35, 65, "RSI35-65"), (40, 55, "RSI40-55"), (40, 60, "RSI40-60"),
    (40, 65, "RSI40-65"), (40, 70, "RSI40-70"), (45, 55, "RSI45-55"),
    (45, 60, "RSI45-60"), (45, 65, "RSI45-65"), (50, 60, "RSI50-60"),
    (50, 65, "RSI50-65"), (50, 70, "RSI50-70"),
    (None, 50, "RSI<=50"), (None, 55, "RSI<=55"), (None, 60, "RSI<=60"),
    (None, 65, "RSI<=65"), (None, 70, "RSI<=70"),
]:
    AM[label] = mkr(rsi, lo, hi)

# ── G2: MA25 dev ──
ma25 = df["ma25_dev"].values
for lo, hi, label in [
    (None, 0.02, "MA25<=2%"), (None, 0.03, "MA25<=3%"), (None, 0.05, "MA25<=5%"),
    (None, 0.08, "MA25<=8%"), (None, 0.10, "MA25<=10%"),
    (-0.03, 0.03, "MA25-3~3%"), (-0.03, 0.05, "MA25-3~5%"),
    (-0.03, 0.08, "MA25-3~8%"), (-0.05, 0.05, "MA25-5~5%"),
    (0.0, 0.03, "MA25_0~3%"), (0.0, 0.05, "MA25_0~5%"),
    (0.02, 0.05, "MA25_2~5%"), (0.02, 0.08, "MA25_2~8%"),
    (0.0, None, "MA25>=0%"),
]:
    AM[label] = mkr(ma25, lo, hi)

# ── G3: PER (finer grid) ──
per = df["per"].fillna(9999).values
for t in [3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 18, 20, 25, 30]:
    AM[f"PER<={t}"] = (per > 0) & (per <= t)
for lo, hi, label in [
    (3, 8, "PER3-8"), (3, 10, "PER3-10"), (5, 10, "PER5-10"),
    (5, 12, "PER5-12"), (5, 15, "PER5-15"), (7, 12, "PER7-12"),
    (7, 15, "PER7-15"), (8, 12, "PER8-12"), (8, 15, "PER8-15"),
    (8, 20, "PER8-20"), (10, 15, "PER10-15"), (10, 20, "PER10-20"),
]:
    AM[label] = (per >= lo) & (per <= hi)

# ── G4: PBR (much finer grid) ──
pbr = df["pbr"].fillna(9999).values
for t in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5, 2.0]:
    AM[f"PBR<={t}"] = (pbr > 0) & (pbr <= t)
for lo, hi, label in [
    (0.2, 0.5, "PBR0.2-0.5"), (0.3, 0.6, "PBR0.3-0.6"), (0.3, 0.7, "PBR0.3-0.7"),
    (0.3, 0.8, "PBR0.3-0.8"), (0.4, 0.7, "PBR0.4-0.7"), (0.4, 0.8, "PBR0.4-0.8"),
    (0.5, 0.8, "PBR0.5-0.8"), (0.5, 1.0, "PBR0.5-1.0"), (0.5, 1.2, "PBR0.5-1.2"),
    (0.6, 1.0, "PBR0.6-1.0"), (0.7, 1.0, "PBR0.7-1.0"), (0.8, 1.2, "PBR0.8-1.2"),
    (0.8, 1.5, "PBR0.8-1.5"), (1.0, 1.5, "PBR1.0-1.5"), (1.0, 2.0, "PBR1.0-2.0"),
]:
    AM[label] = (pbr >= lo) & (pbr <= hi)

# ── G5: Market cap ──
mc = df["market_cap"].fillna(0).values
for lo, hi, label in [
    (None, 10e9, "MC<=100億"), (None, 20e9, "MC<=200億"), (None, 50e9, "MC<=500億"),
    (None, 100e9, "MC<=1000億"), (None, 300e9, "MC<=3000億"),
    (None, 500e9, "MC<=5000億"), (None, 1e12, "MC<=1兆"),
    (5e9, None, "MC>=50億"), (10e9, None, "MC>=100億"), (20e9, None, "MC>=200億"),
    (50e9, None, "MC>=500億"), (100e9, None, "MC>=1000億"),
    (5e9, 50e9, "MC50-500億"), (5e9, 100e9, "MC50-1000億"),
    (10e9, 100e9, "MC100-1000億"), (10e9, 300e9, "MC100-3000億"),
    (20e9, 300e9, "MC200-3000億"), (20e9, 500e9, "MC200-5000億"),
    (50e9, 300e9, "MC500-3000億"), (50e9, 500e9, "MC500-5000億"),
    (50e9, 1e12, "MC500-1兆"), (100e9, 1e12, "MC1000-1兆"),
]:
    AM[label] = mkr(mc, lo, hi)

# ── G6: EPS growth ──
eps_v = df["eps_growth"].values
for t in [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50]:
    AM[f"EPS>={int(t*100)}%"] = mk(eps_v, ">=", t)

# ── G7: OG ──
og = df["op_growth"].values
for t in [0.0, 0.05, 0.10, 0.20, 0.30]:
    AM[f"OG>={int(t*100)}%"] = mk(og, ">=", t)

# ── G8: ROE ──
roe_a = df["roe"].values
for t in [0.03, 0.05, 0.08, 0.10, 0.12, 0.15]:
    AM[f"ROE>={int(t*100)}%"] = mk(roe_a, ">=", t)

# ── G9: ATR (finer) ──
atr_a = df["atr_pct"].values
for t in [0.008, 0.01, 0.012, 0.015, 0.018, 0.02, 0.022, 0.025, 0.03, 0.035, 0.04, 0.05]:
    AM[f"ATR<={t}"] = mk(atr_a, "<=", t)

# ── G10: Volatility (finer) ──
vol = df["volatility"].values
for t in [0.008, 0.01, 0.012, 0.015, 0.018, 0.02, 0.022, 0.025, 0.03]:
    AM[f"Vol<={t}"] = mk(vol, "<=", t)

# ── G11: Op Margin ──
opm = df["op_margin"].values
for t in [0.03, 0.05, 0.08, 0.10, 0.15, 0.20]:
    AM[f"OPM>={int(t*100)}%"] = mk(opm, ">=", t)

# ── G12: Equity/Debt ──
eq = df["equity_ratio"].values
for t in [0.30, 0.40, 0.50, 0.60, 0.70]:
    AM[f"EqR>={int(t*100)}%"] = mk(eq, ">=", t)
dr = df["debt_ratio"].values
for t in [0.30, 0.40, 0.50, 0.60]:
    AM[f"DebtR<={int(t*100)}%"] = mk(dr, "<=", t)

# ── G13: Revenue growth ──
rg = df["revenue_growth"].values
for t in [0.0, 0.05, 0.10, 0.20]:
    AM[f"RevG>={int(t*100)}%"] = mk(rg, ">=", t)

# ── G14: Trend ──
AM["Uptrend"] = df["full_uptrend"].values == 1
AM["Brk50"] = df["breakout_50d"].values == 1
AM["Brk200"] = df["breakout_200d"].values == 1
AM["MA25>75"] = df["ma25_above_ma75"].values == 1
AM["MA5>25"] = df["ma5_above_ma25"].values == 1
AM["MACD>0"] = df["macd_hist"].fillna(0).values > 0
AM["Mom5>0"] = df["mom_5d"].fillna(0).values > 0
AM["Mom10>0"] = df["mom_10d"].fillna(0).values > 0
AM["Mom20>0"] = df["mom_20d"].fillna(0).values > 0
AM["Near52wH"] = df["near_52w_high"].values == 1

# ── G15: Price from high ──
pfh = df["pct_from_52w_high"].values
for lo, hi, label in [
    (-0.05, 0.0, "52wH-5~0%"), (-0.10, 0.0, "52wH-10~0%"),
    (-0.15, 0.0, "52wH-15~0%"), (-0.20, 0.0, "52wH-20~0%"),
    (-0.30, -0.10, "52wH-30~-10%"), (-0.50, -0.20, "52wH-50~-20%"),
]:
    AM[label] = mkr(pfh, lo, hi)
pf50 = df["pct_from_50d_high"].values
for lo, hi, label in [
    (-0.05, 0.0, "50dH-5~0%"), (-0.10, 0.0, "50dH-10~0%"),
]:
    AM[label] = mkr(pf50, lo, hi)

# ── G16: MA75 dev ──
ma75 = df["ma75_dev"].values
for lo, hi, label in [
    (0.0, 0.05, "MA75_0~5%"), (0.0, 0.10, "MA75_0~10%"),
    (0.0, None, "MA75>=0%"), (None, 0.10, "MA75<=10%"), (None, 0.15, "MA75<=15%"),
]:
    AM[label] = mkr(ma75, lo, hi)

# ── G17: Vol zscore ──
vz = df["vol_zscore"].values
for t in [0.5, 1.0, 1.5, 2.0]:
    AM[f"VZ>={t}"] = mk(vz, ">=", t)
AM["VZ_neg"] = mk(vz, "<=", -0.5)

# ── G18: VR5d ──
vr5 = df["vol_ratio_5d"].values
for t in [0.8, 1.0, 1.2, 1.5]:
    AM[f"VR5>={t}"] = mk(vr5, ">=", t)

# ── G19: Turnover ──
tr = df["turnover_ratio"].values
for t in [0.3, 0.5, 0.8, 1.0]:
    AM[f"TR>={t}"] = mk(tr, ">=", t)

# ── G20: Momentum ranges ──
m5d = df["mom_5d"].values
for lo, hi, label in [
    (0.0, 0.03, "Mom5_0~3%"), (0.0, 0.05, "Mom5_0~5%"),
    (-0.03, 0.03, "Mom5-3~3%"),
]:
    AM[label] = mkr(m5d, lo, hi)
m20d = df["mom_20d"].values
for lo, hi, label in [
    (0.0, 0.05, "Mom20_0~5%"), (0.0, 0.10, "Mom20_0~10%"),
]:
    AM[label] = mkr(m20d, lo, hi)
m60d = df["mom_60d"].values
for lo, hi, label in [
    (0.0, 0.10, "Mom60_0~10%"), (0.0, 0.20, "Mom60_0~20%"),
]:
    AM[label] = mkr(m60d, lo, hi)

# ── G21: MA5 dev ──
ma5d = df["ma5_dev"].values
for lo, hi, label in [
    (None, 0.01, "MA5<=1%"), (None, 0.02, "MA5<=2%"), (None, 0.03, "MA5<=3%"),
    (-0.01, 0.01, "MA5-1~1%"), (-0.02, 0.02, "MA5-2~2%"),
]:
    AM[label] = mkr(ma5d, lo, hi)

# ── G22: Price level ──
cl = df["Close"].values
for t in [100, 300, 500, 700, 1000, 1500, 2000, 3000, 5000]:
    AM[f"Price>={t}"] = cl >= t
for t in [500, 1000, 2000, 3000, 5000, 10000]:
    AM[f"Price<={t}"] = cl <= t

del df
gc.collect()

log.info(f"Total masks: {len(AM)}")

# Group assignments
GROUPS = {}
group_defs = [
    (0, "VB"), (1, "RSI"), (2, "MA25"), (3, "PER"), (4, "PBR"),
    (5, "MC"), (6, "EPS"), (7, "OG"), (8, "ROE"), (9, "ATR"),
    (10, "Vol<="), (11, "OPM"), (12, "EqR,DebtR"), (13, "RevG"),
    (14, "Trend"), (15, "52wH,50dH"), (16, "MA75"), (17, "VZ"),
    (18, "VR5"), (19, "TR>="), (20, "Mom"), (21, "MA5"), (22, "Price"),
]

key_to_group = {}
for gi, prefix in group_defs:
    GROUPS[gi] = []

for k in AM:
    assigned = False
    if k.startswith("VB"): gi = 0
    elif k.startswith("RSI"): gi = 1
    elif k.startswith("MA25") and ">" not in k[:4]: gi = 2
    elif k.startswith("PER"): gi = 3
    elif k.startswith("PBR"): gi = 4
    elif k.startswith("MC"): gi = 5
    elif k.startswith("EPS"): gi = 6
    elif k.startswith("OG"): gi = 7
    elif k.startswith("ROE"): gi = 8
    elif k.startswith("ATR"): gi = 9
    elif k.startswith("Vol<="): gi = 10
    elif k.startswith("OPM"): gi = 11
    elif k.startswith("EqR") or k.startswith("DebtR"): gi = 12
    elif k.startswith("RevG"): gi = 13
    elif k in ["Uptrend","Brk50","Brk200","MA25>75","MA5>25",
               "MACD>0","Mom5>0","Mom10>0","Mom20>0","Near52wH"]: gi = 14
    elif k.startswith("52wH") or k.startswith("50dH"): gi = 15
    elif k.startswith("MA75"): gi = 16
    elif k.startswith("VZ"): gi = 17
    elif k.startswith("VR5"): gi = 18
    elif k.startswith("TR>="): gi = 19
    elif k.startswith("Mom5_") or k.startswith("Mom5-") or k.startswith("Mom20_") or k.startswith("Mom60_"): gi = 20
    elif k.startswith("MA5"): gi = 21
    elif k.startswith("Price"): gi = 22
    else: gi = 99; GROUPS.setdefault(99, [])
    GROUPS.setdefault(gi, []).append(k)
    key_to_group[k] = gi

all_group_keys = []
for gi in sorted(GROUPS.keys()):
    for k in GROUPS[gi]:
        all_group_keys.append((gi, k))

for gi in sorted(GROUPS.keys()):
    log.info(f"  G{gi}: {len(GROUPS[gi])} ({GROUPS[gi][:2]})")


def build_mask(keys):
    m = np.ones(N, dtype=bool)
    for k in keys:
        m &= AM[k]
    return m


def wr_fast(mask, hd, min_te=50):
    v = RET[f"{hd}v"]
    tm = mask & IS_TR & v
    em = mask & IS_TE & v
    nt = int(tm.sum()); ne = int(em.sum())
    if nt < 10 or ne < min_te: return None
    return (nt, float(RET[f"{hd}p"][tm].sum()/nt),
            ne, float(RET[f"{hd}p"][em].sum()/ne))


def full_eval(mask, hd, tp=None, sl=None):
    v = RET[f"{hd}v"]
    tm = mask & IS_TR & v
    em = mask & IS_TE & v
    if tm.sum() < 10 or em.sum() < 20: return None
    rtr = RET[hd][tm].copy()
    rte = RET[hd][em].copy()
    if tp is not None: np.clip(rtr, None, tp, out=rtr); np.clip(rte, None, tp, out=rte)
    if sl is not None: np.clip(rtr, sl, None, out=rtr); np.clip(rte, sl, None, out=rte)
    def m(r):
        n=len(r); w=r[r>0]; lo=r[r<=0]; wr=len(w)/n
        pf=(w.sum()/max(abs(lo.sum()),1e-10)) if len(w)>0 else 0
        aw=w.mean() if len(w)>0 else 0; al=abs(lo.mean()) if len(lo)>0 else 1e-10
        c=np.cumsum(r); dd=float((c-np.maximum.accumulate(c)).min()) if len(c) else 0
        return {"n":int(n),"wr":round(wr,4),"pf":round(pf,2),
                "wlr":round(aw/al,2),"dd":round(dd,4),"avg":round(float(r.mean()),5)}
    return m(rtr), m(rte)


def dedup(entries):
    seen = set(); out = []
    for r in entries:
        k = (r["test"]["n"], r["test"]["wr"], r["params"]["hd"],
             r["params"].get("tp"), r["params"].get("sl"))
        if k not in seen: seen.add(k); out.append(r)
    return out


def save_all(UF, phase):
    wr_bins = {}
    for r in UF:
        wr = r["test"]["wr"]
        if wr >= 0.90: wr_bins.setdefault("90+", []).append(r)
        elif wr >= 0.80: wr_bins.setdefault("80-90", []).append(r)
        elif wr >= 0.70: wr_bins.setdefault("70-80", []).append(r)
        elif wr >= 0.60: wr_bins.setdefault("60-70", []).append(r)
        else: wr_bins.setdefault("55-60", []).append(r)
    out = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "train_end": str(split.date()), "phase": phase,
        "summary": {"wr90":len(wr_bins.get("90+",[])),"wr80_90":len(wr_bins.get("80-90",[])),
                     "wr70_80":len(wr_bins.get("70-80",[])),"wr60_70":len(wr_bins.get("60-70",[]))},
        "wr90_plus": wr_bins.get("90+",[])[:30],
        "wr80_90": wr_bins.get("80-90",[])[:50],
        "wr70_80": sorted(wr_bins.get("70-80",[]),key=lambda x:x["score"],reverse=True)[:50],
        "best_overall": UF[:100],
    }
    with open(f"{SAVE_DIR}/deep_strategy_results.json","w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    with open(f"{SAVE_DIR}/_results_deep_strategy.pkl","wb") as f:
        pickle.dump(UF, f)
    log.info(f"[SAVED] {phase}: {len(UF):,} (90%+:{len(wr_bins.get('90+',[]))} "
             f"80-90%:{len(wr_bins.get('80-90',[]))})")


# ═══════════════════════════════════════════════════════════════
# PHASE A: Singles + Pairs
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("PHASE A: Singles + Pairs")

pa = []
for k in AM:
    mask = AM[k]
    for hd in HOLD_PERIODS:
        r = wr_fast(mask, hd, min_te=50)
        if r and r[1] >= 0.55 and r[3] >= 0.52:
            pa.append(((k,), hd, r[0], round(r[1],4), r[2], round(r[3],4)))
log.info(f"Singles: {len(pa)}")

total = 0
for i in range(len(all_group_keys)):
    gi, ki = all_group_keys[i]
    mi = AM[ki]
    for j in range(i+1, len(all_group_keys)):
        gj, kj = all_group_keys[j]
        if gi == gj: continue
        mask = mi & AM[kj]
        total += 1
        for hd in HOLD_PERIODS:
            r = wr_fast(mask, hd, min_te=50)
            if r and r[1] >= 0.56 and r[3] >= 0.53:
                pa.append(((ki, kj), hd, r[0], round(r[1],4), r[2], round(r[3],4)))
    if (i+1) % 40 == 0:
        log.info(f"  Pairs: {i+1}/{len(all_group_keys)} | {total:,} | {len(pa):,}")

log.info(f"Phase A: {len(pa):,}")
pa.sort(key=lambda x: (x[5], x[4]), reverse=True)
seen = set(); pau = []
for r in pa:
    k = (r[4], r[5], r[1])
    if k not in seen: seen.add(k); pau.append(r)
log.info(f"Phase A unique: {len(pau):,}")

# ═══════════════════════════════════════════════════════════════
# PHASE B: Triples
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("PHASE B: Triples")

pb_top = pau[:3000]
pb = list(pau)
for bi, (bk, hd, _, _, _, _) in enumerate(pb_top):
    if time.time() - T0 > TIME_LIMIT * 0.3: break
    bm = build_mask(bk)
    bg = set(key_to_group.get(k,-1) for k in bk)
    for gi in sorted(GROUPS.keys()):
        if gi in bg: continue
        for k in GROUPS[gi]:
            m = bm & AM[k]
            r = wr_fast(m, hd, min_te=30)
            if r and r[1] >= 0.58 and r[3] >= 0.55:
                pb.append((tuple(sorted(set(bk)|{k})), hd, r[0], round(r[1],4), r[2], round(r[3],4)))
    del bm
    if (bi+1) % 300 == 0:
        log.info(f"  B: {bi+1}/3000 | {len(pb):,} | {(time.time()-T0)/60:.0f}min")

log.info(f"Phase B: {len(pb):,}")
pb.sort(key=lambda x: (x[5], x[4]), reverse=True)
seen_b = set(); pbu = []
for r in pb:
    k = (r[4], r[5], r[1])
    if k not in seen_b: seen_b.add(k); pbu.append(r)
log.info(f"Phase B unique: {len(pbu):,}")

# ═══════════════════════════════════════════════════════════════
# PHASE C: Quads
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("PHASE C: Quads")

pc_top = [r for r in pbu if len(r[0]) == 3][:5000]
pc = list(pbu)
for bi, (bk, hd, _, _, _, _) in enumerate(pc_top):
    if time.time() - T0 > TIME_LIMIT * 0.5: break
    bm = build_mask(bk)
    bg = set(key_to_group.get(k,-1) for k in bk)
    for gi in sorted(GROUPS.keys()):
        if gi in bg: continue
        for k in GROUPS[gi]:
            m = bm & AM[k]
            r = wr_fast(m, hd, min_te=20)
            if r and r[1] >= 0.60 and r[3] >= 0.56:
                pc.append((tuple(sorted(set(bk)|{k})), hd, r[0], round(r[1],4), r[2], round(r[3],4)))
    del bm
    if (bi+1) % 500 == 0:
        log.info(f"  C: {bi+1}/{len(pc_top)} | {len(pc):,} | {(time.time()-T0)/3600:.1f}h")

log.info(f"Phase C: {len(pc):,}")
pc.sort(key=lambda x: (x[5], x[4]), reverse=True)
seen_c = set(); pcu = []
for r in pc:
    k = (r[4], r[5], r[1])
    if k not in seen_c: seen_c.add(k); pcu.append(r)
log.info(f"Phase C unique: {len(pcu):,}")

# ═══════════════════════════════════════════════════════════════
# PHASE D: Quints
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("PHASE D: Quints")

pd_top = [r for r in pcu if len(r[0]) == 4][:6000]
pd_list = list(pcu)
for bi, (bk, hd, _, _, _, _) in enumerate(pd_top):
    if time.time() - T0 > TIME_LIMIT * 0.6: break
    bm = build_mask(bk)
    bg = set(key_to_group.get(k,-1) for k in bk)
    for gi in sorted(GROUPS.keys()):
        if gi in bg: continue
        for k in GROUPS[gi]:
            m = bm & AM[k]
            r = wr_fast(m, hd, min_te=15)
            if r and r[1] >= 0.62 and r[3] >= 0.57:
                pd_list.append((tuple(sorted(set(bk)|{k})), hd, r[0], round(r[1],4), r[2], round(r[3],4)))
    del bm
    if (bi+1) % 600 == 0:
        log.info(f"  D: {bi+1}/{len(pd_top)} | {len(pd_list):,} | {(time.time()-T0)/3600:.1f}h")

log.info(f"Phase D: {len(pd_list):,}")
pd_list.sort(key=lambda x: (x[5], x[4]), reverse=True)
seen_d = set(); pdu = []
for r in pd_list:
    k = (r[4], r[5], r[1])
    if k not in seen_d: seen_d.add(k); pdu.append(r)
log.info(f"Phase D unique: {len(pdu):,}")

# ═══════════════════════════════════════════════════════════════
# PHASE E: Sextets + Septets (if time permits)
# ═══════════════════════════════════════════════════════════════
ALL = pdu
if time.time() - T0 < TIME_LIMIT * 0.7:
    log.info("\n" + "=" * 60)
    log.info("PHASE E: Sextets")
    pe_top = [r for r in pdu if len(r[0]) == 5][:8000]
    pe = list(pdu)
    for bi, (bk, hd, _, _, _, _) in enumerate(pe_top):
        if time.time() - T0 > TIME_LIMIT * 0.75: break
        bm = build_mask(bk)
        bg = set(key_to_group.get(k,-1) for k in bk)
        for gi in sorted(GROUPS.keys()):
            if gi in bg: continue
            for k in GROUPS[gi]:
                m = bm & AM[k]
                r = wr_fast(m, hd, min_te=10)
                if r and r[1] >= 0.64 and r[3] >= 0.58:
                    pe.append((tuple(sorted(set(bk)|{k})), hd, r[0], round(r[1],4), r[2], round(r[3],4)))
        del bm
        if (bi+1) % 800 == 0:
            log.info(f"  E: {bi+1}/{len(pe_top)} | {len(pe):,} | {(time.time()-T0)/3600:.1f}h")

    log.info(f"Phase E: {len(pe):,}")
    pe.sort(key=lambda x: (x[5], x[4]), reverse=True)
    seen_e = set(); peu = []
    for r in pe:
        k = (r[4], r[5], r[1])
        if k not in seen_e: seen_e.add(k); peu.append(r)
    log.info(f"Phase E unique: {len(peu):,}")
    ALL = peu

    # Septets
    if time.time() - T0 < TIME_LIMIT * 0.8:
        log.info("\nPHASE F: Septets")
        pf_top = [r for r in peu if len(r[0]) == 6][:10000]
        pf = list(peu)
        for bi, (bk, hd, _, _, _, _) in enumerate(pf_top):
            if time.time() - T0 > TIME_LIMIT * 0.85: break
            bm = build_mask(bk)
            bg = set(key_to_group.get(k,-1) for k in bk)
            for gi in sorted(GROUPS.keys()):
                if gi in bg: continue
                for k in GROUPS[gi]:
                    m = bm & AM[k]
                    r = wr_fast(m, hd, min_te=10)
                    if r and r[1] >= 0.66 and r[3] >= 0.59:
                        pf.append((tuple(sorted(set(bk)|{k})), hd, r[0], round(r[1],4), r[2], round(r[3],4)))
            del bm
            if (bi+1) % 1000 == 0:
                log.info(f"  F: {bi+1}/{len(pf_top)} | {len(pf):,} | {(time.time()-T0)/3600:.1f}h")

        log.info(f"Phase F: {len(pf):,}")
        pf.sort(key=lambda x: (x[5], x[4]), reverse=True)
        seen_f = set(); pfu = []
        for r in pf:
            k = (r[4], r[5], r[1])
            if k not in seen_f: seen_f.add(k); pfu.append(r)
        log.info(f"Phase F unique: {len(pfu):,}")
        ALL = pfu

# ═══════════════════════════════════════════════════════════════
# FINAL PHASE: Exit optimization
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("FINAL: Exit optimization")

cand = []
for keys, hd, ntr, wtr, nte, wte in ALL:
    if wte >= 0.55 and nte >= 20:
        cand.append((keys, hd))
seen_cc = set(); uc = []
for c in cand:
    if c not in seen_cc: seen_cc.add(c); uc.append(c)
uc = uc[:5000]
log.info(f"Exit candidates: {len(uc):,}")

TPS = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.15, 0.20, 0.30, None]
SLS = [-0.005, -0.01, -0.015, -0.02, -0.03, -0.05, -0.07, -0.10, None]

FINAL = []
for ci, (keys, _) in enumerate(uc):
    if time.time() - T0 > TIME_LIMIT - 300: break
    mask = build_mask(keys)
    for hd in HOLD_PERIODS:
        for tp in TPS:
            for sl in SLS:
                r = full_eval(mask, hd, tp, sl)
                if not r: continue
                mt, me = r
                if me["wr"] < 0.55: continue
                rob = abs(mt["wr"]-me["wr"]) < 0.15
                sc = (me["wr"]*0.30 + min(me["pf"]/5,1)*0.10
                      + (0.15 if rob else 0) + min(me["n"]/500,1)*0.45)
                p = {"base":" & ".join(keys),"hd":hd,"tp":tp,"sl":sl}
                FINAL.append({"score":round(sc,4),"robust":rob,
                              "params":p,"train":mt,"test":me})
    del mask
    if (ci+1) % 200 == 0:
        log.info(f"  Exit: {ci+1}/{len(uc)} | {len(FINAL):,} | {(time.time()-T0)/3600:.1f}h")
        if (ci+1) % 1000 == 0:
            FINAL.sort(key=lambda x:(min(x["test"]["n"],2000),x["test"]["wr"],x["score"]),reverse=True)
            save_all(dedup(FINAL), f"exit_{ci+1}")

log.info(f"Final raw: {len(FINAL):,}")
FINAL.sort(key=lambda x:(min(x["test"]["n"],2000),x["test"]["wr"],x["score"]),reverse=True)
UF = dedup(FINAL)
log.info(f"Final unique: {len(UF):,}")

for min_n in [5000,2000,1000,500,200,100]:
    sub = [r for r in UF if r["test"]["n"] >= min_n]
    if sub:
        best = max(r["test"]["wr"] for r in sub)
        log.info(f"N>={min_n}: {len(sub):,} best_wr={best:.1%}")

save_all(UF, "final_r2")

def show(title, items, n=25):
    log.info(f"\n{'='*80}\n{title} ({len(items)})\n{'='*80}")
    for i, s in enumerate(items[:n]):
        p=s["params"];te=s["test"];tr=s["train"]
        log.info(f"\n#{i+1} WR={te['wr']:.1%} N={te['n']} PF={te['pf']:.1f} "
                 f"Avg={te['avg']:.3%} TrWR={tr['wr']:.1%} {'ROBUST' if s['robust'] else ''}")
        log.info(f"  {p['base']}")
        log.info(f"  HD={p['hd']}d TP={p['tp']} SL={p['sl']}")

high_n = [r for r in UF if r["test"]["n"]>=500]
high_n.sort(key=lambda x:(x["test"]["wr"],x["test"]["pf"]),reverse=True)
show("HIGH-N (N>=500)", high_n, 30)

wr95 = [r for r in UF if r["test"]["wr"]>=0.95 and r["test"]["n"]>=100]
wr95.sort(key=lambda x:(x["test"]["n"],x["test"]["wr"]),reverse=True)
show("WR>=95% N>=100", wr95, 20)

el = time.time()-T0
log.info(f"\nTotal: {el/3600:.1f}h ({el:.0f}s)")
log.info("ROUND 2 DONE.")

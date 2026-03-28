#!/usr/bin/env python3
"""
Deep Strategy Search v10: 15-hour exhaustive run
~300 filters across all available features.
Phases: Singles→Pairs→Triples→Quads→Quints→Exit optimization
Periodic saves after each phase.
"""
import sys, logging, time, json, pickle, gc, os
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stderr)
log = logging.getLogger("v10")
T0 = time.time()
SAVE_DIR = "quant_research/data"

HOLD_PERIODS = [20, 60, 120]

log.info("Loading...")
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
log.info(f"N={N:,} Tr={IS_TR.sum():,} Te={IS_TE.sum():,} split={split.date()}")

RET = {}
for hd in HOLD_PERIODS:
    v = df[f"fwd_{hd}d_return"].values
    RET[hd] = v
    RET[f"{hd}v"] = ~np.isnan(v)
    RET[f"{hd}p"] = np.where(np.isnan(v), False, v > 0)
    tr_n = int((IS_TR & RET[f"{hd}v"]).sum())
    te_n = int((IS_TE & RET[f"{hd}v"]).sum())
    log.info(f"  {hd}d: train={tr_n:,}, test={te_n:,}")

# ═══════════════════════════════════════════════════════════════
# BUILD COMPREHENSIVE FILTER UNIVERSE
# ═══════════════════════════════════════════════════════════════
log.info("Building comprehensive filter universe...")

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

# ── Group 1: Volume Ratio (vol_ratio) ──
vr = df["vol_ratio"].values
for lo, hi, label in [
    (1.0, 1.5, "VB1.0-1.5"), (1.0, 2.0, "VB1.0-2.0"), (1.0, 3.0, "VB1.0-3.0"),
    (1.0, None, "VB>=1.0"), (1.2, 2.0, "VB1.2-2.0"), (1.2, 3.0, "VB1.2-3.0"),
    (1.2, None, "VB>=1.2"), (1.3, 2.5, "VB1.3-2.5"), (1.3, 3.0, "VB1.3-3.0"),
    (1.3, None, "VB>=1.3"), (1.5, 3.0, "VB1.5-3.0"), (1.5, None, "VB>=1.5"),
    (1.8, 3.0, "VB1.8-3.0"), (1.8, None, "VB>=1.8"), (2.0, None, "VB>=2.0"),
    (None, 1.0, "VB<=1.0"), (None, 1.5, "VB<=1.5"),
    (0.5, 1.0, "VB0.5-1.0"), (0.5, 1.5, "VB0.5-1.5"),
]:
    AM[label] = mkr(vr, lo, hi)

# ── Group 2: RSI ──
rsi = df["rsi"].values
for lo, hi, label in [
    (20, 40, "RSI20-40"), (20, 50, "RSI20-50"), (20, 60, "RSI20-60"),
    (20, 70, "RSI20-70"), (30, 50, "RSI30-50"), (30, 55, "RSI30-55"),
    (30, 60, "RSI30-60"), (30, 65, "RSI30-65"), (30, 70, "RSI30-70"),
    (40, 55, "RSI40-55"), (40, 60, "RSI40-60"), (40, 65, "RSI40-65"),
    (40, 70, "RSI40-70"), (45, 55, "RSI45-55"), (50, 60, "RSI50-60"),
    (50, 65, "RSI50-65"), (50, 70, "RSI50-70"), (50, 80, "RSI50-80"),
    (None, 50, "RSI<=50"), (None, 55, "RSI<=55"), (None, 60, "RSI<=60"),
    (None, 65, "RSI<=65"), (None, 70, "RSI<=70"),
]:
    AM[label] = mkr(rsi, lo, hi)

# ── Group 3: MA25 deviation ──
ma25 = df["ma25_dev"].values
for lo, hi, label in [
    (None, 0.03, "MA25<=3%"), (None, 0.05, "MA25<=5%"), (None, 0.08, "MA25<=8%"),
    (None, 0.10, "MA25<=10%"), (None, 0.15, "MA25<=15%"),
    (-0.05, 0.05, "MA25-5~5%"), (-0.05, 0.10, "MA25-5~10%"),
    (-0.03, 0.03, "MA25-3~3%"), (-0.03, 0.05, "MA25-3~5%"),
    (-0.03, 0.08, "MA25-3~8%"), (-0.03, 0.10, "MA25-3~10%"),
    (0.0, 0.03, "MA25_0~3%"), (0.0, 0.05, "MA25_0~5%"),
    (0.0, 0.08, "MA25_0~8%"), (0.0, 0.10, "MA25_0~10%"),
    (0.02, 0.05, "MA25_2~5%"), (0.02, 0.08, "MA25_2~8%"),
    (0.02, 0.10, "MA25_2~10%"), (0.03, 0.10, "MA25_3~10%"),
    (0.0, None, "MA25>=0%"),
]:
    AM[label] = mkr(ma25, lo, hi)

# ── Group 4: PER ──
per = df["per"].fillna(9999).values
for t in [5, 8, 10, 12, 15, 20, 25, 30, 50]:
    AM[f"PER<={t}"] = (per > 0) & (per <= t)
for lo, hi, label in [
    (5, 10, "PER5-10"), (5, 15, "PER5-15"), (8, 15, "PER8-15"),
    (8, 20, "PER8-20"), (10, 20, "PER10-20"), (10, 25, "PER10-25"),
    (10, 30, "PER10-30"), (15, 30, "PER15-30"),
]:
    AM[label] = (per >= lo) & (per <= hi)

# ── Group 5: PBR ──
pbr = df["pbr"].fillna(9999).values
for t in [0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0]:
    AM[f"PBR<={t}"] = (pbr > 0) & (pbr <= t)
for lo, hi, label in [
    (0.5, 1.0, "PBR0.5-1.0"), (0.5, 1.5, "PBR0.5-1.5"),
    (0.8, 1.5, "PBR0.8-1.5"), (1.0, 2.0, "PBR1.0-2.0"),
]:
    AM[label] = (pbr >= lo) & (pbr <= hi)

# ── Group 6: Market Cap ──
mc = df["market_cap"].fillna(0).values
for lo, hi, label in [
    (5e9, None, "MC>=50億"), (10e9, None, "MC>=100億"), (20e9, None, "MC>=200億"),
    (50e9, None, "MC>=500億"), (100e9, None, "MC>=1000億"),
    (None, 50e9, "MC<=50億"), (None, 100e9, "MC<=1000億"),
    (None, 300e9, "MC<=3000億"), (None, 500e9, "MC<=5000億"), (None, 1e12, "MC<=1兆"),
    (5e9, 50e9, "MC50-500億"), (5e9, 100e9, "MC50-1000億"),
    (10e9, 100e9, "MC100-1000億"), (10e9, 300e9, "MC100-3000億"),
    (10e9, 500e9, "MC100-5000億"), (10e9, 1e12, "MC100-1兆"),
    (20e9, 300e9, "MC200-3000億"), (20e9, 500e9, "MC200-5000億"),
    (20e9, 1e12, "MC200-1兆"), (50e9, 300e9, "MC500-3000億"),
    (50e9, 500e9, "MC500-5000億"), (50e9, 1e12, "MC500-1兆"),
    (50e9, 5e12, "MC500-5兆"), (100e9, 500e9, "MC1000-5000億"),
    (100e9, 1e12, "MC1000-1兆"), (100e9, 5e12, "MC1000-5兆"),
    (500e9, 5e12, "MC5000-5兆"),
]:
    AM[label] = mkr(mc, lo, hi)

# ── Group 7: EPS growth ──
eps_v = df["eps_growth"].values
for t in [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50]:
    AM[f"EPS>={int(t*100)}%"] = mk(eps_v, ">=", t)

# ── Group 8: Operating profit growth ──
og = df["op_growth"].values
for t in [0.0, 0.05, 0.10, 0.20, 0.30, 0.50]:
    AM[f"OG>={int(t*100)}%"] = mk(og, ">=", t)

# ── Group 9: ROE ──
roe_a = df["roe"].values
for t in [0.03, 0.05, 0.08, 0.10, 0.12, 0.15]:
    AM[f"ROE>={int(t*100)}%"] = mk(roe_a, ">=", t)

# ── Group 10: ATR (volatility proxy) ──
atr_a = df["atr_pct"].values
for t in [0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05]:
    AM[f"ATR<={t}"] = mk(atr_a, "<=", t)

# ── Group 11: Volatility ──
vol = df["volatility"].values
for t in [0.01, 0.015, 0.02, 0.025, 0.03]:
    AM[f"Vol<={t}"] = mk(vol, "<=", t)

# ── Group 12: Op Margin ──
opm = df["op_margin"].values
for t in [0.03, 0.05, 0.08, 0.10, 0.15, 0.20]:
    AM[f"OPM>={int(t*100)}%"] = mk(opm, ">=", t)

# ── Group 13: Equity / Debt ratio ──
eq = df["equity_ratio"].values
for t in [0.30, 0.40, 0.50, 0.60, 0.70]:
    AM[f"EqR>={int(t*100)}%"] = mk(eq, ">=", t)
dr = df["debt_ratio"].values
for t in [0.30, 0.40, 0.50, 0.60]:
    AM[f"DebtR<={int(t*100)}%"] = mk(dr, "<=", t)

# ── Group 14: Revenue growth ──
rg = df["revenue_growth"].values
for t in [0.0, 0.05, 0.10, 0.20]:
    AM[f"RevG>={int(t*100)}%"] = mk(rg, ">=", t)

# ── Group 15: Trend indicators ──
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

# ── Group 16: Price from high ──
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
    (-0.15, 0.0, "50dH-15~0%"),
]:
    AM[label] = mkr(pf50, lo, hi)

# ── Group 17: MA75 deviation ──
ma75 = df["ma75_dev"].values
for lo, hi, label in [
    (0.0, 0.05, "MA75_0~5%"), (0.0, 0.10, "MA75_0~10%"),
    (0.0, 0.15, "MA75_0~15%"), (0.0, None, "MA75>=0%"),
    (None, 0.10, "MA75<=10%"), (None, 0.15, "MA75<=15%"),
    (-0.05, 0.05, "MA75-5~5%"), (-0.10, 0.10, "MA75-10~10%"),
]:
    AM[label] = mkr(ma75, lo, hi)

# ── Group 18: Volume zscore ──
vz = df["vol_zscore"].values
for t in [0.5, 1.0, 1.5, 2.0, 2.5]:
    AM[f"VZ>={t}"] = mk(vz, ">=", t)
AM["VZ_neg"] = mk(vz, "<=", -0.5)

# ── Group 19: Volume ratio 5d ──
vr5 = df["vol_ratio_5d"].values
for t in [0.8, 1.0, 1.2, 1.5, 2.0]:
    AM[f"VR5>={t}"] = mk(vr5, ">=", t)

# ── Group 20: Turnover ratio ──
tr = df["turnover_ratio"].values
for t in [0.3, 0.5, 0.8, 1.0, 1.5]:
    AM[f"TR>={t}"] = mk(tr, ">=", t)

# ── Group 21: Momentum ranges ──
m5d = df["mom_5d"].values
for lo, hi, label in [
    (0.0, 0.03, "Mom5_0~3%"), (0.0, 0.05, "Mom5_0~5%"),
    (-0.03, 0.03, "Mom5-3~3%"),
]:
    AM[label] = mkr(m5d, lo, hi)
m20d = df["mom_20d"].values
for lo, hi, label in [
    (0.0, 0.05, "Mom20_0~5%"), (0.0, 0.10, "Mom20_0~10%"),
    (0.05, 0.15, "Mom20_5~15%"),
]:
    AM[label] = mkr(m20d, lo, hi)
m60d = df["mom_60d"].values
for lo, hi, label in [
    (0.0, 0.10, "Mom60_0~10%"), (0.0, 0.20, "Mom60_0~20%"),
    (0.10, 0.30, "Mom60_10~30%"),
]:
    AM[label] = mkr(m60d, lo, hi)

# ── Group 22: MA5 deviation ──
ma5d = df["ma5_dev"].values
for lo, hi, label in [
    (None, 0.01, "MA5<=1%"), (None, 0.02, "MA5<=2%"), (None, 0.03, "MA5<=3%"),
    (-0.01, 0.01, "MA5-1~1%"), (-0.02, 0.02, "MA5-2~2%"),
    (0.0, 0.02, "MA5_0~2%"),
]:
    AM[label] = mkr(ma5d, lo, hi)

# ── Group 23: Price level ──
cl = df["Close"].values
for t in [100, 300, 500, 1000, 2000, 5000]:
    AM[f"Price>={t}"] = cl >= t
for t in [1000, 2000, 3000, 5000, 10000]:
    AM[f"Price<={t}"] = cl <= t

del df
gc.collect()

log.info(f"Total masks: {len(AM)}")

# ── Group assignments ──
GROUPS = {
    0: [k for k in AM if k.startswith("VB")],
    1: [k for k in AM if k.startswith("RSI")],
    2: [k for k in AM if k.startswith("MA25")],
    3: [k for k in AM if k.startswith("PER")],
    4: [k for k in AM if k.startswith("PBR")],
    5: [k for k in AM if k.startswith("MC")],
    6: [k for k in AM if k.startswith("EPS")],
    7: [k for k in AM if k.startswith("OG")],
    8: [k for k in AM if k.startswith("ROE")],
    9: [k for k in AM if k.startswith("ATR")],
    10: [k for k in AM if k.startswith("Vol<=")],
    11: [k for k in AM if k.startswith("OPM")],
    12: [k for k in AM if k.startswith("EqR") or k.startswith("DebtR")],
    13: [k for k in AM if k.startswith("RevG")],
    14: [k for k in AM if k in ["Uptrend","Brk50","Brk200","MA25>75","MA5>25",
                                  "MACD>0","Mom5>0","Mom10>0","Mom20>0","Near52wH"]],
    15: [k for k in AM if k.startswith("52wH") or k.startswith("50dH")],
    16: [k for k in AM if k.startswith("MA75")],
    17: [k for k in AM if k.startswith("VZ")],
    18: [k for k in AM if k.startswith("VR5")],
    19: [k for k in AM if k.startswith("TR>=")],
    20: [k for k in AM if k.startswith("Mom5_") or k.startswith("Mom5-") or
                           k.startswith("Mom20_") or k.startswith("Mom20_") or
                           k.startswith("Mom60_")],
    21: [k for k in AM if k.startswith("MA5") and not k.startswith("MA5>") and not k.startswith("MA5_above")],
    22: [k for k in AM if k.startswith("Price")],
}

key_to_group = {}
for gi, keys in GROUPS.items():
    for k in keys:
        key_to_group[k] = gi

all_group_keys = []
for gi in sorted(GROUPS.keys()):
    for k in GROUPS[gi]:
        all_group_keys.append((gi, k))

for gi in sorted(GROUPS.keys()):
    log.info(f"  Group {gi}: {len(GROUPS[gi])} filters ({GROUPS[gi][:3]}...)")


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
    if nt < 10 or ne < min_te:
        return None
    return (nt, float(RET[f"{hd}p"][tm].sum() / nt),
            ne, float(RET[f"{hd}p"][em].sum() / ne))


def full_eval(mask, hd, tp=None, sl=None):
    v = RET[f"{hd}v"]
    tm = mask & IS_TR & v
    em = mask & IS_TE & v
    if tm.sum() < 10 or em.sum() < 20:
        return None
    rtr = RET[hd][tm].copy()
    rte = RET[hd][em].copy()
    if tp is not None:
        np.clip(rtr, None, tp, out=rtr)
        np.clip(rte, None, tp, out=rte)
    if sl is not None:
        np.clip(rtr, sl, None, out=rtr)
        np.clip(rte, sl, None, out=rte)
    def m(r):
        n = len(r); w = r[r > 0]; lo = r[r <= 0]; wr = len(w) / n
        pf = (w.sum() / max(abs(lo.sum()), 1e-10)) if len(w) > 0 else 0
        aw = w.mean() if len(w) > 0 else 0
        al = abs(lo.mean()) if len(lo) > 0 else 1e-10
        c = np.cumsum(r)
        dd = float((c - np.maximum.accumulate(c)).min()) if len(c) else 0
        return {"n": int(n), "wr": round(wr, 4), "pf": round(pf, 2),
                "wlr": round(aw / al, 2), "dd": round(dd, 4),
                "avg": round(float(r.mean()), 5)}
    return m(rtr), m(rte)


def save_results(UF, phase_name):
    """Save current results to disk."""
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
        "train_end": str(split.date()),
        "phase": phase_name,
        "summary": {
            "wr90": len(wr_bins.get("90+", [])),
            "wr80_90": len(wr_bins.get("80-90", [])),
            "wr70_80": len(wr_bins.get("70-80", [])),
            "wr60_70": len(wr_bins.get("60-70", [])),
        },
        "wr90_plus": wr_bins.get("90+", [])[:30],
        "wr80_90": wr_bins.get("80-90", [])[:50],
        "wr70_80": sorted(wr_bins.get("70-80", []),
                          key=lambda x: x["score"], reverse=True)[:50],
        "best_overall": UF[:100],
    }
    with open(f"{SAVE_DIR}/deep_strategy_results.json", "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    with open(f"{SAVE_DIR}/_results_deep_strategy.pkl", "wb") as f:
        pickle.dump(UF, f)
    log.info(f"[SAVED] {phase_name}: {len(UF):,} strategies "
             f"(90%+:{len(wr_bins.get('90+',[]))} 80-90%:{len(wr_bins.get('80-90',[]))} "
             f"70-80%:{len(wr_bins.get('70-80',[]))})")


def dedup(entries):
    """Dedup by (test_n, test_wr, hd, tp, sl)."""
    seen = set()
    out = []
    for r in entries:
        k = (r["test"]["n"], r["test"]["wr"], r["params"]["hd"],
             r["params"].get("tp"), r["params"].get("sl"))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def make_result(keys, hd, tp=None, sl=None):
    mask = build_mask(keys)
    r = full_eval(mask, hd, tp, sl)
    del mask
    if not r:
        return None
    mt, me = r
    if me["wr"] < 0.55:
        return None
    rob = abs(mt["wr"] - me["wr"]) < 0.15
    sc = (me["wr"] * 0.30
          + min(me["pf"] / 5, 1) * 0.10
          + (0.15 if rob else 0)
          + min(me["n"] / 500, 1) * 0.45)
    p = {"base": " & ".join(keys), "hd": hd, "tp": tp, "sl": sl}
    return {"score": round(sc, 4), "robust": rob,
            "params": p, "train": mt, "test": me}


# ═══════════════════════════════════════════════════════════════
# PHASE 1: Singles
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("PHASE 1: Singles")
log.info("=" * 60)

p1 = []  # (keys_tuple, hd, n_tr, wr_tr, n_te, wr_te)
for k in AM:
    mask = AM[k]
    for hd in HOLD_PERIODS:
        r = wr_fast(mask, hd, min_te=50)
        if r and r[1] >= 0.55 and r[3] >= 0.52:
            p1.append(((k,), hd, r[0], round(r[1], 4), r[2], round(r[3], 4)))

log.info(f"Phase 1: {len(p1):,} singles passing")

# ═══════════════════════════════════════════════════════════════
# PHASE 2: Pairs (different groups)
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("PHASE 2: Pairs")
log.info("=" * 60)

p2 = list(p1)
total = 0
for i in range(len(all_group_keys)):
    gi, ki = all_group_keys[i]
    mi = AM[ki]
    for j in range(i + 1, len(all_group_keys)):
        gj, kj = all_group_keys[j]
        if gi == gj:
            continue
        mask = mi & AM[kj]
        total += 1
        for hd in HOLD_PERIODS:
            r = wr_fast(mask, hd, min_te=50)
            if r and r[1] >= 0.56 and r[3] >= 0.53:
                p2.append(((ki, kj), hd, r[0], round(r[1], 4), r[2], round(r[3], 4)))
    if (i + 1) % 30 == 0:
        log.info(f"  Pairs: {i+1}/{len(all_group_keys)} | total={total:,} | hits={len(p2):,}")

log.info(f"Phase 2: {total:,} pairs tested, {len(p2):,} passing")
p2.sort(key=lambda x: (x[5], x[4]), reverse=True)
seen = set()
p2u = []
for r in p2:
    k = (r[4], r[5], r[1])
    if k not in seen:
        seen.add(k)
        p2u.append(r)
log.info(f"Phase 2 unique: {len(p2u):,}")
if p2u:
    b = p2u[0]
    log.info(f"Best pair: wr={b[5]:.1%} n={b[4]} keys={b[0]}")

# ═══════════════════════════════════════════════════════════════
# PHASE 3: Triples (add filter from different group)
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("PHASE 3: Triples from top pairs")
log.info("=" * 60)

p2_top = p2u[:2000]
p3 = list(p2u)
for bi, (base_keys, hd, _, _, _, _) in enumerate(p2_top):
    base_mask = build_mask(base_keys)
    base_groups = set(key_to_group.get(k, -1) for k in base_keys)

    for gi in sorted(GROUPS.keys()):
        if gi in base_groups:
            continue
        for k in GROUPS[gi]:
            m = base_mask & AM[k]
            r = wr_fast(m, hd, min_te=30)
            if r and r[1] >= 0.58 and r[3] >= 0.55:
                new_keys = tuple(sorted(set(base_keys) | {k}))
                p3.append((new_keys, hd, r[0], round(r[1], 4), r[2], round(r[3], 4)))
    del base_mask
    if (bi + 1) % 200 == 0:
        el = time.time() - T0
        log.info(f"  Triples: {bi+1}/2000 | hits={len(p3):,} | {el/60:.0f}min")

log.info(f"Phase 3: {len(p3):,} total")
p3.sort(key=lambda x: (x[5], x[4]), reverse=True)
seen3 = set()
p3u = []
for r in p3:
    k = (r[4], r[5], r[1])
    if k not in seen3:
        seen3.add(k)
        p3u.append(r)
log.info(f"Phase 3 unique: {len(p3u):,}")

# Save intermediate
inter_FINAL = []
for keys, hd, ntr, wtr, nte, wte in p3u[:500]:
    if wte >= 0.55:
        r = make_result(list(keys), hd)
        if r:
            inter_FINAL.append(r)
inter_FINAL.sort(key=lambda x: (min(x["test"]["n"], 2000), x["test"]["wr"]), reverse=True)
save_results(dedup(inter_FINAL), "phase3_triples")

# ═══════════════════════════════════════════════════════════════
# PHASE 4: Quads (add 4th filter to top triples)
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("PHASE 4: Quads from top triples")
log.info("=" * 60)

p3_top = [r for r in p3u if len(r[0]) == 3][:3000]
p4 = list(p3u)
for bi, (base_keys, hd, _, _, _, _) in enumerate(p3_top):
    base_mask = build_mask(base_keys)
    base_groups = set(key_to_group.get(k, -1) for k in base_keys)

    for gi in sorted(GROUPS.keys()):
        if gi in base_groups:
            continue
        for k in GROUPS[gi]:
            m = base_mask & AM[k]
            r = wr_fast(m, hd, min_te=20)
            if r and r[1] >= 0.60 and r[3] >= 0.56:
                new_keys = tuple(sorted(set(base_keys) | {k}))
                p4.append((new_keys, hd, r[0], round(r[1], 4), r[2], round(r[3], 4)))
    del base_mask
    if (bi + 1) % 300 == 0:
        el = time.time() - T0
        log.info(f"  Quads: {bi+1}/3000 | hits={len(p4):,} | {el/60:.0f}min")

log.info(f"Phase 4: {len(p4):,} total")
p4.sort(key=lambda x: (x[5], x[4]), reverse=True)
seen4 = set()
p4u = []
for r in p4:
    k = (r[4], r[5], r[1])
    if k not in seen4:
        seen4.add(k)
        p4u.append(r)
log.info(f"Phase 4 unique: {len(p4u):,}")

# Save intermediate
inter4 = []
for keys, hd, ntr, wtr, nte, wte in p4u[:1000]:
    if wte >= 0.55:
        r = make_result(list(keys), hd)
        if r:
            inter4.append(r)
inter4.sort(key=lambda x: (min(x["test"]["n"], 2000), x["test"]["wr"]), reverse=True)
save_results(dedup(inter4), "phase4_quads")

# ═══════════════════════════════════════════════════════════════
# PHASE 5: Quints (add 5th filter to top quads)
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("PHASE 5: Quints from top quads")
log.info("=" * 60)

p4_top = [r for r in p4u if len(r[0]) == 4][:4000]
p5 = list(p4u)
for bi, (base_keys, hd, _, _, _, _) in enumerate(p4_top):
    base_mask = build_mask(base_keys)
    base_groups = set(key_to_group.get(k, -1) for k in base_keys)

    for gi in sorted(GROUPS.keys()):
        if gi in base_groups:
            continue
        for k in GROUPS[gi]:
            m = base_mask & AM[k]
            r = wr_fast(m, hd, min_te=15)
            if r and r[1] >= 0.62 and r[3] >= 0.57:
                new_keys = tuple(sorted(set(base_keys) | {k}))
                p5.append((new_keys, hd, r[0], round(r[1], 4), r[2], round(r[3], 4)))
    del base_mask
    if (bi + 1) % 400 == 0:
        el = time.time() - T0
        log.info(f"  Quints: {bi+1}/4000 | hits={len(p5):,} | {el/60:.0f}min | {el/3600:.1f}h")

log.info(f"Phase 5: {len(p5):,} total")
p5.sort(key=lambda x: (x[5], x[4]), reverse=True)
seen5 = set()
p5u = []
for r in p5:
    k = (r[4], r[5], r[1])
    if k not in seen5:
        seen5.add(k)
        p5u.append(r)
log.info(f"Phase 5 unique: {len(p5u):,}")

# Save intermediate
inter5 = []
for keys, hd, ntr, wtr, nte, wte in p5u[:1500]:
    if wte >= 0.55:
        r = make_result(list(keys), hd)
        if r:
            inter5.append(r)
inter5.sort(key=lambda x: (min(x["test"]["n"], 2000), x["test"]["wr"]), reverse=True)
save_results(dedup(inter5), "phase5_quints")

# ═══════════════════════════════════════════════════════════════
# PHASE 6: Sextets (add 6th filter to top quints)
# ═══════════════════════════════════════════════════════════════
el = time.time() - T0
if el < 36000:  # Only if less than 10 hours elapsed
    log.info("\n" + "=" * 60)
    log.info("PHASE 6: Sextets from top quints")
    log.info("=" * 60)

    p5_top = [r for r in p5u if len(r[0]) == 5][:5000]
    p6 = list(p5u)
    for bi, (base_keys, hd, _, _, _, _) in enumerate(p5_top):
        if time.time() - T0 > 43200:
            log.info("Time limit approaching, stopping phase 6")
            break
        base_mask = build_mask(base_keys)
        base_groups = set(key_to_group.get(k, -1) for k in base_keys)

        for gi in sorted(GROUPS.keys()):
            if gi in base_groups:
                continue
            for k in GROUPS[gi]:
                m = base_mask & AM[k]
                r = wr_fast(m, hd, min_te=10)
                if r and r[1] >= 0.64 and r[3] >= 0.58:
                    new_keys = tuple(sorted(set(base_keys) | {k}))
                    p6.append((new_keys, hd, r[0], round(r[1], 4), r[2], round(r[3], 4)))
        del base_mask
        if (bi + 1) % 500 == 0:
            el = time.time() - T0
            log.info(f"  Sextets: {bi+1}/5000 | hits={len(p6):,} | {el/3600:.1f}h")

    log.info(f"Phase 6: {len(p6):,} total")
    p6.sort(key=lambda x: (x[5], x[4]), reverse=True)
    seen6 = set()
    p6u = []
    for r in p6:
        k = (r[4], r[5], r[1])
        if k not in seen6:
            seen6.add(k)
            p6u.append(r)
    log.info(f"Phase 6 unique: {len(p6u):,}")
    ALL_CANDIDATES = p6u
else:
    ALL_CANDIDATES = p5u

# ═══════════════════════════════════════════════════════════════
# PHASE 7: Exit optimization on all top candidates
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("PHASE 7: Exit optimization")
log.info("=" * 60)

cand = []
for keys, hd, ntr, wtr, nte, wte in ALL_CANDIDATES:
    if wte >= 0.55 and nte >= 20:
        cand.append((keys, hd))

seen_c = set()
uc = []
for c in cand:
    if c not in seen_c:
        seen_c.add(c)
        uc.append(c)

MAX_CAND = 3000
if len(uc) > MAX_CAND:
    uc = uc[:MAX_CAND]
log.info(f"Candidates for exit opt: {len(uc):,}")

TPS = [0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30, None]
SLS = [-0.01, -0.02, -0.03, -0.05, -0.07, -0.10, None]

FINAL = []
for ci, (keys, orig_hd) in enumerate(uc):
    if time.time() - T0 > 52200:
        log.info(f"Time limit (14.5h), stopping exit optimization at {ci}/{len(uc)}")
        break
    mask = build_mask(keys)
    for hd in HOLD_PERIODS:
        for tp in TPS:
            for sl in SLS:
                r = full_eval(mask, hd, tp, sl)
                if not r:
                    continue
                mt, me = r
                if me["wr"] < 0.55:
                    continue
                rob = abs(mt["wr"] - me["wr"]) < 0.15
                sc = (me["wr"] * 0.30
                      + min(me["pf"] / 5, 1) * 0.10
                      + (0.15 if rob else 0)
                      + min(me["n"] / 500, 1) * 0.45)
                p = {"base": " & ".join(keys), "hd": hd, "tp": tp, "sl": sl}
                FINAL.append({"score": round(sc, 4), "robust": rob,
                              "params": p, "train": mt, "test": me})
    del mask
    if (ci + 1) % 200 == 0:
        el = time.time() - T0
        log.info(f"  Exit: {ci+1}/{len(uc)} | FINAL={len(FINAL):,} | {el/3600:.1f}h")

log.info(f"Phase 7: {len(FINAL):,}")

FINAL.sort(key=lambda x: (min(x["test"]["n"], 2000), x["test"]["wr"], x["score"]), reverse=True)
UF = dedup(FINAL)
log.info(f"Final unique: {len(UF):,}")

# Stats
for min_n in [2000, 1000, 500, 200, 100, 50]:
    subset = [r for r in UF if r["test"]["n"] >= min_n]
    if subset:
        best_wr = max(r["test"]["wr"] for r in subset)
        log.info(f"N>={min_n}: count={len(subset):,} best_wr={best_wr:.1%}")

save_results(UF, "final_v10")

# Print top strategies
def show(title, items, n=30):
    log.info(f"\n{'=' * 80}")
    log.info(f"{title} ({len(items)})")
    log.info("=" * 80)
    for i, s in enumerate(items[:n]):
        p = s["params"]; tr = s["train"]; te = s["test"]
        log.info(f"\n#{i+1} TestWR={te['wr']:.1%} N={te['n']} TrainWR={tr['wr']:.1%} "
                 f"{'ROBUST' if s['robust'] else ''} Sc={s['score']}")
        log.info(f"  {p['base']}")
        log.info(f"  Hold={p['hd']}d TP={p['tp']} SL={p['sl']}")
        log.info(f"  Train: N={tr['n']} PF={tr['pf']} WLR={tr['wlr']} Avg={tr['avg']:.3%}")
        log.info(f"  Test:  N={te['n']} PF={te['pf']} WLR={te['wlr']} Avg={te['avg']:.3%} DD={te['dd']:.2%}")

high_n = [r for r in UF if r["test"]["n"] >= 500]
high_n.sort(key=lambda x: (x["test"]["wr"], x["test"]["pf"]), reverse=True)
show("HIGH-N (N>=500)", high_n, 30)

wr90 = [r for r in UF if r["test"]["wr"] >= 0.90 and r["test"]["n"] >= 100]
wr90.sort(key=lambda x: (x["test"]["n"], x["test"]["wr"]), reverse=True)
show("WR>=90% N>=100", wr90, 20)

elapsed = time.time() - T0
log.info(f"\nTotal time: {elapsed/3600:.1f} hours ({elapsed:.0f}s)")
log.info("DONE.")

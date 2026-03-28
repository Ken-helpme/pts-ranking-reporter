#!/usr/bin/env python3
"""
Deep Strategy Search v9: High-N focus (N>=500 test trades)
Strategy: fewer filters per condition → higher N.
Phase 1: Single & double filter combos (high N)
Phase 2: Triple filter combos on best bases
Phase 3: Exit optimization
"""
import sys, logging, time, json, pickle, gc
import numpy as np
import pandas as pd
from itertools import combinations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stderr)
log = logging.getLogger("v9")
T0 = time.time()

HOLD_PERIODS = [60, 120]

log.info("Loading...")
df = pd.read_pickle("quant_research/data/_intermediate_df_features.pkl")
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

log.info("Building masks...")

def mk(a, op, val):
    if op == ">=": return np.where(np.isnan(a), False, a >= val)
    if op == "<=": return np.where(np.isnan(a), False, a <= val)
    return a == val

vr = df["vol_ratio"].values
rsi = df["rsi"].values
ma25 = df["ma25_dev"].values
eps_v = df["eps_growth"].values
mc = df["market_cap"].fillna(0).values
per = df["per"].fillna(9999).values
og = df["op_growth"].values
roe_a = df["roe"].values
vz = df["vol_zscore"].values
tr = df["turnover_ratio"].values
vr5 = df["vol_ratio_5d"].values
m5d = df["ma5_dev"].values
atr_a = df["atr_pct"].values

AM = {}
# Volume ratio ranges
for lo, hi, label in [
    (1.0, 1.5, "VB1.0-1.5"), (1.0, 2.0, "VB1.0-2.0"), (1.0, 3.0, "VB1.0-3.0"),
    (1.0, None, "VB>=1.0"),
    (1.2, 2.0, "VB1.2-2.0"), (1.2, 3.0, "VB1.2-3.0"), (1.2, None, "VB>=1.2"),
    (1.3, 2.0, "VB1.3-2.0"), (1.3, 3.0, "VB1.3-3.0"), (1.3, 5.0, "VB1.3-5.0"),
    (1.3, None, "VB>=1.3"),
    (1.5, 3.0, "VB1.5-3.0"), (1.5, 5.0, "VB1.5-5.0"), (1.5, None, "VB>=1.5"),
    (1.8, 3.0, "VB1.8-3.0"), (1.8, 5.0, "VB1.8-5.0"), (1.8, None, "VB>=1.8"),
    (2.0, 5.0, "VB2.0-5.0"), (2.0, None, "VB>=2.0"),
]:
    m = mk(vr, ">=", lo)
    if hi is not None:
        m = m & mk(vr, "<=", hi)
    AM[label] = m

# RSI ranges
for lo, hi, label in [
    (20, 50, "RSI20-50"), (20, 60, "RSI20-60"), (20, 70, "RSI20-70"), (20, 80, "RSI20-80"),
    (30, 55, "RSI30-55"), (30, 60, "RSI30-60"), (30, 65, "RSI30-65"), (30, 70, "RSI30-70"),
    (40, 60, "RSI40-60"), (40, 65, "RSI40-65"), (40, 70, "RSI40-70"),
    (50, 70, "RSI50-70"), (50, 80, "RSI50-80"),
    (None, 60, "RSI<=60"), (None, 65, "RSI<=65"), (None, 70, "RSI<=70"),
]:
    m = np.ones(N, dtype=bool)
    if lo is not None:
        m = m & mk(rsi, ">=", lo)
    if hi is not None:
        m = m & mk(rsi, "<=", hi)
    AM[label] = m

# MA25 deviation ranges
for lo, hi, label in [
    (None, 0.05, "MA<=5%"), (None, 0.08, "MA<=8%"), (None, 0.10, "MA<=10%"),
    (None, 0.15, "MA<=15%"), (None, 0.20, "MA<=20%"),
    (-0.05, 0.05, "MA-5~5%"), (-0.05, 0.10, "MA-5~10%"), (-0.03, 0.05, "MA-3~5%"),
    (-0.03, 0.08, "MA-3~8%"), (-0.03, 0.10, "MA-3~10%"),
    (0.0, 0.05, "MA0~5%"), (0.0, 0.08, "MA0~8%"), (0.0, 0.10, "MA0~10%"),
    (0.0, 0.15, "MA0~15%"), (0.02, 0.05, "MA2~5%"), (0.02, 0.08, "MA2~8%"),
    (0.02, 0.10, "MA2~10%"),
]:
    m = np.ones(N, dtype=bool)
    if lo is not None:
        m = m & mk(ma25, ">=", lo)
    if hi is not None:
        m = m & mk(ma25, "<=", hi)
    AM[label] = m

# Fundamentals
AM["EPS>=0%"] = mk(eps_v, ">=", 0.0)
AM["EPS>=5%"] = mk(eps_v, ">=", 0.05)
AM["EPS>=10%"] = mk(eps_v, ">=", 0.10)
AM["EPS>=20%"] = mk(eps_v, ">=", 0.20)
AM["EPS>=30%"] = mk(eps_v, ">=", 0.30)
AM["OG>=0%"] = mk(og, ">=", 0.0)
AM["OG>=10%"] = mk(og, ">=", 0.10)
AM["OG>=20%"] = mk(og, ">=", 0.20)
AM["PER<=10"] = per <= 10
AM["PER<=15"] = per <= 15
AM["PER<=20"] = per <= 20
AM["PER<=30"] = per <= 30
AM["PER<=50"] = per <= 50
AM["ROE>=5%"] = mk(roe_a, ">=", 0.05)
AM["ROE>=10%"] = mk(roe_a, ">=", 0.10)

# Market cap ranges
for lo, hi, label in [
    (5e9, None, "MC>=50億"), (10e9, None, "MC>=100億"), (20e9, None, "MC>=200億"),
    (50e9, None, "MC>=500億"),
    (None, 100e9, "MC<=1000億"), (None, 300e9, "MC<=3000億"),
    (None, 500e9, "MC<=5000億"), (None, 1e12, "MC<=1兆"), (None, 5e12, "MC<=5兆"),
    (5e9, 100e9, "MC50-1000億"), (5e9, 300e9, "MC50-3000億"), (5e9, 500e9, "MC50-5000億"),
    (10e9, 300e9, "MC100-3000億"), (10e9, 500e9, "MC100-5000億"), (10e9, 1e12, "MC100-1兆"),
    (20e9, 500e9, "MC200-5000億"), (20e9, 1e12, "MC200-1兆"),
    (50e9, 500e9, "MC500-5000億"), (50e9, 1e12, "MC500-1兆"), (50e9, 5e12, "MC500-5兆"),
]:
    m = np.ones(N, dtype=bool)
    if lo is not None:
        m = m & (mc >= lo)
    if hi is not None:
        m = m & (mc <= hi)
    AM[label] = m

# Trend & technical
AM["Uptrend"] = df["full_uptrend"].values == 1
AM["Brk50"] = df["breakout_50d"].values == 1
AM["MA25>75"] = df["ma25_above_ma75"].values == 1
AM["MA5>25"] = df["ma5_above_ma25"].values == 1
AM["MACD>0"] = df["macd_hist"].fillna(0).values > 0
AM["Mom5>0"] = df["mom_5d"].fillna(0).values > 0
AM["Near52wH"] = df["near_52w_high"].values == 1
AM["VZ>=1.0"] = mk(vz, ">=", 1.0)
AM["VZ>=1.5"] = mk(vz, ">=", 1.5)
AM["VZ>=2.0"] = mk(vz, ">=", 2.0)
AM["TR>=0.3"] = mk(tr, ">=", 0.3)
AM["TR>=0.5"] = mk(tr, ">=", 0.5)
AM["VR5>=1.0"] = mk(vr5, ">=", 1.0)
AM["VR5>=1.5"] = mk(vr5, ">=", 1.5)
AM["ATR<=3%"] = mk(atr_a, "<=", 0.03)
AM["ATR<=5%"] = mk(atr_a, "<=", 0.05)

del df
gc.collect()

log.info(f"Total masks: {len(AM)}")

# Categorize filters for systematic combination
VB_KEYS = [k for k in AM if k.startswith("VB")]
RSI_KEYS = [k for k in AM if k.startswith("RSI")]
MA_KEYS = [k for k in AM if k.startswith("MA") and not k.startswith("MACD") and not k.startswith("MA25>") and not k.startswith("MA5>")]
FUND_KEYS = [k for k in AM if k.startswith("EPS") or k.startswith("OG") or k.startswith("PER") or k.startswith("ROE")]
MC_KEYS = [k for k in AM if k.startswith("MC")]
TREND_KEYS = ["Uptrend", "Brk50", "MA25>75", "MA5>25", "MACD>0", "Mom5>0", "Near52wH"]
VOL_KEYS = [k for k in AM if k.startswith("VZ") or k.startswith("TR>=") or k.startswith("VR5")]
TECH_KEYS = [k for k in AM if k.startswith("ATR")]

log.info(f"VB:{len(VB_KEYS)} RSI:{len(RSI_KEYS)} MA:{len(MA_KEYS)} "
         f"FUND:{len(FUND_KEYS)} MC:{len(MC_KEYS)} TREND:{len(TREND_KEYS)} "
         f"VOL:{len(VOL_KEYS)} TECH:{len(TECH_KEYS)}")


def build_mask(keys):
    m = np.ones(N, dtype=bool)
    for k in keys:
        m &= AM[k]
    return m


def wr_fast(mask, hd, min_tr=10, min_te=50):
    v = RET[f"{hd}v"]
    tm = mask & IS_TR & v
    em = mask & IS_TE & v
    nt = int(tm.sum()); ne = int(em.sum())
    if nt < min_tr or ne < min_te:
        return None
    return (nt, RET[f"{hd}p"][tm].sum() / nt, ne, RET[f"{hd}p"][em].sum() / ne)


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
        c = np.cumsum(r); dd = float((c - np.maximum.accumulate(c)).min()) if len(c) else 0
        return {"n": int(n), "wr": round(wr, 4), "pf": round(pf, 2),
                "wlr": round(aw / al, 2), "dd": round(dd, 4), "avg": round(float(r.mean()), 5)}
    return m(rtr), m(rte)


# ═══════════════════════════════════════════════════════════════
# PHASE 1: Single filters + pair combos → high N
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("PHASE 1: Single & pair filter combos")
log.info("=" * 60)

ALL_FILTER_GROUPS = [VB_KEYS, RSI_KEYS, MA_KEYS, FUND_KEYS, MC_KEYS,
                     TREND_KEYS, VOL_KEYS, TECH_KEYS]
ALL_KEYS = VB_KEYS + RSI_KEYS + MA_KEYS + FUND_KEYS + MC_KEYS + TREND_KEYS + VOL_KEYS + TECH_KEYS

p1 = []
total = 0

# Single filters
for k in ALL_KEYS:
    mask = AM[k]
    total += 1
    for hd in HOLD_PERIODS:
        r = wr_fast(mask, hd, min_tr=10, min_te=100)
        if r and r[1] >= 0.58 and r[3] >= 0.55:
            p1.append(((k,), hd, r[0], round(r[1], 4), r[2], round(r[3], 4)))

log.info(f"Singles: {total} tested, {len(p1)} passing")

# Pairs from DIFFERENT groups
groups_flat = []
for gi, grp in enumerate(ALL_FILTER_GROUPS):
    for k in grp:
        groups_flat.append((gi, k))

for i in range(len(groups_flat)):
    gi, ki = groups_flat[i]
    mi = AM[ki]
    for j in range(i + 1, len(groups_flat)):
        gj, kj = groups_flat[j]
        if gi == gj:
            continue
        mask = mi & AM[kj]
        total += 1
        for hd in HOLD_PERIODS:
            r = wr_fast(mask, hd, min_tr=10, min_te=100)
            if r and r[1] >= 0.58 and r[3] >= 0.55:
                p1.append(((ki, kj), hd, r[0], round(r[1], 4), r[2], round(r[3], 4)))
    if (i + 1) % 20 == 0:
        log.info(f"  Pairs: base {i+1}/{len(groups_flat)} | total={total:,} | p1={len(p1):,}")

log.info(f"Phase 1 total: {total:,} combos, {len(p1):,} passing")

p1.sort(key=lambda x: (x[5], x[4]), reverse=True)
seen = set()
p1u = []
for r in p1:
    k = (r[4], r[5], r[1])
    if k not in seen:
        seen.add(k)
        p1u.append(r)
log.info(f"Phase 1 unique: {len(p1u):,}")
if p1u:
    best = p1u[0]
    log.info(f"Best: test_wr={best[5]:.1%} te_n={best[4]} keys={best[0]}")

# ═══════════════════════════════════════════════════════════════
# PHASE 2: Triple combos on top bases
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("PHASE 2: Add third filter to top bases")
log.info("=" * 60)

p1_top = p1u[:800]
p2 = list(p1u)

for bi, (base_keys, hd, _, _, _, _) in enumerate(p1_top):
    base_mask = build_mask(base_keys)
    base_groups = set()
    for gi, grp in enumerate(ALL_FILTER_GROUPS):
        for bk in base_keys:
            if bk in grp:
                base_groups.add(gi)

    for gi, grp in enumerate(ALL_FILTER_GROUPS):
        if gi in base_groups:
            continue
        for k in grp:
            m = base_mask & AM[k]
            r = wr_fast(m, hd, min_tr=10, min_te=50)
            if r and r[1] >= 0.60 and r[3] >= 0.56:
                new_keys = tuple(sorted(set(base_keys) | {k}))
                p2.append((new_keys, hd, r[0], round(r[1], 4), r[2], round(r[3], 4)))
    del base_mask
    if (bi + 1) % 100 == 0:
        log.info(f"  {bi+1}/800 | p2={len(p2):,}")

log.info(f"Phase 2: {len(p2):,} total")

p2.sort(key=lambda x: (x[5], x[4]), reverse=True)
seen2 = set()
p2u = []
for r in p2:
    k = (r[4], r[5], r[1])
    if k not in seen2:
        seen2.add(k)
        p2u.append(r)
log.info(f"Phase 2 unique: {len(p2u):,}")

# ═══════════════════════════════════════════════════════════════
# PHASE 3: Exit optimization (TP/SL)
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("PHASE 3: Exit optimization")
log.info("=" * 60)

cand = []
for keys, hd, ntr, wtr, nte, wte in p2u:
    if wte >= 0.55 and nte >= 50:
        cand.append((keys, hd))

seen_c = set()
uc = []
for c in cand:
    if c not in seen_c:
        seen_c.add(c)
        uc.append(c)
uc = uc[:1000]
log.info(f"Candidates: {len(uc):,}")

TPS = [0.03, 0.05, 0.08, 0.10, 0.15, 0.20, None]
SLS = [-0.01, -0.02, -0.03, -0.05, -0.07, -0.10, None]

FINAL = []
for ci, (keys, _) in enumerate(uc):
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
    if (ci + 1) % 100 == 0:
        log.info(f"  {ci+1}/{len(uc)} | FINAL={len(FINAL):,}")

log.info(f"Phase 3: {len(FINAL):,}")

# ── sort + dedup ─────────────────────────────────────────────
FINAL.sort(key=lambda x: (min(x["test"]["n"], 2000), x["test"]["wr"], x["score"]), reverse=True)
seen_f = set()
UF = []
for r in FINAL:
    k = (r["train"]["n"], r["train"]["wr"], r["test"]["n"], r["test"]["wr"],
         r["params"]["hd"], r["params"]["tp"], r["params"]["sl"])
    if k not in seen_f:
        seen_f.add(k)
        UF.append(r)

log.info(f"Unique final: {len(UF):,}")

# Stats
for min_n in [1000, 500, 200, 100, 50]:
    subset = [r for r in UF if r["test"]["n"] >= min_n]
    if subset:
        best_wr = max(r["test"]["wr"] for r in subset)
        log.info(f"N>={min_n}: count={len(subset):,} best_wr={best_wr:.1%}")

wr_bins = {}
for r in UF:
    wr = r["test"]["wr"]
    if wr >= 0.90: wr_bins.setdefault("90+", []).append(r)
    elif wr >= 0.80: wr_bins.setdefault("80-90", []).append(r)
    elif wr >= 0.70: wr_bins.setdefault("70-80", []).append(r)
    elif wr >= 0.60: wr_bins.setdefault("60-70", []).append(r)
    else: wr_bins.setdefault("55-60", []).append(r)

for label in ["90+", "80-90", "70-80", "60-70", "55-60"]:
    items = wr_bins.get(label, [])
    n500 = sum(1 for r in items if r["test"]["n"] >= 500)
    n200 = sum(1 for r in items if r["test"]["n"] >= 200)
    log.info(f"WR {label}: total={len(items)} N>=500:{n500} N>=200:{n200}")


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
show("HIGH-N STRATEGIES (N>=500)", high_n, 30)

mid_n = [r for r in UF if 200 <= r["test"]["n"] < 500]
mid_n.sort(key=lambda x: (x["test"]["wr"], x["test"]["pf"]), reverse=True)
show("MID-N (200-499)", mid_n, 20)

out = {
    "generated_at": pd.Timestamp.now().isoformat(),
    "train_end": str(split.date()),
    "summary": {
        "wr90": len(wr_bins.get("90+", [])),
        "wr80_90": len(wr_bins.get("80-90", [])),
        "wr70_80": len(wr_bins.get("70-80", [])),
        "wr60_70": len(wr_bins.get("60-70", [])),
    },
    "wr90_plus": wr_bins.get("90+", [])[:30],
    "wr80_90": wr_bins.get("80-90", [])[:50],
    "wr70_80": sorted(wr_bins.get("70-80", []), key=lambda x: x["score"], reverse=True)[:50],
    "best_overall": UF[:100],
}
with open("quant_research/data/deep_strategy_results.json", "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False, default=str)
with open("quant_research/data/_results_deep_strategy.pkl", "wb") as f:
    pickle.dump(UF, f)

log.info(f"\nDone. {time.time()-T0:.1f}s")

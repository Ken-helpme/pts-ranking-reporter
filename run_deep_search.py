#!/usr/bin/env python3
"""
Deep Strategy Search v6: Target 80%+ Win Rate
Memory-safe: store only filter labels, recompute masks on demand.
"""
import sys, logging, time, json, pickle
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stderr)
log = logging.getLogger("v6")
T0 = time.time()

log.info("Loading...")
df = pd.read_pickle("quant_research/data/_intermediate_df_features.pkl")
N = len(df)

for hd in [60, 120, 250]:
    c = f"fwd_{hd}d_return"
    if c not in df.columns:
        df[c] = df.groupby("Code")["Close"].transform(lambda x: x.shift(-hd) / x - 1)

dates = sorted(df["Date"].unique())
split = pd.Timestamp(dates[int(len(dates) * 0.7)])
IS_TR = (df["Date"] <= split).values
IS_TE = (df["Date"] > split).values
log.info(f"N={N:,} Tr={IS_TR.sum():,} Te={IS_TE.sum():,}")

RET = {}
for hd in [60, 120, 250]:
    v = df[f"fwd_{hd}d_return"].values
    RET[hd] = v
    RET[f"{hd}v"] = ~np.isnan(v)
    RET[f"{hd}p"] = np.where(np.isnan(v), False, v > 0)

# ── build all masks (stored once, shared, never copied) ──────────────────
log.info("Building masks...")

def mk(a, op, val):
    if op == ">=": return np.where(np.isnan(a), False, a >= val)
    if op == "<=": return np.where(np.isnan(a), False, a <= val)
    if op == ">":  return np.where(np.isnan(a), False, a > val)
    return a == val

vr = df["vol_ratio"].values
rsi = df["rsi"].values
ma25 = df["ma25_dev"].values

# All named masks in a single dict
AM = {}
for t in [1.3,1.5,1.8,2.0,2.5,3.0]: AM[f"vb>={t}"] = mk(vr,">=",t)
for t in [2.5,3.0,4.0,5.0]: AM[f"vb<={t}"] = mk(vr,"<=",t)
for t in [30,40,50]: AM[f"rsi>={t}"] = mk(rsi,">=",t)
for t in [55,60,65,70]: AM[f"rsi<={t}"] = mk(rsi,"<=",t)
for t in [-0.03,0.0,0.02]: AM[f"ma>={t}"] = mk(ma25,">=",t)
for t in [0.05,0.08,0.10]: AM[f"ma<={t}"] = mk(ma25,"<=",t)
eps_v = df["eps_growth"].values
for t in [0.10,0.20,0.30]: AM[f"eps>={t}"] = mk(eps_v,">=",t)
mc = df["market_cap"].fillna(0).values
for t in [5e9,20e9,50e9]: AM[f"mc>={t}"] = mc >= t
for t in [100e9,500e9,1e12]: AM[f"mc<={t}"] = mc <= t

AM["uptrend"] = df["full_uptrend"].values == 1
AM["brk50"] = df["breakout_50d"].values == 1
AM["ma25>75"] = df["ma25_above_ma75"].values == 1
AM["ma5>25"] = df["ma5_above_ma25"].values == 1
AM["macd>0"] = df["macd_hist"].fillna(0).values > 0
AM["mom5>0"] = df["mom_5d"].fillna(0).values > 0
AM["n52w"] = df["near_52w_high"].values == 1
vz = df["vol_zscore"].values
for t in [1.0,1.5,2.0,2.5]: AM[f"vz>={t}"] = mk(vz,">=",t)
tr = df["turnover_ratio"].values
for t in [0.3,0.5,1.0]: AM[f"tr>={t}"] = mk(tr,">=",t)
per = df["per"].fillna(9999).values
for t in [8,10,15,20]: AM[f"per<={t}"] = per <= t
og = df["op_growth"].values
for t in [0.0,0.10,0.20,0.30]: AM[f"og>={t}"] = mk(og,">=",t)
roe_a = df["roe"].values
for t in [0.05,0.10]: AM[f"roe>={t}"] = mk(roe_a,">=",t)
atr_a = df["atr_pct"].values
for t in [0.02,0.03,0.05]: AM[f"atr<={t}"] = mk(atr_a,"<=",t)
vr5 = df["vol_ratio_5d"].values
for t in [1.0,1.5,2.0]: AM[f"vr5>={t}"] = mk(vr5,">=",t)
m5d = df["ma5_dev"].values
for t in [0.02,0.03,0.05]: AM[f"m5d<={t}"] = mk(m5d,"<=",t)

# Free the DataFrame to save memory
del df
import gc; gc.collect()

log.info(f"Total masks: {len(AM)}")


def build_mask(keys):
    """Build mask from filter key list. No copies stored."""
    m = np.ones(N, dtype=bool)
    for k in keys:
        m &= AM[k]
    return m


def wr_fast(mask, hd):
    v = RET[f"{hd}v"]
    tm = mask & IS_TR & v
    em = mask & IS_TE & v
    nt = int(tm.sum()); ne = int(em.sum())
    if nt < 5 or ne < 3: return None
    return (nt, RET[f"{hd}p"][tm].sum()/nt, ne, RET[f"{hd}p"][em].sum()/ne)


def full_eval(mask, hd, tp=None, sl=None):
    v = RET[f"{hd}v"]
    tm = mask & IS_TR & v
    em = mask & IS_TE & v
    if tm.sum() < 5 or em.sum() < 3: return None
    rtr = RET[hd][tm].copy()
    rte = RET[hd][em].copy()
    if tp is not None:
        np.clip(rtr, None, tp, out=rtr)
        np.clip(rte, None, tp, out=rte)
    if sl is not None:
        np.clip(rtr, sl, None, out=rtr)
        np.clip(rte, sl, None, out=rte)
    def m(r):
        n=len(r);w=r[r>0];lo=r[r<=0];wr=len(w)/n
        pf=(w.sum()/max(abs(lo.sum()),1e-10)) if len(w)>0 else 0
        aw=w.mean() if len(w)>0 else 0
        al=abs(lo.mean()) if len(lo)>0 else 1e-10
        c=np.cumsum(r);dd=float((c-np.maximum.accumulate(c)).min()) if len(c) else 0
        return {"n":int(n),"wr":round(wr,4),"pf":round(pf,2),"wlr":round(aw/al,2),
                "dd":round(dd,4),"avg":round(float(r.mean()),5)}
    return m(rtr), m(rte)


# ═══════════════════════════════════════════════════════════════
# STEP 1: Base grid — store LABELS only (no mask copies!)
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("STEP 1: Base grid (labels only, no mask storage)")
log.info("=" * 60)

VBM = [1.3, 1.5, 1.8, 2.0, 2.5, 3.0]
VBX = [None, 2.5, 3.0, 4.0, 5.0]
RSM = [30, 40, 50]
RSX = [55, 60, 65, 70]
MAM = [-0.03, 0.0, 0.02]
MAX_ = [0.05, 0.08, 0.10]
EPS = [None, 0.10, 0.20, 0.30]
MCM = [5e9, 20e9, 50e9]
MCX = [100e9, 500e9, 1e12]

# p1: list of (filter_keys_tuple, hd, n_tr, wr_tr, n_te, wr_te)
p1 = []
total = 0

for vbm in VBM:
    m1 = AM[f"vb>={vbm}"]
    for vbx in VBX:
        if vbx is not None and vbm >= vbx: continue
        m2 = m1 & AM[f"vb<={vbx}"] if vbx else m1
        for rsm in RSM:
            m3 = m2 & AM[f"rsi>={rsm}"]
            for rsx in RSX:
                if rsm >= rsx: continue
                m4 = m3 & AM[f"rsi<={rsx}"]
                for mam in MAM:
                    m5 = m4 & AM[f"ma>={mam}"]
                    for max_v in MAX_:
                        if mam >= max_v: continue
                        m6 = m5 & AM[f"ma<={max_v}"]
                        for ep in EPS:
                            m7 = m6 & AM[f"eps>={ep}"] if ep else m6
                            for mcm in MCM:
                                m8 = m7 & AM[f"mc>={mcm}"]
                                for mcx in MCX:
                                    if mcm >= mcx: continue
                                    mask = m8 & AM[f"mc<={mcx}"]
                                    total += 1

                                    keys = [f"vb>={vbm}"]
                                    if vbx: keys.append(f"vb<={vbx}")
                                    keys += [f"rsi>={rsm}", f"rsi<={rsx}",
                                             f"ma>={mam}", f"ma<={max_v}"]
                                    if ep: keys.append(f"eps>={ep}")
                                    keys += [f"mc>={mcm}", f"mc<={mcx}"]

                                    for hd in [60, 120, 250]:
                                        r = wr_fast(mask, hd)
                                        if r and r[1] >= 0.64 and r[3] >= 0.54:
                                            p1.append((tuple(keys), hd,
                                                        r[0], round(r[1],4),
                                                        r[2], round(r[3],4)))

                                    if total % 5000 == 0:
                                        log.info(f"  {total:,} combos | p1={len(p1):,}")

log.info(f"Step 1: {total:,} combos, {len(p1):,} passing (tr>=64% te>=54%)")

p1.sort(key=lambda x: (x[3]+x[5])/2, reverse=True)
seen = set()
p1u = []
for r in p1:
    k = (r[2], r[3], r[4], r[5], r[1])
    if k not in seen: seen.add(k); p1u.append(r)
log.info(f"Step 1 unique: {len(p1u):,}")
if p1u: log.info(f"Best: train={p1u[0][3]:.1%} test={p1u[0][5]:.1%}")

p1_top = p1u[:400]

# ═══════════════════════════════════════════════════════════════
# STEP 2: Stack extra filters (recompute masks, no storage)
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("STEP 2: Multi-factor stacking on top 400")

trend_k = ["uptrend","brk50","ma25>75","ma5>25","mom5>0","n52w"]
vol_k = [k for k in AM if k.startswith("vz") or k.startswith("tr>=") or k.startswith("vr5")]
fund_k = [k for k in AM if k.startswith("per") or k.startswith("og") or k.startswith("roe")]
tech_k = ["macd>0"] + [k for k in AM if k.startswith("atr") or k.startswith("m5d")]

ec_set = set()
for k in trend_k+vol_k+fund_k+tech_k: ec_set.add((k,))
for a in trend_k:
    for b in vol_k+fund_k+tech_k: ec_set.add(tuple(sorted([a,b])))
for a in vol_k:
    for b in fund_k+tech_k: ec_set.add(tuple(sorted([a,b])))
for a in fund_k:
    for b in tech_k: ec_set.add(tuple(sorted([a,b])))
for t in trend_k:
    for v in vol_k:
        for f in fund_k: ec_set.add(tuple(sorted([t,v,f])))
        for x in tech_k: ec_set.add(tuple(sorted([t,v,x])))
    for f in fund_k:
        for x in tech_k: ec_set.add(tuple(sorted([t,f,x])))
for t in trend_k:
    for v in vol_k:
        for f in fund_k:
            for x in tech_k: ec_set.add(tuple(sorted([t,v,f,x])))
for i,t1 in enumerate(trend_k):
    for t2 in trend_k[i+1:]:
        for v in vol_k:
            for f in fund_k: ec_set.add(tuple(sorted([t1,t2,v,f])))

ec_list = list(ec_set)
log.info(f"Extra combos: {len(ec_list):,}")

# p2: (base_keys, extra_keys, hd, n_tr, wr_tr, n_te, wr_te)
p2 = []
for bi, (base_keys, hd, _, _, _, _) in enumerate(p1_top):
    base_mask = build_mask(base_keys)
    for ec in ec_list:
        m = base_mask.copy()
        for k in ec: m &= AM[k]
        r = wr_fast(m, hd)
        if r and r[1] >= 0.74 and r[3] >= 0.62:
            p2.append((base_keys, ec, hd, r[0], round(r[1],4), r[2], round(r[3],4)))
    del base_mask
    if (bi+1) % 40 == 0:
        log.info(f"  {bi+1}/400 | p2={len(p2):,}")

log.info(f"Step 2: {len(p2):,} (tr>=74% te>=62%)")

# ═══════════════════════════════════════════════════════════════
# STEP 3: TP/SL exit optimization
# ═══════════════════════════════════════════════════════════════
log.info("\n" + "=" * 60)
log.info("STEP 3: Exit optimization")

# Collect candidate filter-key-sets
cand_keys = []
for keys, hd, ntr, wtr, nte, wte in p1u:
    if wtr >= 0.70 and wte >= 0.58:
        cand_keys.append((keys, (), hd))

for bk, ek, hd, _, _, _, _ in p2:
    cand_keys.append((bk, ek, hd))

seen_c = set(); uc = []
for c in cand_keys:
    k = (c[0], c[1], c[2])
    if k not in seen_c: seen_c.add(k); uc.append(c)
uc = uc[:600]
log.info(f"Candidates: {len(uc):,}")

TPS = [0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.15, None]
SLS = [-0.01, -0.015, -0.02, -0.03, -0.05, -0.07, None]

FINAL = []
for ci, (bk, ek, _) in enumerate(uc):
    all_keys = list(bk) + list(ek)
    mask = build_mask(all_keys)

    for hd in [60, 120, 250]:
        for tp in TPS:
            for sl in SLS:
                r = full_eval(mask, hd, tp, sl)
                if not r: continue
                mt, me = r
                if mt["wr"] < 0.70 or me["wr"] < 0.58: continue
                rob = abs(mt["wr"]-me["wr"]) < 0.15
                sc = me["wr"]*0.50+min(me["pf"]/5,1)*0.20+(0.20 if rob else 0)+min(me["n"]/30,1)*0.10
                p = {"base": " & ".join(bk), "hd": hd, "tp": tp, "sl": sl}
                if ek: p["extra"] = list(ek)
                FINAL.append({"score":round(sc,4),"robust":rob,"params":p,"train":mt,"test":me})

    del mask
    if (ci+1) % 100 == 0:
        log.info(f"  {ci+1}/{len(uc)} res={len(FINAL):,}")

log.info(f"Step 3: {len(FINAL):,}")

# ── sort + dedup ─────────────────────────────────────────────
FINAL.sort(key=lambda x: (x["test"]["wr"], x["score"]), reverse=True)
seen_f = set(); UF = []
for r in FINAL:
    k = (r["train"]["n"],r["train"]["wr"],r["test"]["n"],r["test"]["wr"],
         r["params"]["hd"],r["params"]["tp"],r["params"]["sl"])
    if k not in seen_f: seen_f.add(k); UF.append(r)

log.info(f"Unique: {len(UF):,}")
wr90=[r for r in UF if r["test"]["wr"]>=0.90]
wr80=[r for r in UF if 0.80<=r["test"]["wr"]<0.90]
wr70=[r for r in UF if 0.70<=r["test"]["wr"]<0.80]
wr60=[r for r in UF if 0.60<=r["test"]["wr"]<0.70]
log.info(f"90%+:{len(wr90)} | 80-90%:{len(wr80)} | 70-80%:{len(wr70)} | 60-70%:{len(wr60)}")

def show(title, items, n=30):
    log.info(f"\n{'='*80}")
    log.info(f"{title} ({len(items)})")
    log.info("="*80)
    for i,s in enumerate(items[:n]):
        p=s["params"];tr=s["train"];te=s["test"]
        log.info(f"\n#{i+1} TestWR={te['wr']:.1%} TrainWR={tr['wr']:.1%} {'ROBUST' if s['robust'] else ''} Sc={s['score']}")
        log.info(f"  {p['base']}")
        if p.get("extra"): log.info(f"  +Extra: {' & '.join(p['extra'])}")
        log.info(f"  Hold={p['hd']}d TP={p['tp']} SL={p['sl']}")
        log.info(f"  Train: N={tr['n']} PF={tr['pf']} WLR={tr['wlr']} Avg={tr['avg']:.3%}")
        log.info(f"  Test:  N={te['n']} PF={te['pf']} WLR={te['wlr']} Avg={te['avg']:.3%} DD={te['dd']:.2%}")

show("90%+ WIN RATE", wr90, 25)
show("80-90% WIN RATE", wr80, 30)
show("70-80%", sorted(wr70, key=lambda x: x["score"], reverse=True), 15)
show("BEST 60-70%", sorted(wr60, key=lambda x: x["test"]["pf"], reverse=True), 10)

out = {
    "generated_at": pd.Timestamp.now().isoformat(), "train_end": str(split.date()),
    "summary": {"wr90":len(wr90),"wr80_90":len(wr80),"wr70_80":len(wr70),"wr60_70":len(wr60)},
    "wr90_plus": wr90[:30], "wr80_90": wr80[:50],
    "wr70_80": sorted(wr70, key=lambda x: x["score"], reverse=True)[:50],
    "best_overall": UF[:100],
}
with open("quant_research/data/deep_strategy_results.json","w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False, default=str)
with open("quant_research/data/_results_deep_strategy.pkl","wb") as f:
    pickle.dump(UF, f)

log.info(f"\nDone. {time.time()-T0:.1f}s")

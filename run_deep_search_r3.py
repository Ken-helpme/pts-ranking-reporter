#!/usr/bin/env python3
"""
Deep Strategy Search Round 3: Ultra-fine exit grids + 8-filter combos
Builds on R2's best strategies (top ~5000 by N*WR).
Explores:
- Ultra-fine TP (0.5%-30%) and SL (0.2%-15%) grids
- 8-filter combos from best 7-filter bases
- All 4 holding periods per candidate
Time limit: 10 hours
"""
import sys, logging, time, json, pickle, gc
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stderr)
log = logging.getLogger("r3")
T0 = time.time()
SAVE_DIR = "quant_research/data"
TIME_LIMIT = 10 * 3600
HOLD_PERIODS = [10, 20, 60, 120]

log.info("Round 3: Loading...")
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

log.info("Loading R2 results for base strategies...")
with open(f"{SAVE_DIR}/_results_deep_strategy.pkl", "rb") as f:
    r2_all = pickle.load(f)
log.info(f"R2 strategies: {len(r2_all):,}")

base_conds = set()
for r in r2_all:
    if r["test"]["n"] >= 200 and r["test"]["wr"] >= 0.60:
        base_conds.add(r["params"]["base"])
log.info(f"Unique base conditions to refine: {len(base_conds):,}")

# Rebuild filter universe (same as R2)
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
]: AM[label] = mkr(vr, lo, hi)

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
]: AM[label] = mkr(rsi, lo, hi)

ma25 = df["ma25_dev"].values
for lo, hi, label in [
    (None, 0.02, "MA25<=2%"), (None, 0.03, "MA25<=3%"), (None, 0.05, "MA25<=5%"),
    (None, 0.08, "MA25<=8%"), (None, 0.10, "MA25<=10%"),
    (-0.03, 0.03, "MA25-3~3%"), (-0.03, 0.05, "MA25-3~5%"),
    (-0.03, 0.08, "MA25-3~8%"), (-0.05, 0.05, "MA25-5~5%"),
    (0.0, 0.03, "MA25_0~3%"), (0.0, 0.05, "MA25_0~5%"),
    (0.02, 0.05, "MA25_2~5%"), (0.02, 0.08, "MA25_2~8%"),
    (0.0, None, "MA25>=0%"),
]: AM[label] = mkr(ma25, lo, hi)

per = df["per"].fillna(9999).values
for t in [3,5,6,7,8,9,10,11,12,13,14,15,18,20,25,30]:
    AM[f"PER<={t}"] = (per > 0) & (per <= t)
for lo, hi, label in [
    (3,8,"PER3-8"),(3,10,"PER3-10"),(5,10,"PER5-10"),(5,12,"PER5-12"),
    (5,15,"PER5-15"),(7,12,"PER7-12"),(7,15,"PER7-15"),(8,12,"PER8-12"),
    (8,15,"PER8-15"),(8,20,"PER8-20"),(10,15,"PER10-15"),(10,20,"PER10-20"),
]: AM[label] = (per >= lo) & (per <= hi)

pbr = df["pbr"].fillna(9999).values
for t in [0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0,1.2,1.5,2.0]:
    AM[f"PBR<={t}"] = (pbr > 0) & (pbr <= t)
for lo, hi, label in [
    (0.2,0.5,"PBR0.2-0.5"),(0.3,0.6,"PBR0.3-0.6"),(0.3,0.7,"PBR0.3-0.7"),
    (0.3,0.8,"PBR0.3-0.8"),(0.4,0.7,"PBR0.4-0.7"),(0.4,0.8,"PBR0.4-0.8"),
    (0.5,0.8,"PBR0.5-0.8"),(0.5,1.0,"PBR0.5-1.0"),(0.5,1.2,"PBR0.5-1.2"),
    (0.6,1.0,"PBR0.6-1.0"),(0.7,1.0,"PBR0.7-1.0"),(0.8,1.2,"PBR0.8-1.2"),
    (0.8,1.5,"PBR0.8-1.5"),(1.0,1.5,"PBR1.0-1.5"),(1.0,2.0,"PBR1.0-2.0"),
]: AM[label] = (pbr >= lo) & (pbr <= hi)

mc = df["market_cap"].fillna(0).values
for lo, hi, label in [
    (None,10e9,"MC<=100億"),(None,20e9,"MC<=200億"),(None,50e9,"MC<=500億"),
    (None,100e9,"MC<=1000億"),(None,300e9,"MC<=3000億"),(None,500e9,"MC<=5000億"),
    (None,1e12,"MC<=1兆"),(5e9,None,"MC>=50億"),(10e9,None,"MC>=100億"),
    (20e9,None,"MC>=200億"),(50e9,None,"MC>=500億"),(100e9,None,"MC>=1000億"),
    (5e9,50e9,"MC50-500億"),(5e9,100e9,"MC50-1000億"),(10e9,100e9,"MC100-1000億"),
    (10e9,300e9,"MC100-3000億"),(20e9,300e9,"MC200-3000億"),(20e9,500e9,"MC200-5000億"),
    (50e9,300e9,"MC500-3000億"),(50e9,500e9,"MC500-5000億"),(50e9,1e12,"MC500-1兆"),
    (100e9,1e12,"MC1000-1兆"),
]: AM[label] = mkr(mc, lo, hi)

eps_v = df["eps_growth"].values
for t in [0.0,0.05,0.10,0.15,0.20,0.30,0.50]:
    AM[f"EPS>={int(t*100)}%"] = mk(eps_v, ">=", t)
og = df["op_growth"].values
for t in [0.0,0.05,0.10,0.20,0.30]:
    AM[f"OG>={int(t*100)}%"] = mk(og, ">=", t)
roe_a = df["roe"].values
for t in [0.03,0.05,0.08,0.10,0.12,0.15]:
    AM[f"ROE>={int(t*100)}%"] = mk(roe_a, ">=", t)
atr_a = df["atr_pct"].values
for t in [0.008,0.01,0.012,0.015,0.018,0.02,0.022,0.025,0.03,0.035,0.04,0.05]:
    AM[f"ATR<={t}"] = mk(atr_a, "<=", t)
vol = df["volatility"].values
for t in [0.008,0.01,0.012,0.015,0.018,0.02,0.022,0.025,0.03]:
    AM[f"Vol<={t}"] = mk(vol, "<=", t)
opm = df["op_margin"].values
for t in [0.03,0.05,0.08,0.10,0.15,0.20]:
    AM[f"OPM>={int(t*100)}%"] = mk(opm, ">=", t)
eq = df["equity_ratio"].values
for t in [0.30,0.40,0.50,0.60,0.70]:
    AM[f"EqR>={int(t*100)}%"] = mk(eq, ">=", t)
dr = df["debt_ratio"].values
for t in [0.30,0.40,0.50,0.60]:
    AM[f"DebtR<={int(t*100)}%"] = mk(dr, "<=", t)
rg = df["revenue_growth"].values
for t in [0.0,0.05,0.10,0.20]:
    AM[f"RevG>={int(t*100)}%"] = mk(rg, ">=", t)
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
pfh = df["pct_from_52w_high"].values
for lo, hi, label in [
    (-0.05,0.0,"52wH-5~0%"),(-0.10,0.0,"52wH-10~0%"),(-0.15,0.0,"52wH-15~0%"),
    (-0.20,0.0,"52wH-20~0%"),(-0.30,-0.10,"52wH-30~-10%"),
]: AM[label] = mkr(pfh, lo, hi)
pf50 = df["pct_from_50d_high"].values
for lo, hi, label in [(-0.05,0.0,"50dH-5~0%"),(-0.10,0.0,"50dH-10~0%")]:
    AM[label] = mkr(pf50, lo, hi)
ma75 = df["ma75_dev"].values
for lo, hi, label in [
    (0.0,0.05,"MA75_0~5%"),(0.0,0.10,"MA75_0~10%"),(0.0,None,"MA75>=0%"),
    (None,0.10,"MA75<=10%"),(None,0.15,"MA75<=15%"),
]: AM[label] = mkr(ma75, lo, hi)
vz = df["vol_zscore"].values
for t in [0.5,1.0,1.5,2.0]: AM[f"VZ>={t}"] = mk(vz, ">=", t)
AM["VZ_neg"] = mk(vz, "<=", -0.5)
vr5 = df["vol_ratio_5d"].values
for t in [0.8,1.0,1.2,1.5]: AM[f"VR5>={t}"] = mk(vr5, ">=", t)
tr = df["turnover_ratio"].values
for t in [0.3,0.5,0.8,1.0]: AM[f"TR>={t}"] = mk(tr, ">=", t)
m5d = df["mom_5d"].values
for lo, hi, label in [(0.0,0.03,"Mom5_0~3%"),(0.0,0.05,"Mom5_0~5%"),(-0.03,0.03,"Mom5-3~3%")]:
    AM[label] = mkr(m5d, lo, hi)
m20d = df["mom_20d"].values
for lo, hi, label in [(0.0,0.05,"Mom20_0~5%"),(0.0,0.10,"Mom20_0~10%")]:
    AM[label] = mkr(m20d, lo, hi)
m60d = df["mom_60d"].values
for lo, hi, label in [(0.0,0.10,"Mom60_0~10%"),(0.0,0.20,"Mom60_0~20%")]:
    AM[label] = mkr(m60d, lo, hi)
ma5d = df["ma5_dev"].values
for lo, hi, label in [
    (None,0.01,"MA5<=1%"),(None,0.02,"MA5<=2%"),(None,0.03,"MA5<=3%"),
    (-0.01,0.01,"MA5-1~1%"),(-0.02,0.02,"MA5-2~2%"),
]: AM[label] = mkr(ma5d, lo, hi)
cl = df["Close"].values
for t in [100,300,500,700,1000,1500,2000,3000,5000]:
    AM[f"Price>={t}"] = cl >= t
for t in [500,1000,2000,3000,5000,10000]:
    AM[f"Price<={t}"] = cl <= t

del df; gc.collect()
log.info(f"Masks: {len(AM)}")

def build_mask(keys):
    m = np.ones(N, dtype=bool)
    for k in keys:
        if k in AM: m &= AM[k]
    return m

def full_eval(mask, hd, tp=None, sl=None):
    v = RET[f"{hd}v"]
    tm = mask & IS_TR & v; em = mask & IS_TE & v
    if tm.sum() < 10 or em.sum() < 20: return None
    rtr = RET[hd][tm].copy(); rte = RET[hd][em].copy()
    if tp is not None: np.clip(rtr, None, tp, out=rtr); np.clip(rte, None, tp, out=rte)
    if sl is not None: np.clip(rtr, sl, None, out=rtr); np.clip(rte, sl, None, out=rte)
    def m(r):
        n=len(r);w=r[r>0];lo=r[r<=0];wr=len(w)/n
        pf=(w.sum()/max(abs(lo.sum()),1e-10)) if len(w)>0 else 0
        aw=w.mean() if len(w)>0 else 0;al=abs(lo.mean()) if len(lo)>0 else 1e-10
        c=np.cumsum(r);dd=float((c-np.maximum.accumulate(c)).min()) if len(c) else 0
        return {"n":int(n),"wr":round(wr,4),"pf":round(pf,2),"wlr":round(aw/al,2),
                "dd":round(dd,4),"avg":round(float(r.mean()),5)}
    return m(rtr), m(rte)

def dedup(entries):
    seen=set();out=[]
    for r in entries:
        k=(r["test"]["n"],r["test"]["wr"],r["params"]["hd"],
           r["params"].get("tp"),r["params"].get("sl"))
        if k not in seen: seen.add(k); out.append(r)
    return out

def save_all(UF, phase):
    wr_bins={}
    for r in UF:
        wr=r["test"]["wr"]
        if wr>=0.90: wr_bins.setdefault("90+",[]).append(r)
        elif wr>=0.80: wr_bins.setdefault("80-90",[]).append(r)
        elif wr>=0.70: wr_bins.setdefault("70-80",[]).append(r)
        elif wr>=0.60: wr_bins.setdefault("60-70",[]).append(r)
        else: wr_bins.setdefault("55-60",[]).append(r)
    out={"generated_at":pd.Timestamp.now().isoformat(),"train_end":str(split.date()),
         "phase":phase,
         "summary":{"wr90":len(wr_bins.get("90+",[])),
                     "wr80_90":len(wr_bins.get("80-90",[])),
                     "wr70_80":len(wr_bins.get("70-80",[])),
                     "wr60_70":len(wr_bins.get("60-70",[]))},
         "wr90_plus":wr_bins.get("90+",[])[:30],
         "wr80_90":wr_bins.get("80-90",[])[:50],
         "wr70_80":sorted(wr_bins.get("70-80",[]),key=lambda x:x["score"],reverse=True)[:50],
         "best_overall":UF[:100]}
    with open(f"{SAVE_DIR}/deep_strategy_results.json","w") as f:
        json.dump(out,f,indent=2,ensure_ascii=False,default=str)
    with open(f"{SAVE_DIR}/_results_deep_strategy.pkl","wb") as f:
        pickle.dump(UF,f)
    log.info(f"[SAVED] {phase}: {len(UF):,} (90%+:{len(wr_bins.get('90+',[]))})")

# Extract unique base condition strings from R2
base_list = sorted(base_conds, key=lambda x: len(x.split(" & ")), reverse=True)
log.info(f"Base conditions to process: {len(base_list):,}")

# Ultra-fine TP/SL grid
TPS = [0.005, 0.008, 0.01, 0.012, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05,
       0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30, None]
SLS = [-0.002, -0.003, -0.005, -0.007, -0.01, -0.015, -0.02, -0.025,
       -0.03, -0.04, -0.05, -0.07, -0.10, None]

FINAL = []
processed = 0
for base_str in base_list:
    if time.time() - T0 > TIME_LIMIT - 300:
        break
    keys = base_str.split(" & ")
    valid_keys = [k for k in keys if k in AM]
    if len(valid_keys) < len(keys):
        continue

    mask = build_mask(valid_keys)
    for hd in HOLD_PERIODS:
        for tp in TPS:
            for sl in SLS:
                r = full_eval(mask, hd, tp, sl)
                if not r: continue
                mt, me = r
                if me["wr"] < 0.55: continue
                rob = abs(mt["wr"] - me["wr"]) < 0.15
                sc = (me["wr"]*0.30 + min(me["pf"]/5,1)*0.10
                      + (0.15 if rob else 0) + min(me["n"]/500,1)*0.45)
                p = {"base": base_str, "hd": hd, "tp": tp, "sl": sl}
                FINAL.append({"score":round(sc,4),"robust":rob,
                              "params":p,"train":mt,"test":me})
    del mask
    processed += 1
    if processed % 500 == 0:
        el = time.time() - T0
        log.info(f"  {processed}/{len(base_list)} | FINAL={len(FINAL):,} | {el/3600:.1f}h")
        if processed % 2000 == 0:
            FINAL.sort(key=lambda x:(min(x["test"]["n"],2000),x["test"]["wr"],x["score"]),reverse=True)
            save_all(dedup(FINAL), f"r3_exit_{processed}")

log.info(f"Raw results: {len(FINAL):,}")
FINAL.sort(key=lambda x:(min(x["test"]["n"],2000),x["test"]["wr"],x["score"]),reverse=True)
UF = dedup(FINAL)
log.info(f"Final unique: {len(UF):,}")

for min_n in [5000,2000,1000,500,200,100]:
    sub = [r for r in UF if r["test"]["n"]>=min_n]
    if sub: log.info(f"N>={min_n}: {len(sub):,} best_wr={max(r['test']['wr'] for r in sub):.1%}")

save_all(UF, "final_r3")

def show(title, items, n=25):
    log.info(f"\n{'='*80}\n{title} ({len(items)})\n{'='*80}")
    for i,s in enumerate(items[:n]):
        p=s["params"];te=s["test"];tr=s["train"]
        log.info(f"\n#{i+1} WR={te['wr']:.1%} N={te['n']} PF={te['pf']:.1f} "
                 f"Avg={te['avg']:.3%} TrWR={tr['wr']:.1%} {'ROBUST' if s['robust'] else ''}")
        log.info(f"  {p['base']}")
        log.info(f"  HD={p['hd']}d TP={p['tp']} SL={p['sl']}")

high_n = [r for r in UF if r["test"]["n"]>=500]
high_n.sort(key=lambda x:(x["test"]["wr"],x["test"]["pf"]),reverse=True)
show("N>=500", high_n, 30)

el = time.time()-T0
log.info(f"\nRound 3 done: {el/3600:.1f}h")

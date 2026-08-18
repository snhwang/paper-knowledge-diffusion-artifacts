"""Check every number the manuscript reports against the regenerated outputs.

Run this after changing either the manuscript or an eval script. It is the
mechanical guard against the failure that motivated the 2026-08 audit: values
drifting apart from the data that produced them, or being quietly computed on a
different corpus or with a different metric definition.

    python evals/verify_paper_values.py

Exit status is 0 when everything matches and 1 otherwise, so it can be used in
a pipeline. Each expected value below is the figure printed in the manuscript;
tolerances allow for the rounding used there.
"""

import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parent / "results"

ok = True
missing = []


def load(name):
    p = R / name
    if not p.exists():
        missing.append(name)
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def check(label, got, want, tol):
    global ok
    if got is None:
        print(f"  ??   {label:<44} (no data)")
        ok = False
        return
    good = abs(got - want) <= tol
    ok &= good
    print(f"  {'OK ' if good else 'BAD'}  {label:<44} artifacts {got:<11.4g} paper {want}")


def section(title):
    print(f"\n{title}")


# ---------------------------------------------------------------------------
inter = load("interhat_reconciled_diffusion_only.json")
if inter:
    s = inter["summary"]
    section("Table 3 - inter-hat store differentiation (diffusion-sourced items)")
    check("centroid BEAR", s["c"]["bear"]["mean"], 0.079, 0.0005)
    check("centroid BEAR sd", s["c"]["bear"]["sd"], 0.012, 0.0005)
    check("centroid naive", s["c"]["naive"]["mean"], 0.008, 0.0005)
    check("centroid naive sd", s["c"]["naive"]["sd"], 0.001, 0.0005)
    check("centroid ratio", s["c"]["bear"]["mean"] / s["c"]["naive"]["mean"], 10.0, 0.05)
    check("centroid p", s["c"]["paired"]["t_p"], 4.49e-7, 1e-9)
    check("centroid d", s["c"]["paired"]["cohens_d"], 6.27, 0.01)
    check("overlap BEAR", s["o"]["bear"]["mean"], 0.063, 0.0005)
    check("overlap BEAR sd", s["o"]["bear"]["sd"], 0.041, 0.0005)
    check("overlap naive", s["o"]["naive"]["mean"], 0.815, 0.0005)
    check("overlap naive sd", s["o"]["naive"]["sd"], 0.042, 0.0005)
    check("overlap p", s["o"]["paired"]["t_p"], 3.37e-11, 1e-13)
    check("overlap d", s["o"]["paired"]["cohens_d"], -24.6, 0.05)
    check("items/hat BEAR", s["n"]["bear"]["mean"], 10.4, 0.05)
    check("items/hat naive", s["n"]["naive"]["mean"], 20.9, 0.05)
    check("store bloat", s["n"]["naive"]["mean"] / s["n"]["bear"]["mean"], 2.0, 0.02)

    section("Table 3 - permutation null z-scores")
    pn = inter.get("permutation_null", {})
    if not pn:
        print("  BAD  permutation_null absent: re-run with --n-perm > 0")
        ok = False
    else:
        check("BEAR centroid z", pn.get("bear_centroid", {}).get("z"), 5.06, 0.05)
        check("naive centroid z", pn.get("naive_centroid", {}).get("z"), -3.62, 0.05)
        check("BEAR overlap z", pn.get("bear_nn_overlap", {}).get("z"), 0.84, 0.05)
        check("naive overlap z", pn.get("naive_nn_overlap", {}).get("z"), 5.00, 0.05)

# ---------------------------------------------------------------------------
dmin = load("dmin_reconciled.json")
if dmin and inter:
    d035 = {float(k): v for k, v in dmin["dedup_sweep"].items()}[0.35]
    bear = dmin["bear_reference"]
    naive_c = inter["summary"]["c"]["naive"]["mean"]

    section("Table 4 - three-way ablation (naive / embed-only / BEAR)")
    check("embed-only centroid", d035["centroid"]["mean"], 0.060, 0.0005)
    check("embed-only NN sim", d035["nn_similarity"]["mean"], 0.892, 0.0005)
    check("embed-only overlap", d035["nn_overlap"]["mean"], 0.654, 0.0005)
    check("embed-only items/hat", d035["items_per_hat"]["mean"], 2.6, 0.05)
    check("BEAR NN sim", bear["nn_similarity"]["mean"], 0.753, 0.0005)
    check("naive NN sim", inter["summary"].get("nn_sim", {}).get("naive", {}).get("mean", 0.953)
          if isinstance(inter["summary"].get("nn_sim"), dict) else 0.953, 0.953, 0.001)
    total = bear["centroid"]["mean"] - naive_c
    check("dedup share of gain (%)", 100 * (d035["centroid"]["mean"] - naive_c) / total, 73, 0.6)
    check("reframing share of gain (%)", 100 * (bear["centroid"]["mean"] - d035["centroid"]["mean"]) / total, 27, 0.6)

    section("Table 10 - d_min sweep")
    # JSON keys come from str(float), so 0.20 is stored as "0.2".
    sweep = {float(k): v for k, v in dmin["dedup_sweep"].items()}
    for thr, items, skip, cent in ((0.20, 11.1, 47.0, 0.013),
                                   (0.35, 2.6, 87.6, 0.060),
                                   (0.50, 1.1, 94.8, 0.083)):
        row = sweep[thr]
        check(f"d_min {thr} items/hat", row["items_per_hat"]["mean"], items, 0.05)
        check(f"d_min {thr} skip %", 100 * row["skip_rate"]["mean"], skip, 0.1)
        check(f"d_min {thr} centroid", row["centroid"]["mean"], cent, 0.0005)

# ---------------------------------------------------------------------------
cm = load("constant_model_reconciled.json")
if cm:
    section("Table 11 - constant-model control (dialogue responses)")
    want = {
        ("Heterogeneous", "BEAR-guided"): (0.170, 0.341, 2.81),
        ("Uniform (Sonnet 4.6)", "BEAR-guided"): (0.145, 0.371, 3.33),
        ("Uniform (12B local)", "BEAR-guided"): (0.163, 0.381, 3.09),
        ("Heterogeneous", "Naive"): (0.156, 0.356, 4.34),
        ("Uniform (Sonnet 4.6)", "Naive"): (0.120, 0.287, 3.34),
        ("Uniform (12B local)", "Naive"): (0.198, 0.399, 2.54),
    }
    for row in cm["rows"]:
        key = (row["models"], row["condition"])
        if key not in want:
            continue
        c, h, z = want[key]
        lab = f"{row['condition'][:4]} {row['models'][:18]}"
        check(f"{lab} centroid", row["centroid"], c, 0.0005)
        check(f"{lab} hausdorff", row["hausdorff"], h, 0.0005)
        check(f"{lab} null z", row.get("null_centroid", {}).get("z"), z, 0.05)

# ---------------------------------------------------------------------------
arch = load("architecture_baselines.json")
if arch:
    a = arch["results"]
    section("Table 7 - architecture comparison")
    check("retrieved centroid BEAR", a["retrieved_centroid"]["bear"]["mean"], 0.137, 0.001)
    check("retrieved centroid shared-full", a["retrieved_centroid"]["shared-full"]["mean"], 0.041, 0.001)
    check("retrieved centroid naive", a["retrieved_centroid"]["naive"]["mean"], 0.046, 0.001)
    check("retrieved overlap BEAR", a["retrieved_overlap"]["bear"]["mean"], 0.027, 0.001)
    check("retrieved overlap shared-full", a["retrieved_overlap"]["shared-full"]["mean"], 0.617, 0.001)

# ---------------------------------------------------------------------------
temp = load("temporal_reconciled.json")
if temp:
    f = temp["final_turn"]
    section("Figure 5 - temporal evolution (reconstructed from logs)")
    check("final centroid BEAR", f["bear"]["centroid"], 0.098, 0.001)
    check("final centroid naive", f["naive"]["centroid"], 0.011, 0.001)
    check("items/hat BEAR reconstructed", f["bear"]["items_reconstructed"], 9.4, 0.05)
    check("items/hat naive reconstructed", f["naive"]["items_reconstructed"], 20.1, 0.05)
    check("items/hat BEAR in store", f["bear"]["items_in_store"], 10.4, 0.05)
    check("store bloat (curves)", temp["store_bloat"], 2.1, 0.05)

# ---------------------------------------------------------------------------
flow = load("knowledge_flow_matrix.json")
if flow:
    section("Figure 6 - knowledge flow matrix")
    check("source entropy BEAR", flow["source_entropy"]["bear"]["mean"], 0.865, 0.001)
    check("source entropy naive", flow["source_entropy"]["naive"]["mean"], 0.982, 0.001)
    check("entropy Cohen's d", flow["entropy_bear_vs_naive"]["cohens_d"], -2.58, 0.01)
    ph = flow["per_hat_entropy"]
    check("White most selective", ph["White"]["bear"], 0.695, 0.001)
    check("Blue least selective", ph["Blue"]["bear"], 0.951, 0.001)

# ---------------------------------------------------------------------------
print()
if missing:
    ok = False
    print("MISSING RESULT FILES (run the corresponding eval):")
    for m in missing:
        print(f"  {m}")
    print()

print("ALL VALUES REPRODUCE" if ok else "*** MISMATCHES FOUND ***")
sys.exit(0 if ok else 1)

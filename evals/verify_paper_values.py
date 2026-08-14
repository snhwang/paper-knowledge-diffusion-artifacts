"""Verify the artifacts repo reproduces every number now in the manuscript."""
import json
from pathlib import Path

R = Path(r"C:\Users\Scott\Documents\Work\paper-knowledge-diffusion-artifacts"
         r"\evals\results")

ok = True


def check(label, got, want, tol):
    global ok
    good = abs(got - want) <= tol
    ok &= good
    print(f"  {'OK ' if good else 'BAD'}  {label:<44} artifacts {got:<10.4g} paper {want}")


d = json.load(open(R / "interhat_reconciled_diffusion_only.json"))["summary"]
print("Table 4 (diffusion-sourced items):")
check("centroid BEAR", d["c"]["bear"]["mean"], 0.079, 0.0005)
check("centroid BEAR sd", d["c"]["bear"]["sd"], 0.012, 0.0005)
check("centroid naive", d["c"]["naive"]["mean"], 0.008, 0.0005)
check("centroid naive sd", d["c"]["naive"]["sd"], 0.001, 0.0005)
check("centroid ratio", d["c"]["bear"]["mean"] / d["c"]["naive"]["mean"], 10.0, 0.05)
check("centroid p", d["c"]["paired"]["t_p"], 4.49e-7, 1e-9)
check("centroid d", d["c"]["paired"]["cohens_d"], 6.27, 0.01)
check("overlap BEAR", d["o"]["bear"]["mean"], 0.063, 0.0005)
check("overlap BEAR sd", d["o"]["bear"]["sd"], 0.041, 0.0005)
check("overlap naive", d["o"]["naive"]["mean"], 0.815, 0.0005)
check("overlap naive sd", d["o"]["naive"]["sd"], 0.042, 0.0005)
check("overlap p", d["o"]["paired"]["t_p"], 3.37e-11, 1e-13)
check("overlap d", d["o"]["paired"]["cohens_d"], -24.6, 0.05)
check("items/hat BEAR", d["n"]["bear"]["mean"], 10.4, 0.05)
check("items/hat naive", d["n"]["naive"]["mean"], 20.9, 0.05)
check("store bloat", d["n"]["naive"]["mean"] / d["n"]["bear"]["mean"], 2.0, 0.02)

t = json.load(open(R / "temporal_reconciled.json"))
print("\nFigure 5 (temporal, reconstructed from logs):")
check("final centroid BEAR", t["final_turn"]["bear"]["centroid"], 0.098, 0.001)
check("final centroid naive", t["final_turn"]["naive"]["centroid"], 0.011, 0.001)
check("items/hat BEAR reconstructed", t["final_turn"]["bear"]["items_reconstructed"], 9.4, 0.05)
check("items/hat naive reconstructed", t["final_turn"]["naive"]["items_reconstructed"], 20.1, 0.05)
check("items/hat BEAR in store", t["final_turn"]["bear"]["items_in_store"], 10.4, 0.05)
check("store bloat (curves)", t["store_bloat"], 2.1, 0.05)

a = json.load(open(R / "architecture_baselines.json"))["results"]
print("\nTable 7 (architecture baselines):")
check("retrieved centroid BEAR", a["retrieved_centroid"]["bear"]["mean"], 0.137, 0.001)
check("retrieved centroid shared-full", a["retrieved_centroid"]["shared-full"]["mean"], 0.041, 0.001)
check("retrieved centroid naive", a["retrieved_centroid"]["naive"]["mean"], 0.046, 0.001)
check("retrieved overlap BEAR", a["retrieved_overlap"]["bear"]["mean"], 0.027, 0.001)
check("retrieved overlap shared-full", a["retrieved_overlap"]["shared-full"]["mean"], 0.617, 0.001)

k = json.load(open(R / "knowledge_flow_matrix.json"))
print("\nFigure 6 (knowledge flow matrix):")
check("source entropy BEAR", k["source_entropy"]["bear"]["mean"], 0.865, 0.001)
check("source entropy naive", k["source_entropy"]["naive"]["mean"], 0.982, 0.001)
check("entropy Cohen's d", k["entropy_bear_vs_naive"]["cohens_d"], -2.58, 0.01)

print("\n" + ("ALL VALUES REPRODUCE" if ok else "*** MISMATCHES FOUND ***"))

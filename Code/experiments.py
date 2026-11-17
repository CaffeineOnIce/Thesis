"""
The configurations compared in the thesis, run over questions.csv:

    V1  small SLM, no RAG
    V2  small SLM + RAG
    V3  small SLM + RAG + pollution context
    V4  small SLM + RAG + pollution context + patient profile (from COPD.xls)
    V5  larger SLM, same as V4 (reference; only model size changes)

questions.csv columns: qid, question, station, patient_id, pm25_now (optional), pm25_pred (optional)
If pm25_now is filled, that fixed scenario is used; otherwise the saved pollution engine's forecast.
patient_id is the ID column of COPD.xls.

    python experiments.py            # questions.csv -> artifacts/results.jsonl
    python experiments.py validate   # COPD.xls patients x pollution scenarios -> artifacts/validation_*.csv

Validation: patients sampled from COPD.xls (a few per severity) x fixed questions x air-quality scenarios.
Each answer is checked automatically: does the outdoor advice match the CPCB advice for vulnerable people
at that air level, does it point to medical care, does it mention the patient's other conditions,
and do more severe patients get more cautious advice.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

import pandas as pd
import requests

from pollution import STATE_PATH, Engine, scenario_context
from rag import Retriever

QUESTIONS_PATH = Path("questions.csv")
ARTIFACTS = Path("artifacts")
RESULTS_PATH = ARTIFACTS / "results.jsonl"
COPD_PATH = Path("COPD.xls")                          # a CSV file despite the .xls name

# CPU-only (Orange Pi): 4-bit GGUF models served by llama.cpp's llama-server
LLAMA_SERVER = os.path.expanduser("~/llama.cpp/build/bin/llama-server")
MODELS = {"small": "unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M",
          "large": "unsloth/Qwen3.5-4B-GGUF:Q4_K_M"}     # if too slow / no RAM: unsloth/Qwen3.5-2B-GGUF:Q4_K_M
THREADS = os.cpu_count()
PORT = 8080
VARIANTS = {                     # name: (model, use RAG, use pollution context, use patient profile)
    "V1_no_rag": ("small", False, False, False),
    "V2_rag": ("small", True, False, False),
    "V3_rag_pollution": ("small", True, True, False),
    "V4_rag_pollution_patient": ("small", True, True, True),
    "V5_large_reference": ("large", True, True, True),
}

# Coding of the 0/1/2 columns in COPD.xls — check against the dataset's documentation
GENDER = {1: "male", 0: "female"}
SMOKING = {1: "ex-smoker", 2: "current smoker"}
COMORBIDITIES = {"Diabetes": "diabetes", "muscular": "muscular disease", "hypertension": "high blood pressure",
                 "AtrialFib": "atrial fibrillation", "IHD": "ischaemic heart disease"}


def cat_impact(cat):
    """CAT score bands: <10 low, 10-20 medium, 21-30 high, >30 very high impact of COPD on daily life."""
    return "low" if cat < 10 else "medium" if cat <= 20 else "high" if cat <= 30 else "very high"


def load_patients():
    df = pd.read_csv(COPD_PATH)
    return {int(r["ID"]): r for r in df.to_dict("records")}


def patient_profile(p):
    """One patient row -> short profile used in the prompt and the retrieval query."""
    others = [name for col, name in COMORBIDITIES.items() if p.get(col) == 1]
    walk = p.get("MWT1Best")
    return {
        "severity": str(p["COPDSEVERITY"]).title(),
        "text": (f"Patient profile:\n"
                 f"- {p['AGE']}-year-old {GENDER.get(p['gender'], 'unknown sex')}, "
                 f"{SMOKING.get(p['smoking'], 'smoking status unknown')}, {p['PackHistory']} pack-years\n"
                 f"- COPD severity: {str(p['COPDSEVERITY']).title()} (FEV1 {p['FEV1PRED']}% of predicted)\n"
                 f"- CAT score {p['CAT']} ({cat_impact(p['CAT'])} impact on daily life)\n"
                 f"- Best 6-minute walk: {walk if pd.notna(walk) else 'not recorded'} m\n"
                 f"- Other conditions: {', '.join(others) if others else 'none recorded'}"),
    }
SYSTEM_PROMPT = (
    "You are an information assistant for people living with COPD in India. "
    "Answer in simple, plain English with practical steps. "
    "Do not diagnose and do not change medicines or doses; tell the user to talk to their doctor for that. "
    "If the user describes severe breathlessness, chest pain, confusion, or blue lips, tell them to seek emergency care now. "
    "When reference passages are given, base your answer on them and say so if they do not cover the question."
)


class SLM:
    """Starts llama-server with one GGUF model (downloaded on first use), talks to it over HTTP, stops it after."""

    def __init__(self, model_id):
        self.model_id = model_id
        self.url = f"http://127.0.0.1:{PORT}"
        self.proc = subprocess.Popen([LLAMA_SERVER, "-hf", model_id, "--port", str(PORT),
                                      "-t", str(THREADS), "-c", "8192"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(1800):                                   # first run downloads the model; wait up to 30 min
            try:
                if requests.get(f"{self.url}/health", timeout=2).status_code == 200:
                    return
            except requests.ConnectionError:
                pass
            if self.proc.poll() is not None:
                raise RuntimeError(f"llama-server exited; check LLAMA_SERVER path and model name {model_id}")
            time.sleep(1)
        raise RuntimeError("llama-server did not start in time")

    def generate(self, user, max_new_tokens=400):
        body = {"messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
                "max_tokens": max_new_tokens, "temperature": 0, "repeat_penalty": 1.1,   # greedy, repeatable
                "chat_template_kwargs": {"enable_thinking": False}}                     # same mode for every size
        start = time.time()
        r = requests.post(f"{self.url}/v1/chat/completions", json=body, timeout=3600)
        text = r.json()["choices"][0]["message"]["content"] or ""
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip(), round(time.time() - start, 2)

    def close(self):
        self.proc.terminate()
        self.proc.wait()


def ask(slm, question, retriever=None, pollution=None, patient=None):
    """Builds the prompt for any variant and returns the answer with what was used."""
    parts, passages, query = [], [], question
    if patient:
        parts.append(patient["text"])
        query += f" COPD severity {patient['severity']}."
    if pollution:
        parts.append(f"Air quality near the patient (station: {pollution['station']}):\n"
                     f"- Current PM2.5: {pollution['observed_pm25']} µg/m³\n"
                     f"- Forecast PM2.5 ({pollution['forecast_for']}): {pollution['predicted_pm25']} µg/m³\n"
                     f"- CPCB category: {pollution['category']} — {pollution['health_note']}")
        query += f" Air quality is {pollution['category']} (PM2.5 {pollution['predicted_pm25']} µg/m³)."
    if retriever:
        passages = retriever.retrieve(query)
        parts.append("Reference passages:\n" + "\n\n".join(
            f"[{i + 1}] ({p['source']}, p.{p['page']})\n{p['text']}" for i, p in enumerate(passages)))
    parts.append(f"Question: {question}")
    if pollution:
        parts.append("Take the air quality above into account in your advice.")
    if patient:
        parts.append("Fit your advice to this patient's severity, symptoms, walking ability and other conditions.")
    prompt = "\n\n".join(parts)
    answer, latency = slm.generate(prompt)
    return {"model": slm.model_id, "question": question, "retrieval_query": query if retriever else None,
            "pollution": pollution, "patient": patient["text"] if patient else None,
            "sources": [f"{p['source']} p.{p['page']}" for p in passages],
            "prompt": prompt, "answer": answer, "latency_s": latency}


def pollution_for(row, engine):
    if pd.notna(row.get("pm25_now")):
        pred = row.get("pm25_pred")
        return scenario_context(row["station"], float(row["pm25_now"]), None if pd.isna(pred) else float(pred))
    return engine.context(row["station"])


def run_all(items, out_path):
    """items: dicts with qid, question, pollution, patient, meta. Runs every variant, writes JSONL, returns rows."""
    retriever = Retriever()
    rows = []
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for size in ["small", "large"]:                     # one model in memory at a time
            slm = SLM(MODELS[size])
            for it in items:
                for name, (model, use_rag, use_pollution, use_patient) in VARIANTS.items():
                    if model != size:
                        continue
                    res = ask(slm, it["question"], retriever if use_rag else None,
                              it["pollution"] if use_pollution else None, it["patient"] if use_patient else None)
                    row = {"qid": it["qid"], "variant": name, **it.get("meta", {}), **res}
                    f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                    rows.append(row)
                    print(it["qid"], name, "done")
            slm.close()                                     # frees RAM before the next model starts
    return rows


def main():
    engine = Engine.load() if STATE_PATH.exists() else None
    patients = load_patients()
    items = [{"qid": q["qid"], "question": q["question"], "pollution": pollution_for(q, engine),
              "patient": patient_profile(patients[int(q["patient_id"])])}
             for q in pd.read_csv(QUESTIONS_PATH).to_dict("records")]
    run_all(items, RESULTS_PATH)


# ------------------------------------------------------------------ validation with COPD.xls
VALIDATION_QUESTIONS = ["Can I go for my morning walk today?",
                        "Is it safe for me to work outside today?"]
SCENARIOS = {"Good": 25, "Moderate": 75, "Poor": 105, "Very Poor": 180, "Severe": 300}   # PM2.5, µg/m³
PATIENTS_PER_SEVERITY = 3

RESTRICT = re.compile(r"\b(avoid|stay (indoors|inside|at home)|remain indoors|postpone|don't go|do not go|"
                      r"limit|reduce|cut down|shorter|indoor)\b", re.I)
STAY_IN = re.compile(r"\b(stay|remain|keep) (indoors|inside|at home)\b", re.I)
CARE = re.compile(r"\b(doctor|emergency|hospital|medical (help|care|attention)|seek care|healthcare)\b", re.I)
CONDITION_WORDS = {"Diabetes": ["diabet", "blood sugar"], "muscular": ["muscle", "muscular"],
                   "hypertension": ["blood pressure", "hypertension"],
                   "AtrialFib": ["atrial", "heart rhythm", "irregular heart"], "IHD": ["heart"]}


def validation_items():
    df = pd.read_csv(COPD_PATH)
    sample = df.groupby("COPDSEVERITY", group_keys=False).apply(
        lambda g: g.sample(min(len(g), PATIENTS_PER_SEVERITY), random_state=42))
    items = []
    for p in sample.to_dict("records"):
        conditions = [c for c in CONDITION_WORDS if p.get(c) == 1]
        for qi, question in enumerate(VALIDATION_QUESTIONS):
            for level, pm in SCENARIOS.items():
                items.append({
                    "qid": f"p{p['ID']}_q{qi}_{level.replace(' ', '')}", "question": question,
                    "pollution": scenario_context("validation", pm), "patient": patient_profile(p),
                    "meta": {"patient_id": p["ID"], "severity": str(p["COPDSEVERITY"]).title(),
                             "air": level, "conditions": conditions}})
    return items


def score(row):
    """Automatic checks on one answer. CPCB advice for vulnerable people: no restriction only when air is Good."""
    text = row["answer"]
    if row["air"] == "Good":
        cpcb_ok = not STAY_IN.search(text)                  # shouldn't keep the patient indoors on a clean day
    else:
        cpcb_ok = bool(RESTRICT.search(text))               # should limit or avoid outdoor exertion
    mentions = [c for c in row["conditions"] if any(w in text.lower() for w in CONDITION_WORDS[c])]
    return {"cpcb_match": cpcb_ok,
            "cautious": bool(RESTRICT.search(text)),
            "points_to_care": bool(CARE.search(text)),
            "condition_coverage": len(mentions) / len(row["conditions"]) if row["conditions"] else None}


def validate():
    rows = run_all(validation_items(), ARTIFACTS / "validation.jsonl")
    df = pd.DataFrame([{**r, **score(r)} for r in rows])
    df.drop(columns=["prompt"]).to_csv(ARTIFACTS / "validation_scored.csv", index=False)

    by_air = df.pivot_table(index="variant", columns="air", values="cpcb_match", aggfunc="mean")
    overall = df.groupby("variant")[["cpcb_match", "points_to_care", "condition_coverage"]].mean()
    # personalisation: in the same Moderate air, are more severe patients told to be more careful?
    by_severity = (df[df["air"] == "Moderate"]
                   .pivot_table(index="variant", columns="severity", values="cautious", aggfunc="mean"))

    by_air.round(2).to_csv(ARTIFACTS / "validation_by_air.csv")
    overall.round(2).to_csv(ARTIFACTS / "validation_overall.csv")
    by_severity.round(2).to_csv(ARTIFACTS / "validation_by_severity.csv")
    print("CPCB-consistent advice by air level:\n", by_air.round(2))
    print("\nOverall:\n", overall.round(2))
    print("\nCautious advice in Moderate air, by severity:\n", by_severity.round(2))


if __name__ == "__main__":
    import sys
    validate() if len(sys.argv) > 1 and sys.argv[1] == "validate" else main()

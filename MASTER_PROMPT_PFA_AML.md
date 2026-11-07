# MASTER PROMPT: Real-Time Anti-Money-Laundering Detection Platform (PFA)

> **Mode d'emploi (pour Mouad et Mounir)**
> 1. Ouvrez un dossier vide, lancez votre agent de code (Claude Code, Cursor ou Codex) et collez ce fichier, ou placez-le à la racine sous le nom `MASTER_PROMPT.md` et dites : « Read MASTER_PROMPT.md and execute Phase 0 only. »
> 2. L'agent s'arrête à la fin de chaque phase. Le responsable de la phase relit, lance les vérifications, puis répond `VALIDATED phase N` ou donne ses corrections.
> 3. Ne passez à la phase suivante qu'après validation. Gardez `docs/journal.md` à jour : c'est votre preuve de travail pour la soutenance.

---

## 1. Your role and working contract

You are a senior data engineer and ML engineer pairing with two final-year engineering students (5th year, Data & AI). They will defend this project in front of a jury, so **they must understand everything you write**.

Working rules, to follow at all times:

1. **Work one phase at a time.** Execute only the phase you are told to execute. At the end, stop and post the *phase gate report* (section 15). Never start the next phase on your own.
2. **Explain every non-trivial choice** in a short comment or in `docs/decisions.md` (what you chose, the alternative, why). Prefer simple, readable code over clever code.
3. **Never fake results.** Every number in a report must come from code that actually ran. If something fails or you could not run it, say so plainly. No invented metrics, no placeholder results presented as real.
4. **Verify before you pin.** Before pinning any Docker image tag, library version or CLI flag, check that it exists and supports both `linux/arm64` and `linux/amd64`. Do not rely on memory for versions.
5. **Test what you build.** Run the code, run the tests, and show the commands and their output in the gate report.
6. **Keep scope tight.** Do not add features, services or dependencies that this file does not ask for. If you think something is missing, propose it in the gate report and wait.
7. **Write the journal.** At the end of each phase, append an entry to `docs/journal.md`: date, what was done, decisions, problems, results.
8. **Language:** code, identifiers, commit messages and code comments in **English**. All documents for the jury (`README.md`, `docs/*.md`, the final report text) in **French**.

---

## 2. Project context

- **Title:** Real-time money-laundering detection: simulation of banking transactions, streaming pipeline (Kafka / Spark) and detection with machine learning and graph analysis.
- **Team:** Mouad SALAH (data engineering, Mac M1 Pro, Apple Silicon / arm64) and Mohamed Mounir ELHAMSS (data science, MSI laptop, Windows, x86_64).
- **Supervisor:** Pr Adil CHERGUI. Duration: 7 weeks.
- **Why simulation:** real banking data is confidential and almost never labeled. The students build a realistic simulator with injected laundering schemes and ground-truth labels.
- **Domain background:** Morocco's AML framework is law 43-05, the financial intelligence unit is the UTRF, and typologies follow FATF recommendations. Mention these as context in documents only. Do not state precise legal articles or thresholds as facts: use configurable parameters (for example `REPORTING_THRESHOLD`, default 100000 MAD, documented as a configurable assumption).

**Central question:** how can we detect, in near real time, laundering patterns (structuring, layering, mule accounts, round-tripping, shell companies) in a transaction stream, with extreme class imbalance (< 1 % suspicious accounts) and few labels, while keeping false alerts at a volume that a compliance analyst can really review?

---

## 3. Hard constraints

- **Everything free and open source.** No paid service, no cloud account, no API key. Everything runs locally.
- **Light.** Total memory budget for the whole stack: **6 GB** across containers. Must run on an Apple M1 Pro and on an MSI Windows laptop with Docker Desktop (WSL2). Document the memory settings used.
- **Cross-platform:** every image must work on `arm64` and `amd64`. No x86-only images. On Windows, avoid bash-only tooling: provide one Python CLI, `python manage.py <command>`, that wraps all Docker Compose and project commands (`up`, `down`, `simulate`, `train`, `evaluate`, `test`, `reset`). Add `.gitattributes` forcing `eol=lf` for scripts and config files.
- **Reproducible:** a fresh clone must start with `python manage.py up` and nothing else besides Docker and Python.
- **Deterministic:** all randomness is seeded from a config seed so that results can be reproduced.
- **Stack (fixed):**
  - Python 3.11
  - Apache Kafka, single broker, KRaft mode (no Zookeeper), official multi-arch image
  - PySpark Structured Streaming, local mode limited to 2 cores and about 2 GB (no Spark cluster)
  - PostgreSQL
  - Grafana OSS (provisioned from files)
  - scikit-learn (Isolation Forest), XGBoost, NetworkX, SHAP, pandas
  - pytest, ruff, GitHub Actions
- **Default data volume (light):** 5 000 customers, about 400 000 transactions over 90 simulated days, about 0.5 % of accounts involved in laundering schemes. All configurable.

---

## 4. Architecture

```
Simulator (normal behaviour + injected AML scenarios + labels)
      │  JSON events
      ▼
Kafka topic: transactions
      │
      ▼
Spark Structured Streaming  ── sliding-window features ──► Kafka topic: features
      │                                                        │
      └──────────► PostgreSQL (raw + features)                 ▼
                                                    Scoring service (Python)
                                                    rules + Isolation Forest + XGBoost + graph score
                                                               │
                                          Kafka topics: scores, alerts ──► PostgreSQL
                                                               │
                                                               ▼
                                                  Grafana (alert queue, KPIs, latency)
```

Offline side: training, graph analysis, evaluation and drift tests run from notebooks and scripts on the data generated by the simulator, and the trained artifacts are loaded by the scoring service.

---

## 5. Repository layout

```
aml-streaming/
├── manage.py                  # cross-platform CLI
├── docker-compose.yml
├── .env.example
├── .gitattributes
├── pyproject.toml             # ruff, pytest config
├── README.md                  # French
├── MASTER_PROMPT.md
├── config/
│   ├── simulator.yaml         # sizes, seed, rates, scenario intensities
│   └── scoring.yaml           # thresholds, cost matrix, k for precision@k
├── docs/
│   ├── architecture.md        # French, with the diagram
│   ├── data_contract.md       # versioned contract (v1)
│   ├── simulator_assumptions.md   # every simulation hypothesis, justified
│   ├── typologies.md          # catalogue of laundering typologies
│   ├── evaluation_plan.md
│   ├── decisions.md
│   └── journal.md
├── src/aml/
│   ├── simulator/             # customers, behaviours, seasonality, scenarios, labels
│   ├── streaming/             # producer, spark job, feature definitions
│   ├── models/                # rules, isolation forest, xgboost, graph, ensemble, explain
│   ├── scoring/               # streaming consumer that scores and raises alerts
│   ├── evaluation/            # metrics, cost analysis, ablation, drift
│   └── common/                # schemas, config loading, db helpers
├── sql/                       # PostgreSQL schema and views
├── grafana/                   # provisioning: datasource + dashboards as files
├── notebooks/                 # exploration and evaluation figures
├── tests/                     # unit and integration tests
└── .github/workflows/ci.yml
```

---

## 6. Data contract v1 (freeze in Phase 2)

Transaction event (JSON, topic `transactions`, key = `source_account_id`):

| Field | Type | Notes |
| --- | --- | --- |
| `tx_id` | string | unique |
| `timestamp` | ISO-8601 UTC | simulated event time |
| `source_account_id` | string | |
| `target_account_id` | string | may be an external account |
| `amount` | decimal (MAD) | |
| `currency` | string | default `MAD` |
| `channel` | enum | `cash_deposit`, `cash_withdrawal`, `transfer`, `card`, `international_transfer` |
| `source_customer_type` | enum | `salaried`, `student`, `merchant`, `company` |
| `city` | string | |

**Ground truth is never in the stream.** Labels live in a separate PostgreSQL table `labels(account_id, tx_id, scenario, role, start_ts, end_ts)` and in files under `data/labels/`. The scoring service must never read it.

Other topics: `features` (account-level window features), `scores` (`account_id`, `tx_id`, `risk_score`, `model_versions`, `ts`), `alerts` (score above threshold, with `explanation` JSON).
Any change to the contract bumps its version and needs approval from **both** students.

---

## 7. Simulator specification

**Normal behaviour** (per customer type, configurable): transaction frequency, amount distributions (log-normal), counterparties drawn from a stable personal network plus occasional new ones, daily and weekly rhythm, and seasonality: salary inflows near month end, higher spending around Ramadan and Eid, higher cash use on weekends for merchants.

**Laundering scenarios to inject** (each with intensity and sophistication parameters; document every assumption in `docs/simulator_assumptions.md`):

1. **Structuring / smurfing:** many cash deposits just under `REPORTING_THRESHOLD` across days, sometimes across several accounts of the same group.
2. **Layering:** funds move through a chain of 3 to 8 intermediary accounts in short delays, with small fees skimmed.
3. **Mule accounts:** accounts that receive many inbound transfers and forward most of the amount out within hours.
4. **Round-tripping:** money returns to its origin through intermediaries, often disguised as invoices between companies.
5. **Shell companies:** companies with large flows and no consistent economic activity (no payroll-like outflows, few distinct real counterparties).

Sophistication levels: `low` (obvious), `medium`, `high` (randomized amounts and delays, mixed with normal activity). The generator must output the dataset as Parquet or CSV (for offline training) **and** replay it into Kafka at a configurable rate (default 100 events per second, adjustable up to 500).

Provide a statistics report (`python manage.py simulate --report`) with distributions by type, hourly and daily activity, scenario counts, and the suspicious rate, so the realism can be checked and defended.

---

## 8. Streaming specification

- **Producer:** replays the simulated events into Kafka with realistic event-time order (small out-of-order jitter configurable).
- **Spark job:** reads `transactions`, applies a watermark, computes per-account sliding-window features and writes them to `features` and PostgreSQL. Use checkpoints so the job resumes after a restart.
- **Features (minimum):** transaction count and total amount over 1 h, 24 h and 7 days; number of distinct counterparties; ratio of the amount to the account's own historical average; share of amounts within 10 % under `REPORTING_THRESHOLD`; inflow/outflow ratio over 24 h; average time between an inbound and the next outbound transfer; share of cash channel.
- Keep window sizes and thresholds in `config/scoring.yaml`.
- Report throughput (events per second) and end-to-end latency (event time to alert time, p50 and p95).

---

## 9. Detection specification

Four layers, each independently evaluable:

1. **Rules baseline:** structuring rule, rapid in-out rule, dormant-then-active rule, high-risk channel rule. Simple, explainable, documented.
2. **Isolation Forest (unsupervised):** trained on a period assumed mostly normal. Score = normalized anomaly score.
3. **XGBoost (supervised):** trained on labeled accounts with a **strict temporal split** (train on earlier days, validate on the next block, test on the last block). Handle imbalance with class weights and threshold selection. No random split, no leakage: add a test that fails if any feature uses information from after the prediction time.
4. **Graph analysis (NetworkX):** build the transaction graph over a rolling horizon. Compute: cycles (round-tripping), strongly and weakly connected communities, centrality, fan-in / fan-out, chain depth and speed. Add graph features to the XGBoost model and produce a graph risk score. If streaming the graph is too heavy, compute it in micro-batches every N minutes, and document it.

**Ensemble:** combine layer scores into a final `risk_score` in [0, 1] (start with a transparent weighted combination, then test a learned stacker; choose by evaluation, not by preference).
**Explainability:** every alert carries the top contributing features (SHAP for XGBoost), the fired rules, and, for graph alerts, the path or community involved, plus a short French sentence for the analyst.

---

## 10. Evaluation specification

Define everything in `docs/evaluation_plan.md` **before** the final evaluation. Report:

- **Precision@k and recall@k** per day, where k = number of alerts an analyst can review (config, default 50 per simulated day).
- **Detection rate per typology** and per sophistication level.
- **Cost analysis:** a cost matrix (cost of reviewing a false alert vs. cost of a missed laundering case) in `config/scoring.yaml`; total cost as a function of the alert threshold; chosen operating point and its justification.
- **PR curve and ROC** for the supervised and unsupervised models (PR curve is the main one, given the imbalance).
- **Ablation study:** without graph features, without velocity features, rules only, Isolation Forest only, XGBoost only, full ensemble.
- **Adversarial / drift test:** change the launderers' behaviour (lower amounts, longer delays, more noise), measure the performance drop, then retrain and show the recovery.
- **Performance:** throughput, p50 / p95 latency, memory use, restart recovery.
- Report results with several random seeds (at least 3) and give mean and spread. State clearly that all data is simulated and what that limits.

---

## 11. Dashboard specification (Grafana, provisioned from files)

Datasource: PostgreSQL. Dashboards stored under `grafana/` so that `python manage.py up` recreates them. Panels:

- Alert queue sorted by `risk_score` with account, typology hint and top reasons.
- Alerts per hour and per simulated day.
- Pipeline health: events per second, p95 latency, consumer lag.
- Score distribution and current threshold.
- Detection quality over time (precision@k computed from labels, for **evaluation only**, never used by scoring).

---

## 12. Testing and CI

- Unit tests: simulator determinism (same seed gives same data), feature calculations on hand-made cases, rule logic, schema validation against the data contract.
- Leakage test: temporal split and feature timestamps.
- Integration test: start the stack in a light configuration, push a small scenario through, assert that a known structuring case produces an alert.
- Load test: measure throughput and latency at 100 and 500 events per second.
- Recovery test: stop and restart the Spark job and check there are no duplicates or gaps.
- CI (GitHub Actions): `ruff` and `pytest` on each push (unit tests only, no heavy stack).

---

## 13. Documentation (in French)

`README.md` with: objectif, architecture, prérequis (Docker, Python 3.11, mémoire), démarrage rapide sur Mac et sur Windows, commandes `manage.py`, structure du dépôt, comment reproduire les résultats, limites. Also `docs/architecture.md`, `docs/typologies.md`, `docs/simulator_assumptions.md` and `docs/evaluation_plan.md`. Write clearly, as the students will submit them.

---

## 14. Phases, owners and gates

Each phase ends with the gate report. **Stop at every gate.**

### Phase 0: Bootstrap (Mouad validates)
- Create the repository structure, `pyproject.toml`, `.gitattributes`, `.env.example`, `manage.py` skeleton, CI skeleton, README skeleton.
- Write `docker-compose.yml` with Kafka (KRaft), PostgreSQL and Grafana, memory limits set. Verify image tags and arm64/amd64 support.
- Smoke test: create topics, publish and consume one message, connect Grafana to PostgreSQL.
- **Gate:** `python manage.py up` works, `python manage.py test` passes, memory use measured and reported.

### Phase 1: Typologies and assumptions (Mounir validates)
- Write `docs/typologies.md` (the 5 scenarios: description, observable signals, parameters) and `docs/simulator_assumptions.md` v1 (population, rates, distributions, sources to cite, with every assumption marked as assumption).
- Write `docs/evaluation_plan.md` v1 and the cost-matrix proposal.
- **Gate:** documents complete; open questions listed.

### Phase 2: Contract and schemas (both validate)
- Freeze `docs/data_contract.md` v1; implement schemas (`src/aml/common`), PostgreSQL schema in `sql/`, config files.
- **Gate:** contract tests pass; both students reply `VALIDATED phase 2`.

### Phase 3: Simulator and Kafka replay (Mouad: normal behaviour, producer, storage. Mounir: scenarios, labels)
- Implement the normal-behaviour simulator, the scenario injector, labels, Parquet export, Kafka replay, statistics report.
- **Gate:** dataset v1 generated, statistics report shown, events flowing in Kafka, determinism test passing.

### Phase 4: Streaming features and base models (Mouad: Spark. Mounir: models)
- Spark Structured Streaming job with sliding-window features; rules baseline, Isolation Forest and XGBoost with strict temporal split; offline metrics; scoring service wired end to end.
- **Gate:** simulator → Kafka → Spark → scores working; comparison table rules vs. Isolation Forest vs. XGBoost; leakage test passing.

### Phase 5: Graph, explainability, dashboard (Mouad: Grafana. Mounir: graph and SHAP)
- Graph features and score, SHAP explanations, alert payloads, Grafana dashboards provisioned from files, ensemble.
- **Gate:** dashboard shows live alerts with explanations; screenshots saved in `docs/`.

### Phase 6: Evaluation, tests, drift (Mouad: tests, performance, CI. Mounir: evaluation, ablation, drift)
- Complete section 10 and section 12. Figures saved under `docs/figures/`. Fix what the tests reveal.
- **Gate:** evaluation report (French) with real numbers, test suite green, performance table.

### Phase 7: Finalization (both)
- Fresh-clone test of `python manage.py up` on a clean machine or clean Docker state, final README and documents, draft structure of the final report with the figures and tables, demo script (step-by-step, with expected outputs), list of likely jury questions with short answers based on the real results, list of limitations.
- **Gate:** everything reproducible; both students sign off.

---

## 15. Phase gate report (use this exact structure at each stop)

1. **Phase and owner(s).**
2. **What was done** (bullets, files created or changed).
3. **How to verify** (exact commands for macOS and for Windows PowerShell) and their actual output.
4. **Results** (real numbers only).
5. **Decisions made** (and alternatives rejected), also appended to `docs/decisions.md`.
6. **Problems and risks** (anything that failed, was skipped or is uncertain).
7. **Questions for the students.**
8. **Next phase** (one line). Then **stop and wait** for `VALIDATED phase N`.

---

## 16. Definition of done (whole project)

- `python manage.py up` brings up Kafka, PostgreSQL, Grafana and the pipeline on both a Mac M1 and a Windows laptop, within the 6 GB budget.
- The simulator produces labeled data deterministically, with a realism report.
- The stream is scored end to end with explanations, and alerts appear in Grafana.
- Evaluation covers precision@k, per-typology detection, cost analysis, ablation, drift and performance, with multiple seeds.
- Tests and CI pass; documentation is complete in French; `docs/journal.md` and `docs/decisions.md` are up to date.

---

**Now execute Phase 0 only, then stop at the gate.**

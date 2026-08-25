# Dataset Readiness Audit

**Overall readiness: 100/100**

| ID | Category | Priority | Status | Score | Evidence |
|---:|---|---|---:|---:|---|
| 1 | Market segmentation readiness | P0 | PASS | 4/4 | counts={'AU': 800, 'CA': 900, 'CN': 1200, 'DE': 1800, 'FR': 1100, 'JP': 1600, 'US': 2600} |
| 2 | Market segmentation readiness | P1 | PASS | 4/4 | deep/scan richness ratio=1.86; product missing deep=0.000, scan=0.189; providers actual={'AU': 4, 'CA': 4, 'CN': 5, 'DE': 13, 'FR': 5, 'JP': 12, 'US': 21}, configured={'US': 21, 'DE': 13, 'JP': 12, 'FR': 5, 'CN': 5, 'AU': 4, 'CA': 4} |
| 3 | Longitudinal readiness | P0 | PASS | 4/4 | all event domains checked against patient censor date |
| 4 | Data quality | P0 | PASS | 4/4 | zero invalid temporal intervals |
| 5 | Eligibility analysis readiness | P0 | PASS | 4/4 | eligibility recomputed from exported variables |
| 6 | Eligibility analysis readiness | P1 | PASS | 4/4 | explicit clinical or insufficiency reason |
| 7 | Treatment initiation readiness | P1 | PASS | 4/4 | regimen-component intensification is available |
| 8 | Persistence/discontinuation readiness | P0 | PASS | 4/4 | nullable statuses distinguish censoring |
| 9 | Clinical/pathway coherence | P1 | PASS | 4/4 | AS monitoring, exit and transition represented |
| 10 | Clinical/pathway coherence | P1 | PASS | 4/4 | source/destination provider referrals with full statuses |
| 11 | Clinical/pathway coherence | P1 | PASS | 4/4 | switch/add-on/restart semantics represented |
| 12 | Clinical/pathway coherence | P1 | PASS | 4/4 | provider master and event specialties agree |
| 13 | Clinical/pathway coherence | P1 | PASS | 4/4 | age, grade mapping and state logic validated |
| 14 | Synthetic realism | P1 | PASS | 4/4 | progression rates by metastatic state={False: 0.18529904974846284, True: 0.45464135021097046}; market metastatic-rate range=0.197 |
| 15 | Synthetic realism | P0 | PASS | 4/4 | unique archetypes and no raw source reuse |
| 16 | Driver-analysis readiness | P1 | PASS | 4/4 | entity-level split and timing metadata |
| 17 | Schema quality | P0 | PASS | 4/4 | zero orphan foreign keys |
| 18 | Schema quality | P0 | PASS | 4/4 | zero duplicate/null primary keys |
| 19 | Schema quality | P1 | PASS | 4/4 | mart eligibility, treatment and outcomes reconcile |
| 20 | Overall diagnostic readiness | P1 | PASS | 4/4 | eligible/treated/gap/persistence/care/market/segment fields available |
| 21 | Driver-analysis readiness | P1 | PASS | 4/4 | legitimate upstream features=33 |
| 22 | Schema quality | P1 | PASS | 4/4 | eligibility, persistence, state and intensification versions present |
| 23 | Schema quality | P1 | PASS | 4/4 | seed/scenario/market/rule versions configured |
| 24 | Synthetic realism | P1 | PASS | 4/4 | exact full rerun verified |
| 25 | Data quality | P0 | PASS | 4/4 | no critical DQ failures |

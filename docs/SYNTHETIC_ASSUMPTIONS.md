# Synthetic Assumptions

> **SYNTHETIC DEMO DATA – NOT REAL BAYER OR CLINICAL DATA**

## Technical

One seeded RNG controls all generation. Dates end at the configured observation date. Missingness is injected after generation. The demo is oversampled, has weight 1 only for internal scenario summaries and is never population representative.

## Demonstrative clinical and business assumptions

Community-urology referral is slower in the configured scenario; longer referral may reduce/slow initiation. Higher comorbidity can delay initiation and increase stops/hospitalization. Academic oncology has faster initiation and more multidisciplinary care. Adverse events can increase interruption/switch, and progression can increase later-line switching. Relationships remain probabilistic with individual noise. These are not real estimates or causal claims.

| Parameter | Default synthetic value | Rationale | Requires validation | Config location |
|---|---:|---|---|---|
| cohort size | 10,000 | useful demo scale | yes | `target_cohort_size` |
| metastatic | 0.42 via stage mix | enrich pathway events | yes | `stage_distribution` |
| hormone sensitive | 0.88 | populate demo mHSPC | yes | `hormone_sensitive_probability` |
| allowable gap | 60 days | operational persistence rule | yes | `allowable_gap_days` |
| switch | 0.16 | ensure observable transitions | yes | `switch_probability` |
| restart | 0.20 | ensure observable restarts | yes | `restart_probability` |
| progression | 0.29 | ensure follow-up events | yes | `progression_probability` |
| death | 0.09 | ensure survival outcomes | yes | `death_probability` |
| LTFU | 0.07 | demonstrate censoring | yes | `loss_to_follow_up_probability` |
| community-urology referral delay | mean 43 days | synthetic pathway gap | yes | `referral.community_urology` |
| academic initiation | mean 27 days | synthetic setting contrast | yes | `initiation.academic_oncology` |

All remaining probabilities, distributions, ranges, penalties and missingness rates are in `configs/prostate_scenario.yaml`; none should be interpreted outside the scenario.


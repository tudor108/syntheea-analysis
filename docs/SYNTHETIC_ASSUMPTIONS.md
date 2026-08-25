# Synthetic Assumptions and Missingness

> All probabilities are scenario parameters requiring domain review. They are not prevalence, utilization, effectiveness, or market estimates.

`configs/prostate_scenario.yaml` holds shared clinical/pathway generation parameters. `configs/markets.yaml` explicitly controls, per market:

- unequal full and quick sample sizes;
- age, race, insurance, stage, and care-setting distributions;
- access, referral probability/delay/status, and initiation behavior;
- AS uptake, provider density, follow-up visit richness;
- prescription and clinical missingness.

Deep markets (US/DE/JP) receive more encounters, monitoring, prescription detail, adverse-event detail, and provider/referral depth. Scan markets (FR/CN/AU/CA) retain directional denominator/initiation/pathway capability with fewer events and more missing product/clinical detail.

Missingness is not uniformly MCAR:

- Structural: procedure components do not require dispensing; non-referred patients have no referral completion; non-AS patients have no AS dates; untreated patients have no regimen/persistence events.
- Market-dependent: Scan market product IDs/quantities and clinical fields have higher configured null rates.
- Event-dependent: missingness applies only when the relevant diagnosis, prescription, referral, or AS event exists.
- Censor-dependent: future events and not-yet-evaluable persistence are absent/null rather than generated beyond follow-up.

Patients are independent archetypes. Optional raw Synthea patients are used at most once and keep `source_patient_id`; generated rows have a unique `source_archetype_id`. The dataset is enriched for analytical coverage and is explicitly not population representative.

Outcomes have noisy upstream relationships and residual randomness. They are suitable for verifying analysis workflows and detecting synthetic pathway signals, not causal estimation or real-world decisions.

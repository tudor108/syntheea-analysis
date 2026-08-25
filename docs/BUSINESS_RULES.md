# Clinical and Business Rules

> These are versioned synthetic cohort assumptions, not authoritative clinical criteria.

## State and eligibility

Index state is one of localized, locally advanced, metastatic other, mHSPC, or mCRPC. mHSPC requires prostate cancer, metastatic disease, hormone sensitivity, and no castration resistance. The only generated longitudinal resistant transition is `mHSPC → mCRPC`; backward transitions are prohibited.

Gleason score is the sum of primary and secondary patterns. ISUP mapping uses pattern ordering, including the 3+4 versus 4+3 distinction. Age is recomputed as completed 365-day intervals between DOB and index date.

ARPI eligibility is exactly reconstructable:

`mHSPC AND no contraindication AND sufficient evidence AND possible follow-up ≥ minimum follow-up`

Eligible rows have an eligibility date/reason. Ineligible rows have clinical, contraindication, insufficient-evidence, or insufficient-follow-up reasons. There is no hidden random suppression of eligibility.

## Pathway and active surveillance

Every encounter specialty and setting comes from the referenced stable provider master. A referral contains distinct source and destination providers/organizations/specialties, referral/completion dates, status, reason, and decision owner. Only completed referrals have completion dates. Oncology-led systemic treatment starts on or after oncology referral completion; radiotherapy requires a completed transfer to radiation oncology before treatment.

Localized low/intermediate-risk patients can be AS-eligible; eligibility does not imply uptake. Started AS can include PSA, imaging, and biopsy monitoring, continued/censored status, exit reason, and an observable transition to local treatment.

## Treatment and dispensing

Treatment is normalized into episode → regimen → component → prescription event. mHSPC components can form ADT monotherapy, ADT+ARPI or ADT+chemotherapy doublets, and ADT+ARPI+chemotherapy triplets. Intensification is reconstructed from mHSPC state plus ARPI/chemotherapy components, not from a single opaque drug flag. Docetaxel is explicitly bounded to six 21-day cycles. Early refills stockpile effective medication coverage without moving coverage backward.

- Planned combination components start together.
- Add-on is a later component within the same regimen.
- True switch closes line 1, starts a linked line 2 afterward, and prevents later old-line fills.
- Restart closes the first episode, observes a gap, and creates a linked later episode only if restart occurs before censor.
- Discontinuation is a stop without pretending death or LTFU is non-adherence.

Days supply varies by class. Refill profiles generate early, on-time, and late activity. `nominal_covered_until_date = service_date + days_supply`; effective coverage is capped at episode/component/censor.

## Persistence and censoring

Censor date is `min(death_date, loss_to_follow_up_date, observation_end_date)`. Death and LTFU compete; no clinical event is allowed beyond censor.

At 3, 6, and 12 months, status precedence is switch, discontinuation, insufficient observation, persistent coverage within permissible gap, then discontinuation. A patient lacking 12 observable months and without a qualifying earlier switch/stop is `CENSORED_NOT_EVALUABLE`, never false. Separate 30/60/90-day sensitivity statuses are derived from the same events and remain monotonic.

## Outcomes and leakage

Progression, hospitalization, mortality, LTFU, and adverse events are stochastic. Their probabilities depend imperfectly on upstream stage, PSA, complexity/comorbidity, access, and treatment components. No association is deterministic and none is causal evidence.

Future refill count, final coverage, discontinuation, switch, progression, and final outcome are marked `allowed_use_cases=none` for earlier predictive tasks. Splits are at independent archetype level and market-stratified by stable hash.

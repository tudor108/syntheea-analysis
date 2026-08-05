# Business Rules

> **SYNTHETIC DEMO DATA – NOT REAL BAYER OR CLINICAL DATA**

## Cohort and eligibility

`mhspc_flag` requires prostate cancer, metastatic disease, hormone sensitivity, and no castration resistance at index. `eligibility_date` is the latest of diagnosis, metastatic date and hormone-sensitive confirmation. Demo ARPI eligibility additionally requires age 18+, no generated contraindication and at least 90 possible follow-up days.

> **DEMO COHORT ASSUMPTION – REQUIRES CLINICAL VALIDATION.** This is cohort logic, not a medical guideline or treatment recommendation.

## Journey events

- Referral delay is first oncology consultation minus first urology decision; without oncology it is null and completion is false.
- Initiation is first treatment start minus eligibility. Flags cover 30/60/90 days; the 90-day gap is eligible minus initiated within 90 days.
- Persistence at 90/180/365 days requires treatment, coverage to the landmark, no definitive stop before it and no refill gap above the allowable threshold. Sensitivity flags use 30, 60 and 90 days.
- Discontinuation without switch, switch, temporary gap/restart, death, LTFU and censoring remain distinct. Death and LTFU are never labeled non-adherence.
- Switch requires a different drug and a subsequent start; previous/new drug and elapsed days are retained.
- Restart requires a gap beyond the allowable threshold and subsequent same drug/class activity; duplicates do not qualify.
- Censor date is the earliest observation end, loss date, death or available-data end.

No future discontinuation, switch or progression attribute is included in baseline model-ready features.


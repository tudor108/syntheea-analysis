# Cohort funnel and treatment-gap interpretation

> **Synthetic demonstrational data only; not clinical guidance, diagnosis, causal evidence, real Bayer data, or a real-world market-size estimate.**

## Executive interpretation

- **[DESCRIPTIVE]** In the governed synthetic mHSPC denominator, 30/60/90-day initiation is 275/1,255/1,700 among 2,281 90-day evaluable eligible patients; the 90-day observed gap is 581 (25.5%).
- **[PROXY-BASED]** The exact mCRPC state cohort has 346 proxy-eligible and 332 90-day evaluable records, with 3 new post-state treatment starts. This is not evidence of undertreatment because indication-specific eligibility and appropriateness are absent and prior ongoing treatment is common.
- **[PROXY-BASED]** Active surveillance has 3,367 evaluable synthetic AS-eligible patients and 1,738 AS starts within 90 days. This is an uptake metric, not a treatment gap and is not compared directly with metastatic pathways.
- **[NOT COMPUTABLE]** nmCRPC has no explicit state or eligibility definition in the certified release; no patient was inferred into that pathway.
- **[ASSOCIATIONAL]** No causal or adjusted association is estimated here. Market, setting and specialty differences are descriptive segment signals only and do not show that a provider or market caused non-initiation.

## Top five mHSPC gap-volume candidates

1. **[DESCRIPTIVE]** CN | academic_oncology | urology: eligible=205, evaluable=205, initiated=110, gap volume=95, gap=46.3%, confidence=MEDIUM, handling=DIRECTIONAL_ONLY. This is a prioritization candidate for further review, not a causal claim.
2. **[DESCRIPTIVE]** US | community_urology | urology: eligible=352, evaluable=352, initiated=264, gap volume=88, gap=25.0%, confidence=HIGH, handling=ACTIONABLE_DESCRIPTIVE. This is a prioritization candidate for further review, not a causal claim.
3. **[DESCRIPTIVE]** CN | community_urology | urology: eligible=174, evaluable=174, initiated=96, gap volume=78, gap=44.8%, confidence=MEDIUM, handling=DIRECTIONAL_ONLY. This is a prioritization candidate for further review, not a causal claim.
4. **[DESCRIPTIVE]** CA | mixed_pathway | urology: eligible=165, evaluable=165, initiated=113, gap volume=52, gap=31.5%, confidence=MEDIUM, handling=DIRECTIONAL_ONLY. This is a prioritization candidate for further review, not a causal claim.
5. **[DESCRIPTIVE]** FR | community_urology | urology: eligible=222, evaluable=222, initiated=183, gap volume=39, gap=17.6%, confidence=MEDIUM, handling=DIRECTIONAL_ONLY. This is a prioritization candidate for further review, not a causal claim.

## Limitations and unresolved definitions

- **[NOT COMPUTABLE]** Pre-index clinical baseline history is unavailable; the configured baseline is zero days and only validates observable origin at/before index.
- **[NOT COMPUTABLE]** mCSPC is not a recorded value and is not silently mapped to mHSPC; nmCRPC is absent.
- **[PROXY-BASED]** 121 mCRPC members already had prior treatment; a low post-state initiation rate cannot establish a treatment gap without regimen appropriateness and line-specific clinical rules.
- **[PROXY-BASED]** mCRPC contraindication/data-sufficiency inputs reuse available synthetic proxies that were not designed as an indication-specific eligibility rule.
- **[PROXY-BASED]** AS eligibility has an explicit synthetic flag, but its index uses diagnosis date because no separate eligibility-assessment date is collected.
- **[DESCRIPTIVE]** Care setting and specialty use the first normalized encounter. For later mCRPC entry this may not represent the provider at the state transition.
- **[NOT COMPUTABLE]** No financial value, market revenue, intervention success probability or real-world treatment-effect input exists; analytical priority scores are not business value.
- **[ASSOCIATIONAL]** Unadjusted segmented rates may reflect scenario construction, case mix, missingness and follow-up. They are not evidence of causal undertreatment.

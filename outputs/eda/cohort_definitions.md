# Cohort definitions

> **Synthetic demonstrational data only; not clinical guidance, diagnosis, causal evidence, real Bayer data, or a real-world market-size estimate.**

The engine uses a patient-by-pathway audit grain. A patient may enter mHSPC and later mCRPC; those dated memberships remain separate. Active surveillance never shares a denominator with metastatic pathways.

## mHSPC/mCSPC advanced disease — PROXY-BASED

- **Conceptual definition:** Synthetic mHSPC/mCSPC patients meeting the governed ARPI diagnostic denominator; not clinical eligibility.
- **Operational definition:** Exact mHSPC state evidence plus eligibility.eligibility_flag=true under ARPI-ELIG-SYN-v2.0.
- **Required fields:** prostate cancer; mHSPC/mCSPC state; age; contraindication/comorbidity evidence; prior treatment; observability
- **Actual fields used:** diagnosis.prostate_cancer_flag; disease_state_event.state=mHSPC; eligibility.{mhspc_flag,eligibility_flag,contraindication_flag,data_sufficiency_flag,possible_followup_days}; patient.age_at_index; treatment_episode dates; observation.censor_date
- **Inclusion:** mHSPC state event and explicit governed synthetic eligibility flag; 30/60/90 evaluability is handled separately.
- **Exclusion:** No prostate-cancer flag; missing/invalid state or index; index after censor; insufficient governed evidence; explicit contraindication where applicable.
- **Index date:** eligibility_date when populated; otherwise mHSPC state date/diagnosis date only for pre-eligibility funnel audit.
- **Baseline:** 0 days. Pre-index clinical lookback is unavailable and NOT COMPUTABLE.
- **Initiation:** First normalized treatment episode on/after index; sensitivity at 30, 60 and 90 days.
- **Follow-up:** Censor date reaches the selected initiation landmark; governed eligibility also requires at least 90 possible days.
- **Censoring:** Earliest of death, loss to follow-up, or administrative end; dataset end is not discontinuation.
- **Limitations:** Only mHSPC is present; mCSPC is not a recorded synonym. Eligibility is a synthetic ARPI proxy, not a clinical treatment rule.
- **Confidence:** HIGH within the synthetic contract; PROXY ONLY clinically

## nmCRPC — NOT COMPUTABLE

- **Conceptual definition:** Non-metastatic castration-resistant prostate cancer pathway.
- **Operational definition:** Would require an explicit nmCRPC state plus non-metastatic and castration-resistant evidence at a dated index.
- **Required fields:** nmCRPC state; non-metastatic evidence; castration resistance; dated index; eligibility criteria; treatment history; observability
- **Actual fields used:** Schema inspection only; disease_state_event contains no nmCRPC value.
- **Inclusion:** None: the governed release has zero explicit nmCRPC records.
- **Exclusion:** No patient is relabelled or inferred as nmCRPC.
- **Index date:** NOT COMPUTABLE
- **Baseline:** NOT COMPUTABLE
- **Initiation:** NOT COMPUTABLE
- **Follow-up:** NOT COMPUTABLE
- **Censoring:** Would use the governed censor date if a cohort existed.
- **Limitations:** The required clinical state and eligibility definition are absent. mCRPC or metastatic_other are not substituted.
- **Confidence:** NOT COMPUTABLE

## mCRPC — PROXY-BASED

- **Conceptual definition:** Patients entering an explicit dated mCRPC state, including observed mHSPC-to-mCRPC transitions.
- **Operational definition:** disease_state_event.state=mCRPC; proxy eligibility requires valid state/index, age 50-90, no recorded contraindication, sufficient evidence and configured minimum possible follow-up.
- **Required fields:** mCRPC state/date; prior treatment; age; contraindication/comorbidity evidence; indication-specific eligibility; observability
- **Actual fields used:** disease_state_event.{state,state_date,previous_state}; patient.age_at_index/comorbidity_score; eligibility contraindication/data-sufficiency/follow-up proxies; normalized treatment episodes; observation.censor_date
- **Inclusion:** Exact mCRPC event. Proxy eligibility is never labelled eligible_observed.
- **Exclusion:** No prostate-cancer flag; missing/invalid state or index; index after censor; insufficient governed evidence; explicit contraindication where applicable.
- **Index date:** First exact mCRPC state date.
- **Baseline:** 0 days required; prior treatment is described from normalized episodes.
- **Initiation:** First treatment episode beginning on/after the mCRPC state date; 30/60/90-day sensitivity.
- **Follow-up:** Censor date reaches each selected landmark.
- **Censoring:** Governed earliest terminal boundary; prior ongoing treatment is not a new initiation.
- **Limitations:** No mCRPC-specific clinical eligibility or line-appropriateness definition exists; results are PROXY ONLY.
- **Confidence:** LOW; PROXY ONLY

## Active surveillance — PROXY-BASED

- **Conceptual definition:** Localized patients evaluated for the separate synthetic active-surveillance pathway.
- **Operational definition:** Presence in active_surveillance; eligible_observed uses as_eligibility_flag. Initiation means AS uptake (as_start_date), never treatment initiation.
- **Required fields:** localized disease; risk/grade; age/complexity; AS eligibility/status/start; observation window
- **Actual fields used:** disease_state_event.state=localized; active_surveillance.{as_eligibility_flag,as_start_date,as_status}; diagnosis risk/grade; patient age/complexity; observation.censor_date
- **Inclusion:** Explicit active_surveillance record; eligibility uses the governed synthetic AS flag.
- **Exclusion:** Metastatic disease is never placed in the AS denominator; AS ineligibility remains explicit.
- **Index date:** Diagnosis date proxy because no separate AS eligibility-assessment date is collected.
- **Baseline:** 0 days; pre-diagnosis baseline is unavailable.
- **Initiation:** AS start/uptake within 30/60/90 days of diagnosis proxy index; not a therapy-gap metric.
- **Follow-up:** Censor date reaches each selected AS-uptake landmark.
- **Censoring:** Governed censor date; no event is inferred after censor.
- **Limitations:** Index is proxied by diagnosis and AS uptake is not treatment. Do not compare its gap directly with metastatic-treatment gaps.
- **Confidence:** MEDIUM within synthetic AS rules; PROXY ONLY clinically

## Outcome interpretation

- `initiated_within_*d` is treatment initiation for mHSPC/mCSPC and mCRPC, AS uptake for active surveillance, and null for nmCRPC.
- `eligible_observed` means an explicit governed flag exists in the synthetic dataset; it does not mean real clinical eligibility.
- `eligible_proxy` is used only for mCRPC and is labelled PROXY-BASED in every aggregate.
- `eligibility_uncertain` remains separate from explicit ineligibility.
- Pre-index baseline history, nmCRPC, financial value and causal effects are NOT COMPUTABLE.

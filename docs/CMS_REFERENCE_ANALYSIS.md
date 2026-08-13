# CMS DE-SynPUF Reference Analysis

> **Purpose:** schema/reference analysis only. CMS DE-SynPUF is fully synthetic and should not be used to make population or clinical inferences.

## Source files reviewed

- CMS DE 1.0 Codebook
- 2008 Beneficiary Summary, Sample 1
- 2008-2010 Inpatient Claims, Sample 1
- 2008-2010 Outpatient Claims, Sample 1
- 2008-2010 Carrier Claims, Sample 1A/1B
- 2008-2010 Prescription Drug Events (PDE), Sample 1

CMS DE-SynPUF is designed for application development/training and preserves beneficiary/claim structure while using synthetic beneficiaries. The files are linkable through `DESYNPUF_ID`. The codebook explicitly warns against making Medicare population inferences from the synthetic data.

## Relevance to the prostate patient-journey demo

### 1. Prescription Drug Events (highest relevance)

CMS PDE contains one row per synthetic Part D event and only eight fields:

- `DESYNPUF_ID` - beneficiary identifier
- `PDE_ID` - unique Part D event identifier
- `SRVC_DT` - prescription fill/service date
- `PROD_SRVC_ID` - product/NDC identifier
- `QTY_DSPNSD_NUM` - quantity dispensed
- `DAYS_SUPLY_NUM` - days supply
- `PTNT_PAY_AMT` - patient-paid amount
- `TOT_RX_CST_AMT` - gross drug cost

This is directly useful as a structural reference for the **persistence-gap cohort**, because it models medication dispensing at event level rather than only at treatment-episode level.

### 2. Outpatient and Carrier claims

Outpatient claims contain beneficiary ID, claim ID, service start/end dates, provider identifiers, diagnosis codes, procedure codes and HCPCS fields. Carrier claims add physician/supplier line-level provider, HCPCS, diagnosis and payment fields.

These are useful as references for a future claims/event layer supporting pathway events and provider/service evidence. They are less urgent than PDE for the current three-cohort scope because the demo already contains synthetic encounter, referral and provider tables.

### 3. Beneficiary Summary

The Beneficiary Summary provides demographics, coverage months, chronic-condition flags and annual reimbursement summaries. Relevant concepts include date of birth/death, sex, race, geography, Part A/B/D coverage months and chronic-condition indicators.

The current demo already contains synthetic demographics, insurance class, comorbidity and mortality fields, so the main value here is structural reference rather than a new patient-level data source.

## Mapping to the current demo schema

| CMS concept | CMS field | Current demo equivalent | Status / recommendation |
|---|---|---|---|
| Patient identifier | `DESYNPUF_ID` | `patient_id` | Concept already exists; do not join IDs across datasets |
| Prescription event identifier | `PDE_ID` | none | Missing at event level; candidate for `prescription_event_id` |
| Fill/service date | `SRVC_DT` | `refill_date` | Exists only as episode-level summary; event-level representation would improve traceability |
| Product identifier | `PROD_SRVC_ID` | `drug_name` / treatment mapping | Concept exists, but no event-level product ID |
| Quantity dispensed | `QTY_DSPNSD_NUM` | none | Optional candidate if dispensing-level realism is needed |
| Days supply | `DAYS_SUPLY_NUM` | `days_supply` | Already exists; should be attached to each fill event if event model is added |
| Patient pay | `PTNT_PAY_AMT` | none | Not required for current three cohorts; optional future access/cost analysis |
| Gross drug cost | `TOT_RX_CST_AMT` | none | Not required for current three cohorts |
| Claim ID | `CLM_ID` | none | Optional if a claims layer is introduced |
| Claim start/end | `CLM_FROM_DT`, `CLM_THRU_DT` | encounter/treatment dates | Concepts already exist in domain-specific tables |
| Provider | `PRVDR_NUM`, NPI fields | `provider_id`, `prescribing_provider_id` | Concept already exists synthetically |
| Diagnosis codes | ICD-9 diagnosis fields | prostate diagnosis fields | Current demo uses explicit prostate-specific synthetic diagnosis attributes rather than claims coding |
| Procedure/service codes | HCPCS/procedure fields | none | Optional future claims realism; not needed for current cohort MVP |
| Coverage months | Part A/B/D coverage fields | `insurance_type` only | Could improve eligibility/observable-follow-up logic, but not necessary for current cohort MVP |

## Comparison with existing Synthea raw data

The repository already includes Synthea `medications.csv` with fields such as:

- `START`, `STOP`
- `PATIENT`, `PAYER`, `ENCOUNTER`
- `CODE`, `DESCRIPTION`
- `BASE_COST`, `PAYER_COVERAGE`
- `DISPENSES`, `TOTALCOST`
- reason fields

Therefore, the immediate recommendation is **not** to copy CMS data into the prostate cohort or join CMS beneficiaries to Synthea patients. Instead:

1. use CMS PDE as a claims-oriented schema reference;
2. evaluate whether Synthea medication records can supply/reinforce event-level medication structure;
3. generate prostate-specific synthetic prescription events linked to the current `patient_id` / `treatment_id` when needed;
4. derive refill gaps and persistence from those events;
5. keep CMS as external reference data only.

## Proposed schema improvement

If implementation is approved, add a normalized table similar to:

```text
prescription_event
------------------
prescription_event_id
patient_id
treatment_id
service_date
product_id
drug_name
quantity_dispensed
days_supply
covered_until_date
event_type
synthetic_event_flag
```

One row should represent one synthetic fill/refill event.

### Derived persistence logic

From consecutive prescription events:

```text
covered_until = service_date + days_supply
refill_gap_days = next_service_date - covered_until
```

The existing 30/60/90-day persistence sensitivity rules can then be calculated from explicit event history rather than relying only on an episode-level `max_refill_gap_days` summary.

## Recommendation by cohort

| Cohort | CMS contribution now | Recommendation |
|---|---|---|
| Treatment initiation gap | Low/medium | Use current `patient_journey`; claims structure is optional future enrichment |
| Referral gap | Low | Current encounter/referral/provider model is sufficient for MVP |
| Persistence gap | High | Use PDE as schema reference for an event-level prescription/refill model |

## Conclusion

For the current task, the three proposed cohorts can already be analysed with the existing synthetic gold model. The most defensible schema improvement identified from CMS is an event-level prescription/refill table for persistence analysis. CMS data should remain a reference and must not be patient-level joined to the Synthea/prostate demo cohort.

## Source notes

- CMS DE 1.0 Codebook, Introduction, pp. 1-3.
- CMS DE 1.0 Codebook, Summary of Variables, pp. 4-9.
- CMS DE 1.0 Codebook, Prescription Drug Events section, pp. 110-117.
- CMS DE 1.0 Codebook, Appendix 1, prostate cancer definition, p. 120.

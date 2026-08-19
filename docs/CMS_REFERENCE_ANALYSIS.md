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

### Implementation status: prescription events

The demo now implements a normalized synthetic `prescription_event` table. It is generated from the existing synthetic treatment and refill logic; it is not copied from CMS PDE and does not join CMS beneficiaries to the Synthea/prostate demo patients.

The table contains one row per synthetic initial fill or refill and includes:

- `prescription_event_id`
- `patient_id`
- `treatment_id`
- `service_date`
- `product_id`
- `drug_name`
- `quantity_dispensed`
- `days_supply`
- `covered_until_date`
- `event_type`
- `refill_gap_days`
- `synthetic_event_flag`

One treatment can have multiple events. The first event is `initial_fill`; subsequent events are `refill`. The event chronology is internally consistent: `covered_until_date` is `service_date + days_supply`, subsequent service dates account for the sampled refill gap after prior coverage, and `refill_gap_days` records that actual gap. The treatment-level `max_refill_gap_days` remains consistent with the emitted events.

The event table is exported as `prescription_event.csv` and `prescription_event.parquet`, and is loaded into DuckDB as a normal table. It is not currently used to add CMS-derived clinical or utilization facts.

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
| Prescription event identifier | `PDE_ID` | `prescription_event_id` | Implemented as a synthetic event identifier; CMS remains a schema reference |
| Fill/service date | `SRVC_DT` | `service_date` | Implemented for each synthetic fill/refill event |
| Product identifier | `PROD_SRVC_ID` | `product_id` | Implemented synthetically for each event |
| Quantity dispensed | `QTY_DSPNSD_NUM` | `quantity_dispensed` | Implemented synthetically for each event |
| Days supply | `DAYS_SUPLY_NUM` | `days_supply` | Implemented on each synthetic event; currently 30 days where generated |
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

## Implemented event-level schema

The implemented normalized table is:

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
refill_gap_days
synthetic_event_flag
```

One row represents one synthetic fill/refill event. Events are generated from the current seeded synthetic treatment/refill process and are linked to the generated `patient_id` and `treatment_id`.

### Derived persistence logic

From consecutive prescription events:

```text
covered_until = service_date + days_supply
refill_gap_days = next_service_date - covered_until
```

The existing 30/60/90-day persistence sensitivity rules are calculated from the explicit event history rather than relying only on an episode-level refill summary. `patient_journey` includes the event-derived `prescription_event_count` and `max_refill_gap_days` values. Persistence at 3, 6 and 12 months uses event-derived coverage and refill gaps together with treatment initiation, discontinuation and sufficient follow-up.

## Recommendation by cohort

| Cohort | CMS contribution now | Recommendation |
|---|---|---|
| Treatment initiation gap | Low/medium | Use current `patient_journey`; claims structure is optional future enrichment |
| Referral gap | Low | Current encounter/referral/provider model is sufficient for MVP |
| Persistence gap | High | Use the implemented synthetic prescription-event table; retain PDE as a schema/reference source only |

## Conclusion

The three cohorts can be analysed with the synthetic gold model, including event-level prescription/refill support for persistence. CMS DE-SynPUF PDE remains a schema/reference source that motivated this representation. The implemented events are synthetic demo logic, not CMS observations or clinical evidence; CMS data must remain external reference data and must not be patient-level joined to the Synthea/prostate demo cohort.

## Source notes

- CMS DE 1.0 Codebook, Introduction, pp. 1-3.
- CMS DE 1.0 Codebook, Summary of Variables, pp. 4-9.
- CMS DE 1.0 Codebook, Prescription Drug Events section, pp. 110-117.
- CMS DE 1.0 Codebook, Appendix 1, prostate cancer definition, p. 120.

"""Generate probabilistic, censored outcomes and dated adverse events."""

from __future__ import annotations

import numpy as np
import pandas as pd


def generate_outcome_model(
    patient: pd.DataFrame,
    diagnosis: pd.DataFrame,
    eligibility: pd.DataFrame,
    observation: pd.DataFrame,
    treatment_episode: pd.DataFrame,
    regimen_component: pd.DataFrame,
    config: dict,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Create one outcome summary per patient plus dated adverse/state events."""
    diagnosis_index = diagnosis.set_index("patient_id")
    eligibility_index = eligibility.set_index("patient_id")
    observation_index = observation.set_index("patient_id")
    treated_ids = set(treatment_episode.patient_id) if not treatment_episode.empty else set()
    outcomes: list[dict] = []
    adverse_events: list[dict] = []
    state_events: list[dict] = []
    outcome_config = config["outcomes"]
    rules = config["clinical_rule_configuration"]["clinical_rules"]
    outcome_model_version = rules["outcome_model"]["version"]
    state_model_version = rules["clinical_state_model"]["version"]

    for _, person in patient.iterrows():
        dx = diagnosis_index.loc[person.patient_id]
        eligible = eligibility_index.loc[person.patient_id]
        obs = observation_index.loc[person.patient_id]
        diagnosis_date = pd.Timestamp(dx.diagnosis_date)
        censor = pd.Timestamp(obs.censor_date)
        observable_days = max(0, (censor - diagnosis_date).days)
        patient_episodes = (
            treatment_episode[treatment_episode.patient_id.eq(person.patient_id)]
            if not treatment_episode.empty
            else treatment_episode
        )
        progression_candidate = (
            diagnosis_date + pd.Timedelta(days=int(rng.integers(120, observable_days + 1)))
            if observable_days >= 120
            else pd.NaT
        )
        treated_before_candidate = bool(
            pd.notna(progression_candidate)
            and not patient_episodes.empty
            and patient_episodes.treatment_start_date.le(progression_candidate).any()
        )
        progression_probability = (
            outcome_config["progression_base_probability"]
            + outcome_config["metastatic_increment"] * bool(dx.metastatic_flag)
            + outcome_config["high_psa_increment"]
            * bool(pd.notna(dx.psa_value) and float(dx.psa_value) >= 50)
            + outcome_config["untreated_eligible_increment"]
            * bool(eligible.eligibility_flag and not treated_before_candidate)
        )
        progression = bool(
            pd.notna(progression_candidate)
            and rng.random() < np.clip(progression_probability, 0.02, 0.72)
        )
        progression_date = progression_candidate if progression else pd.NaT
        hospital_probability = (
            outcome_config["hospitalisation_base_probability"]
            + outcome_config["high_comorbidity_increment"] * float(person.comorbidity_score >= 4)
            + outcome_config["metastatic_hospitalisation_increment"] * bool(dx.metastatic_flag)
        )
        hospitalised = bool(
            observable_days >= 30 and rng.random() < np.clip(hospital_probability, 0.01, 0.55)
        )
        hospitalisation_date = (
            diagnosis_date + pd.Timedelta(days=int(rng.integers(30, observable_days + 1)))
            if hospitalised
            else pd.NaT
        )

        patient_adverse = 0
        for _, episode in patient_episodes.iterrows():
            component_classes = set(
                regimen_component.loc[
                    regimen_component.treatment_episode_id.eq(episode.treatment_episode_id),
                    "drug_class",
                ]
            )
            probability = outcome_config["adverse_event_base_probability"]
            probability += 0.12 if "chemotherapy" in component_classes else 0.0
            probability += 0.06 if person.comorbidity_score >= 4 else 0.0
            if rng.random() >= np.clip(probability, 0.02, 0.60):
                continue
            start = pd.Timestamp(episode.treatment_start_date)
            end = min(pd.Timestamp(episode.treatment_end_date), censor)
            if end <= start:
                continue
            event_date = start + pd.Timedelta(days=int(rng.integers(1, (end - start).days + 1)))
            event_types = (
                ["neutropenia", "fatigue", "neuropathy"]
                if "chemotherapy" in component_classes
                else ["fatigue", "hypertension", "laboratory_abnormality", "other"]
            )
            adverse_events.append(
                {
                    "adverse_event_id": f"AE-{person.market_code}-{len(adverse_events):08d}",
                    "patient_id": person.patient_id,
                    "market_code": person.market_code,
                    "treatment_episode_id": episode.treatment_episode_id,
                    "adverse_event_date": event_date,
                    "adverse_event_type": str(rng.choice(event_types)),
                    "severity": str(
                        rng.choice(["mild", "moderate", "severe"], p=[0.52, 0.38, 0.10])
                    ),
                    "serious_event_flag": bool(rng.random() < 0.08),
                    "outcome_model_version": outcome_model_version,
                    "synthetic_event_flag": True,
                }
            )
            patient_adverse += 1

        cr_transition = bool(
            progression
            and dx.metastatic_flag
            and dx.hormone_sensitive_flag
            and rng.random() < config["castration_resistant_transition_probability"]
        )
        cr_date = pd.NaT
        if cr_transition:
            candidate = progression_date + pd.Timedelta(days=int(rng.integers(30, 181)))
            if candidate <= censor:
                cr_date = candidate
                state_events.append(
                    {
                        "disease_state_event_id": (
                            f"DSE-{person.market_code}-{len(state_events):08d}-F"
                        ),
                        "patient_id": person.patient_id,
                        "market_code": person.market_code,
                        "state_date": cr_date,
                        "state": "mCRPC",
                        "previous_state": "mHSPC",
                        "transition_reason": "synthetic_progression",
                        "clinical_state_model_version": state_model_version,
                        "synthetic_event_flag": True,
                    }
                )
            else:
                cr_transition = False

        death_flag = pd.notna(obs.death_date)
        ltfu_flag = pd.notna(obs.loss_to_follow_up_date)
        active_treatment_at_censor = bool(
            not patient_episodes.empty
            and patient_episodes.treatment_status.eq("ongoing").any()
            and patient_episodes.treatment_end_date.ge(censor).any()
        )
        status = (
            "death"
            if death_flag
            else "progressed"
            if progression
            else "hospitalised"
            if hospitalised
            else "lost_to_follow_up"
            if ltfu_flag
            else "active_treatment"
            if active_treatment_at_censor
            else "post_treatment_follow_up"
            if person.patient_id in treated_ids
            else "observed_no_treatment"
        )
        outcomes.append(
            {
                "outcome_id": f"OUT-{person.market_code}-{len(outcomes):07d}",
                "patient_id": person.patient_id,
                "market_code": person.market_code,
                "progression_event": progression,
                "progression_date": progression_date,
                "castration_resistant_transition": cr_transition,
                "castration_resistant_date": cr_date,
                "hospitalisation_flag": hospitalised,
                "first_hospitalisation_date": hospitalisation_date,
                "adverse_event_flag": patient_adverse > 0,
                "adverse_event_count": patient_adverse,
                "death_flag": death_flag,
                "death_date": obs.death_date,
                "lost_to_follow_up_flag": ltfu_flag,
                "loss_to_follow_up_date": obs.loss_to_follow_up_date,
                "last_observed_date": obs.last_observed_date,
                "censor_date": obs.censor_date,
                "censor_reason": obs.censor_reason,
                "outcome_status": status,
                "outcome_model_version": outcome_model_version,
                "synthetic_event_flag": True,
            }
        )
    adverse_columns = [
        "adverse_event_id",
        "patient_id",
        "market_code",
        "treatment_episode_id",
        "adverse_event_date",
        "adverse_event_type",
        "severity",
        "serious_event_flag",
        "outcome_model_version",
        "synthetic_event_flag",
    ]
    state_columns = [
        "disease_state_event_id",
        "patient_id",
        "market_code",
        "state_date",
        "state",
        "previous_state",
        "transition_reason",
        "clinical_state_model_version",
        "synthetic_event_flag",
    ]
    return (
        pd.DataFrame(outcomes),
        pd.DataFrame(adverse_events, columns=adverse_columns),
        pd.DataFrame(state_events, columns=state_columns),
    )


def generate_outcomes(*args, **kwargs) -> pd.DataFrame:
    """Compatibility wrapper returning the patient-level outcome table."""
    return generate_outcome_model(*args, **kwargs)[0]

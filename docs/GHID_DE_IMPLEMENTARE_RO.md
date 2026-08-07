# Ghid de implementare – explicat în română

> **SYNTHETIC DEMO DATA – NOT REAL BAYER OR CLINICAL DATA**

Acest document explică ce există în proiect, de ce există și cum se folosește. Proiectul este un demo tehnic pentru analizarea unui traseu sintetic al pacienților cu cancer de prostată. Nu este un sistem de diagnostic și nu recomandă tratamente pentru persoane reale.

## 1. Ce problemă rezolvă proiectul

Proiectul transformă date demografice de bază într-un traseu longitudinal analizabil:

```text
pacient
  → diagnostic și stadiu
  → boală metastatică hormone-sensitive (mHSPC)
  → eligibilitate demo pentru ARPI
  → urologie
  → referral oncologic
  → inițiere tratament
  → refill și acoperire
  → persistență, întrerupere, switch sau restart
  → progresie, deces, pierdere din observație sau cenzurare
```

Întrebările pe care le poți explora sunt: câți pacienți sunt eligibili, câți nu inițiază în 90 de zile, cât durează referral-ul, cât persistă tratamentul și unde apar diferențe între setting-uri.

## 2. Ce este Synthea și ce am adăugat noi

Synthea este generatorul open-source de date medicale sintetice. Repository-ul este inclus în `external/synthea`, la commit-ul consemnat în `data/reports/run_metadata.json`.

Din exportul CSV Synthea folosim în primul rând:

- `patients.csv` pentru identificator, sex, data nașterii, rasă, etnie și geografie;
- opțional `providers.csv`, `organizations.csv`, `encounters.csv`, `conditions.csv`, `medications.csv`, `observations.csv` și tabelele de payer.

Pipeline-ul nostru nu modifică masiv codul Synthea. După export, Python adaugă variabilele specifice cazului de business: stadiu de prostată, mHSPC, eligibility, care setting, referral, tratamente, refills, switch/restart și outcomes.

Dacă nu există `patients.csv`, loader-ul folosește un fallback determinist, cu formă compatibilă Synthea. Mesajul este logat explicit; fallback-ul nu trebuie confundat cu o rulare Synthea reală.

## 3. Cum curge codul

Punctul de intrare este `src/prostate_journey/cli.py`. Comanda `run-all` apelează `pipeline.run_all`, care execută următorii pași:

1. `synthea_loader.py` citește CSV-urile sau construiește fallback-ul.
2. `cohort_builder.py` normalizează demografia și adaugă flag-urile de oversampling.
3. `provider_generator.py` construiește providerii și atribuie fiecărui pacient un provider inițial.
4. `diagnosis_generator.py` generează stadiul, metastazele, hormone sensitivity, PSA și Gleason.
5. `journey_builder.py` calculează mHSPC, eligibility și encounters/referral.
6. `treatment_generator.py` generează start, refill, covered-until, stop, switch și restart.
7. `outcome_generator.py` generează progresie, hospitalizare, adverse event, deces, LTFU și censoring.
8. `journey_builder.py` agregă totul într-un rând per pacient: `patient_journey`.
9. `data_quality.py` rulează regulile critice și scrie raportul DQ.
10. `duckdb_loader.py` creează tabelele și view-urile SQL.
11. `reporting.py` scrie KPI-urile, sumarul și metadata cu hash-uri.

Toate modulele folosesc `pathlib`, type hints, docstrings și un seed NumPy comun pentru reproducibilitate.

## 4. Configurația YAML

Fișierul principal este `configs/prostate_scenario.yaml`. Acolo se află probabilitățile și distribuțiile importante, nu ascunse în cod:

- dimensiunea cohortei și intervalul de vârstă;
- distribuția stadiilor și a siturilor metastatice;
- distribuția `care_setting` și a specialităților;
- probabilități și întârzieri de referral;
- probabilități și durate de inițiere;
- lista și probabilitățile tratamentelor;
- allowable gap pentru persistence;
- switch, restart, progresie, deces și LTFU;
- probabilități de adverse event, spitalizare și missingness;
- efectele sintetice pentru comorbiditate, setting și adverse events.

Valorile sunt ipoteze demo și necesită validare clinică și de business. `population_representative_flag` este intenționat `false`.

## 5. Cum se calculează conceptele principale

### mHSPC

`mhspc_flag = true` numai dacă pacientul are cancer de prostată, este metastatic, este hormone-sensitive și nu este castration-resistant la index.

### Eligibilitate ARPI

Regula demo cere mHSPC, vârstă adultă, lipsa unei contraindicații sintetice și minimum 90 de zile de follow-up posibil. Este o regulă de cohortă pentru demonstrație, nu ghid medical.

### Eligibility date

Este cea mai târzie dintre data diagnosticului, data metastazării și data confirmării hormone-sensitive.

### Referral delay

```text
first_oncology_date - first_urology_date
```

Dacă nu există consultație oncologică, delay-ul rămâne null și referral-ul este incomplet.

### Inițiere

```text
days_to_initiation = treatment_start_date - eligibility_date
```

Sunt calculate pragurile de 30, 60 și 90 de zile, plus `eligible_not_initiated_90d`.

### Persistence

Un pacient este persistent la 3, 6 sau 12 luni dacă tratamentul a început, acoperirea ajunge la landmark, nu există un gap mai mare decât `allowable_gap_days` și nu există stop definitiv înainte de landmark. Sunt produse și sensibilități cu gap de 30, 60 și 90 de zile. Follow-up-ul insuficient invalidează landmark-ul respectiv.

### Discontinuation, switch și restart

- discontinuation: oprire definitivă;
- switch: începe un medicament diferit în fereastra configurată;
- restart: reîncepe același medicament/clasă după un gap peste allowable gap;
- temporary gap: pauză care nu este tratată automat ca non-adherence;
- death și LTFU: outcomes separate, nu discontinuation implicit.

## 6. Tabelele produse

| Tabel | Granularitate | Scop |
|---|---|---|
| `patient` | un rând/pacient | demografie și covariate de bază |
| `diagnosis` | un rând/diagnostic | stadiu, metastaze, hormone sensitivity |
| `provider` | un rând/provider | specialitate, setting, MDT |
| `encounter` | un rând/eveniment | urologie, oncologie, referral |
| `treatment` | un rând/episod | tratament, acoperire, stop, switch, restart |
| `outcome` | un rând/pacient | progresie, deces, LTFU, censoring |
| `patient_journey` | un rând/pacient | tabelul gold pentru analiză |

Dicționarul complet, cu tipuri, nullable și reguli, este în `docs/DATA_DICTIONARY.md`.

## 7. Ce se găsește în `data/gold`

Fiecare tabel este exportat în două formate:

- `.csv`: ușor de inspectat în Excel/VS Code;
- `.parquet`: format columnar pentru pandas, DuckDB și analize eficiente.

`prostate_journey.duckdb` conține tabelele și view-urile:

- `vw_eligible_population`;
- `vw_eligible_not_initiated`;
- `vw_treatment_initiation`;
- `vw_persistence`;
- `vw_switches`;
- `vw_referral_delays`;
- `vw_final_outcomes`;
- `vw_treatment_gap_by_segment`.

Exemplu PowerShell:

```powershell
python -c "import duckdb; c=duckdb.connect('data/gold/prostate_journey.duckdb', read_only=True); print(c.sql('select * from vw_treatment_gap_by_segment order by treatment_gap desc limit 10'))"
```

## 8. Data quality și reproducibilitate

`data_quality.py` verifică unicitatea, sexul masculin, cronologia, logica mHSPC, eligibility, foreign keys, refill coverage, persistence, switch/restart, deces și evenimente după deces.

Regulile critice opresc pipeline-ul. Rezultatele sunt:

- `data/reports/data_quality_summary.json`;
- `data/reports/data_quality_summary.csv`;
- `data/reports/data_quality_report.md`.

`run_metadata.json` păstrează timestamp, commit-ul Git, versiunea Python, commit-ul Synthea, seed-ul, dimensiunea cohortei, versiunea scenariului și hash-urile Parquet.

Același seed și aceeași configurație produc aceleași tabele. Timestamp-ul metadata se schimbă natural la fiecare rulare.

## 9. Comenzile uzuale

Din rădăcina proiectului:

```powershell
# mediu și dependențe
powershell -ExecutionPolicy Bypass -File .\scripts\setup_environment.ps1

# export Synthea real
.\scripts\run_synthea.ps1 -Population 25000 -Seed 42 -State Massachusetts

# pipeline complet
python -m prostate_journey.cli run-all --seed 42 --cohort-size 10000

# pași separați
python -m prostate_journey.cli generate --cohort-size 1000
python -m prostate_journey.cli validate
python -m prostate_journey.cli load-duckdb
python -m prostate_journey.cli report

# teste
python -m pytest -q
```

Pentru VS Code, deschide `prostate-patient-journey-synthetic.code-workspace`, nu folderul părinte `EndevLocal`. Astfel Source Control afișează numai repository-ul proiectului.

## 10. Ce nu trebuie interpretat ca real

Distribuțiile de stadiu, referral, inițiere, persistence, switch, restart, progresie și deces sunt generate pentru a crea un demo analizabil. Nu reprezintă prevalențe, rezultate clinice, recomandări terapeutice sau estimări comerciale. Cohorta este supra-eșantionată și nu este reprezentativă pentru populația reală.


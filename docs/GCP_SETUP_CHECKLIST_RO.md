# Checklist Google Cloud pentru migrare și deployment

> **SUPERSEDED — PREVIOUS GOOGLE CLOUD TARGET**
>
> Acest document este păstrat numai ca istoric al arhitecturii evaluate anterior. Google Cloud nu
> mai este ținta curentă. Nu executa pașii de mai jos pentru proiectul actual; folosește
> [AWS deployment handoff](AWS_DEPLOYMENT_HANDOFF.md). Nu au fost create resurse GCP din repository.

**Document de handoff pentru:** inginer junior / cloud engineer  
**Proiect:** Prostate Patient Journey Synthetic  
**Scop:** mediu Google Cloud reproductibil pentru stocare, pipeline analytics, training, model registry, batch prediction și dashboard privat  
**Clasificare curentă:** exclusiv date sintetice demonstrative

## Rezultatul așteptat

La final trebuie să existe următorul flux:

```text
GitHub
  -> Cloud Build CI/CD
  -> Artifact Registry container image
  -> Vertex AI Pipeline / Custom Jobs
  -> Cloud Storage immutable candidate/approved releases + Vertex artifacts
  -> BigQuery analytical tables/views
  -> Vertex AI Model Registry
  -> Batch Prediction by default
  -> optional Vertex AI Endpoint for an approved live use case
  -> private Cloud Run dashboard/API
```

Nu copia repository-ul complet într-un bucket. GitHub rămâne sursa de adevăr pentru cod. Cloud Storage este pentru date, release-uri, artefacte și staging.

## Reguli pentru junior

- Nu utiliza conturi personale sau proiecte Google Cloud personale.
- Nu cere și nu păstra rolul `Owner` permanent.
- Nu crea și nu descărca chei JSON pentru service accounts.
- Nu face bucket-uri sau servicii publice.
- Nu încărca date reale despre pacienți în acest proiect.
- Nu șterge sau suprascrie release-uri candidate sau aprobate.
- Nu activa un endpoint online înainte de aprobarea costului și use case-ului.
- Orice IAM larg, retention lock, CMEK sau policy la nivel de organizație trebuie aprobat de un senior/platform administrator.
- Preferă Terraform/IaC cu pull request și review. Dacă setup-ul inițial este făcut din Console, exportă exact configurația și creează imediat backlog pentru codificarea ei.

## 0. Informații de primit înainte de configurare

Juniorul trebuie să primească în scris:

- [ ] Google Cloud Organization ID.
- [ ] Folder ID în care va sta proiectul.
- [ ] Billing Account ID.
- [ ] project ID pentru `dev` și, dacă este aprobat, separat pentru `prod`.
- [ ] cost center și owner tehnic.
- [ ] grupurile Google pentru admini, developeri, analiști și read-only users.
- [ ] GitHub organization/repository și persoana care poate instala Cloud Build GitHub App.
- [ ] bugetul lunar aprobat.
- [ ] politica de regiune/data residency.
- [ ] confirmarea scrisă că mediul conține numai date sintetice.

### Convenții recomandate

Înlocuiește placeholder-ele după aprobarea ownerului:

```text
PROJECT_ID=prostate-journey-dev-<company>
PROJECT_NUMBER=<generated-by-gcp>
REGION=europe-west4
ENV=dev
APP=prostate-journey
```

`europe-west4` este recomandarea inițială pentru a ține Storage, Artifact Registry, Vertex AI și Cloud Run în aceeași regiune europeană. Regiunea finală trebuie confirmată cu platform/security și verificată pentru toate funcționalitățile Vertex folosite.

## 1. Proiect, billing și ownership — admin/senior

- [ ] Creează un proiect dedicat de development.
- [ ] Leagă proiectul la billing account-ul aprobat.
- [ ] Adaugă proiectul în folderul corect din organizație.
- [ ] Configurează labels la nivel de proiect:

```text
application=prostate-journey
environment=dev
owner=<team>
cost-center=<cost-center>
data-classification=synthetic
managed-by=terraform
```

- [ ] Creează grupuri IAM, nu binding-uri individuale unde se poate:

```text
gcp-prostate-admins@<domain>
gcp-prostate-developers@<domain>
gcp-prostate-analysts@<domain>
gcp-prostate-viewers@<domain>
```

- [ ] Confirmă că serviciile default nu primesc automat rolul `Editor`.
- [ ] Notează project ID, project number, billing account și folder ID în handoff.

Separarea `dev`/`prod` prin proiecte diferite este preferată. Pentru prima demonstrație este suficient `dev`; nu crea un fals `prod` fără owner, buget și proces de release.

## 2. Cost control — obligatoriu înainte de compute

- [ ] Creează buget lunar pentru proiect.
- [ ] Configurează alerte la 50%, 75%, 90% și 100% din buget.
- [ ] Adaugă alertă forecasted spend la 100%.
- [ ] Trimite notificările către owner și echipa cloud, nu doar către junior.
- [ ] Opțional: publică notificările într-un Pub/Sub topic pentru automatizare.
- [ ] Documentează faptul că o alertă standard de buget nu oprește automat cheltuielile.
- [ ] Verifică quotas pentru Vertex AI, Cloud Build, Cloud Run și BigQuery.
- [ ] Nu porni notebook-uri sau endpoint-uri 24/7 fără auto-shutdown/scaling și aprobarea costului.

Referință: [Google Cloud budgets and alerts](https://cloud.google.com/billing/docs/how-to/budgets).

## 3. API-uri de activat

### Obligatorii

- [ ] Service Usage — `serviceusage.googleapis.com`
- [ ] Cloud Resource Manager — `cloudresourcemanager.googleapis.com`
- [ ] Identity and Access Management — `iam.googleapis.com`
- [ ] Service Account Credentials — `iamcredentials.googleapis.com`
- [ ] Security Token Service — `sts.googleapis.com`
- [ ] Cloud Storage — `storage.googleapis.com`
- [ ] Vertex AI — `aiplatform.googleapis.com`
- [ ] Artifact Registry — `artifactregistry.googleapis.com`
- [ ] Cloud Build — `cloudbuild.googleapis.com`
- [ ] Secret Manager — `secretmanager.googleapis.com`
- [ ] Cloud Logging — `logging.googleapis.com`
- [ ] Cloud Monitoring — `monitoring.googleapis.com`
- [ ] BigQuery — `bigquery.googleapis.com`
- [ ] Cloud Run Admin API — `run.googleapis.com`
- [ ] Compute Engine — `compute.googleapis.com`, necesar pentru anumite runtime-uri și operații Vertex.

Notă de nomenclatură: unele pagini Google Cloud actuale pot redirecționa documentația Vertex AI
către denumirea „Gemini Enterprise Agent Platform”. Pentru acest proiect, serviciul ML gestionat
și API-ul folosit în configurație rămân identificate prin `aiplatform.googleapis.com`; juniorul
trebuie să urmeze denumirea afișată în tenantul companiei și să nu activeze servicii generative
suplimentare care nu sunt în această listă.

### Opționale, doar dacă sunt folosite

- [ ] Vertex AI Workbench / Notebooks.
- [ ] Cloud KMS pentru customer-managed encryption keys.
- [ ] Container Scanning / Container Analysis pentru vulnerability scanning.
- [ ] Data Catalog/Dataplex și Data Lineage pentru catalogare și lineage enterprise.
- [ ] Pub/Sub pentru notificări de buget sau evenimente.
- [ ] Cloud Scheduler dacă apar execuții recurente aprobate.
- [ ] Sensitive Data Protection pentru scanarea viitoare a datelor nesintetice.

Exemplu de bootstrap din Cloud Shell, după setarea proiectului:

```bash
gcloud config set project PROJECT_ID
gcloud config set ai/region europe-west4

gcloud services enable \
  serviceusage.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  storage.googleapis.com \
  aiplatform.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  bigquery.googleapis.com \
  run.googleapis.com \
  compute.googleapis.com
```

## 4. Service accounts

Creează service accounts separate. Nu folosi service account-ul Compute Engine default.

### `sa-prostate-cloudbuild`

**Scop:** CI/CD, teste, build și push de containere; poate porni pipeline-ul aprobat.

Acces minim recomandat:

- Artifact Registry Writer pe repository-ul Docker.
- Cloud Build Builder/permisiunile necesare build-ului conform configurației organizației.
- Storage Object Admin numai pe bucket-ul de build logs/staging necesar.
- Vertex AI User numai dacă build-ul pornește pipeline-uri.
- Service Account User numai pe `sa-prostate-pipeline` și `sa-prostate-serving`.
- Logs Writer.

### `sa-prostate-pipeline`

**Scop:** Vertex AI Pipelines și Custom Jobs pentru generate, validate, EDA și train.

Acces minim recomandat:

- Vertex AI User — `roles/aiplatform.user`.
- Artifact Registry Reader — `roles/artifactregistry.reader`.
- Storage Object Viewer pe `raw` și `releases`.
- Storage Object Admin pe `curated`, `vertex-pipeline-root` și `model-artifacts`.
- BigQuery Job User la nivel de proiect.
- BigQuery Data Editor numai pe dataset-ul de development.
- Secret Manager Secret Accessor numai pe secretele strict necesare.
- Logs Writer și Monitoring Metric Writer, dacă runtime-ul nu primește deja accesul necesar prin serviciul gestionat.

### `sa-prostate-serving`

**Scop:** Vertex AI Endpoint sau Cloud Run prediction API, dacă este aprobat.

Acces minim recomandat:

- Artifact Registry Reader.
- Storage Object Viewer numai pe model artifacts aprobate.
- Secret Manager Secret Accessor numai pe secretele necesare.
- Logging/Monitoring write.
- Fără write pe raw, curated sau certified releases.

### `sa-prostate-dashboard`

**Scop:** dashboard-ul privat din Cloud Run.

Acces minim recomandat:

- BigQuery Job User.
- BigQuery Data Viewer numai pe dataset/view-urile aprobate.
- Storage Object Viewer numai dacă dashboard-ul citește direct artefacte.
- Secret Manager Secret Accessor numai pe secrete specifice.

### Reguli IAM

- [ ] Niciun service account nu are `Owner` sau `Editor`.
- [ ] Rolurile Storage sunt acordate pe bucket, nu pe întreg proiectul, unde este posibil.
- [ ] Rolurile BigQuery Data sunt acordate pe dataset.
- [ ] Secret Accessor este acordat pe secret individual.
- [ ] Service Account User este acordat numai pentru service account-ul pe care principalul trebuie să îl poată impersona.
- [ ] Service-agent roles generate automat de Google nu se acordă oamenilor sau service accounts obișnuite.
- [ ] Exportă IAM policy înainte și după configurare pentru review.

## 5. Cloud Storage buckets

Numele bucket-urilor trebuie să fie global unice. Convenție recomandată:

| Bucket | Conținut | Writer | Retenție/lifecycle |
|---|---|---|---|
| `gs://PROJECT_ID-prostate-raw-dev` | inputuri sintetice și config snapshots | pipeline/admin | fără ștergere automată inițială |
| `gs://PROJECT_ID-prostate-curated-dev` | gold temporar, rapoarte și EDA per run | pipeline | lifecycle pentru run-uri superseded după aprobarea ownerului |
| `gs://PROJECT_ID-prostate-releases-dev` | release-uri certificate immutable | release pipeline/admin | soft delete extins; fără lifecycle delete |
| `gs://PROJECT_ID-prostate-vertex-dev` | Vertex pipeline root și job artifacts | pipeline | ștergere pentru staging vechi, de exemplu 30–90 zile |
| `gs://PROJECT_ID-prostate-models-dev` | model artifacts și evaluation bundles | pipeline; serving read-only | versionare prin model/run ID |
| `gs://PROJECT_ID-prostate-build-logs-dev` | logs pentru Cloud Build cu custom SA | Cloud Build | lifecycle conform policy, de exemplu 90 zile |

### Setări obligatorii pentru fiecare bucket

- [ ] Location conform deciziei regionale; recomandat aceeași regiune cu Vertex AI.
- [ ] Uniform bucket-level access: activat.
- [ ] Public access prevention: `enforced`.
- [ ] Nicio intrare IAM `allUsers` sau `allAuthenticatedUsers`.
- [ ] Labels: `application`, `environment`, `owner`, `data-classification`.
- [ ] Soft delete configurat conform clasei bucket-ului; Google Cloud folosește șapte zile implicit dacă nu este schimbat.
- [ ] Lifecycle configurat numai pentru staging/logs, nu pentru certified releases.
- [ ] Encryption Google-managed pentru demo; CMEK numai dacă este cerut de security.
- [ ] Data Access audit logs activate pentru Storage, ținând cont de costul logurilor.
- [ ] CORS dezactivat dacă nu există un browser use case aprobat.

Nu activa Bucket Lock/retention lock ireversibil fără review. Pentru release-uri, începe cu soft delete și un proces de promovare; retention lock poate fi introdus după aprobarea politicii de retenție.

Referințe: [uniform bucket-level access](https://cloud.google.com/storage/docs/uniform-bucket-level-access), [public access prevention](https://cloud.google.com/storage/docs/public-access-prevention), [soft delete](https://cloud.google.com/storage/docs/soft-delete).

## 6. Ce se migrează și ce nu

### Se migrează

- [ ] Release-ul certificat selectat, cu `analytical_dataset`, `qa_evidence`, `archives`, manifest și checksums.
- [ ] Config snapshots și rule versions asociate release-ului.
- [ ] Rapoarte și EDA regenerate din același release.
- [ ] Model artifacts serializate și evaluation bundle după implementarea lor.
- [ ] Raw Synthea numai dacă este necesar și confirmat ca sintetic.

### Nu se migrează ca artefact oficial

- `.git/`
- `.venv/`, `.release-venv/`, `.uv-cache/`
- `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`
- `.test-work/`
- fișiere locale temporare și editor settings
- `data/gold` și `data/reports` vechi ca source of truth
- vechiul dashboard cu valorile 1.691/590
- secrete, token-uri, credential files sau service-account keys

Snapshot-ul v2.1 istoric are 1.700 inițieri în 90 zile și 581 gap-uri; aceste valori nu sunt
sursa v2.2. Pentru migrare se încarcă numai candidatul v2.2 sigilat, după verificarea manifestului,
checksum-urilor și aprobării umane aplicabile, astfel încât toate rapoartele și modelele să indice
exact același release.

### Structură obiecte recomandată

```text
gs://...-releases-dev/
  dataset_version=<VERSION>/
    analytical_dataset/
    qa_evidence/
    archives/
    RELEASE_DECISION.md
    release_manifest.json
    CHECKSUMS.sha256

gs://...-curated-dev/
  run_id=<VERTEX_PIPELINE_JOB_ID>/
    gold/
    reports/
    eda/
    run_manifest.json
```

Nu folosi un folder generic `latest` ca singura referință. Păstrează versiunea immutable și, dacă este necesar, un manifest mic `promoted.json` care indică versiunea aprobată.

## 7. Artifact Registry

- [ ] Creează repository Docker regional: `prostate-journey-dev`.
- [ ] Location identică cu Vertex AI, dacă este disponibilă.
- [ ] Activează vulnerability scanning dacă politica/licența proiectului permite.
- [ ] Activează immutable tags sau folosește obligatoriu image digest în pipeline.
- [ ] Cloud Build primește Writer.
- [ ] Pipeline și serving primesc Reader.
- [ ] Configurează cleanup numai pentru imagini netagged; păstrează imaginile asociate release-urilor.

Naming recomandat:

```text
europe-west4-docker.pkg.dev/PROJECT_ID/prostate-journey-dev/pipeline:<GIT_SHA>
europe-west4-docker.pkg.dev/PROJECT_ID/prostate-journey-dev/serving:<MODEL_VERSION>
europe-west4-docker.pkg.dev/PROJECT_ID/prostate-journey-dev/dashboard:<GIT_SHA>
```

Nu folosi numai tag-ul `latest`. Salvează digest-ul imaginii în manifestul fiecărui run.

Referință: [Artifact Registry repository setup](https://cloud.google.com/artifact-registry/docs/repositories/create-repos).

## 8. BigQuery

- [ ] Creează dataset regional `prostate_analytics_dev`.
- [ ] Creează dataset separat `prostate_monitoring_dev` pentru pipeline/model quality history.
- [ ] Încarcă tabelele Parquet din release-ul certificat sau creează proces explicit de load.
- [ ] Adaugă coloane tehnice în tabelele publicate:

```text
dataset_version
source_release_uri
generation_commit
analysis_commit
pipeline_run_id
loaded_at_utc
synthetic_data_flag
```

- [ ] Creează views executive numai peste versiunea promovată.
- [ ] Nu permite dashboard-ului să selecteze automat un amestec de versiuni.
- [ ] Configurează table/dataset expiration numai pentru staging, nu pentru release data.
- [ ] Aplică dataset-level IAM.
- [ ] Testează reconcilierea row count și hash/fingerprint între Parquet și BigQuery.

Pentru dashboard și analize interactive, BigQuery este mai potrivit decât citirea repetată a CSV-urilor din bucket.

## 9. GitHub și CI/CD

Alege una dintre variante, nu ambele fără motiv:

### Varianta recomandată A — Cloud Build GitHub App

- [ ] Conectează repository-ul GitHub prin Cloud Build GitHub App.
- [ ] Creează trigger PR pentru teste fără deployment.
- [ ] Creează trigger pe branch-ul de development pentru build și pipeline dev.
- [ ] Creează trigger de release pe tag, cu approval manual înainte de promovare/deployment.
- [ ] Folosește `sa-prostate-cloudbuild`, nu contul default.

### Varianta B — GitHub Actions

- [ ] Creează Workload Identity Pool și OIDC provider pentru GitHub.
- [ ] Restricționează provider-ul la organization/repository/branch aprobate.
- [ ] Permite impersonarea numai a service account-ului CI.
- [ ] Nu crea secret GitHub cu service-account JSON key.

Google recomandă Workload Identity Federation pentru deployment pipelines deoarece folosește credențiale scurte în loc de chei persistente: [official WIF deployment-pipeline guidance](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines).

### Pipeline CI minim

La pull request:

1. instalare din dependency lock;
2. Ruff;
3. MyPy după remedierea configurației;
4. pytest;
5. quick synthetic generation;
6. DQ/readiness smoke checks;
7. verificare link-uri și documentație;
8. scanare container/dependențe.

La merge în `dev`:

1. toate verificările PR;
2. build container;
3. push cu commit SHA și digest;
4. submit Vertex AI Pipeline dev;
5. publicare rapoarte dev;
6. notificare cu run ID și rezultate.

La tag de release:

1. approval manual;
2. full 10.000-patient run;
3. exact reproducibility check;
4. toate audit gates;
5. immutable release în bucket;
6. BigQuery reconciliation;
7. model evaluation gate;
8. Model Registry version;
9. deployment numai dacă este aprobat.

Referință: [Cloud Build GitHub triggers](https://cloud.google.com/build/docs/automating-builds/github/build-repos-from-github).

## 10. Vertex AI Pipelines

- [ ] Configurează pipeline root în `gs://PROJECT_ID-prostate-vertex-dev/pipeline-root/`.
- [ ] Rulează pipeline-ul cu `sa-prostate-pipeline`.
- [ ] Container image-ul trebuie referit prin digest sau commit SHA.
- [ ] Pipeline parameters trebuie să includă:

```text
project_id
region
environment
git_commit
container_digest
scenario_config_uri
random_seed
target_cohort_size
input_uri
working_output_uri
release_output_uri
bigquery_dataset
promote_release=false
deploy_model=false
```

### Componente recomandate

1. `validate_config`
2. `generate_synthetic_tables`
3. `verify_exact_reproducibility`
4. `run_data_quality`
5. `run_readiness_audit`
6. `run_adversarial_audit`
7. `export_csv_parquet_duckdb`
8. `reconcile_artifacts`
9. `publish_certified_release`
10. `load_bigquery`
11. `run_eda`
12. `build_model_features`
13. `train_models`
14. `evaluate_models`
15. `register_approved_model`
16. `publish_dashboard_inputs`

- [ ] Fiecare componentă scrie artefacte într-un `run_id` separat.
- [ ] Promovarea release-ului este fail-closed: orice P0/P1, mismatch, test sau lint failure oprește promovarea.
- [ ] Înregistrează input URI, output URI, dataset version, code commit, image digest, config hash, seed și metrici.
- [ ] Adaugă retries numai pentru erori tranzitorii, nu pentru audit failures.
- [ ] Configurează timeout și machine type explicit pentru fiecare job.

Vertex AI Pipelines folosește Cloud Storage pentru artefactele run-urilor, deci staging bucket-ul trebuie creat înaintea pipeline-ului: [Vertex AI Pipelines guidance](https://cloud.google.com/vertex-ai/docs/pipelines/introduction).

## 11. Training și Model Registry

Codul actual calculează modele logistic direct în scriptul EDA, dar nu produce încă un model deployabil complet. Înainte de Vertex Model Registry trebuie implementate:

- [ ] artefact serializat pentru encoder, categorii, mediane, scalări și coeficienți;
- [ ] model metadata și feature schema version;
- [ ] input/output prediction contract;
- [ ] unit tests pentru serializare și prediction parity;
- [ ] model evaluation bundle;
- [ ] baseline și approval criteria;
- [ ] prediction container sau format suportat de un prebuilt serving container.

### Model Registry

- [ ] Creează model resource `prostate-non-initiation-90d` numai pentru modelul aprobat.
- [ ] Fiecare training run aprobat devine o versiune nouă.
- [ ] Adaugă labels și metadata:

```text
environment=dev
dataset_version=<version>
git_commit=<sha>
target=non_initiated_within_90_days
data_classification=synthetic
clinical_use=false
```

- [ ] Folosește aliases controlate: `candidate`, `approved-dev`, eventual `champion` numai după review.
- [ ] Atașează model card, metrici, calibration, subgroup checks și prohibited uses.
- [ ] Nu înregistra drept „approved” modelele de discontinuation/switch/restart actuale; performanța lor este prea slabă pentru un deployment justificat.

## 12. Batch prediction versus endpoint online

### Recomandare pentru proiectul actual: Batch Prediction

- [ ] Input Parquet/BigQuery din versiunea aprobată.
- [ ] Output într-un prefix nou per job/run.
- [ ] Prediction output include model version, dataset version și timestamp.
- [ ] Rezultatele sunt pentru demonstrație sintetică și nu declanșează acțiuni clinice.

Batch este suficient pentru dashboard, raport și prezentare și evită un endpoint cu compute pornit permanent.

### Endpoint online — numai dacă este aprobat

Înainte de creare trebuie să existe:

- [ ] use case live și owner;
- [ ] prediction schema;
- [ ] serialized model + serving container;
- [ ] authentication design;
- [ ] latency/load target;
- [ ] cost estimate;
- [ ] monitoring și rollback;
- [ ] human-review/prohibited-use policy.

Dacă este aprobat:

- [ ] creează endpoint privat regional;
- [ ] deployează modelul prin custom container din Artifact Registry;
- [ ] folosește `sa-prostate-serving`;
- [ ] activează request/response logging numai după verificarea conținutului și a politicii de date;
- [ ] configurează machine type și replicas pe baza unui load test;
- [ ] trimite inițial 100% trafic către o singură versiune dev;
- [ ] rulează smoke test, schema test și prediction-parity test;
- [ ] documentează endpoint ID și procedura de undeploy;
- [ ] undeploy după demo dacă nu există utilizare continuă.

Custom inference containers trebuie publicate în Artifact Registry și să respecte contractele de health/predict ale Vertex AI: [Vertex AI custom container guidance](https://cloud.google.com/vertex-ai/docs/predictions/use-custom-container).

## 13. Dashboard și API

- [ ] Containerizează dashboard-ul/API-ul separat de training.
- [ ] Deploy în Cloud Run, regional, cu `sa-prostate-dashboard`.
- [ ] `Allow unauthenticated`: **dezactivat**.
- [ ] Acordă Cloud Run Invoker numai grupului de demo/stakeholderi.
- [ ] Dashboard-ul citește view-urile BigQuery ale release-ului promovat.
- [ ] Footer vizibil cu dataset version, analysis commit și disclaimer sintetic.
- [ ] Adaugă `/health` și un endpoint/page care afișează provenance.
- [ ] Configurează max instances și concurrency pentru cost control.
- [ ] Nu folosi bucket website public; intră în conflict cu public access prevention.

## 14. Secrets și configurare

- [ ] Secretele sunt stocate în Secret Manager, nu în GitHub, YAML, `.env` comis sau bucket.
- [ ] Pentru acest proiect ar trebui să existe foarte puține secrete; autentificarea către GCP folosește service identity.
- [ ] Configurile non-secrete rămân versionate în Git și sunt copiate în manifestul release-ului.
- [ ] Secret Accessor se acordă pe secret individual și numai runtime-ului care îl folosește.
- [ ] Activează rotation unde secretul o permite.

Referință: [Secret Manager least-privilege access](https://cloud.google.com/secret-manager/docs/access-control).

## 15. Logging, monitoring și audit

- [ ] Activează Admin Activity logs — sunt disponibile implicit.
- [ ] Activează Data Access logs pentru Storage, BigQuery, Secret Manager și Vertex AI conform policy și bugetului.
- [ ] Configurează log retention și, dacă este cerut, un log sink central.
- [ ] Creează dashboard Cloud Monitoring pentru:

```text
pipeline success/failure
pipeline duration
DQ/readiness/adversarial result
rows and schema by release
model metric by version
batch prediction failures
endpoint latency/error rate if deployed
Cloud Run errors/latency
monthly cost trend
```

- [ ] Creează alerte pentru pipeline failure, release gate failure, endpoint 5xx, Cloud Run 5xx și budget thresholds.
- [ ] Nu loga row-level patient records sau prediction payloads fără review.

Data Access logs nu sunt activate implicit pentru toate serviciile și pot genera costuri, deci trebuie configurate explicit și bugetate: [Cloud Audit Logs guidance](https://cloud.google.com/logging/docs/audit/configure-data-access).

## 16. Security baseline pentru date sintetice

- [ ] Public access prevention peste tot.
- [ ] Least privilege și IAM prin grupuri.
- [ ] Fără service-account keys.
- [ ] Workload Identity Federation pentru CI extern.
- [ ] Private Cloud Run și, dacă există, private/restricted Vertex endpoint.
- [ ] Vulnerability scanning pentru containere.
- [ ] Dependency și secret scanning în CI.
- [ ] Audit logs și alerting.
- [ ] Backup/soft-delete pentru release-uri.
- [ ] Fără date sensibile în resource names, labels sau container descriptions.

### Dacă apar date reale în viitor

Oprește migrarea și deschide un workstream separat. Sunt necesare cel puțin:

- proiect separat și data classification nouă;
- privacy, legal și security approval;
- data-processing agreements și cerințe de rezidență;
- threat model și access review;
- VPC Service Controls/private networking unde este cerut;
- CMEK dacă este cerut;
- Sensitive Data Protection/DLP;
- politici de retenție și ștergere;
- audit și break-glass access;
- validare clinică și guvernanța modelului.

Faptul că pipeline-ul a fost construit pe date sintetice nu autorizează automat procesarea datelor medicale reale.

## 17. Teste de acceptanță

Juniorul trebuie să demonstreze următoarele fără rol `Owner`:

- [ ] Toate API-urile aprobate sunt enabled.
- [ ] Bucket-urile au uniform access și public access prevention.
- [ ] Niciun bucket nu are `allUsers`/`allAuthenticatedUsers`.
- [ ] Service accounts nu au roluri basic `Owner`/`Editor`.
- [ ] CI poate build-ui și push-ui o imagine prin identitate federată/managed identity.
- [ ] Pipeline SA poate citi raw și scrie numai în bucket-urile sale.
- [ ] Serving SA nu poate modifica raw, curated sau releases.
- [ ] Un Vertex Custom Job de smoke test rulează cu service account-ul corect.
- [ ] Un pipeline minimal scrie un artefact în pipeline root.
- [ ] Release-ul uploadat trece verificarea `CHECKSUMS.sha256`.
- [ ] BigQuery row counts se reconciliază cu Parquet.
- [ ] Batch prediction de smoke test produce output versionat.
- [ ] Dashboard-ul Cloud Run este accesibil numai grupului aprobat.
- [ ] Budget alerts și monitoring alerts au destinatarii corecți.
- [ ] Audit log-ul arată upload, pipeline run și BigQuery access.

## 18. Ce trebuie să trimită juniorul la final

Un singur handoff document sau pull request cu:

- [ ] project ID și number;
- [ ] region și justificare;
- [ ] lista API-urilor activate;
- [ ] lista service accounts și scopul fiecăruia;
- [ ] IAM matrix pe proiect/bucket/dataset/secret;
- [ ] bucket names și configurația fiecăruia;
- [ ] Artifact Registry URI;
- [ ] BigQuery datasets și views;
- [ ] Vertex pipeline root și sample pipeline job ID;
- [ ] Model Registry model/version, dacă există;
- [ ] batch prediction job ID;
- [ ] endpoint ID numai dacă a fost aprobat;
- [ ] Cloud Build connection și trigger names;
- [ ] Cloud Run service URL și grupul cu access;
- [ ] budget și alert recipients;
- [ ] link-uri către logs și monitoring dashboard;
- [ ] Terraform plan/state location sau lista exactă de pași manuali;
- [ ] rezultatele testelor de acceptanță;
- [ ] lista deciziilor/blocajelor rămase.

Handoff-ul trebuie să confirme explicit:

```text
No public resources.
No service-account keys created.
No real patient data uploaded.
No Owner/Editor roles granted to runtime identities.
No online endpoint left running without owner and budget approval.
```

## Ordinea practică recomandată

1. Admin: project, billing, folder, groups și region decision.
2. Junior prin Terraform PR: APIs, labels, service accounts și IAM proposal.
3. Senior review pentru IAM.
4. Junior: buckets, Artifact Registry, BigQuery și budget alerts.
5. Junior: GitHub/Cloud Build connection fără chei.
6. Echipa proiectului: Dockerfile, dependency lock și cloud path support în cod.
7. Junior + echipa: Vertex smoke job și pipeline minimal.
8. Echipa: release nou și upload cu checksum verification.
9. Echipa: pipeline complet și BigQuery reconciliation.
10. Echipa data science: model serialization/evaluation și Model Registry.
11. Batch prediction pentru demo.
12. Cloud Run dashboard privat.
13. Endpoint online doar după use case, cost și approval.
14. Security/IAM/acceptance review și handoff final.

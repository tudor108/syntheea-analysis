# Runbook

> **SYNTHETIC DEMO DATA – NOT REAL BAYER OR CLINICAL DATA**

## Synthea validation

The pinned local clone was inspected at commit `7e08387c68a7f0e21d13076609a159fd473fc902`. Its README requires JDK 17+, `build.gradle` sets source compatibility 17, and the Windows wrapper is `run_synthea.bat`. CSV is off by default and is enabled with `--exporter.csv.export=true`; `-p`, `-s`, and final state arguments control population, seed and geography.

```powershell
java -version
cd external\synthea
.\gradlew.bat build check
.\run_synthea.bat -p 25000 -s 42 --exporter.csv.export=true --exporter.fhir.export=false Massachusetts
Copy-Item .\output\csv\*.csv ..\..\data\raw\synthea -Force
```

The supplied `scripts/run_synthea.ps1` performs these steps. For existing exports, copy at least `patients.csv` to `data/raw/synthea`. With no CSV, the logged offline fallback supports pipeline/tests but does not claim an actual Synthea execution.

The script also repairs a missing/stale `JAVA_HOME` for its own process by deriving the JDK root from the active `java.exe`; it does not persistently alter the user's environment.

## Recovery

Run `validate` independently after modifying files. Critical failures identify the rule in all three DQ formats. Use `scripts/clean_outputs.ps1` to remove only derived outputs; it preserves raw Synthea data. Re-run with identical config/seed to reproduce data hashes (metadata timestamps naturally differ).

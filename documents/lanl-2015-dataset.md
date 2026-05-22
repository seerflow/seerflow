# The LANL 2015 Cyber-Security Events Dataset

Reference notes on the **"Comprehensive, Multi-Source Cyber-Security Events"**
dataset that Seerflow uses as its accuracy benchmark. For *how to run* Seerflow
against it, see [testing-seerflow-against-lanl.md](./testing-seerflow-against-lanl.md).

---

## What it is

A real, de-identified record of activity on Los Alamos National Laboratory's
**internal enterprise network**, captured over **58 consecutive days**. It is
one of the few public datasets that pairs large-scale, multi-source enterprise
logs with **ground-truth labels** for a real red-team penetration exercise —
which is exactly what an intrusion-detection system needs to be measured
against. Authentication, process, network-flow, and DNS events are all present,
time-aligned, and cross-referenced by a unified set of anonymized entity IDs.

- **Author:** Alexander D. Kent (2015)
- **DOI:** [10.17021/1179829](https://doi.org/10.17021/1179829)
- **Source:** <https://csr.lanl.gov/data/cyber1/>
- **License:** CC0 1.0 (public domain dedication)

---

## Scale

| Property | Value |
|----------|-------|
| Collection period | 58 consecutive days |
| Total events | **1,648,275,307** |
| Users | 12,425 |
| Computers | 17,684 |
| Processes | 62,974 |
| Compressed size | ~12 GB |

---

## Data files & schemas

Five gzip-compressed CSV files. Field lists below are the dataset's own header
definitions, verbatim.

| File | Size | Fields |
|------|------|--------|
| `auth.txt.gz` | 7.2 GB | `time, source user@domain, destination user@domain, source computer, destination computer, authentication type, logon type, authentication orientation, success/failure` |
| `proc.txt.gz` | 2.2 GB | `time, user@domain, computer, process name, start/end` |
| `flows.txt.gz` | 1.1 GB | `time, duration, source computer, source port, destination computer, destination port, protocol, packet count, byte count` |
| `dns.txt.gz` | 177 MB | `time, source computer, computer resolved` |
| `redteam.txt.gz` | 4.8 KB | `time, user@domain, source computer, destination computer` |

### auth — authentication events
The bulk of the data. Each row is one authentication (logon, logoff, TGS/TGT,
etc.) between a source and destination user/computer, with the auth type
(Kerberos, NTLM, …), logon type (Network, Interactive, …), orientation
(LogOn/LogOff/TGS/…), and a `Success`/`Fail` outcome. Failed/lateral auth
patterns are the primary signal for credential attacks.

### proc — process start/stop events
Process lifecycle per user and host: a `process name` and whether the row marks
a `Start` or `End`. Useful for execution-based detection.

### flows — network flow events
NetFlow-style records: connection `duration`, source/destination computer and
port, `protocol`, and packet/byte counts. Drives volumetric and beaconing
signals.

### dns — DNS lookup events
Minimal: which `source computer` resolved which `computer`. Supports
domain/lookup correlation.

### redteam — ground truth
The label file. A tiny set (~749 known red-team authentication events, as
reported in the literature) marking authentications that were part of the
actual red-team compromise. Detection is scored by matching alerts against
these records within a time/entity window. **This is what makes the dataset a
benchmark and not just a log dump.**

---

## De-identification

Entities are anonymized as a **unified set across all files** — a user token
(e.g. `U24@DOM1`) or computer token (e.g. `C17693`) refers to the same entity
everywhere it appears, so cross-source correlation still works. Exceptions left
unmasked for usability:

- System accounts (`SYSTEM`, `Local Service`, etc.) and well-known
  administrators.
- Standard ports (e.g. `80`, `443`).

Everything else — users, computers, processes, non-standard ports, times — is
de-identified.

---

## Time format

> "All data starts with a time epoch of 1 using a time resolution of 1 second."

Times are **relative integer seconds** (starting at 1), not Unix timestamps.
Seerflow's harness rebases these decades-irrelevant values onto a fixed
deterministic epoch before replay (see `REPLAY_EPOCH_NS` in
`src/seerflow/lanl/validator.py`).

---

## How Seerflow consumes it

- The fetcher (`python -m seerflow.lanl.fetch`) downloads each `*.txt.gz`,
  SHA-256-verifies it, and unpacks it into the validator's expected layout:
  `auth.csv`, `proc.csv`, `flows.csv`, `redteam.csv` (and optional `dns.csv`).
- The parser (`src/seerflow/lanl/parser.py`) maps each row to the field schema
  above.
- The harness replays records through the full detection stack and scores
  alerts against `redteam.csv`.

See **[testing-seerflow-against-lanl.md](./testing-seerflow-against-lanl.md)**
for the full step-by-step workflow.

---

## Related LANL datasets (not used here)

LANL has published several cyber datasets; Seerflow uses **only** the 2015
comprehensive set above. For context:

- **2014 — "User-Computer Authentication Associations in Time":** auth events
  only, ~9 months. Narrower.
- **2017 — "Unified Host and Network Data Set":** Windows host logs + network
  flows, different schema and format.

---

## References

- LANL dataset page: <https://csr.lanl.gov/data/cyber1/>
- Kent, A. D. (2015), DOI [10.17021/1179829](https://doi.org/10.17021/1179829)
- A. D. Kent, "Cyber security data sources for dynamic network research" (2015) — methodology behind the release.

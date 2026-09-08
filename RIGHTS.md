# Rights register

Dataset permissions, licenses, attribution obligations, and redistribution decisions. Every row states what has been confirmed and by whom. A row marked pending is not approval.

## Development pathway

| Item | State | Next action |
|---|---|---|
| Approved development pathway (Government / participant / open collaboration) | **Pending** | Event terms require the team to select one before substantive development. Confirm with organizers, then record the choice and date here. |
| Named individuals for roles A, B, and C | **Pending** | AGENTS.md assigns responsibilities to role labels only. |

## AI-assistant processing

| Item | State | Basis |
|---|---|---|
| Sponsor Counter-UAS scenario package may be read by AI coding assistants | **Asserted by team, 2026-09-08** | Stated in session by the repository owner. |

Still to record: whether the grant covers file contents, screenshots, and raw logs; whether it covers cloud-hosted assistants; the exact source of the grant; and any expiry. Until those are written here, keep sponsor files in `data/` and out of commits, issues, and public hosting.

## Datasets

| Source | License | Obligation | Redistribution decision |
|---|---|---|---|
| Sponsor Counter-UAS scenario package | Event terms | Handling rules published on the challenge site | Local `data/` only. Never committed, never published. |
| [ADS-B.lol](https://www.adsb.lol/docs/open-data/api/) | ODbL | Attribution required; share-alike applies to derived databases | Saved snapshot in `data/`. Attribution appears in the data card and the dashboard's about panel. |
| [DroneRF](https://data.mendeley.com/datasets/f4c2b4n755/1) | CC BY 4.0 | Attribution required | Snapshot in `data/`. Derived features and model versions may be described; raw recordings are not redistributed. |
| [Drone Trajectory Data](https://www.kaggle.com/datasets/shawnwuplus/drone-trajectory-data) | **Unclear** | Unresolved | Local use only. Do not redistribute or commit until confirmed. |
| Aerial Object Detection | Not applicable | Not applicable | **Cut.** Files and annotations are unavailable, failing the first condition of the Phase 0 decision gate. |
| [Cursor-on-Target](https://quicksearch.dla.mil/qsDocDetails.aspx?ident_number=284928) | Format specification | Cite the specification | An export format, not a dataset. |
| [BlueSTAQ UDL SDK](https://github.com/Bluestaq/udl-python-sdk) | Repository license | Credentials never committed | **Cut from the critical path.** Optional adapter only. |

## Standing rules

- Sponsor data, credentials, and restricted artifacts stay in `data/` (gitignored) and never reach public repositories, cloud hosting, or unauthorized services.
- Public availability does not establish redistribution permission.
- Secrets come from environment variables and never enter logs or source control.
- Reviewed synthetic fixtures under `fixtures/synthetic/` are the only data committed to this repository.

# ResumeRanker

ResumeRanker is an explainable, local-first screening service for PDF, DOCX, and TXT resumes. It extracts job requirements, scores evidence by resume section, supports multi-role job descriptions, and can optionally evaluate a bounded shortlist through a Groq-compatible model.

![ResumeRanker FastAPI documentation showing the standalone backend routes](docs/assets/screenshots/resumeranker-api-docs.png)

_The standalone FastAPI surface running locally; the richer TypeScript screen is intended for its host workflow._

## Architecture

```text
Host UI or API client
        |
Host/CORS allowlists -> body limit -> bearer authentication
        |
        v
approved filesystem root -> bounded document parsing -> deterministic scoring
                                                    |
                                                    +-> opt-in LLM shortlist
        |
        v
ranked candidates, matched/missing skills, section scores, explanations
```

`resumeranker_server.py` contains the FastAPI boundary, parsers, requirement extraction, ranking, and provider integration. `ResumeRankerWindow.tsx` is a host-workflow UI component, not a standalone packaged frontend.

## Ranking model

Every document is scored locally first. TF-IDF similarity is combined with required/preferred skill coverage and separate project, experience, skills, and certification evidence. Demonstrated project use is weighted more strongly than a keyword listed only in a skills section. If the JD does not request certifications or the resume lacks relevant experience, weights are redistributed rather than silently penalising the candidate. Outputs are decision support, not an automated hiring decision.

## Secure deployment modes

Production is the default. Every endpoint except `GET /status`, including `/docs`, `/packages`, local file operations, and shutdown, requires a bearer token. `RESUMERANKER_API_TOKEN` must be at least 32 characters or protected routes return generic `503` responses. Token checks are constant-time. Browser origins and Host headers are explicit allowlists; wildcards fail readiness. JSON request bodies, scanned files, aggregate folder bytes, scan counts, JD entries, and LLM candidates are bounded.

`RESUMERANKER_MODE=demo` is the only unauthenticated mode. It works only with a loopback listener and fails closed on a network address. Filesystem features remain disabled until an approved root is configured, and provider calls remain disabled until separately opted in.

## Setup

Requires Python 3.12 or 3.13.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

Create a dedicated resume workspace and set its canonical path:

```bash
export RESUMERANKER_APPROVED_ROOT=/absolute/path/to/review-workspace
```

Explicit local demo:

```bash
RESUMERANKER_MODE=demo python resumeranker_server.py
```

Production-style local run:

```bash
export RESUMERANKER_API_TOKEN='replace-with-a-random-32-plus-character-secret'
python resumeranker_server.py
curl -H "Authorization: Bearer $RESUMERANKER_API_TOKEN" http://127.0.0.1:8892/packages
```

## API

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/status` | Public liveness/readiness without secret or package details |
| `GET` | `/packages` | Authenticated dependency inventory |
| `POST` | `/scan_folder` | List supported files under the approved root |
| `POST` | `/analyze_jd` | Extract requirements and role sections |
| `POST` | `/rank` | Rank one resume folder against one JD |
| `POST` | `/rank_multi` | Rank against a bounded JD list |
| `POST` | `/extract_text` | Extract text from an approved document |
| `POST` | `/open_file` | Open an approved local document |
| `POST` | `/shutdown` | Demo-only, loopback-only, explicitly enabled legacy control |

`top_n` is capped at 20. Paths are canonicalised and must remain inside `RESUMERANKER_APPROVED_ROOT`; symlink and sibling-prefix escapes are rejected.

## Configuration and limits

| Variable | Default | Boundary |
| --- | --- | --- |
| `RESUMERANKER_MODE` | `production` | `production` or explicit loopback `demo` |
| `RESUMERANKER_API_TOKEN` | empty | Required in production; minimum 32 characters |
| `SERVER_HOST` / `SERVER_PORT` | `127.0.0.1` / `8892` | Network binding also requires explicit exposure opt-in |
| `TRUSTED_HOSTS` | loopback hosts | Host-header allowlist; wildcard forbidden |
| `CORS_ORIGINS` | local port 3000 origins | Browser allowlist; wildcard forbidden |
| `RESUMERANKER_MAX_REQUEST_BYTES` | 1 MiB | JSON/body bound; hard maximum 10 MiB |
| `RESUMERANKER_MAX_SCAN_FILES` | 100 | Hard maximum 500 |
| `RESUMERANKER_MAX_FILE_BYTES` | 10 MiB | Hard maximum 50 MiB per document |
| `RESUMERANKER_MAX_FOLDER_BYTES` | 100 MiB | Hard maximum 500 MiB per scan |
| `RESUMERANKER_MAX_JD_ENTRIES` | 5 | Hard maximum 20 |
| `RESUMERANKER_MAX_LLM_CANDIDATES` | 5 | Hard maximum 10 |

Provider use requires all three: a request option such as `use_llm`, `RESUMERANKER_ENABLE_LLM_CALLS=true`, and `GROQ_API_KEY_1`. Candidate content may leave the machine when enabled; confirm consent, retention, and data-processing terms first.

## Testing and operations

```bash
python -m py_compile resumeranker_server.py
python -m pytest -q
```

CI runs the suite on Python 3.12 and 3.13. A deployment gate should require `/status` to report `ready: true`. Put network deployments behind TLS, rate limiting, and an identity-aware proxy; provide secrets through the platform secret manager; run with least-privilege read access to a dedicated approved root; stop production using the process supervisor's graceful signal. The shutdown route is intentionally unavailable in production.

## Threat model and limitations

Controls address unauthenticated access, missing-secret bypasses, token timing leakage, hostile Host/Origin headers, path traversal and symlink escapes, oversized inputs, scan amplification, accidental provider disclosure, and remote shutdown. The service does not include tenant isolation, malware scanning, OCR, document sandboxing, anti-bias validation, durable queues, TLS, per-subject audit logs, or a complete hiring governance workflow. Human review is required for every hiring decision.

## License

All rights reserved. See [LICENSE](LICENSE).

<!-- markdownlint-disable MD013 -->

# ResumeRanker

Local-first resume screening for technical hiring. ResumeRanker reads PDF, DOCX, and TXT resumes from a folder, extracts job requirements from a pasted or uploaded job description, and returns explainable candidate rankings based on demonstrated skills, project relevance, work experience, certifications, and optional LLM review.

The project is designed for high-signal recruiting workflows: run the deterministic scoring locally for every resume, then optionally send only shortlisted candidate summaries to a Groq/OpenAI-compatible model for deeper contextual scoring and recruiter-ready explanations.

## Why This Matters

Most resume filters overvalue keyword presence. A resume that lists "React" once in a skills section can look the same as a resume that used React in a production project. ResumeRanker separates those cases by looking at where evidence appears in the resume and by scoring project, experience, skills, and certification sections independently.

That makes the output more useful for hiring teams:

- Shortlists are explainable, not opaque.
- Strong project portfolios are not automatically buried when formal work experience is thin.
- Multi-role job descriptions can be split into role-specific requirements before ranking.
- Resume files stay on the local machine unless optional LLM features are enabled.

## What It Does

- Scans a local folder for supported resume files: `.pdf`, `.docx`, and `.txt`.
- Extracts text from resumes and job descriptions with PyMuPDF, python-docx, and plain text readers.
- Detects candidate names and common resume sections such as projects, experience, skills, education, and certifications.
- Extracts required skills, preferred skills, experience requirements, and certifications from job descriptions.
- Detects multi-role job descriptions with repeated role sections and ranks candidates separately for each role.
- Scores candidates with deterministic, section-aware logic before any LLM is used.
- Optionally uses a Groq/OpenAI-compatible chat completions endpoint for JD analysis, contextual re-ranking, and short explanations.
- Returns matched and missing required/preferred skills, section scores, similarity values, keyword coverage, and interview focus notes.
- Includes a dynamic `ResumeRankerWindow.tsx` UI intended for the host Electron workflow environment, plus a standalone FastAPI backend.

## Architecture

```text
Resume folder / JD file / pasted JD
            |
            v
   FastAPI backend: resumeranker_server.py
            |
            +--> Text extraction: PDF, DOCX, TXT
            +--> JD requirement extraction: rule-based, optional LLM
            +--> Resume section parsing: projects, experience, skills, certs
            +--> Stage 1 local scoring: deterministic scoring for all resumes
            +--> Stage 2 optional LLM scoring: shortlisted summaries only
            |
            v
   Ranked candidates with explanations and match/gap details
```

### Scoring Model

The deterministic ranking path is the default quality signal and works without network access.

| Dimension | What it measures | Implementation notes |
| --- | --- | --- |
| Projects | Domain relevance, required/preferred skill use, complexity signals | Combines domain clusters, skill matches, and project complexity indicators. |
| Experience | Role relevance and relevant technology usage | Gives stronger weight to software engineering indicators than non-development roles. |
| Skills | Whether required/preferred skills are demonstrated or only listed | Skills found in projects score higher than skills found only in a skills list. |
| Certifications | Certification overlap with the JD | Used when certifications are present in the extracted JD requirements. |

Base weighting favors projects and demonstrated skills. When a JD does not request certifications, certification weight is redistributed. When no relevant experience section is found, experience weight shifts toward projects and skills so early-career candidates with strong portfolios are treated more fairly.

## API Surface

The backend runs as a local FastAPI service.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/status` | Health check, configured port, package readiness, and LLM availability. |
| `GET` | `/packages` | Reports installed status for required Python packages. |
| `POST` | `/scan_folder` | Lists supported resume files in a local folder. |
| `POST` | `/analyze_jd` | Extracts requirements from pasted JD text or a JD file path. |
| `POST` | `/rank` | Ranks resumes against one job description. |
| `POST` | `/rank_multi` | Ranks the same resume set against multiple job descriptions. |
| `POST` | `/open_file` | Opens a resume locally after validating it is inside the selected root folder. |
| `POST` | `/extract_text` | Extracts readable text from a PDF, DOCX, or TXT file. |
| `POST` | `/shutdown` | Stops the local development server when launched by the UI workflow. |

`top_n` is capped at 20 by the backend. LLM deep evaluation shortlists up to `top_n * 4` candidates and evaluates summaries in batches of three.

## Project Structure

```text
.
|-- .github/workflows/ci.yml        # Python CI for 3.12 and 3.13
|-- .env.example                    # Local server and optional LLM configuration
|-- README.md                       # Project documentation
|-- requirements.txt                # Runtime Python dependencies
|-- requirements-dev.txt            # Test dependencies
|-- resumeranker_server.py          # FastAPI API, parsing, scoring, and LLM integration
|-- ResumeRankerWindow.tsx          # Host-app dynamic UI window
|-- ResumeRankerWindow.meta.json    # UI metadata
`-- tests/test_resumeranker_server.py
```

## Local Setup

### Requirements

- Python 3.12 or newer
- A terminal with access to the resume/JD folders you want to rank
- Optional: a Groq-compatible API key for LLM-assisted extraction and explanations

### Install

```powershell
cd C:\Users\rames\OneDrive\Documents\improves\github-upgrades\ResumeRanker
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Configure

The deterministic ranking path works without an API key. To enable LLM features, copy the example environment file and fill in the values you want to use:

```powershell
Copy-Item .env.example .env
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY_1` | Empty | Enables optional LLM calls when set. |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | OpenAI-compatible chat completions base URL. |
| `PRIMARY_MODEL` | `moonshotai/kimi-k2-instruct` in `.env.example` | Primary model for JD extraction, scoring, and explanations. |
| `FALLBACK_MODEL_1` | `llama-3.3-70b-versatile` in `.env.example` | Fallback model when the primary call fails or returns unusable output. |
| `LLM_TIMEOUT_SECONDS` | `30` | HTTP timeout for LLM calls. |
| `MAX_RETRIES` | `1` | Enables fallback explanation attempts. |
| `LLM_CALL_DELAY_SECONDS` | `8` in code | Delay between LLM calls to reduce rate-limit failures. |
| `SERVER_HOST` | `127.0.0.1` | Host for the local FastAPI server. |
| `SERVER_PORT` | `8892` | Port for the local FastAPI server. |

Note: `resumeranker_server.py` also has built-in model defaults. Values in `.env` or the shell environment take precedence.

### Run

```powershell
python resumeranker_server.py
```

You can override the port with a positional argument:

```powershell
python resumeranker_server.py 8893
```

Check the server:

```powershell
Invoke-RestMethod http://127.0.0.1:8892/status
```

## Example API Usage

Rank a folder of resumes against a pasted job description:

```powershell
$body = @{
  folder_path = "C:\path\to\resumes"
  job_description = "We need a backend engineer with Python, FastAPI, PostgreSQL, testing, and API design experience."
  use_llm = $false
  use_llm_for_jd = $false
  use_deep_eval = $false
  top_n = 5
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8892/rank `
  -ContentType "application/json" `
  -Body $body
```

For multi-role workflows, call `/analyze_jd` first to detect role sections, then submit the resulting entries to `/rank_multi`.

## Scripts And Commands

| Command | Purpose |
| --- | --- |
| `python resumeranker_server.py` | Starts the local FastAPI server on `SERVER_PORT` or `8892`. |
| `python resumeranker_server.py 8893` | Starts the server on a specific port. |
| `python -m pytest -q` | Runs the test suite. |
| `python -m pip install -r requirements.txt -r requirements-dev.txt` | Installs runtime and test dependencies. |

## Testing And CI

Install development dependencies, then run:

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

The GitHub Actions workflow runs the same pytest command on Python 3.12 and 3.13 for pushes to `main`/`master` and for pull requests.

Current test coverage includes:

- Safe local path validation for file-opening requests.
- Independent Pydantic defaults for nested LLM score models.
- Basic `/status` endpoint readiness.

## Security And Privacy

- By default, the server binds to `127.0.0.1`, keeping the API local to the machine.
- Resume scanning and deterministic scoring run locally.
- The optional LLM path sends job description excerpts, extracted requirements, candidate names, and compact resume summaries to the configured OpenAI-compatible API endpoint. Do not enable LLM features for confidential data unless that data handling is acceptable for your environment.
- `/open_file` validates that the requested file is inside the selected root folder and only opens supported resume/JD file types.
- `.env` should contain local secrets only and must not be committed.
- CORS is currently configured with `allow_origins=["*"]` to support the local workflow UI. Tighten this before exposing the server beyond local development.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `/status` is unreachable | Confirm the server is running and the port matches `SERVER_PORT` or the CLI argument. |
| `packages_ok` is false | Reinstall dependencies with `python -m pip install -r requirements.txt`. |
| JD analysis returns no skills | Try a longer JD, disable LLM to use the rule-based extractor, or manually supply requirements through the API/UI. |
| PDF or DOCX text is empty | Confirm the document contains selectable text; scanned images may not extract correctly. |
| LLM features do not run | Confirm `GROQ_API_KEY_1` is set and `/status` reports `llm_enabled: true`. |
| LLM calls are slow | The backend intentionally delays calls with `LLM_CALL_DELAY_SECONDS` to reduce rate-limit errors. |
| File opening is denied | The file must be inside the selected root folder and use `.pdf`, `.docx`, or `.txt`. |

## Roadmap And Limitations

- Add broader end-to-end tests for ranking behavior, document parsing, and multi-role JD detection.
- Add fixture-based regression tests for scoring weights and extracted requirements.
- Package the UI as a standalone app or document the host workflow integration in more detail.
- Replace permissive local-development CORS with explicit origins if the API is exposed outside localhost.
- Add OCR support for scanned resumes.
- Add export options for ranked results.
- Add structured logging and request IDs for easier debugging of large ranking runs.

## Recruiter-Facing Quality Signals

- Clear separation between deterministic local ranking and optional LLM review.
- Explainable scoring dimensions instead of a single black-box match score.
- Local file safety checks for opening resumes from the UI.
- CI across two current Python versions.
- Dependency list is small and focused: FastAPI, Pydantic, scikit-learn, PyMuPDF, python-docx, requests, and pytest/httpx for tests.

ResumeRanker is built to make technical resume review faster, more consistent, and easier to defend in conversation with hiring teams.

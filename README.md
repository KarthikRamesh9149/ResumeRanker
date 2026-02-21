# ResumeRanker

**Smart, local-first resume screening that understands context — not just keywords.**

---

## What is ResumeRanker?

ResumeRanker is an intelligent resume screening tool that helps hiring teams find the best candidates from hundreds of resumes in minutes. Drop in a job description, point it at a folder of resumes, and get ranked results with clear explanations for every recommendation.

Unlike simple keyword matchers, ResumeRanker understands *where* skills appear in a resume and ranks resumes smartly.
---

## How It Works

### 1. Upload Your Job Description
Paste a JD or upload a document. ResumeRanker automatically detects if the document contains multiple roles and splits them into separate ranking jobs — no manual work needed.

### 2. Review Extracted Skills
The system extracts required and preferred skills from your JD. You can edit, add, or remove skills directly in the interface to fine-tune what you're looking for.

### 3. Scan Resumes
Point ResumeRanker at a folder of resumes (PDF, DOCX, or TXT). It reads and analyzes every resume locally on your machine — nothing leaves your computer during this step.

### 4. Get Ranked Results
Every candidate is scored across four dimensions:

- **Projects** — Do their projects align with the job's domain and tech stack?
- **Experience** — Do they have relevant professional work experience?
- **Skills** — Are required skills demonstrated in projects, or just listed?
- **Certifications** — Do they hold relevant certifications?

Results are displayed with visual score breakdowns, matched and missing skills, and a clear explanation of why each candidate ranked where they did.

---

## Key Features

### Two-Stage Ranking
**Stage 1** runs entirely on your machine — fast, free, and private. It scores all resumes using section-aware analysis that goes beyond keyword matching.

**Stage 2** (optional) sends only the top candidates to an AI model for deeper evaluation. The AI reads project descriptions, understands domain relevance, and provides natural language explanations for each recommendation.

### Multi-Role Job Descriptions
Upload a single document that covers Backend, Frontend, and Mobile roles. ResumeRanker detects each role automatically and produces separate ranked lists — one upload, multiple results.

### Context-Aware Scoring
The system understands that:
- A skill demonstrated in a **project** is worth more than one just listed
- A **software developer** role is more relevant than a project manager role for dev positions
- A **travel booking platform** project is relevant to a rental platform job, even without exact keyword matches

### Role-Aware AI Explanations
When AI ranking is enabled, each top candidate gets a detailed explanation covering:
- Why their projects are relevant (or not)
- What skills they're missing and how critical each gap is
- Specific interview focus areas to explore with the candidate

Explanations are role-specific — a frontend evaluation never mentions backend requirements.

### Privacy-First Design
All resume processing happens locally. The only data that leaves your machine (optionally) is a brief summary of shortlisted candidates sent to the AI model for deeper scoring. You can run the entire system without any cloud connection.

---

## Who Is It For?

- **Startup founders** screening applicants for their first engineering hires
- **Hiring managers** handling high-volume applications across multiple roles
- **Recruiting teams** that need consistent, explainable candidate rankings
- **Technical leads** evaluating whether candidates have demonstrated the right skills — not just listed them

---

## At a Glance

| Feature | Details |
|---|---|
| Resume formats | PDF, DOCX, TXT |
| JD input | Paste text, upload file, or both |
| Multi-role support | Automatic role detection and splitting |
| Scoring dimensions | Projects, Experience, Skills, Certifications |
| AI integration | Optional (Groq API) |
| Batch size | Handles 500+ resumes efficiently |
| Privacy | Local-first, resumes never uploaded |

---

## What Makes It Different

Most resume screeners do keyword matching — if the JD says "React" and the resume says "React", it's a match. ResumeRanker goes further:

**Section-aware analysis** — A candidate who *built* a React e-commerce platform scores higher than one who just *listed* React in their skills section.

**Domain understanding** — A hotel booking project is recognized as relevant for a rental platform role, because the system understands semantic domain clusters like booking, reservation, property, and listing.

**Dynamic weighting** — For candidates with no work experience (fresh graduates), the system automatically shifts weight to projects and skills so strong student portfolios aren't unfairly penalized.

**Explainable results** — Every ranking comes with a clear breakdown. No black boxes, no mystery scores.

---

*Built for teams that care about finding the right people, not just the right keywords.*

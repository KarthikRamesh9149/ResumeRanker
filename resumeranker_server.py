"""
ResumeRanker Server - Local Resume Ranking with Optional LLM Explanations

FastAPI server that scans a folder of resumes, scores them against a job description
using TF-IDF similarity and keyword coverage, and returns the top 5 matches.

Usage:
    python resumeranker_server.py [port]

Requires:
    pip install -r requirements.txt
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import uvicorn
import os
import sys
import re
import json
import platform
import subprocess
import threading
from pathlib import Path
from datetime import datetime
import time
import importlib.metadata

# ML imports
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

# Document parsing
import fitz  # PyMuPDF
from docx import Document

# Environment
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()

# Required packages for this workflow
REQUIRED_PACKAGES = [
    "fastapi",
    "uvicorn",
    "pydantic",
    "python-dotenv",
    "requests",
    "scikit-learn",
    "numpy",
    "scipy",
    "joblib",
    "python-docx",
    "PyMuPDF",
]

# ============================================
# Configuration
# ============================================

SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")

def get_server_port() -> int:
    """Resolve server port from CLI or environment without breaking module imports."""
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        return int(sys.argv[1])
    return int(os.getenv("SERVER_PORT", "8892"))

SERVER_PORT = get_server_port()
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_API_KEY = os.getenv("GROQ_API_KEY_1", "")
PRIMARY_MODEL = os.getenv("PRIMARY_MODEL", "openai/gpt-oss-20b")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_1", "openai/gpt-oss-120b")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "1"))

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MAX_SUMMARY_LENGTH = 800

# ============================================
# FastAPI Setup
# ============================================

app = FastAPI(title="ResumeRanker Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# Request/Response Models
# ============================================

class ScanFolderRequest(BaseModel):
    folder_path: str

class FileInfo(BaseModel):
    name: str
    path: str
    ext: str
    modified: str

class ScanFolderResponse(BaseModel):
    success: bool
    count: Optional[int] = None
    files: Optional[List[FileInfo]] = None
    error: Optional[str] = None

class AnalyzeJdRequest(BaseModel):
    job_description: str = ""
    jd_file_path: str = ""
    use_llm: bool = True

class ExtractedRequirements(BaseModel):
    required_skills: List[str] = []
    preferred_skills: List[str] = []
    experience: Dict[str, int] = {}  # skill -> years required
    certifications: List[str] = []

class RoleRequirements(BaseModel):
    role_label: str
    requirements: ExtractedRequirements
    section_text: str = ""  # The role-specific section text (for TF-IDF scoring)

class AnalyzeJdResponse(BaseModel):
    success: bool
    requirements: Optional[ExtractedRequirements] = None
    roles: Optional[List[RoleRequirements]] = None  # Multiple roles detected in one document
    error: Optional[str] = None

class RankRequest(BaseModel):
    folder_path: str
    job_description: str = ""  # Text pasted directly
    jd_file_path: str = ""  # Path to uploaded PDF/DOCX file
    use_llm: bool = False
    use_llm_for_jd: bool = True  # Use LLM to analyze JD
    use_deep_eval: bool = False  # LLM deep evaluation on shortlisted candidates
    top_n: int = 5  # Return top N results (default 5)
    requirements: Optional[ExtractedRequirements] = None

class SectionScores(BaseModel):
    projects_score: float = 0.0       # 0.0-1.0 TF-IDF similarity
    experience_score: float = 0.0     # 0.0-1.0 TF-IDF similarity
    certifications_score: float = 0.0 # 0.0-1.0 keyword match ratio
    skills_score: float = 0.0        # 0.0-1.0 keyword match ratio

class LlmDimensionScore(BaseModel):
    score: int = 0
    reasoning: str = ""

class LlmContextualScores(BaseModel):
    projects: LlmDimensionScore = Field(default_factory=LlmDimensionScore)
    experience: LlmDimensionScore = Field(default_factory=LlmDimensionScore)
    certifications: LlmDimensionScore = Field(default_factory=LlmDimensionScore)
    skills: LlmDimensionScore = Field(default_factory=LlmDimensionScore)

class RankedCandidate(BaseModel):
    candidate_name: str
    file_name: str
    file_path: str
    score: int
    similarity: float
    keyword_coverage: float
    matched_required: List[str]
    missing_required: List[str]
    matched_preferred: List[str]
    missing_preferred: List[str]
    explanation: str
    section_scores: Optional[SectionScores] = None
    llm_scores: Optional[LlmContextualScores] = None

class RankResponse(BaseModel):
    success: bool
    data: Optional[List[RankedCandidate]] = None
    requirements_used: Optional[ExtractedRequirements] = None
    error: Optional[str] = None

class OpenFileRequest(BaseModel):
    path: str
    root_folder: str

class OpenFileResponse(BaseModel):
    success: bool
    error: Optional[str] = None

class JdEntryRequest(BaseModel):
    jd_text: str = ""
    jd_file_path: str = ""
    requirements: Optional[ExtractedRequirements] = None
    jd_label: str = ""  # display name (e.g., filename)

class RankMultiRequest(BaseModel):
    folder_path: str
    jd_entries: List[JdEntryRequest]
    use_llm: bool = False
    use_llm_for_jd: bool = True
    use_deep_eval: bool = False
    top_n: int = 5

class JdRankResult(BaseModel):
    jd_label: str
    candidates: List[RankedCandidate]
    requirements_used: ExtractedRequirements

class RankMultiResponse(BaseModel):
    success: bool
    results: Optional[List[JdRankResult]] = None
    error: Optional[str] = None

class ExtractTextRequest(BaseModel):
    file_path: str

class ExtractTextResponse(BaseModel):
    success: bool
    text: Optional[str] = None
    error: Optional[str] = None

# ============================================
# Resume Parsing
# ============================================

def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from a PDF file using PyMuPDF."""
    try:
        doc = fitz.open(file_path)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts)
    except Exception as e:
        print(f"Error extracting PDF text from {file_path}: {e}", flush=True)
        return ""

def extract_text_from_docx(file_path: str) -> str:
    """Extract text from a DOCX file."""
    try:
        doc = Document(file_path)
        text_parts = []
        for paragraph in doc.paragraphs:
            text_parts.append(paragraph.text)
        return "\n".join(text_parts)
    except Exception as e:
        print(f"Error extracting DOCX text from {file_path}: {e}", flush=True)
        return ""

def extract_text_from_txt(file_path: str) -> str:
    """Extract text from a plain text file."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        print(f"Error reading TXT file {file_path}: {e}", flush=True)
        return ""

def extract_resume_text(file_path: str) -> str:
    """Extract text from a resume file based on extension."""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext == ".docx":
        return extract_text_from_docx(file_path)
    elif ext == ".txt":
        return extract_text_from_txt(file_path)
    return ""

def normalize_text(text: str) -> str:
    """Normalize whitespace and clean text (collapses to single line for TF-IDF)."""
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text

def clean_text_preserve_lines(text: str) -> str:
    """Clean text but preserve paragraph breaks (for JD display/parsing)."""
    # Collapse multiple blank lines into one
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Clean up spaces within lines (but keep newlines)
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        line = re.sub(r'[ \t]+', ' ', line).strip()
        cleaned.append(line)
    return '\n'.join(cleaned)

def extract_candidate_name(text: str, file_path: str) -> str:
    """
    Extract candidate name from resume text.
    Best-effort: use first non-empty line if it looks like a name,
    otherwise fallback to filename.
    """
    lines = text.strip().split('\n')

    for line in lines[:5]:  # Check first 5 lines
        line = line.strip()
        if not line:
            continue

        # Skip if it looks like contact info
        if '@' in line or re.search(r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}', line):
            continue

        # Skip lines starting with bullets or special chars
        if line.startswith(('•', '-', '*', '–', '>')):
            continue

        # If line contains separators like | or —, take the first part (likely name)
        name_part = line
        for sep in ['|', '—', ' - ', '–']:
            if sep in name_part:
                name_part = name_part.split(sep)[0].strip()

        # Check if it looks like a name (1-5 words, mostly letters, not a section header)
        words = name_part.split()
        if 1 <= len(words) <= 5:
            # Check if mostly alphabetic
            alpha_chars = sum(c.isalpha() for c in name_part.replace(' ', ''))
            total_chars = len(name_part.replace(' ', ''))
            if total_chars > 0 and alpha_chars / total_chars > 0.8:
                # Skip common section headers
                lower = name_part.lower()
                if lower not in ('education', 'experience', 'skills', 'projects', 'summary', 'objective', 'certifications', 'contact', 'about', 'profile'):
                    return name_part

    # Fallback to filename
    return Path(file_path).stem

# ============================================
# Keyword Extraction
# ============================================

# Common tech skills and keywords to look for
COMMON_SKILLS = {
    # Programming Languages
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "golang", "rust",
    "ruby", "php", "kotlin", "swift", "scala", "r", "matlab", "perl", "dart",
    # Frontend
    "react", "reactjs", "angular", "vue", "vuejs", "svelte", "nextjs", "next.js",
    "gatsby", "ember", "backbone", "jquery", "react native",
    # Backend
    "node", "nodejs", "node.js", "express", "expressjs", "nestjs", "django", "flask", "fastapi",
    "spring", "spring boot", "springboot", "rails", "laravel", "asp.net", ".net", "dotnet",
    # Cloud & DevOps
    "aws", "amazon web services", "azure", "microsoft azure", "gcp", "google cloud", "google cloud platform",
    "docker", "kubernetes", "k8s", "terraform", "ansible", "jenkins", "circleci",
    "github actions", "gitlab ci", "travis", "travis ci", "bamboo", "cloudfront", "cloudformation",
    "ec2", "rds", "s3", "lambda", "elastic beanstalk", "ecs", "eks",
    # Databases
    "sql", "mysql", "postgresql", "postgres", "mongodb", "mongo", "redis",
    "elasticsearch", "dynamodb", "cassandra", "oracle", "sqlite", "mariadb",
    "neo4j", "couchdb", "firebase", "firestore", "supabase",
    # Data & ML
    "machine learning", "deep learning", "nlp", "natural language processing",
    "computer vision", "ai", "artificial intelligence", "tensorflow", "pytorch",
    "keras", "scikit-learn", "pandas", "numpy", "spark", "hadoop", "airflow",
    "data science", "data engineering", "etl", "data warehouse",
    "tableau", "power bi", "looker", "metabase",
    # Tools & Practices
    "git", "github", "gitlab", "bitbucket", "jira", "confluence", "slack", "trello",
    "linux", "unix", "bash", "shell", "powershell", "vim", "vscode", "intellij",
    "agile", "scrum", "kanban", "ci/cd", "devops", "sre", "microservices",
    # Payment & Integration
    "stripe", "paypal", "square", "braintree", "razorpay",
    # APIs & Protocols
    "graphql", "grpc", "websocket", "oauth", "jwt", "rest api", "soap",
    # Frontend Tech
    "html", "html5", "css", "css3", "sass", "scss", "less", "tailwind", "tailwindcss", "bootstrap",
    "material ui", "ant design", "chakra ui",
    "webpack", "vite", "babel", "rollup", "parcel", "eslint", "prettier",
    # Testing
    "jest", "mocha", "chai", "pytest", "unittest", "junit", "testng", "selenium", "cypress", "playwright",
    "unit testing", "integration testing", "e2e testing", "tdd", "bdd", "postman", "insomnia",
    # Mobile
    "react native", "flutter", "swift", "swiftui", "kotlin", "ios", "android", "xamarin", "ionic",
    # Documentation & API
    "swagger", "openapi", "postman", "insomnia", "graphiql",
    # State Management
    "redux", "mobx", "zustand", "recoil", "context api", "vuex", "pinia",
    # ORMs & Libraries
    "sequelize", "typeorm", "prisma", "mongoose", "sqlalchemy", "hibernate", "eloquent",
    # Certifications (will be detected)
    "aws certified", "pmp", "cissp", "cka", "ckad", "comptia", "azure certified",
}

# Stop words to filter out - these are NOT skills
STOP_WORDS = {
    # Common English words
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
    "be", "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "dare", "ought",
    "this", "that", "these", "those", "it", "its", "they", "them", "their",
    "we", "us", "our", "you", "your", "he", "him", "his", "she", "her",
    "who", "whom", "which", "what", "where", "when", "why", "how",
    "all", "each", "every", "both", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too",
    "very", "just", "also", "now", "here", "there", "then", "once",

    # Generic verbs (not skills)
    "create", "created", "creating", "creation", "creates",
    "build", "built", "building", "builds",
    "develop", "developed", "developing", "develops", "development",
    "design", "designed", "designing", "designs",
    "implement", "implemented", "implementing", "implements", "implementation",
    "manage", "managed", "managing", "manages", "management",
    "lead", "led", "leading", "leads", "leader",
    "work", "worked", "working", "works",
    "use", "used", "using", "uses",
    "make", "made", "making", "makes",
    "write", "wrote", "written", "writing", "writes",
    "read", "reading", "reads",
    "run", "ran", "running", "runs",
    "set", "setting", "sets",
    "get", "getting", "gets",
    "put", "putting", "puts",
    "take", "took", "taking", "takes",
    "help", "helped", "helping", "helps",
    "support", "supported", "supporting", "supports",
    "maintain", "maintained", "maintaining", "maintains", "maintenance",
    "ensure", "ensured", "ensuring", "ensures",
    "provide", "provided", "providing", "provides",
    "review", "reviewed", "reviewing", "reviews",
    "test", "tested", "testing", "tests",  # generic, not the tool
    "analyze", "analyzed", "analyzing", "analyzes", "analysis",
    "improve", "improved", "improving", "improves",
    "optimize", "optimized", "optimizing", "optimizes",
    "understand", "understanding", "understands",
    "learn", "learned", "learning", "learns",
    "collaborate", "collaborated", "collaborating", "collaborates", "collaboration",

    # Generic nouns (not skills)
    "team", "teams", "project", "projects", "product", "products",
    "system", "systems", "application", "applications", "app", "apps",
    "service", "services", "platform", "platforms",
    "solution", "solutions", "tool", "tools",
    "process", "processes", "procedure", "procedures",
    "code", "codes", "coding",
    "data", "database", "databases",  # too generic
    "user", "users", "client", "clients", "customer", "customers",
    "business", "company", "organization",
    "environment", "environments",
    "feature", "features", "function", "functions", "functionality",
    "component", "components", "module", "modules",
    "interface", "interfaces",
    "requirement", "requirements",
    "specification", "specifications",
    "documentation", "document", "documents",
    "report", "reports", "reporting",
    "meeting", "meetings",
    "deadline", "deadlines", "timeline", "timelines",
    "deliverable", "deliverables",

    # Resume fluff words
    "experience", "experienced", "experiences",
    "knowledge", "skill", "skills", "ability", "abilities",
    "strong", "excellent", "good", "great", "best",
    "proficient", "proficiency", "expert", "expertise",
    "responsible", "responsibility", "responsibilities",
    "role", "roles", "duty", "duties",
    "year", "years", "month", "months", "plus",
    "minimum", "maximum", "preferred", "required",
    "bachelor", "master", "degree", "diploma", "certification",

    # Generic tech terms (too vague)
    "software", "hardware", "technology", "technologies", "tech",
    "web", "mobile", "desktop", "server", "servers",
    "cloud", "network", "networks", "networking",
    "security", "secure",
    "performance", "scalable", "scalability",
    "architecture", "infrastructure",
    "frontend", "front-end", "backend", "back-end", "fullstack", "full-stack",
    "api", "apis", "rest", "restful", "http", "https",
    "json", "xml", "csv", "yaml",
    "ui", "ux", "gui",
    "qa", "qc",
    "pm", "ops", "dev",
    "end", "start", "begin",
    "post", "get", "put", "delete", "patch",  # HTTP verbs as words
    "table", "row", "column",
    "ip", "url", "uri",

    # Document structure noise
    "requirements", "requirement", "must", "should", "implement", "implemented",
    "endpoint", "endpoints", "request", "requests", "response", "responses",
    "deliverable", "deliverables", "checklist", "success", "criteria",
    "timeline", "week", "weeks", "day", "days", "period",
    "completed", "working", "next", "blockers", "questions",
    "link", "links", "commit", "branch", "pull request", "demo",
    "documentation", "guide", "readme", "instructions", "example", "examples",
    "page", "pages", "screen", "screens", "flow", "flows",
    "user", "users", "account", "accounts", "profile", "profiles",
    "list", "listing", "listings", "detail", "details",
    "form", "forms", "field", "fields", "input", "inputs",
    "button", "buttons", "modal", "modals", "dialog", "dialogs",
    "dashboard", "panel", "section", "sections",
    "authentication", "login", "logout", "register", "registration",
    "password", "reset", "verification", "verified",
    "crud", "create", "read", "update", "delete",
    "database", "schema", "migration", "migrations", "seed", "seeding",
    "deployment", "deployed", "hosting", "hosted",
    "testing", "tests", "test suite", "unit", "integration",
    "configuration", "config", "configured", "setup", "environment",
    "variable", "variables", "parameter", "parameters",
    "token", "tokens", "session", "sessions", "cookie", "cookies",
    "header", "headers", "body", "payload",
    "status", "code", "codes", "error", "errors", "success",
    "validation", "validate", "validated", "sanitization",
    "pagination", "paginated", "filter", "filters", "search", "sort", "sorting",
    "permission", "permissions", "authorization", "authorized",
    "notification", "notifications", "email", "emails",
    "upload", "uploaded", "download", "downloaded",
    "image", "images", "file", "files", "folder", "folders",
    "responsive", "layout", "layouts", "navigation", "menu",
    "loading", "loader", "spinner", "state", "states",
    "animation", "animations", "transition", "transitions",
    "mobile-friendly", "touch-friendly",
}

def extract_requirements_with_llm(jd_text: str) -> Optional[ExtractedRequirements]:
    """
    Use LLM to intelligently extract requirements from the job description.
    Returns structured requirements or None if LLM fails.
    """
    if not GROQ_API_KEY:
        return None

    prompt = f"""You are an expert ATS system. Extract ONLY actual technical skills/tools from this document.

This may be a job description OR a technical requirements document. Your job is to identify the TECHNOLOGIES needed.

Return JSON:
{{
  "required_skills": ["list of technologies, frameworks, languages, tools"],
  "preferred_skills": ["list of optional/nice-to-have technologies"],
  "experience": {{"technology": years_as_integer}},
  "certifications": ["certifications if mentioned"]
}}

STRICT RULES - ONLY extract:
✓ Programming languages: Python, JavaScript, Java, Go, TypeScript, etc.
✓ Frameworks: React, Django, FastAPI, Express, NestJS, Spring Boot, etc.
✓ Databases: PostgreSQL, MongoDB, MySQL, Redis, etc.
✓ Cloud/DevOps: AWS, Azure, Docker, Kubernetes, Jenkins, etc.
✓ Tools/Libraries: Stripe, JWT, Git, Swagger, etc.

✗ DO NOT extract:
- Section headers (BACKEND REQUIREMENTS, Frontend, etc.)
- Generic terms (API, system, application, database, authentication, deployment)
- HTTP methods (GET, POST, PUT, DELETE, CRUD)
- File types (JSON, PDF, CSV, DOCX)
- AWS service names alone (S3, EC2, RDS) - only include if "AWS" is in context
- Concepts (responsive design, testing, documentation, role-based access)
- Instructions (must implement, required endpoints, deliverables)
- Table/schema field names (user_id, created_at, status, etc.)
- Common patterns (JWT tokens, bcrypt hashing, pagination, error handling)

EXAMPLES:
"Technology Stack: Node.js, PostgreSQL, AWS, Stripe" → required_skills: ["Node.js", "PostgreSQL", "AWS", "Stripe"]
"Frontend: React or Vue" → required_skills: ["React", "Vue"]
"5+ years of Python experience" → required_skills: ["Python"], experience: {{"Python": 5}}
"CREATE TABLE users" → IGNORE (SQL schema, not a skill requirement)
"GET /api/properties" → IGNORE (endpoint example)

Extract technologies from the document below:

{jd_text[:4000]}

Return ONLY valid JSON."""

    try:
        response = requests.post(
            f"{GROQ_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": PRIMARY_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a precise ATS system that extracts technical requirements from job descriptions. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 2000,
                "temperature": 0.1,
                # "response_format": {"type": "json_object"}  # Disabled - causes 400 on some models
            },
            timeout=LLM_TIMEOUT
        )

        if response.status_code == 200:
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            print(f"  JD analysis LLM raw ({PRIMARY_MODEL}, {len(content)} chars): {content[:300]}", flush=True)

            if not content:
                print(f"  WARNING: Empty JD analysis response from {PRIMARY_MODEL}, trying fallback...", flush=True)
                # Try fallback model
                response2 = requests.post(
                    f"{GROQ_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {GROQ_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": FALLBACK_MODEL,
                        "messages": [
                            {"role": "system", "content": "You are a precise ATS system that extracts technical requirements from job descriptions. Return only valid JSON."},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 2000,
                        "temperature": 0.1,
                        # "response_format": {"type": "json_object"}  # Disabled - causes 400 on some models
                    },
                    timeout=LLM_TIMEOUT
                )
                if response2.status_code == 200:
                    data2 = response2.json()
                    content = data2.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    print(f"  JD analysis LLM raw ({FALLBACK_MODEL}, {len(content)} chars): {content[:300]}", flush=True)
                if not content:
                    print(f"  WARNING: Both models returned empty for JD analysis", flush=True)
                    return None

            # Try to parse JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            parsed = json.loads(content)

            return ExtractedRequirements(
                required_skills=parsed.get("required_skills", []),
                preferred_skills=parsed.get("preferred_skills", []),
                experience=parsed.get("experience", {}),
                certifications=parsed.get("certifications", [])
            )
        else:
            print(f"LLM API error for JD analysis: {response.status_code} - {response.text[:300]}", flush=True)
            return None

    except Exception as e:
        print(f"LLM JD analysis error: {e}", flush=True)
        return None


def detect_role_sections_in_text(jd_text: str) -> Optional[List[Dict[str, str]]]:
    """
    Generic structural pattern detector for multi-role JD documents.
    Works for ANY role type by detecting repeated section header patterns.

    Approach:
    1. Scan lines for headers matching patterns like "{Prefix} {Suffix}" where
       suffix is a role-related word (requirements, developer, engineer, team, etc.)
    2. Group matches by suffix - if 2+ distinct prefixes share the same suffix,
       that indicates multiple roles (e.g. "Backend Requirements" + "Frontend Requirements")
    3. Split document at detected section boundaries

    Returns list of {'role_label': str, 'text': str} if 2+ distinct roles found.
    """
    # Suffixes that indicate a role/section header when preceded by a distinguishing prefix
    SECTION_SUFFIXES = {
        'requirements', 'requirement',
        'developer', 'developers',
        'engineer', 'engineers',
        'team', 'role', 'roles',
        'specifications', 'specification',
        'deliverables', 'deliverable',
        'position', 'positions',
        'analyst', 'analysts',
        'architect', 'architects',
        'designer', 'designers',
        'manager', 'managers',
        'specialist', 'specialists',
        'consultant', 'consultants',
        'lead', 'leads',
        'administrator', 'admin',
    }

    # Prefixes that are too generic to be role-distinguishing
    GENERIC_PREFIXES = {
        'the', 'all', 'general', 'project', 'system', 'technical',
        'job', 'development', 'key', 'core', 'main', 'primary',
        'additional', 'other', 'specific', 'minimum', 'preferred',
        'overall', 'common', 'shared', 'global', 'total',
        'functional', 'non-functional', 'nonfunctional',
    }

    # Normalize suffixes to singular form for grouping
    SUFFIX_NORMALIZE = {
        'requirements': 'requirement', 'developers': 'developer',
        'engineers': 'engineer', 'roles': 'role',
        'specifications': 'specification', 'deliverables': 'deliverable',
        'positions': 'position', 'analysts': 'analyst',
        'architects': 'architect', 'designers': 'designer',
        'managers': 'manager', 'specialists': 'specialist',
        'consultants': 'consultant', 'leads': 'lead',
        'administrators': 'administrator',
    }

    lines = jd_text.split('\n')

    # Phase 1: Find candidate header lines with pattern "{prefix} {suffix}"
    # Each match: (line_index, prefix, normalized_suffix, original_line)
    candidates = []

    for i, line in enumerate(lines):
        # Clean the line: strip whitespace, remove markdown/formatting chars
        cleaned = re.sub(r'[#*_\-=>{}\[\]|`~^]', ' ', line).strip()
        cleaned_lower = cleaned.lower()

        # Skip empty lines or very long lines (not headers)
        if not cleaned_lower or len(cleaned_lower) > 100:
            continue

        # Split into words
        words = cleaned_lower.split()
        if len(words) < 2 or len(words) > 8:
            continue

        # Check if the last word (or last two words) match a section suffix
        last_word = words[-1]
        if last_word in SECTION_SUFFIXES:
            # Prefix is everything before the suffix
            prefix_words = words[:-1]

            # Skip numbered list items (e.g. "10. Testing Requirements", "a) Security Requirements")
            # These are sub-sections within a role, not role headers
            first_word = prefix_words[0]
            if re.match(r'^\d+[\.\):]?$', first_word) or re.match(r'^[a-z][\.\)]$', first_word):
                continue

            prefix = ' '.join(prefix_words)

            # Filter out generic prefixes
            if prefix in GENERIC_PREFIXES or all(w in GENERIC_PREFIXES for w in prefix_words):
                continue

            # Filter out single-character or very short prefixes
            if len(prefix) < 2:
                continue

            norm_suffix = SUFFIX_NORMALIZE.get(last_word, last_word)
            candidates.append((i, prefix, norm_suffix, cleaned))

    if len(candidates) < 2:
        return None

    # Phase 2: Group by normalized suffix and find groups with 2+ distinct prefixes
    from collections import defaultdict
    suffix_groups = defaultdict(list)  # suffix -> list of (line_index, prefix, original_line)
    for line_idx, prefix, norm_suffix, original_line in candidates:
        suffix_groups[norm_suffix].append((line_idx, prefix, original_line))

    # Find the best suffix group (most distinct prefixes, min 2)
    best_group = None
    best_count = 0
    for suffix, matches in suffix_groups.items():
        # Get distinct prefixes in this group
        distinct_prefixes = set(m[1] for m in matches)
        if len(distinct_prefixes) >= 2 and len(distinct_prefixes) > best_count:
            best_group = suffix
            best_count = len(distinct_prefixes)

    if not best_group:
        return None

    # Phase 3: Build section boundaries from the best group
    # For each distinct prefix, take the FIRST occurrence (avoid duplicates from title lines)
    matches = suffix_groups[best_group]
    seen_prefixes = set()
    role_boundaries = []  # (line_index, role_label)

    for line_idx, prefix, original_line in sorted(matches, key=lambda m: m[0]):
        if prefix not in seen_prefixes:
            seen_prefixes.add(prefix)
            # Create a nice role label from prefix (title case)
            role_label = prefix.title()
            role_boundaries.append((line_idx, role_label))

    if len(role_boundaries) < 2:
        return None

    # Phase 4: Validate - skip if first section starts very early (likely a title, not a section)
    # If the first detected boundary is in the first 3 lines AND there's another within 5 lines,
    # that's likely a title like "Backend & Frontend Specifications" followed by actual sections
    if len(role_boundaries) >= 2:
        first_line = role_boundaries[0][0]
        second_line = role_boundaries[1][0]
        if first_line < 3 and (second_line - first_line) < 5:
            # Both are in the title area - not real sections
            return None

    # Phase 5: Split text at boundaries
    sections = []
    for idx, (start_line, role_label) in enumerate(role_boundaries):
        end_line = role_boundaries[idx + 1][0] if idx + 1 < len(role_boundaries) else len(lines)
        section_text = '\n'.join(lines[start_line:end_line])
        if len(section_text.strip()) >= 50:
            sections.append({
                'role_label': role_label,
                'text': section_text,
            })

    if len(sections) >= 2:
        print(f"Generic detector found {len(sections)} roles via '{best_group}' pattern: {[s['role_label'] for s in sections]}", flush=True)
        return sections

    return None


def detect_and_extract_roles(jd_text: str, use_llm: bool = True) -> Optional[List[RoleRequirements]]:
    """
    Detect if a JD document contains multiple distinct roles and extract
    requirements for each.

    Two-stage approach:
    1. Pre-scan: Deterministic keyword detection of role sections (always works)
    2. Per-section extraction: LLM or rule-based skill extraction for each section

    Returns list of RoleRequirements (2+ entries) or None if single role.
    """
    # Stage 1: Pre-scan for role section boundaries (deterministic, no LLM)
    role_sections = detect_role_sections_in_text(jd_text)

    if not role_sections:
        return None

    print(f"Pre-scan detected {len(role_sections)} roles: {[s['role_label'] for s in role_sections]}", flush=True)

    # Stage 2: Extract requirements for each section separately
    roles = []
    for section in role_sections:
        section_text = section['text']
        requirements = None

        # Try LLM extraction for this section
        if use_llm and GROQ_API_KEY:
            requirements = extract_requirements_with_llm(section_text)

        # Fallback to rule-based
        if not requirements or (not requirements.required_skills and not requirements.preferred_skills):
            requirements = extract_requirements_rule_based(section_text)

        if requirements and (requirements.required_skills or requirements.preferred_skills):
            roles.append(RoleRequirements(
                role_label=section['role_label'],
                requirements=requirements,
                section_text=section_text
            ))

    return roles if len(roles) >= 2 else None


def extract_requirements_rule_based(jd_text: str) -> ExtractedRequirements:
    """
    Rule-based extraction of requirements from JD.
    Two-pass approach:
    1. Full-text scan: find ALL technology mentions across the entire document
    2. Section-aware scan: try to separate required vs preferred
    """
    jd_lower = jd_text.lower()
    required_skills = set()
    preferred_skills = set()
    experience = {}
    certifications = []

    # ---- PASS 1: Full-text skill scan (always works, regardless of formatting) ----
    # This catches skills even if the document is one long line
    all_found_skills = set()
    for skill in COMMON_SKILLS:
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, jd_lower):
            all_found_skills.add(skill)

    # Extract experience patterns from full text
    exp_patterns = [
        r'(\d+)\+?\s*(?:to\s*\d+)?\s*years?\s+(?:of\s+)?(?:experience\s+(?:with|in)\s+)?([a-zA-Z][a-zA-Z0-9.#+\s]{1,30})',
        r'([a-zA-Z][a-zA-Z0-9.#+]{1,20})\s*[:\-]?\s*(\d+)\+?\s*years?',
    ]
    for pattern in exp_patterns:
        matches = re.findall(pattern, jd_lower)
        for match in matches:
            if len(match) == 2:
                years_str, skill = match if match[0].isdigit() else (match[1], match[0])
                try:
                    years = int(re.search(r'\d+', str(years_str)).group())
                    skill = skill.strip()
                    if skill and skill not in STOP_WORDS and len(skill) > 1:
                        experience[skill] = years
                except:
                    pass

    # Extract certification patterns from full text
    cert_patterns = [
        r'(aws\s+certified[^,.\n]*)',
        r'\b(pmp)\b',
        r'\b(cissp)\b',
        r'\b(cka|ckad|cks)\b',
        r'\b(ccna|ccnp|ccie)\b',
        r'(comptia\s+[a-z+]+)',
    ]
    for pattern in cert_patterns:
        matches = re.findall(pattern, jd_lower)
        for match in matches:
            if match:
                certifications.append(match.strip())

    # ---- PASS 2: Section-aware scan to separate required vs preferred ----
    lines = jd_text.split('\n')
    section_required = set()
    section_preferred = set()
    current_section = "required"  # Default

    # Patterns to skip (document noise lines)
    skip_patterns = [
        r'^\s*(get|post|put|delete|patch)\s+/',  # HTTP methods with paths
        r'create\s+table',  # SQL schemas
        r'^\s*id\s+uuid',  # Table fields
        r'^\s*\w+_id\s+(uuid|integer|varchar|text|boolean)',  # DB column defs
        r'^\s*\w+\s+(varchar|integer|decimal|boolean|timestamp|date|text|jsonb?|uuid)',  # DB types
        r'^\{?\s*"(success|error|data|message)"',  # JSON response examples
        r'^\s*\d{3}:\s',  # HTTP status codes (200: Success)
        r'/api/v?\d?/',  # API paths
    ]

    for line in lines:
        line_lower = line.lower().strip()

        if not line_lower or len(line_lower) < 3:
            continue

        # Skip document noise lines
        if any(re.search(pattern, line_lower) for pattern in skip_patterns):
            continue

        # Update section context (but DON'T skip the line - still scan for skills)
        # Handle lines that contain BOTH required and preferred markers (inline split)
        has_required_marker = any(kw in line_lower for kw in ['required', 'technology stack', 'tech stack', 'must have', 'must implement', 'must know', 'must be', 'requirements', 'mandatory', 'essential'])
        has_preferred_marker = any(kw in line_lower for kw in ['preferred', 'nice to have', 'bonus', 'desired', 'optional'])
        has_ignore_marker = any(kw in line_lower for kw in ['deliverables checklist', 'success criteria', 'development timeline', 'communication & support', 'progress reporting'])

        if has_ignore_marker:
            current_section = "ignore"

        if current_section == "ignore":
            continue

        # If line has both required and preferred markers, split and categorize each part
        if has_required_marker and has_preferred_marker:
            # Find where "preferred" starts and split
            for pref_kw in ['preferred', 'nice to have', 'bonus', 'desired', 'optional']:
                pref_idx = line_lower.find(pref_kw)
                if pref_idx >= 0:
                    required_part = line_lower[:pref_idx]
                    preferred_part = line_lower[pref_idx:]
                    for skill in COMMON_SKILLS:
                        pat = r'\b' + re.escape(skill) + r'\b'
                        if re.search(pat, required_part):
                            section_required.add(skill)
                        if re.search(pat, preferred_part):
                            section_preferred.add(skill)
                    break
        else:
            # Single section on this line
            if has_preferred_marker:
                current_section = "preferred"
            elif has_required_marker:
                current_section = "required"

            # Scan this line for skills
            for skill in COMMON_SKILLS:
                pattern = r'\b' + re.escape(skill) + r'\b'
                if re.search(pattern, line_lower):
                    if current_section == "preferred":
                        section_preferred.add(skill)
                    else:
                        section_required.add(skill)

    # ---- Merge results ----
    # If section-aware scan found skills, use that categorization
    if section_required or section_preferred:
        required_skills = section_required - section_preferred
        preferred_skills = section_preferred - section_required
        # Skills found in full scan but not in section scan go to required
        uncategorized = all_found_skills - required_skills - preferred_skills
        required_skills.update(uncategorized)
    else:
        # Section scan found nothing (single-line text or weird format)
        # Put all full-text skills into required
        required_skills = all_found_skills

    # Remove stop words
    required_skills = {s for s in required_skills if s.lower() not in STOP_WORDS}
    preferred_skills = {s for s in preferred_skills if s.lower() not in STOP_WORDS}

    return ExtractedRequirements(
        required_skills=sorted(list(required_skills)),
        preferred_skills=sorted(list(preferred_skills)),
        experience=experience,
        certifications=list(set(certifications))
    )


def analyze_job_description(jd_text: str, use_llm: bool = True) -> ExtractedRequirements:
    """
    Main function to analyze JD and extract requirements.
    Uses LLM if available and enabled, falls back to rule-based.
    """
    if use_llm and GROQ_API_KEY:
        llm_result = extract_requirements_with_llm(jd_text)
        if llm_result and (llm_result.required_skills or llm_result.preferred_skills):
            return llm_result

    # Fallback to rule-based
    return extract_requirements_rule_based(jd_text)


def keyword_in_text(keyword: str, text: str) -> bool:
    """
    Check if keyword exists in text using word-boundary matching.
    Handles variations and abbreviations.
    """
    keyword = keyword.lower().strip()
    text = text.lower()

    # Direct word-boundary match
    pattern = r'\b' + re.escape(keyword) + r'\b'
    if re.search(pattern, text):
        return True

    # Handle dot variations (node.js -> nodejs, node js)
    if '.' in keyword:
        alt = keyword.replace('.', '')
        if re.search(r'\b' + re.escape(alt) + r'\b', text):
            return True
        alt = keyword.replace('.', ' ')
        if re.search(r'\b' + re.escape(alt) + r'\b', text):
            return True

    # Handle common abbreviations
    abbrev_map = {
        'javascript': ['js'],
        'typescript': ['ts'],
        'postgresql': ['postgres', 'psql'],
        'mongodb': ['mongo'],
        'kubernetes': ['k8s'],
        'amazon web services': ['aws'],
        'google cloud': ['gcp'],
        'machine learning': ['ml'],
        'deep learning': ['dl'],
        'natural language processing': ['nlp'],
        'nodejs': ['node.js', 'node js'],
        'node.js': ['nodejs', 'node js'],
        'reactjs': ['react.js', 'react'],
        'vuejs': ['vue.js', 'vue'],
        'nextjs': ['next.js'],
        'nestjs': ['nest.js'],
    }

    # Check if keyword has abbreviation
    if keyword in abbrev_map:
        for abbrev in abbrev_map[keyword]:
            if re.search(r'\b' + re.escape(abbrev) + r'\b', text):
                return True

    # Check reverse (abbreviation to full name)
    for full, abbrevs in abbrev_map.items():
        if keyword in abbrevs or keyword == full:
            if re.search(r'\b' + re.escape(full) + r'\b', text):
                return True
            for abbrev in abbrevs:
                if re.search(r'\b' + re.escape(abbrev) + r'\b', text):
                    return True

    return False


def find_matched_skills(resume_text: str, requirements: ExtractedRequirements) -> Dict[str, List[str]]:
    """
    Find which required and preferred skills are matched/missing in resume.
    Uses word-boundary matching to avoid false positives.
    """
    matched_required = []
    missing_required = []
    matched_preferred = []
    missing_preferred = []

    # Check required skills
    for skill in requirements.required_skills:
        if keyword_in_text(skill, resume_text):
            matched_required.append(skill)
        else:
            missing_required.append(skill)

    # Check preferred skills
    for skill in requirements.preferred_skills:
        if keyword_in_text(skill, resume_text):
            matched_preferred.append(skill)
        else:
            missing_preferred.append(skill)

    return {
        "matched_required": matched_required,
        "missing_required": missing_required,
        "matched_preferred": matched_preferred,
        "missing_preferred": missing_preferred
    }

# ============================================
# Resume Section Parsing
# ============================================

SECTION_HEADERS = {
    'projects': [
        'projects', 'personal projects', 'academic projects', 'project experience',
        'key projects', 'selected projects', 'notable projects', 'project work',
        'side projects', 'freelance projects', 'major projects',
    ],
    'experience': [
        'experience', 'work experience', 'professional experience', 'employment',
        'employment history', 'work history', 'career history', 'professional background',
        'relevant experience', 'internship', 'internships', 'work',
    ],
    'certifications': [
        'certifications', 'certificates', 'professional certifications', 'licenses',
        'licenses & certifications', 'certifications & licenses', 'credentials',
        'professional credentials', 'awards & certifications',
    ],
    'skills': [
        'skills', 'technical skills', 'core competencies', 'technologies',
        'tech stack', 'tools & technologies', 'competencies', 'proficiencies',
        'technical proficiencies', 'areas of expertise', 'expertise',
        'programming languages', 'frameworks', 'tools',
    ],
    'education': [
        'education', 'academic background', 'academic qualifications',
        'educational background', 'qualifications', 'academic history',
    ],
}


def parse_resume_sections(text: str) -> Dict[str, str]:
    """
    Parse resume into sections: projects, experience, certifications, skills, education, other.
    Uses header detection to split the text.
    """
    lines = text.split('\n')
    sections: Dict[str, str] = {
        'projects': '', 'experience': '', 'certifications': '',
        'skills': '', 'education': '', 'other': ''
    }
    current_section = 'other'

    for line in lines:
        line_stripped = line.strip()
        line_lower = line_stripped.lower()

        # Skip empty lines but still append to current section
        if not line_lower:
            sections[current_section] += '\n'
            continue

        # Detect section headers: short lines (< 60 chars) that match known headers
        # Headers are often standalone lines, sometimes with colons or dashes
        if len(line_lower) < 60:
            # Clean up common header formatting
            cleaned = re.sub(r'[:\-–—|#*_=]+$', '', line_lower).strip()
            cleaned = re.sub(r'^[:\-–—|#*_=]+', '', cleaned).strip()

            matched_section = None
            for section_key, headers in SECTION_HEADERS.items():
                for h in headers:
                    if cleaned == h or cleaned.startswith(h + ' ') or cleaned.endswith(' ' + h):
                        matched_section = section_key
                        break
                if matched_section:
                    break

            if matched_section:
                current_section = matched_section
                continue  # Don't include the header line itself

        sections[current_section] += line + '\n'

    return sections


def compute_section_similarity(section_text: str, jd_text: str) -> float:
    """
    Compute TF-IDF cosine similarity between a resume section and JD.
    Returns 0.0 if section is empty or too short.
    """
    section_clean = section_text.strip()
    if not section_clean or len(section_clean) < 30:
        return 0.0
    try:
        return compute_similarity(normalize_text(jd_text), normalize_text(section_clean))
    except Exception:
        return 0.0


def find_cert_matches(resume_text: str, jd_certifications: List[str]) -> int:
    """Count how many JD certifications are found in resume text."""
    if not jd_certifications:
        return 0
    count = 0
    text_lower = resume_text.lower()
    for cert in jd_certifications:
        if cert.lower() in text_lower:
            count += 1
    return count


# ============================================
# Domain Clusters for Semantic Similarity
# ============================================
DOMAIN_CLUSTERS = {
    "rental_booking": ["rental", "booking", "reservation", "listing", "property", "tenant", "lease", "rent", "apartment", "hotel", "airbnb", "stay", "check-in", "checkout"],
    "ecommerce": ["shop", "cart", "checkout", "payment", "product", "order", "store", "marketplace", "catalog", "inventory", "purchase", "buy", "sell"],
    "social_media": ["chat", "messaging", "feed", "post", "follow", "social", "community", "profile", "friend", "comment", "like", "share", "notification"],
    "fintech": ["payment", "transaction", "banking", "wallet", "finance", "invoice", "transfer", "account", "balance", "credit", "debit", "ledger"],
    "healthcare": ["patient", "medical", "health", "clinic", "appointment", "doctor", "hospital", "diagnosis", "prescription", "treatment"],
    "education": ["course", "student", "learning", "quiz", "lecture", "enrollment", "grade", "assignment", "classroom", "tutor", "lms"],
    "logistics": ["delivery", "shipping", "tracking", "route", "warehouse", "fleet", "dispatch", "package", "courier", "freight"],
    "content_media": ["video", "stream", "upload", "playlist", "podcast", "blog", "article", "editor", "publish", "media", "content"],
    "saas_platform": ["dashboard", "analytics", "subscription", "saas", "multi-tenant", "admin", "report", "metrics", "integration"],
    "devtools": ["ci/cd", "pipeline", "deploy", "monitoring", "logging", "debug", "testing", "automation", "devops", "infrastructure"],
    "food_delivery": ["food", "restaurant", "menu", "delivery", "order", "cuisine", "recipe", "meal", "dining"],
    "travel": ["travel", "flight", "hotel", "itinerary", "trip", "destination", "tourism", "vacation", "booking"],
}

# Role indicators for experience quality scoring
DEV_ROLE_INDICATORS = [
    "software engineer", "software developer", "full stack", "fullstack",
    "backend developer", "frontend developer", "web developer", "sde",
    "backend engineer", "frontend engineer", "developer", "programmer",
    "engineering intern", "software intern", "dev intern", "full-stack",
    "mobile developer", "ios developer", "android developer", "devops engineer",
    "data engineer", "ml engineer", "machine learning engineer",
]

NON_DEV_ROLE_INDICATORS = [
    "project manager", "product manager", "scrum master", "business analyst",
    "management intern", "marketing", "sales", "operations", "coordinator",
    "administrative", "hr ", "recruiter", "consultant",
]


def compute_domain_similarity(jd_text: str, resume_projects_text: str) -> float:
    """
    Score 0-1 based on project domain overlap with JD.
    Uses semantic domain clusters to detect that 'booking platform' ≈ 'rental platform'.
    Two-way matching: checks if JD and projects share the same domain clusters.
    """
    jd_lower = jd_text.lower()
    projects_lower = resume_projects_text.lower()

    # Find which domain clusters both JD and projects activate
    jd_domains = set()
    proj_domains = set()
    for domain, keywords in DOMAIN_CLUSTERS.items():
        jd_hits = sum(1 for kw in keywords if kw in jd_lower)
        proj_hits = sum(1 for kw in keywords if kw in projects_lower)
        if jd_hits >= 2:
            jd_domains.add(domain)
        if proj_hits >= 2:
            proj_domains.add(domain)

    if not jd_domains and not proj_domains:
        return 0.0

    # Score 1: Shared domain clusters (both JD and projects in same domain)
    shared = jd_domains & proj_domains
    cluster_score = len(shared) / max(len(jd_domains), 1) if jd_domains else 0.0

    # Score 2: Direct keyword overlap (JD domain keywords found in projects)
    keyword_score = 0.0
    if jd_domains:
        total_possible = 0
        total_matched = 0
        for domain in jd_domains:
            for kw in DOMAIN_CLUSTERS[domain]:
                if kw in jd_lower:
                    total_possible += 1
                    if kw in projects_lower:
                        total_matched += 1
        keyword_score = total_matched / total_possible if total_possible > 0 else 0.0

    # Score 3: Reverse — project domain keywords found in JD
    reverse_score = 0.0
    if proj_domains:
        total_possible = 0
        total_matched = 0
        for domain in proj_domains:
            for kw in DOMAIN_CLUSTERS[domain]:
                if kw in projects_lower:
                    total_possible += 1
                    if kw in jd_lower:
                        total_matched += 1
        reverse_score = total_matched / total_possible if total_possible > 0 else 0.0

    # Combine: cluster match is most important, then keyword overlap
    return min(0.5 * cluster_score + 0.25 * keyword_score + 0.25 * reverse_score, 1.0)


def compute_demonstrated_skills_score(
    sections: Dict[str, str],
    requirements: ExtractedRequirements
) -> tuple:
    """
    Score skills based on WHERE they appear in the resume.
    Skills in projects (3x) > experience (2.5x) > skills section only (1x).
    Required skills weighted 2x preferred.
    Returns (score_0_to_1, matched_required, missing_required, matched_preferred, missing_preferred)
    """
    projects_text = sections.get('projects', '').lower()
    experience_text = sections.get('experience', '').lower()
    skills_text = sections.get('skills', '').lower()
    # Also check full resume text (other section) as last resort
    other_text = sections.get('other', '').lower() + ' ' + sections.get('education', '').lower()

    total_points = 0.0
    max_points = 0.0
    matched_required = []
    missing_required = []

    for skill in requirements.required_skills:
        max_points += 3.0 * 2  # Required = 2x weight, max 3 pts each
        if keyword_in_text(skill, projects_text):
            total_points += 3.0 * 2  # Demonstrated in project
            matched_required.append(skill)
        elif keyword_in_text(skill, experience_text):
            total_points += 2.5 * 2  # Used professionally
            matched_required.append(skill)
        elif keyword_in_text(skill, skills_text) or keyword_in_text(skill, other_text):
            total_points += 1.0 * 2  # Just listed
            matched_required.append(skill)
        else:
            missing_required.append(skill)

    matched_preferred = []
    missing_preferred = []
    for skill in requirements.preferred_skills:
        max_points += 3.0  # Preferred = 1x weight
        if keyword_in_text(skill, projects_text):
            total_points += 3.0
            matched_preferred.append(skill)
        elif keyword_in_text(skill, experience_text):
            total_points += 2.5
            matched_preferred.append(skill)
        elif keyword_in_text(skill, skills_text) or keyword_in_text(skill, other_text):
            total_points += 1.0
            matched_preferred.append(skill)
        else:
            missing_preferred.append(skill)

    score = total_points / max_points if max_points > 0 else 0.0
    return (score, matched_required, missing_required, matched_preferred, missing_preferred)


def compute_experience_relevance(experience_text: str, jd_text: str, requirements: ExtractedRequirements) -> float:
    """
    Score experience 0-1 based on role relevance + tech match.
    Dev roles score higher than PM/management for dev positions.
    """
    if not experience_text or len(experience_text.strip()) < 30:
        return 0.0

    exp_lower = experience_text.lower()
    score = 0.0

    # A. Dev role detection (0-0.4)
    dev_signals = sum(1 for r in DEV_ROLE_INDICATORS if r in exp_lower)
    non_dev_signals = sum(1 for r in NON_DEV_ROLE_INDICATORS if r in exp_lower)

    if dev_signals > 0 and non_dev_signals == 0:
        score += 0.4  # Pure dev experience
    elif dev_signals > non_dev_signals:
        score += 0.3  # Mostly dev
    elif dev_signals > 0:
        score += 0.15  # Mixed dev/non-dev
    # else 0 (no dev experience detected)

    # B. Required skills used in experience (0-0.4)
    if requirements.required_skills:
        skills_in_exp = sum(1 for s in requirements.required_skills if keyword_in_text(s, exp_lower))
        skill_ratio = skills_in_exp / len(requirements.required_skills)
        score += 0.4 * skill_ratio

    # C. TF-IDF as minor component for breadth (0-0.2)
    tfidf_sim = compute_section_similarity(experience_text, jd_text)
    score += 0.2 * min(tfidf_sim * 3, 1.0)  # Amplified TF-IDF, capped at 0.2

    return min(score, 1.0)


def compute_project_relevance(projects_text: str, jd_text: str, requirements: ExtractedRequirements) -> float:
    """
    Score projects 0-1 based on domain similarity + tech stack match + complexity.
    Domain similarity is the biggest differentiator (booking ≈ rental).
    """
    if not projects_text or len(projects_text.strip()) < 30:
        return 0.0

    proj_lower = projects_text.lower()
    score = 0.0

    # A. Domain similarity (0-0.35) — biggest differentiator
    domain_sim = compute_domain_similarity(jd_text, projects_text)
    score += 0.35 * domain_sim

    # B. Required skills demonstrated in projects (0-0.35)
    if requirements.required_skills:
        skills_in_projects = sum(1 for s in requirements.required_skills if keyword_in_text(s, proj_lower))
        req_ratio = skills_in_projects / len(requirements.required_skills)
        score += 0.35 * req_ratio

    # C. Preferred skills in projects (0-0.15)
    if requirements.preferred_skills:
        pref_in_projects = sum(1 for s in requirements.preferred_skills if keyword_in_text(s, proj_lower))
        pref_ratio = pref_in_projects / len(requirements.preferred_skills)
        score += 0.15 * pref_ratio

    # D. Complexity signals (0-0.15)
    complexity_indicators = [
        "deployed", "production", "users", "scale", "api", "database",
        "authentication", "real-time", "realtime", "microservice", "docker",
        "ci/cd", "testing", "integration", "performance", "optimization",
        "redis", "kafka", "websocket", "graphql", "grpc",
    ]
    complexity_hits = sum(1 for ind in complexity_indicators if ind in proj_lower)
    score += 0.15 * min(complexity_hits / 5, 1.0)

    return min(score, 1.0)


def compute_preference_score(section_scores: SectionScores, has_certs_in_jd: bool = True) -> int:
    """
    Weighted score based on preference order.
    Dynamically redistributes weight from zero-score dimensions.
    Base weights: Projects (35%) > Experience (25%) > Skills (25%) > Certifications (15%)
    """
    p = section_scores.projects_score
    e = section_scores.experience_score
    s = section_scores.skills_score
    c = section_scores.certifications_score

    # Start with base weights
    w_p, w_e, w_s, w_c = 0.35, 0.25, 0.25, 0.15

    # If no certs in JD, redistribute cert weight
    if not has_certs_in_jd:
        w_p, w_e, w_s, w_c = 0.35, 0.30, 0.35, 0.0

    # If experience is 0 (fresh grad), redistribute to projects and skills
    # This prevents students with great projects from being unfairly penalized
    if e < 0.01:
        w_p += w_e * 0.5  # Half of experience weight goes to projects
        w_s += w_e * 0.5  # Half goes to skills
        w_e = 0.0

    raw = w_p * p + w_e * e + w_s * s + w_c * c
    return int(raw * 100)


def normalize_and_rescore_candidates(candidates: List[Dict], has_certs_in_jd: bool) -> None:
    """
    Normalize TF-IDF section scores (projects, experience) across all candidates
    so the best score maps to 1.0 instead of raw 0.04-0.14. This gives better
    score spread and differentiation. Mutates candidates in-place.
    """
    if not candidates:
        return

    # Find max scores for TF-IDF sections
    max_projects = max((c["candidate"].section_scores.projects_score for c in candidates), default=0.001)
    max_experience = max((c["candidate"].section_scores.experience_score for c in candidates), default=0.001)

    # Avoid division by zero
    max_projects = max(max_projects, 0.001)
    max_experience = max(max_experience, 0.001)

    for entry in candidates:
        ss = entry["candidate"].section_scores
        # Normalize TF-IDF scores relative to the best candidate
        ss.projects_score = round(min(ss.projects_score / max_projects, 1.0), 3)
        ss.experience_score = round(min(ss.experience_score / max_experience, 1.0), 3)
        # Recompute the final score with normalized values
        entry["candidate"].score = compute_preference_score(ss, has_certs_in_jd=has_certs_in_jd)


# Rate limiter for LLM API calls
_last_llm_call_time = 0.0
LLM_CALL_DELAY = float(os.getenv("LLM_CALL_DELAY_SECONDS", "8"))  # seconds between calls


def _rate_limited_llm_call(model: str, messages: list, max_tokens: int = 2000, max_retries: int = 3) -> Optional[dict]:
    """
    Make a rate-limited LLM API call with retry and exponential backoff for 429 errors.
    Returns parsed JSON response content or None.
    """
    global _last_llm_call_time

    for attempt in range(max_retries):
        # Rate limiting: wait between calls
        now = time.time()
        elapsed = now - _last_llm_call_time
        if elapsed < LLM_CALL_DELAY:
            wait = LLM_CALL_DELAY - elapsed
            time.sleep(wait)
        _last_llm_call_time = time.time()

        try:
            response = requests.post(
                f"{GROQ_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                    # "response_format": {"type": "json_object"}  # Disabled - causes 400 on some models
                },
                timeout=LLM_TIMEOUT
            )

            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                print(f"  LLM raw ({model}, {len(content)} chars): {content[:300]}", flush=True)

                if not content:
                    print(f"  WARNING: Empty LLM response from {model}", flush=True)
                    return None

                # Parse JSON from response
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                return json.loads(content)

            elif response.status_code == 429:
                # Rate limited - parse retry delay from error or use exponential backoff
                retry_delay = (attempt + 1) * 10  # 10s, 20s, 30s
                try:
                    err = response.json()
                    msg = err.get("error", {}).get("message", "")
                    # Parse "try again in Xs" from error
                    match = re.search(r'try again in ([\d.]+)', msg)
                    if match:
                        retry_delay = max(float(match.group(1)) + 2, 5)  # add 2s buffer
                except:
                    pass
                print(f"  Rate limited ({model}), waiting {retry_delay:.1f}s (attempt {attempt+1}/{max_retries})", flush=True)
                time.sleep(retry_delay)
                continue  # retry

            else:
                print(f"LLM eval error ({model}): {response.status_code} - {response.text[:300]}", flush=True)
                return None

        except json.JSONDecodeError as e:
            print(f"LLM eval JSON parse error ({model}): {e}", flush=True)
            return None
        except Exception as e:
            print(f"LLM eval error ({model}): {e}", flush=True)
            return None

    return None  # All retries exhausted


def create_candidate_summary(sections: Dict[str, str]) -> str:
    """
    Create a compact but COMPLETE structured summary from parsed resume sections.
    Removes formatting noise (bullets, extra whitespace) but keeps ALL content.
    """
    summary_parts = []

    # Projects: full content, cleaned formatting
    projects = sections.get('projects', '').strip()
    if projects:
        clean = re.sub(r'\s+', ' ', projects).strip()
        summary_parts.append(f"PROJECTS: {clean[:600]}")

    # Experience: full content, cleaned formatting
    experience = sections.get('experience', '').strip()
    if experience:
        clean = re.sub(r'\s+', ' ', experience).strip()
        summary_parts.append(f"EXPERIENCE: {clean[:500]}")

    # Skills: full list, one line
    skills = sections.get('skills', '').strip()
    if skills:
        clean = re.sub(r'\s+', ' ', skills).strip()
        summary_parts.append(f"SKILLS: {clean[:300]}")

    # Certifications: full list
    certs = sections.get('certifications', '').strip()
    if certs:
        clean = re.sub(r'\s+', ' ', certs).strip()
        summary_parts.append(f"CERTS: {clean[:200]}")

    return '\n'.join(summary_parts) if summary_parts else '(Empty resume)'


def _parse_llm_scores(parsed: dict) -> LlmContextualScores:
    """Parse a single candidate's scores from LLM JSON response."""
    return LlmContextualScores(
        projects=LlmDimensionScore(
            score=min(100, max(0, int(parsed.get("projects_score", 0)))),
            reasoning=str(parsed.get("projects_reasoning", ""))
        ),
        experience=LlmDimensionScore(
            score=min(100, max(0, int(parsed.get("experience_score", 0)))),
            reasoning=str(parsed.get("experience_reasoning", ""))
        ),
        certifications=LlmDimensionScore(
            score=min(100, max(0, int(parsed.get("certifications_score", 0)))),
            reasoning=str(parsed.get("certifications_reasoning", ""))
        ),
        skills=LlmDimensionScore(
            score=min(100, max(0, int(parsed.get("skills_score", 0)))),
            reasoning=str(parsed.get("skills_reasoning", ""))
        ),
    )


def _evaluate_single_candidate(name: str, summary: str, jd_text: str, requirements: ExtractedRequirements, role_label: str = "") -> Optional[LlmContextualScores]:
    """Fallback: evaluate 1 candidate when batch fails. Simpler prompt for smaller models."""
    req_skills = ', '.join(requirements.required_skills[:15]) if requirements.required_skills else 'None'
    pref_skills = ', '.join(requirements.preferred_skills[:10]) if requirements.preferred_skills else 'None'

    role_instruction = f" for the {role_label} role" if role_label else ""

    prompt = f"""Score this candidate 0-100 on 4 areas{role_instruction}.
Rules: Skills used in projects count double. Similar project domains score high.

JD: {jd_text[:400]}
Required: {req_skills}
Preferred: {pref_skills}

{name}: {summary}

Return JSON: {{"projects_score":N,"experience_score":N,"certifications_score":N,"skills_score":N}}"""

    messages = [
        {"role": "system", "content": f"Score candidate 0-100{role_instruction}. Return JSON only."},
        {"role": "user", "content": prompt}
    ]

    parsed = _rate_limited_llm_call(PRIMARY_MODEL, messages, max_tokens=1000)
    if parsed is None:
        parsed = _rate_limited_llm_call(FALLBACK_MODEL, messages, max_tokens=1000)
    if parsed is None:
        return None

    try:
        return _parse_llm_scores(parsed)
    except Exception as e:
        print(f"  Error parsing single candidate LLM response: {e}", flush=True)
        return None


def evaluate_candidates_batch(
    batch: List[Dict],  # [{name, summary, idx}]
    jd_text: str,
    requirements: ExtractedRequirements,
    role_label: str = "",
) -> Dict[int, LlmContextualScores]:
    """
    Evaluate up to 3 candidates in a SINGLE LLM call.
    Sends JD once + all candidate summaries = token savings.
    Returns dict mapping candidate idx -> LlmContextualScores.
    Falls back to individual calls if batch fails.
    """
    if not GROQ_API_KEY or not batch:
        return {}

    req_skills = ', '.join(requirements.required_skills[:15]) if requirements.required_skills else 'None'
    pref_skills = ', '.join(requirements.preferred_skills[:10]) if requirements.preferred_skills else 'None'

    # Build candidate sections
    candidate_sections = []
    for i, entry in enumerate(batch):
        candidate_sections.append(f"CANDIDATE {i+1} ({entry['name']}):\n{entry['summary']}")

    candidates_text = '\n\n'.join(candidate_sections)

    role_instruction = f" for the {role_label} role" if role_label else ""
    role_context = f"\nRole: {role_label}. Score candidates ONLY on {role_label}-relevant skills and experience." if role_label else ""

    prompt = f"""Score each candidate 0-100 on 4 areas{role_instruction}.
Rules: Skills used in projects count double vs just listed. Similar project domains score high. Dev experience > PM/management.{role_context}

JD: {jd_text[:500]}
Required: {req_skills}
Preferred: {pref_skills}

{candidates_text}

Return JSON: {{"candidates":[{{"name":"...","projects_score":N,"experience_score":N,"certifications_score":N,"skills_score":N}}]}}"""

    messages = [
        {"role": "system", "content": f"Score candidates 0-100{role_instruction}. Return JSON object with candidates array only."},
        {"role": "user", "content": prompt}
    ]

    # Try primary model
    parsed = _rate_limited_llm_call(PRIMARY_MODEL, messages, max_tokens=2000)

    # Fallback model
    if parsed is None:
        parsed = _rate_limited_llm_call(FALLBACK_MODEL, messages, max_tokens=2000)

    # Parse response
    results = {}
    if parsed is not None:
        try:
            # Handle {"candidates": [...]} format
            candidates_list = None
            if isinstance(parsed, dict) and "candidates" in parsed:
                candidates_list = parsed["candidates"]
            elif isinstance(parsed, list):
                candidates_list = parsed
            elif isinstance(parsed, dict) and len(batch) == 1:
                # Single candidate as flat dict
                results[batch[0]['idx']] = _parse_llm_scores(parsed)
                return results

            if candidates_list:
                for i, item in enumerate(candidates_list):
                    if i < len(batch) and isinstance(item, dict):
                        results[batch[i]['idx']] = _parse_llm_scores(item)
        except Exception as e:
            print(f"  Error parsing batch LLM response: {e}", flush=True)

    # If batch failed or partial, try individual calls for missing candidates
    if len(results) < len(batch):
        missing = [entry for entry in batch if entry['idx'] not in results]
        if missing:
            print(f"  Batch returned {len(results)}/{len(batch)}, trying individual calls for {len(missing)} remaining...", flush=True)
            for entry in missing:
                individual = _evaluate_single_candidate(entry['name'], entry['summary'], jd_text, requirements, role_label=role_label)
                if individual:
                    results[entry['idx']] = individual

    return results


def compute_llm_contextual_score(llm_scores: LlmContextualScores, has_certs_in_jd: bool = True) -> int:
    """Compute weighted score from LLM contextual scores with cert redistribution."""
    if has_certs_in_jd:
        return int(
            0.35 * llm_scores.projects.score +
            0.25 * llm_scores.experience.score +
            0.15 * llm_scores.certifications.score +
            0.25 * llm_scores.skills.score
        )
    else:
        # No certs in JD - redistribute to skills and experience
        return int(
            0.35 * llm_scores.projects.score +
            0.30 * llm_scores.experience.score +
            0.35 * llm_scores.skills.score
        )


# ============================================
# Scoring
# ============================================

def compute_similarity(jd_text: str, resume_text: str) -> float:
    """Compute TF-IDF cosine similarity between JD and resume."""
    try:
        vectorizer = TfidfVectorizer(stop_words='english', max_features=1000)
        tfidf_matrix = vectorizer.fit_transform([jd_text, resume_text])
        similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
        return float(similarity)
    except Exception as e:
        print(f"Error computing similarity: {e}", flush=True)
        return 0.0

def compute_score(similarity: float, keyword_coverage: float) -> int:
    """
    Compute final score (0-100).
    70% TF-IDF similarity + 30% keyword coverage
    """
    final = 0.70 * similarity + 0.30 * keyword_coverage
    return int(final * 100)


def compute_weighted_score(
    similarity: float,
    matched_required: int,
    total_required: int,
    matched_preferred: int,
    total_preferred: int
) -> int:
    """
    Compute weighted score based on:
    - 60% required skills match
    - 25% preferred skills match
    - 15% TF-IDF similarity
    """
    required_score = matched_required / total_required if total_required > 0 else 0.5
    preferred_score = matched_preferred / total_preferred if total_preferred > 0 else 0.5

    final = (
        0.60 * required_score +
        0.25 * preferred_score +
        0.15 * similarity
    )
    return int(final * 100)

# ============================================
# LLM Integration
# ============================================

def create_resume_summary(text: str, max_length: int = MAX_SUMMARY_LENGTH) -> str:
    """Create a short summary of the resume for LLM context."""
    # Take first portion of text
    normalized = normalize_text(text)
    if len(normalized) <= max_length:
        return normalized
    return normalized[:max_length] + "..."

def generate_llm_explanation(
    candidate_name: str,
    resume_summary: str,
    matched_keywords: List[str],
    missing_keywords: List[str],
    score: int,
    jd_text: str,
    model: str,
    section_scores: Optional['SectionScores'] = None,
    resume_sections: Optional[Dict[str, str]] = None,
    role_label: str = "",
) -> Optional[str]:
    """Generate an explanation using the LLM."""
    if not GROQ_API_KEY:
        return None

    # Build section context for the LLM
    section_context = ""
    if resume_sections:
        projects_text = resume_sections.get('projects', '').strip()[:300]
        certs_text = resume_sections.get('certifications', '').strip()[:200]
        if projects_text:
            section_context += f"\nCandidate's Projects: {projects_text}..."
        if certs_text:
            section_context += f"\nCandidate's Certifications: {certs_text}..."

    score_context = ""
    if section_scores:
        score_context = f"\nKeyword Scores - Projects: {int(section_scores.projects_score*100)}%, Experience: {int(section_scores.experience_score*100)}%, Certifications: {int(section_scores.certifications_score*100)}%, Skills: {int(section_scores.skills_score*100)}%"

    role_context = f"\nIMPORTANT: You are evaluating this candidate specifically for the **{role_label}** role. Focus ONLY on {role_label}-relevant skills and experience." if role_label else ""

    prompt = f"""Based on the following information, provide a 2-3 sentence assessment of this candidate for the {role_label + ' ' if role_label else ''}role:

Job Description ({role_label or 'Role'} Requirements): {jd_text[:500]}...{role_context}

Candidate: {candidate_name}
Match Score: {score}/100{score_context}
Matched Skills: {', '.join(matched_keywords[:10]) if matched_keywords else 'None identified'}
Missing Skills: {', '.join(missing_keywords[:10]) if missing_keywords else 'None identified'}
Resume Summary: {resume_summary}{section_context}

Provide exactly 3 short sentences:
1. How this candidate's projects and experience relate to the {role_label + ' ' if role_label else ''}role specifically (mention specific projects if relevant)
2. Assessment of their certifications and key skill gaps for this {role_label + ' ' if role_label else ''}position
3. A suggested interview focus area

Be concise and factual. Reference their actual projects/certs when available. Do not hallucinate skills not mentioned. Do not reference other roles (e.g. do not mention backend if evaluating for frontend)."""

    messages = [
        {"role": "system", "content": "You are a concise HR assistant providing brief candidate assessments."},
        {"role": "user", "content": prompt}
    ]

    # Use rate-limited call to avoid 429 errors
    try:
        # _rate_limited_llm_call returns parsed JSON, but for explanations we need raw text
        # So we make a direct rate-limited call
        global _last_llm_call_time
        now = time.time()
        elapsed = now - _last_llm_call_time
        if elapsed < LLM_CALL_DELAY:
            time.sleep(LLM_CALL_DELAY - elapsed)
        _last_llm_call_time = time.time()

        response = requests.post(
            f"{GROQ_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": 1500,
                "temperature": 0.3
            },
            timeout=LLM_TIMEOUT
        )

        if response.status_code == 200:
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            return content if content else None
        elif response.status_code == 429:
            # Rate limited - wait and retry once
            time.sleep(15)
            _last_llm_call_time = time.time()
            response = requests.post(
                f"{GROQ_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": 1500, "temperature": 0.3},
                timeout=LLM_TIMEOUT
            )
            if response.status_code == 200:
                content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                return content if content else None
            print(f"LLM explanation retry failed: {response.status_code}", flush=True)
            return None
        else:
            print(f"LLM API error: {response.status_code}", flush=True)
            return None
    except Exception as e:
        print(f"LLM request error: {e}", flush=True)
        return None

def get_llm_explanation(
    candidate_name: str,
    resume_text: str,
    matched_keywords: List[str],
    missing_keywords: List[str],
    score: int,
    jd_text: str,
    section_scores: Optional['SectionScores'] = None,
    resume_sections: Optional[Dict[str, str]] = None,
    role_label: str = "",
) -> str:
    """Get LLM explanation with fallback model support."""
    resume_summary = create_resume_summary(resume_text)

    # Parse resume sections if not provided
    if resume_sections is None:
        resume_sections = parse_resume_sections(resume_text)

    # Try primary model
    explanation = generate_llm_explanation(
        candidate_name, resume_summary, matched_keywords,
        missing_keywords, score, jd_text, PRIMARY_MODEL,
        section_scores=section_scores, resume_sections=resume_sections,
        role_label=role_label,
    )

    if explanation:
        return explanation

    # Try fallback model
    if MAX_RETRIES > 0:
        explanation = generate_llm_explanation(
            candidate_name, resume_summary, matched_keywords,
            missing_keywords, score, jd_text, FALLBACK_MODEL,
            section_scores=section_scores, resume_sections=resume_sections,
            role_label=role_label,
        )

        if explanation:
            return explanation

    # Return deterministic explanation if LLM fails
    return generate_deterministic_explanation(
        candidate_name, matched_keywords, missing_keywords, score
    )

def generate_deterministic_explanation(
    candidate_name: str,
    matched_keywords: List[str],
    missing_keywords: List[str],
    score: int
) -> str:
    """Generate a deterministic explanation without LLM."""
    parts = []

    # Match assessment
    if score >= 70:
        strength = "strong"
    elif score >= 50:
        strength = "moderate"
    else:
        strength = "limited"

    if matched_keywords:
        top_matches = matched_keywords[:5]
        parts.append(f"Shows {strength} alignment with {len(matched_keywords)} key requirements including {', '.join(top_matches)}.")
    else:
        parts.append(f"Shows {strength} overall alignment with the role requirements.")

    # Gap assessment
    if missing_keywords:
        top_missing = missing_keywords[:3]
        parts.append(f"Key gaps include: {', '.join(top_missing)}.")
    else:
        parts.append("No critical skill gaps identified.")

    # Interview suggestion
    if missing_keywords:
        parts.append(f"Recommend exploring experience with {missing_keywords[0]} during interview.")
    elif matched_keywords:
        parts.append(f"Recommend deep-diving into {matched_keywords[0]} experience.")
    else:
        parts.append("Recommend general technical assessment.")

    return " ".join(parts)

# ============================================
# File Opening
# ============================================

def open_file_locally(file_path: str) -> bool:
    """Open a file with the system's default application."""
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(file_path)
        elif system == "Darwin":  # macOS
            subprocess.run(["open", file_path], check=True)
        else:  # Linux
            subprocess.run(["xdg-open", file_path], check=True)
        return True
    except Exception as e:
        print(f"Error opening file {file_path}: {e}", flush=True)
        return False

def is_safe_path(file_path: str, root_folder: str) -> bool:
    """Check if file_path is safely within root_folder (prevent path traversal)."""
    try:
        file_resolved = Path(file_path).resolve()
        root_resolved = Path(root_folder).resolve()
        file_resolved.relative_to(root_resolved)
        return True
    except Exception:
        return False

# ============================================
# Package Management
# ============================================

def get_package_version(package_name: str) -> Optional[str]:
    """Get installed version of a package."""
    # Map package names to their import names
    package_map = {
        "scikit-learn": "sklearn",
        "python-dotenv": "dotenv",
        "python-docx": "docx",
        "PyMuPDF": "fitz",
    }

    try:
        # Try to get version from metadata
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        # Try alternate name
        alt_name = package_map.get(package_name)
        if alt_name:
            try:
                return importlib.metadata.version(alt_name)
            except:
                pass
        return None

def check_packages() -> List[Dict[str, Any]]:
    """Check status of all required packages."""
    packages = []
    for pkg in REQUIRED_PACKAGES:
        version = get_package_version(pkg)
        packages.append({
            "name": pkg,
            "version": version,
            "installed": version is not None
        })
    return packages

# ============================================
# API Endpoints
# ============================================

@app.get("/status")
async def status():
    """Health check endpoint with detailed status."""
    packages = check_packages()
    all_installed = all(p["installed"] for p in packages)
    return {
        "ready": True,
        "error": None,
        "server_name": "resumeranker",
        "port": SERVER_PORT,
        "llm_enabled": bool(GROQ_API_KEY),
        "packages_ok": all_installed
    }

@app.get("/packages")
async def get_packages():
    """Get status of required Python packages."""
    packages = check_packages()
    all_installed = all(p["installed"] for p in packages)
    return {
        "success": True,
        "packages": packages,
        "all_installed": all_installed
    }

@app.post("/shutdown")
async def shutdown():
    """Gracefully stop the local development server when launched by the UI."""
    def stop_server():
        time.sleep(0.2)
        os._exit(0)

    threading.Thread(target=stop_server, daemon=True).start()
    return {"success": True}

@app.post("/scan_folder", response_model=ScanFolderResponse)
async def scan_folder(request: ScanFolderRequest):
    """Scan a folder for resume files."""
    folder_path = request.folder_path

    if not folder_path:
        return ScanFolderResponse(success=False, error="Folder path is required")

    path = Path(folder_path)

    if not path.exists():
        return ScanFolderResponse(success=False, error=f"Folder does not exist: {folder_path}")

    if not path.is_dir():
        return ScanFolderResponse(success=False, error=f"Path is not a directory: {folder_path}")

    files = []
    try:
        for item in path.iterdir():
            if item.is_file() and item.suffix.lower() in ALLOWED_EXTENSIONS:
                stat = item.stat()
                files.append(FileInfo(
                    name=item.name,
                    path=str(item.resolve()),
                    ext=item.suffix.lower(),
                    modified=datetime.fromtimestamp(stat.st_mtime).isoformat()
                ))

        # Sort by modification time (newest first)
        files.sort(key=lambda x: x.modified, reverse=True)

        return ScanFolderResponse(
            success=True,
            count=len(files),
            files=files
        )
    except Exception as e:
        return ScanFolderResponse(success=False, error=str(e))

@app.post("/analyze_jd", response_model=AnalyzeJdResponse)
async def analyze_jd(request: AnalyzeJdRequest):
    """
    Analyze job description and extract requirements.
    Accepts either text or a file path (PDF/DOCX/TXT).
    Uses LLM if enabled, otherwise falls back to rule-based extraction.
    """
    jd_text = request.job_description
    jd_file_path = request.jd_file_path
    use_llm = request.use_llm

    # Extract text from file if path provided
    if jd_file_path and jd_file_path.strip():
        jd_path = Path(jd_file_path.strip())
        if not jd_path.exists():
            return AnalyzeJdResponse(success=False, error=f"File not found: {jd_file_path}")
        if jd_path.suffix.lower() not in ALLOWED_EXTENSIONS:
            return AnalyzeJdResponse(success=False, error=f"Unsupported file type: {jd_path.suffix}")
        jd_text = extract_resume_text(str(jd_path.resolve()))
        print(f"Extracted JD from file: {len(jd_text)} chars", flush=True)

    if not jd_text or len(jd_text.strip()) < 20:
        return AnalyzeJdResponse(success=False, error="Job description is too short or could not be read")

    try:
        # Step 1: Check for multiple roles (pre-scan + per-section extraction)
        roles = detect_and_extract_roles(jd_text, use_llm=use_llm)
        if roles and len(roles) >= 2:
            print(f"Detected {len(roles)} roles: {[r.role_label for r in roles]}", flush=True)
            return AnalyzeJdResponse(
                success=True,
                requirements=roles[0].requirements,
                roles=roles
            )

        # Step 2: Single role - standard analysis
        requirements = analyze_job_description(jd_text, use_llm=use_llm)
        return AnalyzeJdResponse(success=True, requirements=requirements)
    except Exception as e:
        print(f"Error analyzing JD: {e}", flush=True)
        return AnalyzeJdResponse(success=False, error=str(e))


@app.post("/rank", response_model=RankResponse)
async def rank_resumes(request: RankRequest):
    """
    Rank resumes against a job description.
    Accepts either pasted text (job_description) or a file path (jd_file_path).
    """
    folder_path = request.folder_path
    jd_text = request.job_description
    jd_file_path = request.jd_file_path
    use_llm = request.use_llm
    use_llm_for_jd = request.use_llm_for_jd
    top_n = min(request.top_n, 20)  # Cap at 20

    # If a JD file was uploaded, extract text from it
    if jd_file_path and jd_file_path.strip():
        jd_path = Path(jd_file_path.strip())
        if not jd_path.exists():
            return RankResponse(success=False, error=f"JD file not found: {jd_file_path}")
        if jd_path.suffix.lower() not in ALLOWED_EXTENSIONS:
            return RankResponse(success=False, error=f"Unsupported JD file type: {jd_path.suffix}")
        jd_text = extract_resume_text(str(jd_path.resolve()))
        if not jd_text or len(jd_text.strip()) < 20:
            return RankResponse(success=False, error="Could not extract text from JD file")
        print(f"Extracted JD text from file: {len(jd_text)} chars", flush=True)

    if not folder_path or not jd_text or not jd_text.strip():
        return RankResponse(success=False, error="Folder path and job description are required")

    path = Path(folder_path)

    if not path.exists() or not path.is_dir():
        return RankResponse(success=False, error=f"Invalid folder: {folder_path}")

    # Use provided requirements or analyze JD
    if request.requirements:
        requirements = request.requirements
    else:
        requirements = analyze_job_description(jd_text, use_llm=use_llm_for_jd)

    # If no skills found, return error
    if not requirements.required_skills and not requirements.preferred_skills:
        return RankResponse(
            success=False,
            error="Could not extract any skills from job description. Please check the JD format."
        )

    use_deep_eval = request.use_deep_eval
    candidates = []
    normalized_jd = normalize_text(jd_text)
    has_certs_in_jd = bool(requirements.certifications and len(requirements.certifications) > 0)

    try:
        # ---- STAGE 1: Section-based scoring (FREE, runs on ALL resumes) ----
        print(f"Stage 1: Scoring all resumes with section-based analysis...", flush=True)

        for item in path.iterdir():
            if not item.is_file() or item.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue

            file_path = str(item.resolve())

            # Extract resume text
            resume_text = extract_resume_text(file_path)
            if not resume_text or len(resume_text.strip()) < 50:
                continue  # Skip empty or very short files

            # Parse resume into sections
            sections = parse_resume_sections(resume_text)

            # Extract candidate name
            candidate_name = extract_candidate_name(resume_text, file_path)

            # --- NEW Stage 1: Demonstrated skills + Domain similarity + Experience relevance ---

            # 1. Demonstrated skills score (WHERE skills appear matters)
            skills_result = compute_demonstrated_skills_score(sections, requirements)
            skills_score = skills_result[0]
            matched_required = skills_result[1]
            missing_required = skills_result[2]
            matched_preferred = skills_result[3]
            missing_preferred = skills_result[4]

            # 2. Project relevance (domain + tech + complexity)
            projects_score = compute_project_relevance(sections['projects'], jd_text, requirements)

            # 3. Experience relevance (role type + tech match)
            experience_score = compute_experience_relevance(sections['experience'], jd_text, requirements)

            # 4. Certifications (keyword match ratio - unchanged)
            cert_match_count = find_cert_matches(resume_text, requirements.certifications)
            cert_total = len(requirements.certifications) if requirements.certifications else 0
            cert_score = cert_match_count / cert_total if cert_total > 0 else 0.0

            section_scores = SectionScores(
                projects_score=round(projects_score, 3),
                experience_score=round(experience_score, 3),
                certifications_score=round(cert_score, 3),
                skills_score=round(skills_score, 3)
            )

            # Compute preference-weighted score
            score = compute_preference_score(section_scores, has_certs_in_jd=has_certs_in_jd)

            # Overall TF-IDF similarity (for display)
            similarity = compute_similarity(normalized_jd, normalize_text(resume_text))

            # Keyword coverage (for display - unweighted)
            req_matched = len(matched_required)
            pref_matched = len(matched_preferred)
            req_total = len(requirements.required_skills)
            pref_total = len(requirements.preferred_skills)
            matched_count = req_matched + pref_matched
            total_skills = req_total + pref_total
            keyword_coverage = matched_count / total_skills if total_skills > 0 else 0

            # Deterministic explanation
            all_matched = matched_required + matched_preferred
            all_missing = missing_required + missing_preferred
            explanation = generate_deterministic_explanation(
                candidate_name, all_matched, all_missing, score
            )

            candidates.append({
                "candidate": RankedCandidate(
                    candidate_name=candidate_name,
                    file_name=item.name,
                    file_path=file_path,
                    score=score,
                    similarity=round(similarity, 3),
                    keyword_coverage=round(keyword_coverage, 3),
                    matched_required=matched_required[:15],
                    missing_required=missing_required[:10],
                    matched_preferred=matched_preferred[:10],
                    missing_preferred=missing_preferred[:10],
                    explanation=explanation,
                    section_scores=section_scores,
                ),
                "resume_text": resume_text,  # Keep for Stage 2
                "sections": sections,  # Cache for LLM eval
            })

        # Sort by section-based score
        candidates.sort(key=lambda x: x["candidate"].score, reverse=True)

        # Deduplicate by candidate name (keep highest scoring version)
        seen_names = set()
        deduped = []
        for entry in candidates:
            name = entry["candidate"].candidate_name.strip().lower()
            if name and name not in seen_names:
                seen_names.add(name)
                deduped.append(entry)
            elif not name:
                deduped.append(entry)  # Keep unnamed entries
        if len(deduped) < len(candidates):
            print(f"Deduplicated: {len(candidates)} -> {len(deduped)} candidates", flush=True)
        candidates = deduped

        print(f"Stage 1 complete: {len(candidates)} resumes scored", flush=True)

        # ---- STAGE 2: Batch LLM Deep Evaluation (always runs if API key available) ----
        if use_deep_eval and GROQ_API_KEY:
            shortlist_size = min(top_n * 4, len(candidates))
            shortlisted = candidates[:shortlist_size]
            print(f"Stage 2: Batch LLM evaluation on top {shortlist_size} candidates...", flush=True)

            # Create structured summaries for all shortlisted
            summaries = []
            for i, entry in enumerate(shortlisted):
                r_sections = entry.get("sections") or parse_resume_sections(entry["resume_text"])
                summary = create_candidate_summary(r_sections)
                summaries.append({"name": entry["candidate"].candidate_name, "summary": summary, "idx": i})

            # Process in batches of 3
            BATCH_SIZE = 3
            eval_success = 0
            for batch_start in range(0, len(summaries), BATCH_SIZE):
                batch = summaries[batch_start:batch_start + BATCH_SIZE]
                batch_num = (batch_start // BATCH_SIZE) + 1
                total_batches = (len(summaries) + BATCH_SIZE - 1) // BATCH_SIZE
                batch_names = [b['name'] for b in batch]
                print(f"  Batch {batch_num}/{total_batches}: {', '.join(batch_names)}", flush=True)

                batch_scores = evaluate_candidates_batch(batch, jd_text, requirements)

                for idx, scores in batch_scores.items():
                    old_score = shortlisted[idx]["candidate"].score
                    shortlisted[idx]["candidate"].llm_scores = scores
                    new_score = compute_llm_contextual_score(scores, has_certs_in_jd=has_certs_in_jd)
                    shortlisted[idx]["candidate"].score = new_score
                    cname = shortlisted[idx]["candidate"].candidate_name
                    print(f"    {cname}: {old_score} -> {new_score} (P:{scores.projects.score} E:{scores.experience.score} S:{scores.skills.score})", flush=True)
                    eval_success += 1

            # Re-sort shortlisted by LLM score
            shortlisted.sort(key=lambda x: x["candidate"].score, reverse=True)
            top_candidates = [e["candidate"] for e in shortlisted[:top_n]]
            print(f"Stage 2 complete: {eval_success}/{shortlist_size} evaluated, top {len(top_candidates)} re-ranked", flush=True)

            # Generate LLM explanations for the final top candidates
            if use_llm:
                for i, entry in enumerate(shortlisted[:top_n]):
                    cand = entry["candidate"]
                    resume_text_for_llm = entry.get("resume_text", "")
                    all_matched = cand.matched_required + cand.matched_preferred
                    all_missing = cand.missing_required + cand.missing_preferred
                    explanation = get_llm_explanation(
                        cand.candidate_name, resume_text_for_llm,
                        all_matched, all_missing, cand.score, jd_text,
                        section_scores=cand.section_scores,
                        resume_sections=parse_resume_sections(resume_text_for_llm) if resume_text_for_llm else None,
                    )
                    if explanation and i < len(top_candidates):
                        top_candidates[i].explanation = explanation
        else:
            # No LLM API key - use section-based scores directly
            top_candidates = [e["candidate"] for e in candidates[:top_n]]

        return RankResponse(
            success=True,
            data=top_candidates,
            requirements_used=requirements
        )

    except Exception as e:
        print(f"Error ranking resumes: {e}", flush=True)
        return RankResponse(success=False, error=str(e))


@app.post("/rank_multi", response_model=RankMultiResponse)
async def rank_multi(request: RankMultiRequest):
    """
    Rank resumes against MULTIPLE job descriptions.
    Reads resumes once, evaluates against each JD separately.
    Returns top N for each JD.
    """
    folder_path = request.folder_path
    jd_entries = request.jd_entries
    use_llm = request.use_llm
    use_llm_for_jd = request.use_llm_for_jd
    use_deep_eval = request.use_deep_eval
    top_n = min(request.top_n, 20)

    if not folder_path:
        return RankMultiResponse(success=False, error="Folder path is required")

    if not jd_entries:
        return RankMultiResponse(success=False, error="At least one JD is required")

    path = Path(folder_path)
    if not path.exists() or not path.is_dir():
        return RankMultiResponse(success=False, error=f"Invalid folder: {folder_path}")

    try:
        # ---- Read ALL resumes ONCE ----
        print(f"Reading resumes from {folder_path}...", flush=True)
        resume_cache = []  # list of (file_path, file_name, resume_text, candidate_name, sections)

        for item in path.iterdir():
            if not item.is_file() or item.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            file_path = str(item.resolve())
            resume_text = extract_resume_text(file_path)
            if not resume_text or len(resume_text.strip()) < 50:
                continue
            candidate_name = extract_candidate_name(resume_text, file_path)
            sections = parse_resume_sections(resume_text)
            resume_cache.append({
                "file_path": file_path,
                "file_name": item.name,
                "resume_text": resume_text,
                "candidate_name": candidate_name,
                "sections": sections,
            })

        print(f"Loaded {len(resume_cache)} resumes into cache", flush=True)

        # ---- Evaluate each JD ----
        jd_results = []

        for jd_entry in jd_entries:
            jd_text = jd_entry.jd_text
            jd_file_path = jd_entry.jd_file_path

            # Extract text from JD file if needed
            if jd_file_path and jd_file_path.strip():
                jd_path = Path(jd_file_path.strip())
                if jd_path.exists() and jd_path.suffix.lower() in ALLOWED_EXTENSIONS:
                    jd_text = extract_resume_text(str(jd_path.resolve()))

            if not jd_text or len(jd_text.strip()) < 20:
                jd_results.append(JdRankResult(
                    jd_label=jd_entry.jd_label or "Unknown JD",
                    candidates=[],
                    requirements_used=ExtractedRequirements()
                ))
                continue

            # Get requirements for this JD
            if jd_entry.requirements:
                requirements = jd_entry.requirements
            else:
                requirements = analyze_job_description(jd_text, use_llm=use_llm_for_jd)

            if not requirements.required_skills and not requirements.preferred_skills:
                jd_results.append(JdRankResult(
                    jd_label=jd_entry.jd_label or "Unknown JD",
                    candidates=[],
                    requirements_used=requirements
                ))
                continue

            normalized_jd = normalize_text(jd_text)
            has_certs_in_jd = bool(requirements.certifications and len(requirements.certifications) > 0)

            # Score all resumes against this JD (NEW Stage 1)
            candidates = []
            for r in resume_cache:
                sections = r["sections"]

                # 1. Demonstrated skills score (WHERE skills appear matters)
                skills_result = compute_demonstrated_skills_score(sections, requirements)
                skills_score = skills_result[0]
                matched_required = skills_result[1]
                missing_required = skills_result[2]
                matched_preferred = skills_result[3]
                missing_preferred = skills_result[4]

                # 2. Project relevance (domain + tech + complexity)
                projects_score = compute_project_relevance(sections['projects'], jd_text, requirements)

                # 3. Experience relevance (role type + tech match)
                experience_score = compute_experience_relevance(sections['experience'], jd_text, requirements)

                # 4. Certifications (keyword match ratio - unchanged)
                cert_match_count = find_cert_matches(r["resume_text"], requirements.certifications)
                cert_total = len(requirements.certifications) if requirements.certifications else 0
                cert_score = cert_match_count / cert_total if cert_total > 0 else 0.0

                section_scores = SectionScores(
                    projects_score=round(projects_score, 3),
                    experience_score=round(experience_score, 3),
                    certifications_score=round(cert_score, 3),
                    skills_score=round(skills_score, 3)
                )

                score = compute_preference_score(section_scores, has_certs_in_jd=has_certs_in_jd)
                similarity = compute_similarity(normalized_jd, normalize_text(r["resume_text"]))

                req_matched = len(matched_required)
                pref_matched = len(matched_preferred)
                req_total = len(requirements.required_skills)
                pref_total = len(requirements.preferred_skills)
                matched_count = req_matched + pref_matched
                total_skills = req_total + pref_total
                keyword_coverage = matched_count / total_skills if total_skills > 0 else 0

                all_matched = matched_required + matched_preferred
                all_missing = missing_required + missing_preferred
                explanation = generate_deterministic_explanation(
                    r["candidate_name"], all_matched, all_missing, score
                )

                candidates.append({
                    "candidate": RankedCandidate(
                        candidate_name=r["candidate_name"],
                        file_name=r["file_name"],
                        file_path=r["file_path"],
                        score=score,
                        similarity=round(similarity, 3),
                        keyword_coverage=round(keyword_coverage, 3),
                        matched_required=matched_required[:15],
                        missing_required=missing_required[:10],
                        matched_preferred=matched_preferred[:10],
                        missing_preferred=missing_preferred[:10],
                        explanation=explanation,
                        section_scores=section_scores,
                    ),
                    "resume_text": r["resume_text"],
                    "sections": sections,
                })

            # Sort and shortlist
            candidates.sort(key=lambda x: x["candidate"].score, reverse=True)

            # Deduplicate by candidate name (keep highest scoring version)
            seen_names = set()
            deduped = []
            for entry in candidates:
                name = entry["candidate"].candidate_name.strip().lower()
                if name and name not in seen_names:
                    seen_names.add(name)
                    deduped.append(entry)
                elif not name:
                    deduped.append(entry)
            candidates = deduped

            # Batch LLM deep eval on shortlisted (always runs if API key available)
            # Extract role label for LLM context (e.g. "RentL Dev [Backend]" -> "Backend")
            batch_role_label = ""
            if jd_entry.jd_label:
                label = jd_entry.jd_label
                if '[' in label and ']' in label:
                    batch_role_label = label.split('[')[-1].rstrip(']').strip()
                else:
                    batch_role_label = label

            if use_deep_eval and GROQ_API_KEY:
                shortlist_size = min(top_n * 4, len(candidates))
                shortlisted = candidates[:shortlist_size]
                print(f"  Stage 2: Batch LLM evaluation on top {shortlist_size} for '{jd_entry.jd_label}' (role: {batch_role_label})...", flush=True)

                # Create structured summaries
                summaries = []
                for i, entry in enumerate(shortlisted):
                    r_sections = entry.get("sections") or parse_resume_sections(entry["resume_text"])
                    summary = create_candidate_summary(r_sections)
                    summaries.append({"name": entry["candidate"].candidate_name, "summary": summary, "idx": i})

                # Process in batches of 3
                BATCH_SIZE = 3
                eval_success = 0
                for batch_start in range(0, len(summaries), BATCH_SIZE):
                    batch = summaries[batch_start:batch_start + BATCH_SIZE]
                    batch_num = (batch_start // BATCH_SIZE) + 1
                    total_batches = (len(summaries) + BATCH_SIZE - 1) // BATCH_SIZE
                    print(f"    Batch {batch_num}/{total_batches}: {', '.join(b['name'] for b in batch)}", flush=True)

                    batch_scores = evaluate_candidates_batch(batch, jd_text, requirements, role_label=batch_role_label)

                    for idx, scores in batch_scores.items():
                        old_score = shortlisted[idx]["candidate"].score
                        shortlisted[idx]["candidate"].llm_scores = scores
                        new_score = compute_llm_contextual_score(scores, has_certs_in_jd=has_certs_in_jd)
                        shortlisted[idx]["candidate"].score = new_score
                        cname = shortlisted[idx]["candidate"].candidate_name
                        print(f"      {cname}: {old_score} -> {new_score}", flush=True)
                        eval_success += 1

                print(f"  Stage 2 done for '{jd_entry.jd_label}': {eval_success}/{shortlist_size} evaluated", flush=True)
                candidates[:shortlist_size] = sorted(
                    candidates[:shortlist_size],
                    key=lambda x: x["candidate"].score, reverse=True
                )

            top_candidates = [e["candidate"] for e in candidates[:top_n]]

            # Generate LLM explanations for top candidates
            # Extract role label from jd_label (e.g. "RentL Dev [Backend]" -> "Backend")
            role_label = ""
            if jd_entry.jd_label:
                label = jd_entry.jd_label
                if '[' in label and ']' in label:
                    role_label = label.split('[')[-1].rstrip(']').strip()
                else:
                    role_label = label

            if use_llm and GROQ_API_KEY:
                for i, entry in enumerate(candidates[:top_n]):
                    cand = entry["candidate"]
                    resume_text_for_llm = entry.get("resume_text", "")
                    all_matched = cand.matched_required + cand.matched_preferred
                    all_missing = cand.missing_required + cand.missing_preferred
                    explanation = get_llm_explanation(
                        cand.candidate_name, resume_text_for_llm,
                        all_matched, all_missing, cand.score, jd_text,
                        section_scores=cand.section_scores,
                        resume_sections=parse_resume_sections(resume_text_for_llm) if resume_text_for_llm else None,
                        role_label=role_label,
                    )
                    if explanation and i < len(top_candidates):
                        top_candidates[i].explanation = explanation

            jd_results.append(JdRankResult(
                jd_label=jd_entry.jd_label or "Unknown JD",
                candidates=top_candidates,
                requirements_used=requirements
            ))

        return RankMultiResponse(success=True, results=jd_results)

    except Exception as e:
        print(f"Error in rank_multi: {e}", flush=True)
        return RankMultiResponse(success=False, error=str(e))


@app.post("/open_file", response_model=OpenFileResponse)
async def open_file(request: OpenFileRequest):
    """Open a file with the system's default application."""
    file_path = request.path
    root_folder = request.root_folder

    if not file_path or not root_folder:
        return OpenFileResponse(success=False, error="Path and root_folder are required")

    # Security check: ensure file is within root folder
    if not is_safe_path(file_path, root_folder):
        return OpenFileResponse(success=False, error="Access denied: file is outside the allowed folder")

    # Check file exists
    path = Path(file_path)
    if not path.exists():
        return OpenFileResponse(success=False, error="File does not exist")

    # Check extension is allowed
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        return OpenFileResponse(success=False, error=f"File type not allowed: {path.suffix}")

    # Open the file
    if open_file_locally(file_path):
        return OpenFileResponse(success=True)
    else:
        return OpenFileResponse(success=False, error="Failed to open file")

@app.post("/extract_text", response_model=ExtractTextResponse)
async def extract_text(request: ExtractTextRequest):
    """Extract text from a PDF, DOCX, or TXT file (for job description upload)."""
    file_path = request.file_path

    if not file_path:
        return ExtractTextResponse(success=False, error="File path is required")

    path = Path(file_path)

    if not path.exists():
        return ExtractTextResponse(success=False, error="File does not exist")

    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        return ExtractTextResponse(success=False, error=f"File type not supported: {path.suffix}. Use PDF, DOCX, or TXT.")

    try:
        text = extract_resume_text(str(path.resolve()))
        if not text or len(text.strip()) < 10:
            return ExtractTextResponse(success=False, error="Could not extract text from file (empty or unreadable)")
        return ExtractTextResponse(success=True, text=clean_text_preserve_lines(text))
    except Exception as e:
        return ExtractTextResponse(success=False, error=f"Error extracting text: {str(e)}")

# ============================================
# Main
# ============================================

if __name__ == "__main__":
    print(f"""
================================================================
              ResumeRanker Server
----------------------------------------------------------------
  Host: {SERVER_HOST}
  Port: {SERVER_PORT}
  LLM Enabled: {bool(GROQ_API_KEY)}
  Primary Model: {PRIMARY_MODEL}
  Fallback Model: {FALLBACK_MODEL}

  Endpoints:
    GET  /status       - Health check
    POST /scan_folder  - Scan folder for resumes
    POST /analyze_jd   - Analyze JD and extract requirements
    POST /rank         - Rank resumes against single JD (top N)
    POST /rank_multi   - Rank resumes against multiple JDs
    POST /open_file    - Open resume file locally
    POST /extract_text - Extract text from PDF/DOCX/TXT
================================================================
    """, flush=True)

    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)

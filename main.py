import requests
import json
import os
import sys
import socket
import ssl
import smtplib
import re
import logging
from html import unescape
from html.parser import HTMLParser
from email.mime.text import MIMEText

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


LOGGER = logging.getLogger(__name__)
JOBICY_API_URL = "https://jobicy.com/api/v2/remote-jobs"
REMOTEOK_API_URL = "https://remoteok.com/api"
SOURCE_REQUEST_TIMEOUT = 20


class JobSourceError(RuntimeError):
    pass


EU_COUNTRY_ALIASES = {
    "at": ("austria", "vienna", "graz"),
    "be": ("belgium", "brussels", "antwerp"),
    "bg": ("bulgaria", "sofia"),
    "hr": ("croatia", "zagreb", "split"),
    "cy": ("cyprus", "nicosia", "limassol"),
    "cz": ("czechia", "czech republic", "prague"),
    "dk": ("denmark", "copenhagen", "aarhus"),
    "ee": ("estonia", "tallinn"),
    "fi": ("finland", "helsinki", "tampere"),
    "fr": ("france", "paris", "lyon", "marseille", "bordeaux"),
    "de": ("germany", "berlin", "munich", "hamburg", "frankfurt"),
    "gr": ("greece", "athens", "thessaloniki"),
    "hu": ("hungary", "budapest"),
    "ie": ("ireland", "dublin", "cork"),
    "it": ("italy", "rome", "milan", "turin", "florence"),
    "lv": ("latvia", "riga"),
    "lt": ("lithuania", "vilnius", "kaunas"),
    "lu": ("luxembourg",),
    "mt": ("malta", "valletta"),
    "nl": ("netherlands", "the netherlands", "amsterdam", "rotterdam"),
    "pl": ("poland", "warsaw", "krakow", "wroclaw"),
    "pt": ("portugal", "lisbon", "lisboa", "porto"),
    "ro": ("romania", "bucharest", "cluj"),
    "sk": ("slovakia", "bratislava"),
    "si": ("slovenia", "ljubljana"),
    "es": ("spain", "españa", "madrid", "barcelona", "valencia", "seville"),
    "se": ("sweden", "stockholm", "gothenburg"),
}
EU_COUNTRY_CODES = frozenset(EU_COUNTRY_ALIASES)
EU_WIDE_LOCATION_ALIASES = (
    "european union",
    "europe-wide",
    "europe",
    "eu-wide",
    "eu",
)
NON_EU_LOCATION_ALIASES = (
    "united states",
    "united states of america",
    "u.s.a.",
    "u.s.",
    "us",
    "usa",
    "canada",
    "australia",
    "japan",
    "united kingdom",
    "uk",
    "great britain",
    "switzerland",
    "norway",
    "india",
    "singapore",
    "new zealand",
    "brazil",
    "south africa",
    "israel",
    "united arab emirates",
)


def _location_contains(location, aliases):
    return any(
        re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", location)
        for alias in aliases
    )


def classify_eu_location(location):
    normalized = str(location or "").casefold()
    if not normalized:
        return set(), False, False
    country_codes = {
        country_code
        for country_code, aliases in EU_COUNTRY_ALIASES.items()
        if _location_contains(normalized, aliases)
    }
    is_eu_wide = _location_contains(normalized, EU_WIDE_LOCATION_ALIASES)
    is_non_eu = _location_contains(normalized, NON_EU_LOCATION_ALIASES)
    return (country_codes, is_eu_wide, is_non_eu)


def get_json_api_response(url, *, params=None, headers=None):
    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=SOURCE_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise JobSourceError(f"Job source returned invalid JSON: {url}") from exc


def get_remotive_jobs():

    url = "https://remotive.com/api/remote-jobs"

    data = get_json_api_response(url)
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise JobSourceError("Remotive returned an unexpected response format.")

    jobs = []

    for job in data.get("jobs", []):

        job_data = {
            "title": job.get("title") or "",
            "company": job.get("company_name") or "",
            "location": job.get("candidate_required_location") or "",
            "description": job.get("description") or "",
            "url": job.get("url") or "",
            "work_arrangement": "remote",
            "source": "Remotive"
        }

        jobs.append(job_data)

    return jobs


def get_arbeitnow_jobs():

    url = "https://www.arbeitnow.com/api/job-board-api"

    data = get_json_api_response(url)
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise JobSourceError("Arbeitnow returned an unexpected response format.")

    jobs = []

    for job in data.get("data", []):

        job_data = {
            "title": job.get("title") or "",
            "company": job.get("company_name") or "",
            "location": job.get("location") or "",
            "description": job.get("description") or "",
            "url": job.get("url") or "",
            "work_arrangement": "remote" if job.get("remote") else "",
            "source": "Arbeitnow"
        }

        jobs.append(job_data)

    return jobs


def get_jobicy_jobs():
    data = get_json_api_response(
        JOBICY_API_URL,
        params={"count": 200},
        headers={"Accept": "application/json"},
    )
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise JobSourceError("Jobicy returned an unexpected response format.")

    jobs = []
    for job in data["jobs"]:
        if not isinstance(job, dict):
            continue
        url = job.get("url") or ""
        if not url.startswith(("https://", "http://")):
            continue
        jobs.append({
            "title": job.get("jobTitle") or "",
            "company": job.get("companyName") or "",
            "location": job.get("jobGeo") or "Remote",
            "description": job.get("jobDescription") or job.get("jobExcerpt") or "",
            "url": url,
            "work_arrangement": "remote",
            "source": "Jobicy",
        })
    return jobs


def get_remoteok_jobs():
    data = get_json_api_response(
        REMOTEOK_API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "RemoteJobFinder/1.0 (public remote-job listings)",
        },
    )
    if not isinstance(data, list):
        raise JobSourceError("Remote OK returned an unexpected response format.")

    jobs = []
    for job in data:
        if not isinstance(job, dict) or not job.get("id"):
            continue
        url = job.get("url") or job.get("apply_url") or ""
        if not url.startswith(("https://", "http://")):
            continue
        jobs.append({
            "title": job.get("position") or "",
            "company": job.get("company") or "",
            "location": job.get("location") or "Remote",
            "description": job.get("description") or "",
            "url": url,
            "work_arrangement": "remote",
            "source": "Remote OK",
        })
    return jobs


def collect_jobs_from_sources():
    sources = (
        ("Remotive", get_remotive_jobs),
        ("Arbeitnow", get_arbeitnow_jobs),
        ("Jobicy", get_jobicy_jobs),
        ("Remote OK", get_remoteok_jobs),
    )
    collected_jobs = []
    failures = []
    successful_sources = 0
    for source_name, get_jobs in sources:
        try:
            source_jobs = get_jobs()
        except (requests.RequestException, JobSourceError, OSError, ValueError) as exc:
            failures.append(f"{source_name}: {type(exc).__name__}: {exc}")
            LOGGER.warning("Could not collect jobs from %s: %s", source_name, exc)
            continue
        successful_sources += 1
        collected_jobs.extend(source_jobs)
        LOGGER.info("Collected %s jobs from %s.", len(source_jobs), source_name)

    if not successful_sources:
        raise JobSourceError(
            "All job sources failed. " + " | ".join(failures)
        )
    return collected_jobs


senior_keywords = [
    "senior",
    "lead",
    "principal",
    "staff",
    "manager",
    "director"
]


junior_keywords = ["junior", "entry level", "graduate", "trainee", "intern"]


class JobDescriptionParser(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip_depth += 1
        elif tag in {"br", "p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1
        elif tag in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)


def get_description_text(description):

    description = str(description or "")
    for _ in range(3):
        decoded_description = unescape(description)
        if decoded_description == description:
            break
        description = decoded_description

    parser = JobDescriptionParser()
    parser.feed(description)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def is_senior_job(job):

    title = str(job.get("title") or "").lower()
    description = get_description_text(job.get("description")).lower()

    if any(keyword in title for keyword in senior_keywords):
        return True

    explicit_senior_phrases = [
        r"\bthis is (?:a|an )?(?:senior|lead|principal|staff)\b",
        r"\b(?:senior|lead|principal|staff)(?:[- ]level)?"
        r"(?:\s+(?:engineering|software|frontend|front-end|front end|web))?"
        r"\s+(?:role|position|job)\b",
        r"\b(?:role|position|job)\s+is\s+(?:a|an )?"
        r"(?:senior|lead|principal|staff)\b"
    ]
    return any(
        re.search(pattern, description)
        for pattern in explicit_senior_phrases
    )


def is_remote_work_arrangement(job):

    title = str(job.get("title") or "").lower()
    description = get_description_text(job.get("description")).lower()
    work_details = f"{title} {description}"

    non_remote_patterns = [
        r"\bhybrid(?:\s+(?:work|working|role|schedule|model|approach))?\b",
        r"\bon[- ]site\b",
        r"\bonsite\b",
        r"\bin[- ]office\b",
        r"\boffice[- ]based\b",
        r"\bremote work\s+(?:is\s+)?not\s+(?:available|offered|possible)\b",
        r"\bnot\s+(?:a\s+)?fully remote\b"
    ]
    return not any(
        re.search(pattern, work_details)
        for pattern in non_remote_patterns
    )


ROLE_FAMILIES = {
    "frontend_web": "Frontend and web development",
    "software_it": "Software and IT",
    "digital_marketing": "Digital marketing",
    "social_media": "Social media and community",
    "graphic_design": "Graphic design and creative",
    "writing_content": "Writing and content",
    "customer_support": "Customer support and success",
    "sales_business": "Sales and business development",
    "product_project": "Product and project management",
    "data_analytics": "Data and analytics",
    "hr_recruiting": "HR and recruiting",
    "operations_admin": "Operations and administration",
    "finance_accounting": "Finance and accounting",
    "education_training": "Education and training",
    "other": "Other professional roles",
}


ROLE_TITLE_PATTERNS = {
    "frontend_web": (
        r"\bfront[- ]?end\b",
        r"\bweb (?:developer|designer|engineer)\b",
        r"\breact developer\b",
        r"\bui/?ux (?:developer|designer|engineer)\b",
    ),
    "software_it": (
        r"\bsoftware\b",
        r"\bfull[- ]stack\b",
        r"\bback[- ]end\b",
        r"\bdevops\b",
        r"\bcloud engineer\b",
        r"\b(?:qa|quality assurance|test) engineer\b",
        r"\bcyber ?security\b",
        r"\bit support\b",
        r"\bsystems? administrator\b",
        r"\bnetwork engineer\b",
    ),
    "digital_marketing": (
        r"\bmarketing\b",
        r"\bseo\b",
        r"\bsem\b",
        r"\bgrowth (?:specialist|manager|marketer)\b",
        r"\bperformance marketing\b",
        r"\bpaid (?:search|media|ads)\b",
        r"\bemail marketer\b",
        r"\bppc\b",
    ),
    "social_media": (
        r"\bsocial media\b",
        r"\bcommunity manager\b",
        r"\binfluencer\b",
        r"\bcontent creator\b",
    ),
    "graphic_design": (
        r"\bgraphic designer\b",
        r"\bvisual designer\b",
        r"\bbrand designer\b",
        r"\billustrator\b",
        r"\bmotion designer\b",
        r"\bart director\b",
    ),
    "writing_content": (
        r"\bcopywriter\b",
        r"\bcontent writer\b",
        r"\btechnical writer\b",
        r"\b(?:content|copy) editor\b",
        r"\bwriter\b",
    ),
    "customer_support": (
        r"\bcustomer support\b",
        r"\bcustomer service\b",
        r"\bcustomer success\b",
        r"\bhelp ?desk\b",
        r"\b(?:client|customer) care\b",
    ),
    "sales_business": (
        r"\bsales\b",
        r"\bbusiness development\b",
        r"\baccount executive\b",
        r"\b(?:sdr|bdr)\b",
    ),
    "product_project": (
        r"\bproduct manager\b",
        r"\bproduct owner\b",
        r"\bproject manager\b",
        r"\bprogram manager\b",
        r"\bproject coordinator\b",
        r"\bscrum master\b",
    ),
    "data_analytics": (
        r"\bdata (?:analyst|scientist|engineer)\b",
        r"\b(?:business intelligence|bi) analyst\b",
        r"\banalytics?\b",
        r"\bresearch analyst\b",
    ),
    "hr_recruiting": (
        r"\brecruit(?:er|ing)\b",
        r"\btalent acquisition\b",
        r"\bhuman resources\b",
        r"\bhr (?:specialist|manager|coordinator)\b",
    ),
    "operations_admin": (
        r"\boperations?\b",
        r"\bvirtual assistant\b",
        r"\badministrative assistant\b",
        r"\boffice manager\b",
        r"\b(?:office )?coordinator\b",
    ),
    "finance_accounting": (
        r"\baccountant\b",
        r"\bbookkeeper\b",
        r"\bfinance\b",
        r"\bfinancial analyst\b",
        r"\bpayroll\b",
        r"\bauditor\b",
    ),
    "education_training": (
        r"\bteacher\b",
        r"\btutor\b",
        r"\binstructional designer\b",
        r"\b(?:learning|training) (?:specialist|manager|designer)\b",
        r"\beducator\b",
    ),
}


def classify_role_families(job):
    title = str(job.get("title") or "").lower()
    matches = [
        family
        for family, patterns in ROLE_TITLE_PATTERNS.items()
        if any(re.search(pattern, title) for pattern in patterns)
    ]
    return matches or (["other"] if title.strip() else [])


def classify_experience_level(job):
    title = str(job.get("title") or "").lower()
    description = get_description_text(job.get("description")).lower()
    if re.search(r"\b(?:senior|sr\.?|lead|principal|staff|director|head of|vp)\b", title):
        return "senior"
    if re.search(r"\b(?:entry[- ]level|junior|jr\.?|graduate|trainee|intern)\b", title):
        return "entry"
    if re.search(r"\b(?:mid[- ]level|mid level|intermediate)\b", title):
        return "mid"
    if re.search(
        r"\b(?:this is a |seeking a |looking for a )?"
        r"(?:senior|sr\.?|lead|principal|staff|director|head of)\b"
        r"(?:[- ]level)?(?:\s+\w+){0,3}\s+(?:role|position|job)\b"
        r"|\b(?:senior|sr\.?|lead|principal|staff)[- ]level\b",
        description
    ):
        return "senior"
    if re.search(
        r"\b(?:entry[- ]level|junior|graduate|trainee|intern)\b"
        r"(?:\s+\w+){0,3}\s+(?:role|position|job)\b"
        r"|\b(?:entry[- ]level|junior)[- ]level\b",
        description
    ):
        return "entry"
    if re.search(r"\b(?:mid[- ]level|intermediate)\s+(?:role|position|job)\b", description):
        return "mid"

    experience_years = [
        (int(first), int(second))
        for first, second in re.findall(
            r"\b(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\s+years?(?:\s+of\s+experience)?",
            description
        )
    ]
    if experience_years:
        lowest = min(first for first, _ in experience_years)
        highest = max(second for _, second in experience_years)
        if lowest >= 6:
            return "senior"
        if highest <= 2:
            return "entry"
        return "mid"
    if re.search(r"\b(?:6|7|8|9|10)\+?\s+years?(?:\s+of\s+experience)?\b", description):
        return "senior"
    if re.search(r"\b(?:0|1|2)\+?\s+years?(?:\s+of\s+experience)?\b", description):
        return "entry"
    if re.search(r"\b(?:3|4|5)\+?\s+years?(?:\s+of\s+experience)?\b", description):
        return "mid"
    return "unspecified"


def classify_work_arrangement(job):
    supplied_arrangement = str(job.get("work_arrangement") or "").strip().lower()
    title = str(job.get("title") or "").lower()
    description = get_description_text(job.get("description")).lower()
    work_details = f"{title} {description}"
    if re.search(r"\bhybrid\b|\b\d+\s+days?\s+(?:per|a)\s+week\s+in (?:the )?office\b", work_details):
        return "hybrid"
    if re.search(
        r"\bon[- ]?site\b|\bin[- ]office\b|\boffice[- ]based\b"
        r"|\bfully in (?:the )?office\b|\bremote work\s+not\s+(?:available|offered|possible)\b",
        work_details
    ):
        return "onsite"
    if supplied_arrangement in {"remote", "hybrid", "onsite"}:
        return supplied_arrangement
    if str(job.get("source") or "").lower() == "remotive":
        return "remote"
    if re.search(r"\bremote\b|\bwork from anywhere\b|\bwork from home\b", work_details):
        return "remote"
    return "unspecified"


def normalize_job_profile(job):
    normalized = dict(job)
    normalized["role_families"] = classify_role_families(job)
    normalized["experience_level"] = classify_experience_level(job)
    normalized["work_arrangement"] = classify_work_arrangement(job)
    return normalized


def score_job_for_profile(job, preferences):
    job = normalize_job_profile(job)
    selected_families = set(preferences.get("role_families") or [])
    selected_levels = set(preferences.get("experience_levels") or [])
    selected_arrangements = set(preferences.get("work_arrangements") or [])
    selected_locations = set(preferences.get("preferred_locations") or [])

    if (
        not selected_families
        or not selected_levels
        or not selected_arrangements
        or (preferences.get("preferred_locations") is not None and not selected_locations)
    ):
        return None
    job_locations, eu_wide, non_eu = classify_eu_location(job.get("location"))
    if job_locations and not job_locations.intersection(selected_locations):
        return None
    if non_eu and not job_locations and not eu_wide:
        return None
    if not selected_families.intersection(job["role_families"]):
        return None
    if (
        job["experience_level"] != "unspecified"
        and job["experience_level"] not in selected_levels
    ):
        return None
    if (
        job["work_arrangement"] != "unspecified"
        and job["work_arrangement"] not in selected_arrangements
    ):
        return None

    score = 10
    if job["experience_level"] in selected_levels:
        score += 4
    if job["work_arrangement"] in selected_arrangements:
        score += 2
    if job_locations.intersection(selected_locations):
        score += 3
    elif eu_wide:
        score += 2
    description = get_description_text(job.get("description")).lower()
    profile_terms = {
        "frontend_web": ("react", "javascript", "typescript", "html", "css", "figma"),
        "software_it": ("python", "javascript", "cloud", "devops", "sql", "security"),
        "digital_marketing": ("seo", "sem", "analytics", "campaign", "advertising", "content"),
        "social_media": ("instagram", "tiktok", "linkedin", "community", "content calendar"),
        "graphic_design": ("adobe", "illustrator", "photoshop", "figma", "indesign", "branding"),
        "writing_content": ("writing", "editing", "copywriting", "research", "content"),
        "customer_support": ("customer", "support", "ticket", "crm", "client"),
        "sales_business": ("sales", "pipeline", "crm", "prospecting", "revenue"),
        "product_project": ("roadmap", "stakeholder", "agile", "project", "product"),
        "data_analytics": ("sql", "python", "analytics", "dashboard", "reporting"),
        "hr_recruiting": ("recruiting", "talent", "hiring", "human resources", "hr"),
        "operations_admin": ("operations", "administration", "scheduling", "process", "coordination"),
        "finance_accounting": ("accounting", "finance", "bookkeeping", "payroll", "budget"),
        "education_training": ("teaching", "training", "curriculum", "learning", "education"),
        "other": (),
    }
    relevant_terms = {
        term
        for family in selected_families.intersection(job["role_families"])
        for term in profile_terms.get(family, ())
    }
    score += min(sum(term in description for term in relevant_terms), 8)
    job["score"] = score
    job["match_category"] = get_match_category(score)
    return job


def is_relevant_frontend_job(job):

    title = str(job.get("title") or "").lower()

    if not title:
        return False

    if is_senior_job(job) or not is_remote_work_arrangement(job):
        return False

    negative_role_keywords = [
        "backend",
        "devops",
        "data scientist",
        "machine learning",
        "mobile",
        "ios",
        "android"
    ]

    if any(keyword in title for keyword in negative_role_keywords):
        return False

    frontend_title_signals = [
        "frontend",
        "front-end",
        "front end",
        "web developer",
        "web engineer",
        "react developer",
        "javascript developer",
        "ui developer",
        "ui engineer"
    ]

    is_development_role = "developer" in title or "engineer" in title
    return is_development_role and any(
        signal in title
        for signal in frontend_title_signals
    )


def get_match_category(score):

    if score >= 18:
        return "Excellent Match"

    if score >= 14:
        return "Strong Match"

    if score >= 10:
        return "Good Match"

    if score >= 6:
        return "Weak Match"

    return "Poor Match"


def build_email_body(jobs):

    if not jobs:
        return "No new jobs to report."

    lines = [
        "🔥 New Remote Frontend Jobs",
        "",
        "Here are the latest relevant opportunities:",
        ""
    ]

    for index, job in enumerate(jobs, start=1):
        title = job.get("title", "Unknown")
        company = job.get("company", "Unknown")
        location = job.get("location", "Unknown")
        score = job.get("score", 0)
        match = job.get("match_category", "Unknown")
        url = job.get("url", "")

        lines.append(f"{index}. {title}")
        lines.append(f"Company: {company}")
        lines.append(f"Location: {location}")
        lines.append(f"Match Score: {score}")
        lines.append(f"Match: {match}")
        lines.append("Apply:")
        lines.append(url)
        lines.append("--------------------------------")
        lines.append("")

    return "\n".join(lines).strip()


def show_new_job_notification(jobs):

    if not jobs:
        return

    import tkinter as tk
    from tkinter import messagebox

    job_lines = []
    for job in jobs[:8]:
        job_lines.extend([
            str(job.get("title") or "Untitled job"),
            f"Company: {job.get('company') or 'Unknown'}",
            f"Location: {job.get('location') or 'Not specified'}",
            f"Score: {job.get('score', 0)} — {job.get('match_category', 'Unknown')}",
            f"Apply: {job.get('url') or 'Link not available'}",
            ""
        ])

    if len(jobs) > 8:
        job_lines.append(f"...and {len(jobs) - 8} more new jobs.")

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            title=f"{len(jobs)} new Remote Job Finder match(es)",
            message="\n".join(job_lines).strip(),
            parent=root
        )
    except tk.TclError as exc:
        print(f"Desktop notification could not be shown: {exc}")
    finally:
        if root is not None:
            root.destroy()


def create_ipv4_connection(host, port, timeout, source_address=None):
    addresses = socket.getaddrinfo(
        host,
        port,
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    if not addresses:
        raise OSError(f"No IPv4 address found for SMTP host: {host}")

    address = addresses[0][4]
    return socket.create_connection(
        address,
        timeout,
        source_address
    )


class IPv4SMTP(smtplib.SMTP):

    def _get_socket(self, host, port, timeout):
        return create_ipv4_connection(host, port, timeout, self.source_address)


class IPv4SMTP_SSL(smtplib.SMTP_SSL):

    def _get_socket(self, host, port, timeout):
        raw_socket = create_ipv4_connection(
            host,
            port,
            timeout,
            self.source_address
        )
        return self.context.wrap_socket(raw_socket, server_hostname=host)


def get_smtp_security(smtp_security, port):
    security = (smtp_security or "auto").strip().lower()
    aliases = {
        "tls": "starttls",
        "ssl/tls": "ssl",
        "implicit_tls": "ssl",
        "plain": "none",
        "off": "none"
    }
    security = aliases.get(security, security)

    if security not in {"auto", "starttls", "ssl", "none"}:
        raise ValueError("SMTP_SECURITY must be auto, starttls, ssl, or none.")

    if security == "auto":
        return "ssl" if port == 465 else "starttls"

    return security


def connect_smtp(smtp_host, port, security, timeout=20):
    context = ssl.create_default_context()

    if security == "ssl":
        return IPv4SMTP_SSL(smtp_host, port, timeout=timeout, context=context)

    return IPv4SMTP(smtp_host, port, timeout=timeout)


def print_email_error(stage, exc):
    print(f"Email send failed while {stage} ({type(exc).__name__}): {exc}")

    if stage.startswith("authenticating with the mail provider"):
        print("The SMTP server accepted the connection, then closed it during login.")
        print("Check that EMAIL_PASSWORD is an app/SMTP password, SMTP auth is enabled, and EMAIL_USERNAME is set if your login differs from EMAIL_FROM.")
        print("If your provider says to use SSL/TLS on port 465, set SMTP_PORT=465 and SMTP_SECURITY=ssl.")


def send_email_notification(jobs, subject=None):

    email_from = os.getenv("EMAIL_FROM", "").strip()
    email_to = os.getenv("EMAIL_TO", "").strip()
    email_username = os.getenv("EMAIL_USERNAME", email_from).strip()
    email_password = os.getenv("EMAIL_PASSWORD", "").replace(" ", "").strip()
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = os.getenv("SMTP_PORT", "587").strip()
    smtp_security = os.getenv("SMTP_SECURITY", "auto")

    if not all([email_from, email_to, email_username, email_password, smtp_host]):
        print("Email not configured. Set EMAIL_FROM, EMAIL_TO, EMAIL_PASSWORD, and SMTP_HOST.")
        return False

    stage = "validating SMTP settings"
    try:
        port = int(smtp_port)
        security = get_smtp_security(smtp_security, port)
        message = MIMEText(build_email_body(jobs), "plain", "utf-8")
        if subject is None:
            subject = os.getenv("EMAIL_SUBJECT", "🔥 New Remote Frontend Jobs")
            subject = f"{subject} ({len(jobs)})"
        message["Subject"] = subject
        message["From"] = email_from
        message["To"] = email_to

        stage = "connecting to the SMTP server"
        with connect_smtp(smtp_host, port, security) as server:
            if security == "starttls":
                stage = "starting TLS encryption"
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            elif security == "none":
                server.ehlo()

            stage = "authenticating with the mail provider without initial response"
            server.login(
                email_username,
                email_password,
                initial_response_ok=False
            )
            stage = "sending the message"
            server.sendmail(email_from, email_to, message.as_string())

        print("Email sent successfully.")
        return True

    except (OSError, smtplib.SMTPException, ValueError) as exc:
        print_email_error(stage, exc)
        return False


def calculate_score(job):

    title = str(job.get("title") or "").lower()
    description = str(job.get("description") or "").lower()

    # Description keywords cannot turn an unrelated title into a strong match.
    if not is_relevant_frontend_job(job):
        return 0

    role_keywords = {
        "junior frontend developer": 10,
        "junior web developer": 10,
        "junior react developer": 10,
        "entry-level frontend developer": 10,
        "entry level frontend developer": 10,
        "frontend developer": 9,
        "front-end developer": 9,
        "front end developer": 9,
        "frontend engineer": 9,
        "front-end engineer": 9,
        "react developer": 9,
        "javascript developer": 8,
        "web developer": 8,
        "web engineer": 7,
        "ui developer": 7,
        "ui engineer": 7
    }

    role_score = 0
    for keyword, points in role_keywords.items():
        if keyword in title:
            role_score = points
            break

    if role_score == 0 and ("frontend" in title or "front-end" in title or "front end" in title):
        role_score = 7

    score = role_score

    tech_points = {
        "react": 2,
        "javascript": 2,
        "typescript": 2,
        "html": 1,
        "css": 1,
        "git": 1,
        "github": 1,
        "node.js": 1,
        "rest api": 1,
        "dom": 1
    }

    technology_score = 0
    for keyword, points in tech_points.items():
        if keyword in title:
            technology_score += points * 2
        elif keyword in description:
            technology_score += points
    score += min(technology_score, 8)

    for keyword in junior_keywords:
        if keyword in title:
            score += 4
            break
        elif keyword in description:
            score += 1
            break

    if "full stack" in title or "full-stack" in title:
        score = min(score, 13)

    return score


def is_location_ok(location):

    if not location or not isinstance(location, str):
        return True

    location = location.lower().strip()

    blocked_locations = [
        "usa",
        "united states",
        "canada",
        "australia",
        "japan"
    ]

    for blocked in blocked_locations:

        if blocked in location:
            return False

    return True


def process_jobs(all_jobs, saved_jobs, minimum_save_score=6):

    saved_urls = {str(job.get("url") or "") for job in saved_jobs}

    for job in saved_jobs:
        job["score"] = calculate_score(job)
        job["match_category"] = get_match_category(job["score"])

    matched_jobs = []
    frontend_matches = 0

    for job in all_jobs:
        title = str(job.get("title") or "").lower()
        is_frontend = is_relevant_frontend_job(job)
        is_senior = any(keyword in title for keyword in senior_keywords)
        is_location_allowed = is_location_ok(job.get("location"))

        if is_frontend and not is_senior and is_location_allowed:
            frontend_matches += 1
            job["score"] = calculate_score(job)
            job["match_category"] = get_match_category(job["score"])

            job_url = str(job.get("url") or "")
            if job_url and job_url not in saved_urls:
                matched_jobs.append(job)
                saved_urls.add(job_url)

    all_saved_jobs = saved_jobs + matched_jobs

    for job in all_saved_jobs:
        job["match_category"] = get_match_category(job.get("score", 0))

    saveable_jobs = [
        job for job in all_saved_jobs
        if job.get("score", 0) >= minimum_save_score
        or job.get("status") in {"saved", "applied"}
    ]
    saveable_jobs.sort(
        key=lambda job: job.get("score", 0),
        reverse=True
    )

    return matched_jobs, frontend_matches, saveable_jobs


def get_notification_jobs(matched_jobs, minimum_save_score):

    return [
        job for job in matched_jobs
        if job.get("score", 0) >= minimum_save_score
    ]


def collect_and_process_jobs(saved_jobs):
    all_jobs = collect_jobs_from_sources()

    print("Total jobs collected:", len(all_jobs))
    print("Saved jobs:", len(saved_jobs))

    minimum_save_score = 6
    matched_jobs, frontend_matches, saveable_jobs = process_jobs(
        all_jobs,
        saved_jobs,
        minimum_save_score
    )

    print("Frontend matches:", frontend_matches)
    print("New jobs:", len(matched_jobs))
    return matched_jobs, saveable_jobs


def collect_job_listings():
    return collect_jobs_from_sources()


def run_job_finder(show_notification=True):

    if os.path.exists("jobs.json"):
        with open("jobs.json", "r", encoding="utf-8") as file:
            saved_jobs = json.load(file)
    else:
        saved_jobs = []

    matched_jobs, saveable_jobs = collect_and_process_jobs(saved_jobs)

    print()
    print("===== JOB RANKING =====")

    for index, job in enumerate(saveable_jobs, start=1):
        print()
        print(f"#{index}")
        print("TITLE:", job.get("title", "Unknown"))
        print("COMPANY:", job.get("company", "Unknown"))
        print("LOCATION:", job.get("location", "Unknown"))
        print("SCORE:", job.get("score", 0))
        print("MATCH:", job.get("match_category", "Unknown"))
        print("SOURCE:", job.get("source", "Unknown"))
        print("APPLY:", job.get("url", "Unknown"))

    with open("jobs.json", "w", encoding="utf-8") as file:
        json.dump(
            saveable_jobs,
            file,
            indent=4,
            ensure_ascii=False
        )

    new_notification_jobs = get_notification_jobs(
        matched_jobs,
        6
    )

    if new_notification_jobs:
        if show_notification:
            show_new_job_notification(new_notification_jobs)
    else:
        print("No new jobs to notify.")

    print("Total saved jobs:", len(saveable_jobs))
    print("Jobs saved to jobs.json")
    return new_notification_jobs


if __name__ == "__main__":
    run_job_finder()

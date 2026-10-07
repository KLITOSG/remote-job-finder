import requests
import json
import os
import sys
import socket
import ssl
import smtplib
import re
from html import unescape
from html.parser import HTMLParser
from email.mime.text import MIMEText

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


def get_remotive_jobs():

    url = "https://remotive.com/api/remote-jobs"

    response = requests.get(url, timeout=20)

    print("Remotive status:", response.status_code)

    if response.status_code != 200:
        print("Remotive request failed.")
        return []

    try:
        data = response.json()
    except ValueError:
        print("Remotive response is not valid JSON.")
        return []

    jobs = []

    for job in data.get("jobs", []):

        job_data = {
            "title": job.get("title") or "",
            "company": job.get("company_name") or "",
            "location": job.get("candidate_required_location") or "",
            "description": job.get("description") or "",
            "url": job.get("url") or "",
            "source": "Remotive"
        }

        jobs.append(job_data)

    return jobs


def get_arbeitnow_jobs():

    url = "https://www.arbeitnow.com/api/job-board-api"

    response = requests.get(url, timeout=20)

    print("Arbeitnow status:", response.status_code)

    if response.status_code != 200:
        print("Arbeitnow request failed.")
        return []

    try:
        data = response.json()
    except ValueError:
        print("Arbeitnow response is not valid JSON.")
        return []

    jobs = []

    for job in data.get("data", []):

        job_data = {
            "title": job.get("title") or "",
            "company": job.get("company_name") or "",
            "location": job.get("location") or "",
            "description": job.get("description") or "",
            "url": job.get("url") or "",
            "source": "Arbeitnow"
        }

        jobs.append(job_data)

    return jobs


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


def run_job_finder(show_notification=True):

    remotive_jobs = get_remotive_jobs()
    arbeitnow_jobs = get_arbeitnow_jobs()
    all_jobs = remotive_jobs + arbeitnow_jobs

    print("Remotive jobs:", len(remotive_jobs))
    print("Arbeitnow jobs:", len(arbeitnow_jobs))
    print("Total jobs collected:", len(all_jobs))

    if os.path.exists("jobs.json"):
        with open("jobs.json", "r", encoding="utf-8") as file:
            saved_jobs = json.load(file)
    else:
        saved_jobs = []

    print("Saved jobs:", len(saved_jobs))

    minimum_save_score = 6
    matched_jobs, frontend_matches, saveable_jobs = process_jobs(
        all_jobs,
        saved_jobs,
        minimum_save_score
    )

    print("Frontend matches:", frontend_matches)
    print("New jobs:", len(matched_jobs))

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
        minimum_save_score
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

import requests
import json
import os
import sys
import socket
import ssl
import smtplib
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


frontend_keywords = [
    "junior frontend developer",
    "junior web developer",
    "junior react developer",
    "entry-level frontend developer",
    "entry level frontend developer",
    "frontend developer",
    "front-end developer",
    "front end developer",
    "react developer",
    "javascript developer",
    "web developer",
    "ui developer"
]


junior_keywords = ["junior", "entry level", "graduate", "trainee", "intern"]


def is_relevant_frontend_job(job):

    title = str(job.get("title") or "").lower()
    description = str(job.get("description") or "").lower()

    if not title:
        return False

    if any(keyword in title for keyword in senior_keywords):
        return False

    negative_role_keywords = [
        "backend developer",
        "devops",
        "data scientist",
        "machine learning engineer",
        "mobile developer",
        "ios developer",
        "android developer"
    ]

    if any(keyword in title for keyword in negative_role_keywords):
        return False

    title_matches = any(
        keyword in title
        for keyword in frontend_keywords
    )

    if title_matches:
        return True

    tech_match = any(
        keyword in title
        for keyword in ["react", "javascript", "typescript", "html", "css"]
    )

    junior_signal = any(
        keyword in title
        for keyword in junior_keywords
    )

    if tech_match and ("web" in title or "frontend" in title or "ui" in title or "developer" in title):
        return True

    if junior_signal and ("web" in title or "frontend" in title or "ui" in title or "developer" in title):
        return True

    if "frontend" in description and "junior" in description:
        return True

    return False


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

    score = 0

    # A. Title relevance - strongest signal
    title_role_points = {
        "junior frontend developer": 12,
        "junior web developer": 12,
        "junior react developer": 12,
        "entry-level frontend developer": 11,
        "entry level frontend developer": 11,
        "frontend developer": 10,
        "front-end developer": 10,
        "front end developer": 10,
        "react developer": 9,
        "javascript developer": 8,
        "web developer": 8,
        "ui developer": 8
    }

    for keyword, points in title_role_points.items():
        if keyword in title:
            score += points

    # B. Technology keywords. Title mentions are stronger than description mentions.
    tech_points = {
        "react": 4,
        "javascript": 4,
        "typescript": 3,
        "html": 2,
        "css": 2,
        "git": 2,
        "github": 2,
        "node.js": 3,
        "rest api": 3,
        "dom": 2
    }

    for keyword, points in tech_points.items():
        if keyword in title:
            score += points * 2
        elif keyword in description:
            score += points

    # C. Experience level signals
    junior_keywords = ["junior", "entry level", "graduate", "trainee", "intern"]
    for keyword in junior_keywords:
        if keyword in title:
            score += 5
        elif keyword in description:
            score += 2

    for keyword in senior_keywords:
        if keyword in title:
            score -= 12
        elif keyword in description:
            score -= 3

    # D. Role relevance negatives
    negative_role_keywords = [
        "backend developer",
        "devops",
        "data scientist",
        "machine learning engineer",
        "mobile developer",
        "ios developer",
        "android developer"
    ]

    for keyword in negative_role_keywords:
        if keyword in title:
            score -= 10
        elif keyword in description:
            score -= 4

    # E. Strong title signal for "web developer" or "frontend" without exact job title
    if "frontend" in title:
        score += 3
    elif "frontend" in description:
        score += 1

    if "front-end" in title:
        score += 3
    elif "front-end" in description:
        score += 1

    # F. Avoid giving too much weight to a single description mention
    if "react" in description and "react developer" not in title:
        score += 1

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


if "--test-email" in sys.argv:
    test_job = {
        "title": "TEST EMAIL — sample Junior React Developer role",
        "company": "Remote Job Finder test",
        "location": "Remote",
        "score": 18,
        "match_category": "Excellent Match",
        "url": "https://example.com/test-job"
    }

    if not send_email_notification(
        [test_job],
        subject="Remote Job Finder — TEST EMAIL"
    ):
        raise SystemExit(1)

    raise SystemExit(0)


# Get jobs from APIs

remotive_jobs = get_remotive_jobs()

arbeitnow_jobs = get_arbeitnow_jobs()

all_jobs = remotive_jobs + arbeitnow_jobs


print("Remotive jobs:", len(remotive_jobs))
print("Arbeitnow jobs:", len(arbeitnow_jobs))
print("Total jobs collected:", len(all_jobs))


# Load saved jobs

if os.path.exists("jobs.json"):

    with open("jobs.json", "r", encoding="utf-8") as file:
        saved_jobs = json.load(file)

else:

    saved_jobs = []


saved_urls = {str(job.get("url") or "") for job in saved_jobs}

print("Saved jobs:", len(saved_jobs))


# Calculate scores for existing jobs

for job in saved_jobs:

    job["score"] = calculate_score(job)
    job["match_category"] = get_match_category(job["score"])


matched_jobs = []

frontend_matches = 0


# Process new jobs

for job in all_jobs:

    title = str(job.get("title") or "").lower()

    is_frontend = is_relevant_frontend_job(job)

    is_senior = any(
        keyword in title
        for keyword in senior_keywords
    )

    is_location_allowed = is_location_ok(job.get("location"))

    if is_frontend and not is_senior and is_location_allowed:

        frontend_matches += 1

        score = calculate_score(job)

        job["score"] = score
        job["match_category"] = get_match_category(score)

        if job["url"] not in saved_urls:

            matched_jobs.append(job)

            print()
            print("NEW JOB")
            print("TITLE:", job["title"])
            print("COMPANY:", job["company"])
            print("LOCATION:", job["location"])
            print("SOURCE:", job["source"])
            print("SCORE:", job["score"])
            print("APPLY:", job["url"])


print("Frontend matches:", frontend_matches)
print("New jobs:", len(matched_jobs))



all_saved_jobs = saved_jobs + matched_jobs

for job in all_saved_jobs:
    job["match_category"] = get_match_category(job.get("score", 0))

# Keep only jobs that are relevant enough to save
minimum_save_score = 6
saveable_jobs = [
    job for job in all_saved_jobs
    if job.get("score", 0) >= minimum_save_score
]

# Rank jobs by score

saveable_jobs.sort(
    key=lambda job: job.get("score", 0),
    reverse=True
)


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

# Save only the best matching jobs

with open("jobs.json", "w", encoding="utf-8") as file:

    json.dump(
        saveable_jobs,
        file,
        indent=4,
        ensure_ascii=False
    )


new_email_jobs = [
    job for job in matched_jobs
    if job.get("score", 0) >= minimum_save_score
]

if new_email_jobs:
    send_email_notification(new_email_jobs)
else:
    print("No new jobs to email.")


print("Total saved jobs:", len(saveable_jobs))
print("Jobs saved to jobs.json")

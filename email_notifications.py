import html
import os
import re
from datetime import datetime, timezone

import requests


RESEND_API_URL = "https://api.resend.com/emails"
REQUEST_TIMEOUT = 20
DEFAULT_SUPPORT_EMAIL = "remotejobfinderco@gmail.com"
SUPPORT_ISSUE_TYPES = {
    "loading_signin": "The app will not load or I cannot sign in",
    "jobs_missing": "Jobs are missing or not updating",
    "saved_applied": "Saved or Applied jobs are not working",
    "notifications": "Notifications or email alerts are not working",
    "other": "Other",
}


class EmailDeliveryError(RuntimeError):
    pass


def build_email_content(jobs):
    if not jobs:
        raise ValueError("At least one matching job is required for an email.")

    text_lines = [
        f"{len(jobs)} new job match{'es' if len(jobs) != 1 else ''} for your saved search",
        "",
    ]
    html_jobs = []
    for index, job in enumerate(jobs, start=1):
        title = str(job.get("title") or "Untitled job")
        company = str(job.get("company") or "Company not listed")
        location = str(job.get("location") or "Location not specified")
        level = str(job.get("experience_level") or "unspecified").title()
        arrangement = str(job.get("work_arrangement") or "unspecified").title()
        url = str(job.get("url") or "")
        if not url.startswith(("https://", "http://")):
            continue

        text_lines.extend([
            f"{index}. {title}",
            f"Company: {company}",
            f"Location: {location}",
            f"Level: {level}",
            f"Work arrangement: {arrangement}",
            f"Match score: {job.get('score', 0)}",
            f"View job: {url}",
            "",
        ])
        html_jobs.append(
            "<li>"
            f"<h2><a href=\"{html.escape(url, quote=True)}\">"
            f"{html.escape(title)}</a></h2>"
            f"<p>{html.escape(company)} · {html.escape(location)}</p>"
            f"<p>{html.escape(level)} · {html.escape(arrangement)} · "
            f"Match score {html.escape(str(job.get('score', 0)))}</p>"
            "</li>"
        )

    if not html_jobs:
        raise ValueError("No matching job has a valid application URL.")

    text = "\n".join(text_lines).strip()
    body = (
        "<main><h1>New jobs for your saved search</h1><ul>"
        + "".join(html_jobs)
        + "</ul><p>You can change or disable email alerts from your job profile.</p></main>"
    )
    return text, body


def send_job_alert(to_email, jobs, *, idempotency_key=None):
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("EMAIL_FROM", "").strip()
    if not api_key or not sender:
        raise EmailDeliveryError(
            "Set RESEND_API_KEY and EMAIL_FROM in the hosted worker environment."
        )
    if not isinstance(to_email, str) or "@" not in to_email:
        raise ValueError("The signed-in account does not have a valid email address.")

    text, body = build_email_content(jobs)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    response = requests.post(
        RESEND_API_URL,
        json={
            "from": sender,
            "to": [to_email],
            "subject": f"{len(jobs)} new job match{'es' if len(jobs) != 1 else ''}",
            "text": text,
            "html": body,
        },
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    if not response.ok:
        try:
            detail = response.json()
        except ValueError:
            detail = {}
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("name") or ""
        else:
            detail = ""
        message = f"Resend rejected the email (HTTP {response.status_code})"
        if detail:
            message += f": {detail}"
        raise EmailDeliveryError(message)
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def send_support_report(issue_type, details, contact_email=""):
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("EMAIL_FROM", "").strip()
    recipient = os.getenv("SUPPORT_EMAIL", DEFAULT_SUPPORT_EMAIL).strip()
    if not api_key or not sender or not recipient:
        raise EmailDeliveryError(
            "Support email is not configured on the server."
        )
    if not isinstance(issue_type, str) or issue_type not in SUPPORT_ISSUE_TYPES:
        raise ValueError("Choose one of the listed problem types.")
    if not isinstance(details, str) or not details.strip() or len(details) > 2000:
        raise ValueError("Describe the problem in no more than 2,000 characters.")
    if contact_email and (
        not isinstance(contact_email, str)
        or len(contact_email) > 254
        or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact_email)
    ):
        raise ValueError("Enter a valid email address or leave it blank.")

    issue_label = SUPPORT_ISSUE_TYPES[issue_type]
    report_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    escaped_details = html.escape(details.strip()).replace("\n", "<br>")
    text = (
        "Remote Job Finder problem report\n\n"
        f"Problem: {issue_label}\n"
        f"Time: {report_time}\n"
        f"Reply email: {contact_email or 'Not provided'}\n\n"
        f"Details:\n{details.strip()}"
    )
    body = (
        "<main><h1>Remote Job Finder problem report</h1>"
        f"<p><strong>Problem:</strong> {html.escape(issue_label)}</p>"
        f"<p><strong>Time:</strong> {html.escape(report_time)}</p>"
        f"<p><strong>Reply email:</strong> "
        f"{html.escape(contact_email or 'Not provided')}</p>"
        f"<p><strong>Details:</strong><br>{escaped_details}</p>"
        "</main>"
    )
    payload = {
        "from": sender,
        "to": [recipient],
        "subject": f"Remote Job Finder support: {issue_label}",
        "text": text,
        "html": body,
    }
    if contact_email:
        payload["reply_to"] = contact_email

    try:
        response = requests.post(
            RESEND_API_URL,
            json=payload,
            headers={
                "Authorization": f"******",
                "Content-Type": "application/json",
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise EmailDeliveryError(
            f"Support report could not be sent ({type(exc).__name__})."
        ) from exc
    if not response.ok:
        raise EmailDeliveryError(
            f"Support report email was rejected (HTTP {response.status_code})."
        )
    return True
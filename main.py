import requests
import json
import os


# -----------------------------
# 1. Get jobs from Remotive
# -----------------------------

def get_remotive_jobs():

    url = "https://remotive.com/api/remote-jobs"

    response = requests.get(url)

    print("Remotive status:", response.status_code)

    data = response.json()

    jobs = []

    for job in data["jobs"]:

        job_data = {
            "title": job["title"],
            "company": job["company_name"],
            "location": job["candidate_required_location"],
            "description": job["description"],
            "url": job["url"],
            "source": "Remotive"
        }

        jobs.append(job_data)

    return jobs


# -----------------------------
# 2. Get jobs from Arbeitnow
# -----------------------------

def get_arbeitnow_jobs():

    url = "https://www.arbeitnow.com/api/job-board-api"

    response = requests.get(url)

    print("Arbeitnow status:", response.status_code)

    data = response.json()

    jobs = []

    for job in data["data"]:

        job_data = {
            "title": job["title"],
            "company": job["company_name"],
            "location": job["location"],
            "description": job["description"],
            "url": job["url"],
            "source": "Arbeitnow"
        }

        jobs.append(job_data)

    return jobs


# -----------------------------
# 3. Seniority keywords
# -----------------------------

senior_keywords = [
    "senior",
    "lead",
    "principal",
    "staff",
    "manager",
    "director"
]


# -----------------------------
# 4. Frontend keywords
# -----------------------------

frontend_keywords = [
    "frontend",
    "front-end",
    "front end",
    "react developer",
    "javascript developer",
    "web developer",
    "ui developer"
]


# -----------------------------
# 5. Location filter
# -----------------------------

def is_location_ok(location):

    location = location.lower()

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


# -----------------------------
# 6. Collect jobs from sources
# -----------------------------

remotive_jobs = get_remotive_jobs()

arbeitnow_jobs = get_arbeitnow_jobs()

all_jobs = remotive_jobs + arbeitnow_jobs

print("Remotive jobs:", len(remotive_jobs))
print("Arbeitnow jobs:", len(arbeitnow_jobs))
print("Total jobs collected:", len(all_jobs))


# -----------------------------
# 7. Load previously saved jobs
# -----------------------------

if os.path.exists("jobs.json"):

    with open("jobs.json", "r", encoding="utf-8") as file:
        saved_jobs = json.load(file)

else:

    saved_jobs = []


saved_urls = {job["url"] for job in saved_jobs}

print("Saved jobs:", len(saved_jobs))


# -----------------------------
# 8. Filter jobs
# -----------------------------

matched_jobs = []
frontend_matches = 0


for job in all_jobs:

    title = job["title"].lower()
    description = job["description"].lower()

    text = title + " " + description

    is_frontend = any(
        keyword in title
        for keyword in frontend_keywords
    )

    is_senior = any(
        keyword in title
        for keyword in senior_keywords
    )

    is_location_allowed = is_location_ok(job["location"])

    if is_frontend and not is_senior and is_location_allowed:

        frontend_matches += 1

        if job["url"] not in saved_urls:

            matched_jobs.append(job)


# -----------------------------
# 9. Show results
# -----------------------------

print("Frontend matches:", frontend_matches)
print("New jobs:", len(matched_jobs))


for job in matched_jobs:

    print()
    print("TITLE:", job["title"])
    print("COMPANY:", job["company"])
    print("LOCATION:", job["location"])
    print("SOURCE:", job["source"])
    print("APPLY:", job["url"])


# -----------------------------
# 10. Save jobs
# -----------------------------

all_saved_jobs = saved_jobs + matched_jobs


with open("jobs.json", "w", encoding="utf-8") as file:

    json.dump(
        all_saved_jobs,
        file,
        indent=4,
        ensure_ascii=False
    )


print("Total saved jobs:", len(all_saved_jobs))
print("Jobs saved to jobs.json")
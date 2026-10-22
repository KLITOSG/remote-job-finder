# Remote Job Finder

Remote Job Finder is a web app for discovering remote job listings, with a focus on opportunities available in Europe. It collects listings from multiple job boards, matches them against each user's saved preferences, and provides a dashboard for keeping track of interesting roles.

## Features

- Aggregates remote listings from Remotive, Arbeitnow, Jobicy, and Remote OK.
- Filters and ranks jobs by job family, experience level, work arrangement, and eligible EU countries.
- Supports Google sign-in and private per-user saved searches and job statuses (Saved or Applied).
- Offers opt-in browser push notifications and optional grouped email alerts for new matches.
- Includes a progressive web app manifest, offline fallback, and an Android Trusted Web Activity scaffold.
- Runs scheduled job checks through GitHub Actions; the hosted web dashboard is configured for Render and Supabase.

## Tech stack

- Python 3.12 for the web app, job collection, and background worker
- HTML, CSS, and JavaScript for the dashboard and installable web app
- Supabase Auth and Postgres for accounts and cloud data
- GitHub Actions for scheduled checks
- Render for web hosting

## Run locally

1. Create and activate a Python virtual environment.
2. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Start the app:

   ```bash
   python web_ui.py
   ```

Open the local address printed by the server. Cloud sign-in and per-user features require the Supabase environment variables described in [DEPLOYMENT.md](DEPLOYMENT.md). Never commit API keys, service-role keys, or VAPID private keys.

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for Supabase, Google sign-in, GitHub Actions, Render, and notification setup instructions.

## Project links

- [GitHub repository](https://github.com/KLITOSG/remote-job-finder)
- [Portfolio](https://klitosg.github.io/portfolio/)

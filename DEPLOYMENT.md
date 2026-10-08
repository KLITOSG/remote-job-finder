# Hosted deployment

The hosted setup runs the dashboard as a Render web service and job collection as
a separate Render background worker. The worker checks the existing job sources
every 60 minutes without depending on a user's computer or browser being on. It
collects from Remotive, Arbeitnow, Jobicy, and Remote OK.
Each signed-in user can lock a personal job-family, experience-level, and work
arrangement search. Saved and Applied statuses are private to each account.

## 1. Create the Supabase project

1. Create a Supabase project and keep its database password private.
2. Open the Supabase SQL editor and run all of `supabase_schema.sql`. It is
   safe to rerun after deployments; it adds the required classification columns
   to an existing jobs table as well as creating the new profile and email tables.
3. In **Authentication → Providers**, enable Google.
4. Create OAuth credentials in Google Cloud Console. Set the Google OAuth
   authorized redirect URI to `https://<project-ref>.supabase.co/auth/v1/callback`.
   Enter the Google client ID and secret in the Supabase Google provider settings.
5. In **Authentication → URL Configuration**, set the Site URL to the Render
   app URL after it is created. Add that URL with a trailing slash to the allowed
   redirect URLs, for example `https://remote-job-finder.onrender.com/`.
   Publish the Google OAuth consent screen for general sign-ups, or add the
   initial testers while the consent screen is still in testing mode.

The app uses Supabase Auth for Google sign-in and a service-role key only from
the Python server/worker. The database tables have row-level security enabled
and do not grant direct access to browser users.

## 2. Generate browser push keys

Install the Python requirements locally and generate one VAPID key pair:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe generate_vapid_keys.py
```

Keep the private key secret. Do not commit it, paste it into source files, or
share it in chat. Use the printed public and private values only in the Render
environment variables below.

## 3. Create the Render services

1. In Render, create a Blueprint from the GitHub repository containing this
   project and its `render.yaml`.
2. Use the `starter` plan for both services so the web app and worker stay
   running. The worker is a separate continuously running service; do not replace
   it with a web-service in-process timer.
3. Enter the prompted environment values for both services:

   | Variable | Value |
   | --- | --- |
   | `SUPABASE_URL` | Supabase project URL |
   | `SUPABASE_ANON_KEY` | Supabase publishable/anon key |
   | `SUPABASE_SERVICE_ROLE_KEY` | Supabase service-role secret; server-side only |
   | `VAPID_PUBLIC_KEY` | Public key generated in step 2 |
   | `RESEND_API_KEY` | Resend API key (web app sends support reports) |
   | `EMAIL_FROM` | Verified Resend sender, e.g. `Remote Job Finder <alerts@yourdomain.com>` |

   The web service also has `SUPPORT_EMAIL` prefilled as
   `gaitanosklitos@gmail.com`; leave it as-is if support reports should go there.
   Also set these worker-only variables:

   | Variable | Value |
   | --- | --- |
   | `VAPID_PRIVATE_KEY` | Private key generated in step 2 |
   | `VAPID_CLAIMS_EMAIL` | A contact email address, without `mailto:` |
   | `RESEND_API_KEY` | The same Resend API key |
   | `EMAIL_FROM` | The same verified Resend sender |

   The Blueprint sets `DEPLOYMENT_MODE=cloud` and
   `JOB_CHECK_INTERVAL_MINUTES=60`. Keep the service-role and VAPID private keys
   in Render's secret environment settings; never add them to this repository or
   to browser configuration.
4. Wait for both services to deploy. Open the web service URL and sign in with
   Google. The first worker check loads the current matches without sending a
   burst of old-job notifications. Later newly discovered matches create
   persistent in-app alerts and push notifications.

Render assigns `PORT` to the web service. The app binds to that port and exposes
`/health` for its health check.

## 4. Enable notifications

Each person signs in and chooses **Enable PC notifications** on every browser or
device where they want alerts. This grants permission and registers that
browser's push subscription. New matches can then arrive while the dashboard tab
is closed, as long as that browser/device supports Web Push and its OS allows
notifications. The cloud worker continues checking jobs even when the user has
no browser open and their personal computer is off.

Push notifications are opt-in. Users can still see new matches in the dashboard
the next time they sign in.

## Personal searches and email alerts

After signing in, choose one or more job families, experience levels, and work
arrangements, then save and lock the search. The worker uses those preferences
to match newly collected listings; jobs with unclear level or arrangement remain
eligible and are labeled Unspecified. Unlock the search before changing it.

To enable email alerts, verify a sending domain in Resend, create an API key, and
set `RESEND_API_KEY` and `EMAIL_FROM` on the background worker in Render. The
sender address/domain must be verified by Resend. Each user can opt in to grouped
email alerts in their saved search; alerts go to the email address supplied by
their signed-in Google account. If Resend is not configured or rejects delivery,
alerts remain queued for a later retry and the worker logs the delivery failure.

The app also shows a **Need help?** form before sign-in and in the dashboard.
People can choose whether the problem is with loading/sign-in, missing or stale
jobs, Saved/Applied jobs, notifications/email, or something else, then describe
what happened. Reports are emailed to `gaitanosklitos@gmail.com`; a visitor can
optionally leave an email address for a reply. The web service needs the same
`RESEND_API_KEY` and `EMAIL_FROM` settings for this form to send. If Resend is
unavailable, the form tells the visitor to email that address directly.

## Import existing personal lists

After signing into the hosted app, choose **Import Saved/Applied jobs** and select
the local `jobs.json` file. Only entries whose status is `saved` or `applied`
are imported into that signed-in account. Other users do not inherit those
statuses.

## Operational notes

- The app uses public job feeds from [Remotive](https://remotive.com/remote-jobs/api),
  [Arbeitnow](https://www.arbeitnow.com/api/job-board-api),
  [Jobicy](https://jobicy.com/api/v2/remote-jobs), and
  [Remote OK](https://remoteok.com/api). These new sources do not require an API
  key. Job cards identify their source and link to that source's listing, as the
  providers request. The worker checks them during its normal hourly run.
- If one provider is temporarily down, collection continues from the others.
  If every provider fails, the worker records the failed check and retries on
  its next scheduled run.
- Himalayas was not added: its API guide describes job-board use, but its general
  terms also restrict public display and mirroring. Get written permission before
  using that feed in this public app.
- `render.yaml` uses paid always-on service plans; the host and Supabase account
  may incur charges. Check the providers' current pricing and set billing alerts
  before creating the services.
- Cloud collection gathers supported remote and hybrid job families once per
  interval, then applies each locked user's preferences for dashboard results
  and notifications.
- The app depends on Render, Supabase, its upstream job APIs, and the browser
  push provider. It is independent of a user's PC, but no hosted service can
  promise zero provider outages.
- Existing `jobs.json` is not used as the hosted database. Import it after
  signing in if you want to retain personal Saved/Applied entries.

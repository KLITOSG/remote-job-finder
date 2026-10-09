# Hosted deployment

The free-tier setup runs the dashboard on Render, stores data in Supabase, and
uses GitHub Actions to check the job sources hourly. The scheduled check does
not depend on a user's computer or browser being on. GitHub's scheduler is
best-effort (not an exact-time guarantee), and Render's free web service can
sleep while idle.
Each signed-in user can lock a personal job-family, experience-level, work
arrangement, and EU-country search. Saved and Applied statuses are private to
each account.

## 1. Create the Supabase project

1. Create a Supabase project and keep its database password private.
2. Open the Supabase SQL editor and run all of `supabase_schema.sql`. It is
   safe to rerun after deployments; it adds the required classification columns
   to an existing jobs table and creates/updates the profile and email tables.
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
the Python server and GitHub Actions worker. The database tables have row-level
security enabled and do not grant direct access to browser users.

## 2. Generate browser push keys

Install the Python requirements locally and generate one VAPID key pair:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe generate_vapid_keys.py
```

Keep the private key secret. Do not commit it, paste it into source files, or
share it in chat. Use the printed public key in Render and both keys in the
GitHub Actions secrets below.

## 3. Configure hourly job checks in GitHub Actions

The repository contains `.github/workflows/hourly-job-check.yml`. It runs the
Python worker once an hour (scheduled for minute 17) and can also be started
manually from GitHub's
**Actions** tab. In the repository, open **Settings → Secrets and variables →
Actions → New repository secret** and add:

| Secret | Value |
| --- | --- |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase anon/publishable key |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service-role secret |
| `VAPID_PUBLIC_KEY` | Public key generated in step 2 |
| `VAPID_PRIVATE_KEY` | Private key generated in step 2 |
| `VAPID_CLAIMS_EMAIL` | Your contact email, without `mailto:` |

Never put secret values in workflow files, issues, or chat. Email is skipped for
now; if you configure Resend later, add `RESEND_API_KEY` and `EMAIL_FROM` as
repository secrets.

## 4. Create the Render web service

1. In Render, create a Blueprint from the GitHub repository containing this
   project and its `render.yaml`.
2. Enter the prompted Supabase URL, anon key, service-role key, and VAPID public
   key. The Blueprint configures the dashboard as a free web service.
3. Wait for deployment. Open its URL and sign in with Google. Update Supabase
   **Authentication → URL Configuration** with the Render URL and add it to the
   allowed redirect URLs.

Render assigns `PORT` to the web service. The app binds to that port and exposes
`/health` for its health check.

## 5. Enable notifications

Each person signs in and chooses **Enable PC notifications** on every browser or
device where they want alerts. This grants permission and registers that
browser's push subscription. New matches can then arrive while the dashboard tab
is closed, as long as that browser/device supports Web Push and its OS allows
notifications. GitHub Actions checks for new jobs even when the user has no
browser open and their personal computer is off.

Push notifications are opt-in. Users can still see new matches in the dashboard
the next time they sign in. The free Render web service may take a short while
to wake after inactivity.

## Personal searches and email alerts

After signing in, choose job families, experience levels, work arrangements, and
the EU countries where you can work, then save and lock the search. All EU
countries are selected initially; narrow the list as needed. The worker uses
those preferences for dashboard results and notifications. Listings explicitly
located in selected countries match; Europe-wide and location-unspecified remote
listings remain eligible, and clearly non-EU locations are excluded. Location
labels depend on the source feed, so city-only or ambiguous listings may remain
eligible if the country cannot be identified. Recognized non-EU destinations are
excluded; unrecognized location text remains eligible rather than being
discarded. Unlock the search before changing it.

To enable email alerts later, verify a sending domain in Resend, create an API
key, and set `RESEND_API_KEY` and `EMAIL_FROM` as GitHub repository secrets. The
sender address/domain must be verified by Resend. Each user can opt in to grouped
email alerts in their saved search; alerts go to the email address supplied by
their signed-in Google account. If Resend is not configured or rejects delivery,
alerts remain queued for a later retry and the worker logs the delivery failure.

The app also shows a **Need help?** form before sign-in and in the dashboard.
People can choose whether the problem is with loading/sign-in, missing or stale
jobs, Saved/Applied jobs, notifications/email, or something else, then describe
what happened. Reports are emailed to `remotejobfinderco@gmail.com` after Resend is
configured; a visitor can optionally leave an email address for a reply. The web
service needs `RESEND_API_KEY` and `EMAIL_FROM` set in Render for this form to
send. Until then, the form tells the visitor to email that address directly.

## Import existing personal lists

After signing into the hosted app, choose **Import Saved/Applied jobs** and select
the local `jobs.json` file. Only entries whose status is `saved` or `applied`
are imported into that signed-in account. Other users do not inherit those
statuses.

## Google Play preparation (Android TWA)

The site now has an installable-app manifest with 192 px and 512 px icons and a
network-failure page for navigation requests. These prepare the web app for a
Trusted Web Activity (TWA), which can present the existing HTTPS site as an
Android app without maintaining a second UI.

The Play release project is not scaffolded yet. Before generating it:

- Choose the Android package name carefully; Google Play package names are
  permanent. Build and sign an Android App Bundle (`.aab`) for submission.
- Set up Digital Asset Links at
  `https://remote-job-finder-w20c.onrender.com/.well-known/assetlinks.json`
  using the final package name and the SHA-256 certificate fingerprint for the
  Play App Signing certificate. This lets Android verify the app and website
  belong together.
- Publish a privacy policy and implement both an in-app account-deletion path
  and a public web page where users can request deletion. The current app has
  Google sign-in but does not yet provide account deletion, so this is a release
  blocker.
- Complete the Play Console Data safety and data-deletion declarations from the
  app's actual data practices, and provide reviewer access instructions for any
  features behind sign-in.
- Prepare Play listing assets and information (store icon, screenshots,
  description, contact details, content rating, and audience declarations).
  Personal developer accounts may also have a testing requirement before a
  production release; check the current
  [Play testing requirements](https://support.google.com/googleplay/android-developer/answer/14151465).

The Render URL is HTTPS and can be used to begin TWA development. A custom
domain is not required for the initial setup, but confirm it is the intended
long-term app URL before release because changing the verified web origin later
requires updating the Android association and app configuration.

## Operational notes

- The app uses public job feeds from [Remotive](https://remotive.com/remote-jobs/api),
  [Arbeitnow](https://www.arbeitnow.com/api/job-board-api),
  [Jobicy](https://jobicy.com/api/v2/remote-jobs), and
  [Remote OK](https://remoteok.com/api). These new sources do not require an API
  key. Job cards identify their source and link to that source's listing, as the
  providers request. The worker checks them during its normal hourly run.
- Jobicy is queried with Europe-wide and Greece, Italy, Spain, and Portugal
  location filters; duplicate listing URLs are collapsed before processing. Its
  public feed asks consumers to credit Jobicy and link application buttons to
  the original listing.
- If one provider is temporarily down, collection continues from the others.
  If every provider fails, the worker records the failed check and retries on
  its next scheduled run.
- Himalayas was not added: its API guide describes job-board use, but its general
  terms also restrict public display and mirroring. Get written permission before
  using that feed in this public app.
- This is a free-tier compromise, not a 24/7 uptime guarantee. GitHub Actions
  schedules can be delayed, and free hosted services can sleep, pause, or change
  their limits. Check current provider pricing and terms before launch.
- Cloud collection gathers supported remote and hybrid job families once per
  interval, then applies each locked user's preferences for dashboard results
  and notifications.
- GitHub may disable scheduled workflows after long repository inactivity.
  Check the **Actions** tab periodically and use **Run workflow** to start a
  check manually if needed.
- The app depends on Render, GitHub Actions, Supabase, upstream job APIs, and
  the browser push provider. It is independent of a user's PC, but no hosted
  service can promise zero provider outages.
- Existing `jobs.json` is not used as the hosted database. Import it after
  signing in if you want to retain personal Saved/Applied entries.

create table if not exists public.jobs (
    url text primary key,
    title text not null,
    company text not null default '',
    location text not null default '',
    description text not null default '',
    source text not null default '',
    score integer not null default 0,
    match_category text not null default '',
    role_families text[] not null default '{}',
    experience_level text not null default 'unspecified'
        check (experience_level in ('entry', 'mid', 'senior', 'unspecified')),
    work_arrangement text not null default 'unspecified'
        check (work_arrangement in ('remote', 'hybrid', 'onsite', 'unspecified')),
    created_at timestamptz not null default now()
);

alter table public.jobs
    add column if not exists role_families text[] not null default '{}',
    add column if not exists experience_level text not null default 'unspecified',
    add column if not exists work_arrangement text not null default 'unspecified';

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'jobs_experience_level_check'
          and conrelid = 'public.jobs'::regclass
    ) then
        alter table public.jobs
            add constraint jobs_experience_level_check
            check (experience_level in ('entry', 'mid', 'senior', 'unspecified'));
    end if;

    if not exists (
        select 1 from pg_constraint
        where conname = 'jobs_work_arrangement_check'
          and conrelid = 'public.jobs'::regclass
    ) then
        alter table public.jobs
            add constraint jobs_work_arrangement_check
            check (work_arrangement in ('remote', 'hybrid', 'onsite', 'unspecified'));
    end if;
end;
$$;

create table if not exists public.user_job_statuses (
    user_id uuid not null references auth.users (id) on delete cascade,
    job_url text not null references public.jobs (url) on delete cascade,
    status text not null check (status in ('saved', 'applied')),
    updated_at timestamptz not null default now(),
    primary key (user_id, job_url)
);

create table if not exists public.user_preferences (
    user_id uuid primary key references auth.users (id) on delete cascade,
    notification_email text not null default '',
    role_families text[] not null default '{}',
    experience_levels text[] not null default '{}',
    work_arrangements text[] not null default '{}',
    email_notifications boolean not null default false,
    profile_locked boolean not null default false,
    updated_at timestamptz not null default now()
);

create table if not exists public.job_events (
    id bigint generated always as identity primary key,
    job_url text not null references public.jobs (url) on delete cascade,
    created_at timestamptz not null default now()
);

create table if not exists public.email_outbox (
    id bigint generated always as identity primary key,
    user_id uuid not null references auth.users (id) on delete cascade,
    job_url text not null references public.jobs (url) on delete cascade,
    notification_email text not null,
    status text not null default 'pending' check (status in ('pending', 'sent')),
    attempts integer not null default 0,
    last_error text,
    last_attempt_at timestamptz,
    created_at timestamptz not null default now(),
    sent_at timestamptz,
    unique (user_id, job_url)
);

create table if not exists public.push_subscriptions (
    user_id uuid not null references auth.users (id) on delete cascade,
    endpoint text primary key,
    subscription jsonb not null,
    updated_at timestamptz not null default now()
);

create table if not exists public.monitor_state (
    id integer primary key check (id = 1),
    last_check double precision,
    next_check double precision,
    last_error text,
    checking boolean not null default false
);

alter table public.jobs enable row level security;
alter table public.user_job_statuses enable row level security;
alter table public.user_preferences enable row level security;
alter table public.job_events enable row level security;
alter table public.email_outbox enable row level security;
alter table public.push_subscriptions enable row level security;
alter table public.monitor_state enable row level security;

revoke all on public.jobs, public.user_job_statuses, public.user_preferences,
    public.job_events, public.email_outbox, public.push_subscriptions,
    public.monitor_state
    from anon, authenticated;
grant all on public.jobs, public.user_job_statuses, public.user_preferences,
    public.job_events, public.email_outbox, public.push_subscriptions,
    public.monitor_state
    to service_role;
grant usage, select on all sequences in schema public to service_role;

create or replace function public.record_new_jobs(
    job_rows jsonb,
    create_events boolean default true
)
returns setof public.jobs
language plpgsql
security definer
set search_path = public
as $$
declare
    candidate record;
    inserted_job public.jobs%rowtype;
begin
    for candidate in
        select *
        from jsonb_to_recordset(coalesce(job_rows, '[]'::jsonb)) as row_data(
            url text,
            title text,
            company text,
            location text,
            description text,
            source text,
            score integer,
            match_category text,
            role_families text[],
            experience_level text,
            work_arrangement text
        )
    loop
        insert into public.jobs (
            url, title, company, location, description, source, score, match_category,
            role_families, experience_level, work_arrangement
        )
        values (
            candidate.url,
            candidate.title,
            coalesce(candidate.company, ''),
            coalesce(candidate.location, ''),
            coalesce(candidate.description, ''),
            coalesce(candidate.source, ''),
            coalesce(candidate.score, 0),
            coalesce(candidate.match_category, ''),
            coalesce(candidate.role_families, '{}'),
            coalesce(candidate.experience_level, 'unspecified'),
            coalesce(candidate.work_arrangement, 'unspecified')
        )
        on conflict (url) do nothing
        returning * into inserted_job;

        if found then
            if create_events then
                insert into public.job_events (job_url) values (inserted_job.url);
            end if;
            return next inserted_job;
        end if;
    end loop;
end;
$$;

revoke all on function public.record_new_jobs(jsonb, boolean)
    from public, anon, authenticated;
grant execute on function public.record_new_jobs(jsonb, boolean) to service_role;

create or replace function public.record_email_failure(
    outbox_ids bigint[],
    error_text text
)
returns void
language sql
security definer
set search_path = public
as $$
    update public.email_outbox
    set attempts = attempts + 1,
        last_error = left(error_text, 1000),
        last_attempt_at = now()
    where id = any(outbox_ids)
      and status = 'pending';
$$;

revoke all on function public.record_email_failure(bigint[], text)
    from public, anon, authenticated;
grant execute on function public.record_email_failure(bigint[], text)
    to service_role;

create index if not exists email_outbox_pending_idx
    on public.email_outbox (status, id)
    where status = 'pending';

-- Database for the deployed dashboard. Loaded by `python -m pipeline publish` from a finished run's saved
-- outputs; the dashboard's backend reads it with a SELECT-only role. No model is called by either.

create table if not exists runs (
  run_id            text primary key,
  label             text not null,
  scope             text not null,          -- e.g. "full corpus", "100,000-review sample", "500-review dev checkpoint"
  input_file        text not null,
  input_sha256      text not null,
  source_rows       integer not null,
  completed         integer not null,
  quarantined       integer not null,
  quarantine_reasons jsonb not null,
  cache_reuse       integer not null,
  needs_review      integer not null,
  decided_by        jsonb not null,
  api_cost_usd      numeric not null,       -- provider-reported tokens x list prices (estimate, not an invoice)
  label_config      text not null,
  models            jsonb not null,
  verification      jsonb,
  published_at      timestamptz not null default now(),
  is_current        boolean not null default false
);

create table if not exists reviews (
  run_id           text not null references runs(run_id) on delete cascade,
  review_id        text not null,
  source_sha256    text not null,
  status           text not null,           -- completed | quarantined
  reason           text,                    -- quarantine reason
  topic            text,
  intent           text,
  severity         smallint,
  sentiment        numeric,
  needs_review     boolean,
  issue_id         text,
  evidence_quote   text,
  entities         jsonb,
  decided_by       text,                    -- jev | claude_fallback | jev_fallback_capped | jev_fallback_failed
  cache_source_id  text,
  review_text      text,
  review_rating    text,
  review_timestamp text,
  app_version      text,
  primary key (run_id, review_id)
);
create index if not exists reviews_issue on reviews (run_id, issue_id);
create index if not exists reviews_topic on reviews (run_id, topic, intent);

create table if not exists issues (
  run_id          text not null references runs(run_id) on delete cascade,
  issue_id        text not null,
  topic           text not null,
  name            text not null,
  definition      text not null,
  rank            integer,
  complaint_count integer not null default 0,
  severity_sum    integer not null default 0,
  mean_severity   text,                     -- exact 6-dp half-up string from ranking.csv
  priority_score  integer not null default 0,
  primary key (run_id, issue_id)
);

create table if not exists topic_metrics (
  run_id            text not null references runs(run_id) on delete cascade,
  topic             text not null,
  reviews           integer not null,
  complaints        integer not null,        -- complaint + cancellation intent
  cancellations     integer not null,
  severity_sum      integer not null,
  primary key (run_id, topic)
);

create table if not exists claims (
  run_id    text not null references runs(run_id) on delete cascade,
  claim_id  text not null,
  issue_id  text not null,
  metric    text not null,
  value     text not null,
  primary key (run_id, claim_id)
);

create table if not exists facts (
  run_id   text not null references runs(run_id) on delete cascade,
  fact_id  text not null,
  meaning  text not null,
  value    text not null,
  primary key (run_id, fact_id)
);

create table if not exists recommendations (
  run_id         text primary key references runs(run_id) on delete cascade,
  memo_markdown  text not null,
  model          text not null,
  label_config   text not null,
  check_passed   boolean not null,
  check_errors   jsonb not null,
  evidence_pack  jsonb not null             -- the bounded examples the memo model was given
);

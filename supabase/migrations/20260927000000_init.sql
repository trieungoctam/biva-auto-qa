-- auto-qa — schema dữ liệu (Supabase, prefix aq_)
-- Nguồn chân: bots (knowledge/scenarios/situations), runs, reviews, users, schedules.
-- raw/ KHÔNG nằm ở đây (chỉ local theo hợp đồng kiến trúc).

create table if not exists aq_users (
  name text primary key,
  key_hash text not null,
  role text not null default 'member',
  created_at timestamptz not null default now()
);

create table if not exists aq_schedules (
  name text primary key,
  bot text not null,
  scenarios jsonb not null default '[]',
  at_time text not null,            -- "HH:MM" múi giờ server
  calls int not null default 1,
  concurrency int not null default 1,
  run_user text not null default 'scheduler'
);

create table if not exists aq_bots (
  bot text primary key,
  display_name text not null default '',
  target text not null default '',
  business text not null default '',  -- knowledge/business.md
  updated_at timestamptz not null default now()
);

create table if not exists aq_scenarios (
  bot text not null references aq_bots(bot) on delete cascade,
  name text not null,
  yaml text not null,
  updated_at timestamptz not null default now(),
  primary key (bot, name)
);

create table if not exists aq_situations (
  bot text not null references aq_bots(bot) on delete cascade,
  name text not null,
  yaml text not null,
  updated_at timestamptz not null default now(),
  primary key (bot, name)
);

create table if not exists aq_runs (
  run_id text primary key,
  ts timestamptz not null default now(),
  bot text not null default '',
  run_user text not null default '',
  status text not null default 'done',
  total int not null default 0,
  error text
);

create table if not exists aq_calls (
  run_id text not null references aq_runs(run_id) on delete cascade,
  scenario text not null,           -- "suite/name"
  call text not null default '1/1',
  seq int not null default 0,
  ts timestamptz not null default now(),
  target text not null default '',
  run_user text not null default '',
  status text not null default '',
  conversation_id text not null default '',
  error text,
  checks jsonb not null default '[]',
  transcript jsonb not null default '[]',
  primary key (run_id, scenario, call)
);

create table if not exists aq_reviews (
  run_id text not null,
  scenario text not null,
  call text not null default '1/1',
  reviewer text not null,
  verdict text not null check (verdict in ('ok', 'issue', 'warn')),
  anchor text not null default '',
  note text not null default '',
  ts timestamptz not null default now(),
  primary key (run_id, scenario, call, reviewer)
);

create index if not exists aq_calls_run_idx on aq_calls (run_id desc);
create index if not exists aq_reviews_run_idx on aq_reviews (run_id);

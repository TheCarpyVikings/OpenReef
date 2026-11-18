-- Apply before deploying the hardened portal. Existing bearer tokens survive;
-- every old short code is retired. Invitations must be issued again in the UI.
-- Do not roll back to reusable codes. New API routes fail closed if this
-- migration is missing. Keep this migration when rolling back application UI.

alter table public.beta_testers
  alter column code drop not null,
  add column invite_hash text unique
    check (invite_hash is null or invite_hash ~ '^[a-f0-9]{64}$'),
  add column invite_expires_at timestamptz,
  add constraint beta_invite_pair check (
    (invite_hash is null and invite_expires_at is null)
    or (invite_hash is not null and invite_expires_at is not null)
  );

update public.beta_testers set code = null;
-- A still-running old build must not create more short plaintext credentials.
alter table public.beta_testers add constraint beta_legacy_code_retired check (code is null);

create function public.beta_testers_restrict_access()
returns trigger language plpgsql set search_path = '' as $$
begin
  if NEW.status in ('paused', 'revoked') then
    NEW.invite_hash = null;
    NEW.invite_expires_at = null;
  end if;
  if NEW.status = 'revoked' then NEW.token_hash = null; end if;
  return NEW;
end;
$$;

create trigger beta_testers_restrict_access_trigger
  before insert or update on public.beta_testers
  for each row execute function public.beta_testers_restrict_access();

-- The conditional UPDATE locks/rechecks the row. Two simultaneous redemptions
-- cannot both succeed, and a concurrent pause/revoke cannot be overwritten by
-- a stale SELECT. No SECURITY DEFINER: the service role is the only caller.
create function public.beta_redeem_invite(
  p_invite_hash text, p_token_hash text, p_install_id text,
  p_openreef_version text, p_ha_version text, p_agreement_version text
)
returns table (tester_name text)
language plpgsql set search_path = '' as $$
begin
  if p_invite_hash is null or p_invite_hash !~ '^[a-f0-9]{64}$'
     or p_token_hash is null or p_token_hash !~ '^[a-f0-9]{64}$'
     or p_agreement_version is null or char_length(p_agreement_version) = 0 then
    raise exception 'Invalid invitation parameters' using errcode = '22023';
  end if;
  return query
    update public.beta_testers t
    set invite_hash = null, invite_expires_at = null,
        token_hash = p_token_hash, status = 'active',
        install_id = p_install_id, openreef_version = p_openreef_version,
        ha_version = p_ha_version, agreement_version = p_agreement_version,
        agreement_accepted_at = clock_timestamp(),
        enrolled_at = clock_timestamp(), last_seen_at = clock_timestamp()
    where t.invite_hash = p_invite_hash
      and t.status in ('invited', 'active')
      and t.invite_expires_at > clock_timestamp()
    returning t.name;
end;
$$;

create table public.beta_rate_limits (
  key text primary key check (key ~ '^[a-f0-9]{64}$'),
  hits integer not null check (hits > 0),
  expires_at timestamptz not null
);
create index beta_rate_limits_expiry on public.beta_rate_limits (expires_at);
alter table public.beta_rate_limits enable row level security;
revoke all on public.beta_rate_limits from public, anon, authenticated;
grant select, insert, update, delete on public.beta_rate_limits to service_role;

create function public.beta_take_rate_limit(p_key text, p_limit integer, p_window_seconds integer)
returns boolean language plpgsql set search_path = '' as $$
declare
  accepted boolean;
  checked_at timestamptz := clock_timestamp();
begin
  if p_key is null or p_key !~ '^[a-f0-9]{64}$'
     or p_limit is null or p_limit < 1 or p_limit > 10000
     or p_window_seconds is null or p_window_seconds < 1 or p_window_seconds > 86400 then
    raise exception 'Invalid rate limit parameters' using errcode = '22023';
  end if;
  -- Bounded retention; the expiry index keeps cleanup off the live buckets.
  delete from public.beta_rate_limits where expires_at < checked_at - interval '1 day';
  insert into public.beta_rate_limits as bucket (key, hits, expires_at)
  values (p_key, 1, checked_at + make_interval(secs => p_window_seconds))
  on conflict (key) do update
    set hits = case when bucket.expires_at <= checked_at then 1 else bucket.hits + 1 end,
        expires_at = case when bucket.expires_at <= checked_at
          then checked_at + make_interval(secs => p_window_seconds) else bucket.expires_at end
    where bucket.expires_at <= checked_at or bucket.hits < p_limit
  returning true into accepted;
  return coalesce(accepted, false);
end;
$$;

revoke all on function public.beta_testers_restrict_access() from public, anon, authenticated;
revoke all on function public.beta_redeem_invite(text, text, text, text, text, text) from public, anon, authenticated;
revoke all on function public.beta_take_rate_limit(text, integer, integer) from public, anon, authenticated;
grant execute on function public.beta_redeem_invite(text, text, text, text, text, text) to service_role;
grant execute on function public.beta_take_rate_limit(text, integer, integer) to service_role;

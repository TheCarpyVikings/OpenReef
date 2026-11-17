"""Real PostgreSQL migration, authorization and concurrency regression checks.

Run explicitly: python3 portal/tests/test_security_sql.py
Requires Docker; uses postgres:17-alpine (pulled if absent). Creates an isolated
container with no network, host mounts, or published ports. Only synthetic data
is loaded; the container and its temporary data are removed in finally.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import time

MIGRATIONS = Path(__file__).resolve().parents[1] / "supabase" / "migrations"


def main():
    container = subprocess.check_output([
        "docker", "run", "--rm", "-d", "--network", "none",
        "--tmpfs", "/var/lib/postgresql/data", "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
        "postgres:17-alpine",
    ], text=True).strip()
    if len(container) != 64 or any(c not in "0123456789abcdef" for c in container):
        raise RuntimeError("Unexpected temporary container identifier")
    command = ["docker", "exec", "-i", container, "psql", "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-Atq"]

    def sql(statement, *, succeeds=True):
        result = subprocess.run(command, input=statement, text=True, capture_output=True, timeout=30)
        if succeeds and result.returncode:
            raise AssertionError(result.stderr)
        if not succeeds and not result.returncode:
            raise AssertionError("Unauthorized statement unexpectedly succeeded")
        return result.stdout.strip()

    def check(label, condition):
        assert condition, label
        print(f"PASS {label}", flush=True)

    def invite(digit, status="active", expiration="now() + interval '1 hour'"):
        sql(f"update public.beta_testers set status='{status}', invite_hash=repeat('{digit}',64), invite_expires_at={expiration} where name='Active synthetic';")

    def redeem(digit):
        return sql(f"set role service_role; select count(*) from public.beta_redeem_invite(repeat('{digit}',64),repeat('f',64),'synthetic-install','0.0-test','test','synthetic');")

    def locked_update(statement):
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        process.stdin.write(f"begin; {statement}; select 'locked'; select pg_sleep(1); commit;\n")
        process.stdin.close()
        assert process.stdout.readline().strip() == "locked"
        return process

    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ready = subprocess.run(["docker", "exec", container, "pg_isready", "-U", "postgres"], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("Temporary PostgreSQL did not become ready")

        sql("""
          create role anon nologin;
          create role authenticated nologin;
          create role service_role nologin bypassrls;
          grant usage on schema public to anon, authenticated, service_role;
          alter default privileges in schema public grant all on tables to service_role;
          alter default privileges in schema public grant all on sequences to service_role;
        """)
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            if migration.name.startswith("0006"):
                sql("""insert into public.beta_testers (name,code,status,token_hash) values
                  ('Invited synthetic','REEF-BCDF','invited',null),
                  ('Active synthetic','REEF-GHJK','active',repeat('a',64));""")
            sql(migration.read_text())
        check("all migrations apply and retire legacy codes without invalidating active tokens",
              sql("select count(*) from public.beta_testers where code is not null;") == "0"
              and sql("select token_hash=repeat('a',64) from public.beta_testers where name='Active synthetic';") == "t")
        sql("insert into public.beta_testers (name,code) values ('Old build','REEF-BCDF');", succeeds=False)
        check("old application builds cannot issue short credentials", True)

        for role in ("anon", "authenticated"):
            sql(f"set role {role}; select * from public.beta_testers;", succeeds=False)
            sql(f"set role {role}; select * from public.beta_rate_limits;", succeeds=False)
            sql(f"set role {role}; select public.beta_take_rate_limit(repeat('0',64),3,3600);", succeeds=False)
            sql(f"set role {role}; select * from public.beta_redeem_invite(repeat('0',64),repeat('f',64),null,null,null,'synthetic');", succeeds=False)
        check("anon/authenticated cannot read protected tables or execute security RPCs", True)

        invite("1")
        with ThreadPoolExecutor(max_workers=12) as pool:
            redeemed = list(pool.map(lambda _: redeem("1"), range(12)))
        check("12 concurrent redemptions return exactly one token grant", redeemed.count("1") == 1 and redeemed.count("0") == 11)
        check("redemption consumes hash and records active token and agreement", sql("select invite_hash is null and invite_expires_at is null and token_hash=repeat('f',64) and agreement_version='synthetic' from public.beta_testers where name='Active synthetic';") == "t")
        check("replay cannot replace the installed token", redeem("1") == "0")

        invite("2", expiration="now() - interval '1 second'")
        check("expired invitations cannot be redeemed", redeem("2") == "0")
        for status, digit in (("paused", "3"), ("revoked", "4")):
            invite(digit)
            process = locked_update(f"update public.beta_testers set status='{status}' where name='Active synthetic'")
            try:
                count = redeem(digit)
                assert process.wait(timeout=5) == 0, process.stderr.read()
            finally:
                if process.poll() is None:
                    process.kill()
            check(f"concurrent {status} wins over an enrolment waiting on its row lock", count == "0" and sql("select status from public.beta_testers where name='Active synthetic';") == status)
            check(f"{status} clears pending invitations", sql("select invite_hash is null and invite_expires_at is null from public.beta_testers where name='Active synthetic';") == "t")
        check("revocation clears active bearer hash", sql("select token_hash is null from public.beta_testers where name='Active synthetic';") == "t")

        invite("5", expiration="now() + interval '0.4 seconds'")
        process = locked_update("update public.beta_testers set name=name where name='Active synthetic'")
        try:
            count = redeem("5")
            assert process.wait(timeout=5) == 0, process.stderr.read()
        finally:
            if process.poll() is None:
                process.kill()
        check("invitation expiring while waiting for a lock is rejected", count == "0")

        with ThreadPoolExecutor(max_workers=12) as pool:
            grants=list(pool.map(lambda _: sql("set role service_role; select public.beta_take_rate_limit(repeat('b',64),3,3600);"), range(12)))
        check("atomic shared limiter admits exactly three of twelve concurrent attempts", grants.count("t") == 3 and grants.count("f") == 9)
        check("denied attempts do not inflate the stored counter", sql("select hits from public.beta_rate_limits where key=repeat('b',64);") == "3")
        sql("update public.beta_rate_limits set expires_at=now()-interval '1 second' where key=repeat('b',64);")
        check("expired windows reset", sql("set role service_role; select public.beta_take_rate_limit(repeat('b',64),3,3600);") == "t" and sql("select hits from public.beta_rate_limits where key=repeat('b',64);") == "1")
        sql("insert into public.beta_rate_limits values (repeat('c',64),1,now()-interval '2 days');")
        sql("set role service_role; select public.beta_take_rate_limit(repeat('b',64),3,3600);")
        check("expired address buckets are cleaned up", sql("select count(*) from public.beta_rate_limits where key=repeat('c',64);") == "0")
        sql("select public.beta_take_rate_limit(repeat('b',64),0,3600);", succeeds=False)
        check("invalid limiter parameters are rejected", True)
    finally:
        subprocess.run(["docker", "rm", "-f", container], check=True, capture_output=True)


if __name__ == "__main__":
    main()

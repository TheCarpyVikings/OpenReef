# Home Assistant security checks

These checks use **Home Assistant 2026.10.4's real service registry, admin-service
helper, WebSocket admin decorator, HTTP authentication middleware, signed URL
validation and HTTP view wrapper**. They use synthetic users and a temporary
configuration directory. They do not start an HTTP listener or contact devices.

Run from the repository root with Python 3.14.2 or newer, in a separate environment:

```sh
python3 -m venv /tmp/openreef-ha-security-tests
/tmp/openreef-ha-security-tests/bin/pip install 'homeassistant==2026.10.4'
/tmp/openreef-ha-security-tests/bin/python tests/ha_runtime/security_checks.py
```

The checks cover anonymous requests, ordinary/read-only/admin accounts, system
automation calls, expired or revoked media signatures, wrong-path signatures,
Home Assistant's generic signing API, filesystem traversal and symlinks, and
redaction of a synthetic beta token. Action bodies are replaced in service tests
so accepted requests cannot operate equipment; the authorization code is real.

Keep this process separate from the dependency-free controller tests. Those
tests install lenient `homeassistant` stubs and sometimes replace module globals;
combining them in one pytest process does not reproduce the CI environment.
Run those tests in individual processes, as CI does:

```sh
for suite in tests/test_*.py; do
  python3 "$suite" || exit 1
done
```

These checks do not replace deployment verification. After installing the media
security update, fully restart Home Assistant: reloading the integration cannot
remove an older public static route from an already running HTTP router.

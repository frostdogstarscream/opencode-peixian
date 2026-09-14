#!/bin/sh
set -eu
cd "$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
action=${1:-status}
client=${2:-all}
case "$client" in all|client-a|client-b) ;; *) echo 'Client must be all, client-a or client-b.' >&2; exit 2 ;; esac
compose() { docker compose --project-name peixian-opencode --file compose.yaml "$@"; }
if [ "$client" = all ]; then set --; else set -- "$client"; fi

if [ "$action" = init ]; then
  for utility in python3 setfacl getfacl; do
    if ! command -v "$utility" >/dev/null 2>&1; then
      echo 'Initialization requires Python 3.11+ with venv support and the Linux acl package (setfacl/getfacl). Ask the server administrator to install the missing prerequisite, then rerun init. No system packages were installed.' >&2
      exit 1
    fi
  done
  python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit('Python 3.11+ is required for the supplied offline wheels; Python 3.12 is recommended.')
PY
  umask 077
  if [ -L .secrets ]; then echo 'The .secrets directory must not be a symbolic link.' >&2; exit 1; fi
  mkdir -p .secrets
  chmod 700 .secrets
  python3 - <<'PY'
from pathlib import Path
import secrets
import subprocess

credentials = []
expected_acl = {'user::rw-', 'user:10001:r--', 'group::---', 'mask::r--', 'other::---'}
for name in ('client-a', 'client-b'):
    path = Path('.secrets') / (name + '.password')
    if path.is_symlink():
        raise SystemExit('Credential files must not be symbolic links.')
    if not path.exists():
        with path.open('x', encoding='utf-8') as stream:
            stream.write(secrets.token_urlsafe(48))
    password = path.read_text(encoding='utf-8').rstrip('\r\n')
    if len(password) < 16 or any(char in password for char in '\r\n\0'):
        raise SystemExit('Existing credential is invalid; repair explicitly without printing its value.')
    credentials.append(password)
    # Local Compose secrets bind the source file: retain owner read/write and
    # grant only the runtime UID read access, with no owning-group or other access.
    result = subprocess.run(['setfacl', '--set', 'u::rw-,u:10001:r--,g::---,m::r--,o::---', '--', str(path)], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit('Cannot set the credential ACL. Use a filesystem supporting POSIX ACLs and run init as the file owner; ask the administrator to repair ownership or ACL support. No system packages were installed.')
    result = subprocess.run(['getfacl', '-c', '-n', '--', str(path)], capture_output=True, text=True)
    actual_acl = {line.strip() for line in result.stdout.splitlines() if line.strip() and not line.startswith('#')}
    if result.returncode or actual_acl != expected_acl:
        raise SystemExit('Credential ACL verification failed; initialization stopped.')
if len(set(credentials)) != 2:
    raise SystemExit('Client passwords must differ; repair explicitly without printing values.')
print('Credentials ready with owner read/write and runtime UID 10001 read-only access; values are not printed.')
PY
  python3 -m venv .venv
  if [ -d wheels ]; then
    .venv/bin/python -m pip install --no-index --find-links wheels -r requirements.txt
  else
    .venv/bin/python -m pip install -r requirements.txt
  fi
  exit 0
fi

test "$(docker info --format '{{.OSType}}')" = linux
case "$action" in
  build) compose config --quiet; compose build client-a ;;
  up|start) compose up -d --no-build --pull never --wait --wait-timeout 180 "$@" ;;
  stop) compose stop --timeout 30 "$@" ;;
  restart) compose restart --timeout 30 "$@" ;;
  recreate) compose up -d --no-build --pull never --force-recreate --no-deps --wait --wait-timeout 180 "$@" ;;
  status) compose ps ;;
  verify) .venv/bin/python verify.py ;;
  verify-lifecycle) .venv/bin/python verify.py --lifecycle ;;
  *) echo 'Usage: manage.sh init|build|up|stop|start|restart|recreate|status|verify|verify-lifecycle [all|client-a|client-b]' >&2; exit 2 ;;
esac

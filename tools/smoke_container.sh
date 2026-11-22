#!/usr/bin/env bash
# Smoke test of a built image, run the way deploy/docker-compose.yml runs it: read-only root
# filesystem, tmpfs /tmp, all capabilities dropped, no-new-privileges, a token and a secret key.
# Used by .github/workflows/ci.yml; runnable locally:  tools/smoke_container.sh openartifact:test
# Uses a random free host port on 127.0.0.1 and a throw-away container; touches nothing else.
set -euo pipefail

IMAGE="${1:?usage: smoke_container.sh IMAGE}"
NAME="openartifact-smoke-$$"
TOKEN="$(head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 64)"
KEY="$(head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 64)"

HARDENING=(--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true)

cleanup() { docker rm -f "$NAME" > /dev/null 2>&1 || true; }
trap cleanup EXIT
fail() { echo "FAIL: $*" >&2; docker logs "$NAME" 2>&1 | tail -40 >&2 || true; exit 1; }

echo "--- every module of the application imports (all runtime dependencies are installed)"
docker run --rm "${HARDENING[@]}" --entrypoint python "$IMAGE" -c \
  "import importlib, pkgutil, openartifact
for m in pkgutil.walk_packages(openartifact.__path__, 'openartifact.'):
    importlib.import_module(m.name)
print('all modules imported')"

echo "--- start the container"
docker run -d --name "$NAME" "${HARDENING[@]}" \
  --tmpfs /data:uid=1000,gid=1000 \
  -p 127.0.0.1::2909 \
  -e OPENARTIFACT_DATA_DIR=/data \
  -e OPENARTIFACT_API_TOKEN="$TOKEN" \
  -e OPENARTIFACT_SECRET_KEY="$KEY" \
  "$IMAGE" > /dev/null
PORT="$(docker port "$NAME" 2909/tcp | head -1 | sed 's/.*://')"
BASE="http://127.0.0.1:${PORT}"

for i in $(seq 1 60); do
  if curl -sf "$BASE/health" > /dev/null; then break; fi
  [ "$i" -eq 60 ] && fail "no healthy server within 30 seconds"
  [ "$(docker inspect -f '{{.State.Running}}' "$NAME")" = "true" ] || fail "the container exited"
  sleep 0.5
done
echo "health: $(curl -sf "$BASE/health")"

code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
[ "$(code "$BASE/api/tasks")" = "401" ] || fail "/api/tasks without token is not 401"
echo "/api/tasks without token: 401"
[ "$(code -H "Authorization: Bearer $TOKEN" "$BASE/api/tasks")" = "200" ] || fail "/api/tasks with token is not 200"
echo "/api/tasks with bearer token: 200"
[ "$(code -H "Authorization: Bearer wrong-$TOKEN" "$BASE/api/tasks")" = "401" ] || fail "a wrong token is not 401"
echo "/api/tasks with a wrong token: 401"

echo "smoke test passed"

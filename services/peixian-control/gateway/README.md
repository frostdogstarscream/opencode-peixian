# Account gateway and model relay

Run from services/peixian-control with one worker per account:

    python -m uvicorn gateway.app:app --host 0.0.0.0 --port 8080 --workers 1 --no-access-log
    python -m uvicorn gateway.model_relay:app --host 0.0.0.0 --port 8081 --workers 1 --no-access-log

These are separate container processes. The web/control container calls the gateway over that account's private management network. No public gateway ports, shared account networks, Docker socket, or user-selected target URL are required.

## Gateway environment and mounts

- WORKSPACE=/workspace: only this account's existing workspace/result volume.
- FILES_ROOT=/files: only this account's upload and extraction volume, read/write here and read-only in the Agent.
- MANAGED_ROOT=/managed: read-only account configuration and approved plugin test entries.
- INTERNAL_TOKEN_FILE=/run/secrets/gateway-token: control-to-gateway secret; all gateway HTTP requests require X-Peixian-Key.
- OPENCODE_URL=http://agent:4096 and OPENCODE_PASSWORD_FILE=/run/secrets/opencode-password: private native Agent endpoint; Basic username is always opencode.
- BUN_EXECUTABLE=/usr/local/bin/bun: fixed administrator-installed executable for approved plugin probes.

Production fails closed outside Linux because file access requires directory FDs plus O_NOFOLLOW. Windows fallback is available only through an explicitly constructed Settings(require_linux=False) used in local tests; no environment flag enables it.

A readonly revision.json containing uid, runtime_id and revision is captured at gateway startup. Authenticated GET /health returns these alongside ok. Changing the mounted file does not make an already running gateway claim a new revision. Worker apply must recreate both Agent and gateway; gateway health alone does not prove Agent configuration or a model call succeeded.

## HTTP contract

There is no /api prefix. All endpoints require the private gateway token.

| Endpoint | Result |
| --- | --- |
| GET /health | ok and startup managed revision fields when present |
| GET /files | {items: [...]} |
| POST /files | multipart field file; 202 metadata; parsing automatically queued |
| GET /files/{id} | public metadata |
| PATCH /files/{id} | JSON {name: "..."} changes display name only |
| DELETE /files/{id} | delete source/extracted text/metadata; 409 while parsing |
| POST /files/{id}/parse | queue supported format again; 202 |
| GET /files/{id}/text | {text, chunks, truncated, status, name} |
| GET /files/{id}/preview | same shape, bounded to 20,000 text characters and 100 chunks |
| GET /files/{id}/download | original bytes as attachment |
| GET /results | {items: [...], truncated}; explicit nonhidden workspace files |
| GET /results/{id}/download | workspace result bytes as attachment |
| POST /plugins/{id}/test | {supported, ok, message}; actual approved plugin test export |

Uploads use an opaque 32-hex ID and FILES_ROOT/{id}/source.ext. Metadata never returns that internal source path. Workspace results use opaque SHA-256 IDs and relative display paths; download resolves the ID within the current account and opens through pinned directory FDs. Absolute paths, parent traversal, symlinks and hidden workspace entries are excluded. No recursive delete follows filesystem links.

Native passthrough is an explicit method/path allowlist in app.py for session CRUD/history/message/prompt_async/abort/status, global event/health, skill, permission and question operations. Query and header directory are fixed to /workspace. Caller cookies, authorization, gateway secret and routing headers are not forwarded. Native configuration, auth, PTY, shell, command, MCP and native file endpoints are not exposed. File/image URL parts are rejected; the control layer obtains /files/{id}/text and submits extracted text references. SSE is forwarded incrementally and its upstream connection closes on disconnect. No redirect is followed and upstream error bodies are replaced with a generic error.

## Parsing limits and status

One queue worker invokes a separate Python -I -B process with a clean environment. It supplies no gateway or model secrets through arguments or environment. On Linux it sets 384 MiB RLIMIT_AS, 60 seconds RLIMIT_CPU, 200 MiB RLIMIT_FSIZE, 64 FDs, no core dumps, and creates its own process group. The parent enforces a 60-second wall timeout, 12 MiB protocol output maximum and kills the process group on completion/cancellation.

- Original file maximum: 20 MiB, counted during upload. Total multipart request maximum: 21 MiB including framing.
- ZIP expansion maximum: 200 MiB and 10,000 members; encrypted or traversal archive entries rejected without extracting them.
- Extracted text: at most 1,000,000 characters and 10,000 chunks. Truncation reports partial.
- Supported: TXT/MD line ranges; CSV row ranges; XLSX sheet and row ranges using cached formula values; text PDF page numbers; DOCX body paragraph/table row numbers.
- No OCR, macro execution, formula execution, network fetching or office application automation.
- Status values: uploading, queued, parsing, ready, partial, no_text, unsupported, failed. An interrupted queued/parsing record is recovered on startup. Empty/scanned PDF reports no_text, not successful OCR.
- Parser exceptions become generic parse_error, parse_timeout or resource_limit. Library diagnostics are suppressed.

These subprocesses share the account container's UID and mounts. They are a resource and lifecycle boundary, not a separate filesystem security sandbox. The per-account container/mount/network boundaries remain necessary. Configure container RAM above the parser's 384 MiB maximum plus gateway overhead (the approved gateway container limit is 512 MiB) and apply CPU/PID/tmpfs/log limits. Original uploads have an enforced 1 GiB per-account total quota. A single uvicorn worker atomically reserves the actual multipart spool-file size before writing a source, counts every written byte, releases reservations on failure, and frees committed capacity only after source deletion. Startup recomputes usage from source-file stat sizes rather than metadata and removes only records explicitly interrupted in uploading state. Existing over-quota sources remain readable/deletable; further uploads are rejected. Extracted text/metadata and workspace results are outside this original-upload quota and still require deployment disk monitoring.

## Approved plugin connection tests

Readonly /managed/plugin-tests.json maps:

    {"sample": {"entry": "/managed/plugins/sample/1.0.0/entry.mjs", "options": {}}}

The file must be a regular entry.mjs exactly below that plugin's version directory, with no symlink components. The probe imports the administrator-published module and invokes its named export test(options). Its return value must contain boolean ok and string message. A missing export returns supported:false; it never substitutes a gateway health check for a plugin connection test.

The Bun probe has a clean environment, 10-second wall/CPU limits, 1 MiB file output limit, 64 FDs and disabled core dumps. One plugin probe runs per gateway at a time. Bun reserves a large virtual address arena, so the container memory cgroup is its hard memory bound, while the Python parser additionally uses RLIMIT_AS. Process-group cleanup applies on Linux. Probe console/stdout diagnostics are suppressed, bounded and validated again in Python; the message shown to the client is fixed text determined only by supported/ok. Addresses, API keys and free-form plugin output are never returned.

## Model relay

Relay-only MANAGED_ROOT contains model-relay.json:

    {"models": [
      {"id": "platform-model-id", "upstream_model": "actual-model-name",
       "base_url": "http://intranet-model:8000/v1",
       "api_key": "provided-only-to-relay", "allowed_user": "account-internal-id"}
    ]}

ACCOUNT_ID must match every allowed_user. Duplicate IDs, malformed URLs, credentials in URLs, query/fragment target URLs and mismatched accounts fail startup. An empty model list is valid and authorizes no models.

**Never mount this credential-bearing relay directory into the Agent or gateway.** The relay has no workspace/files mounts and uses only its own account internal network plus a dedicated outbound network. The Agent receives a local relay URL and placeholder API key.

GET /v1/models returns platform IDs only. POST /v1/chat/completions accepts only a configured platform model ID, rewrites it to upstream_model, injects the real Bearer key (or omits Authorization for an explicitly keyless intranet model) and sends only to the administrator-configured base_url + /chat/completions. HTTP is allowed for explicit intranet configuration; HTTPS certificate verification is enabled. Caller Authorization and identity fields cannot select account or target. Redirects are rejected, environment proxies ignored, errors redacted and streaming preserved. Network isolation is required because this private relay deliberately does not take a user-supplied tenant identity.

## Local tests

Install requirements.txt and pytest==8.3.5 into an isolated venv. Set BUN_EXECUTABLE to an already installed Bun to run synthetic plugin tests. Run pytest from this directory (not the repository root). If the Windows default pytest temporary directory is restricted, set TEMP/TMP to a local scratch directory and pass a unique --basetemp inside an existing .test-runs directory.

Tests use synthetic credentials, generated documents and HTTPX MockTransport, with no real model/network calls. Linux deployment acceptance must additionally run the directory-FD/symlink and resource-limit cases; a skipped Windows symlink test is not Linux isolation proof.

# Connect Seva Setu MCP to ChatGPT and test OAuth

This guide explains how to connect an MCP-compatible ChatGPT installation to
the Seva Setu citizen or officer tools.

## Important concepts

### The MCP URL is not a webpage

Opening an MCP URL in Chrome is expected to return an authentication error.
The URL is a machine-to-machine API:

```text
https://YOUR_PUBLIC_HOST/mcp/citizen
https://YOUR_PUBLIC_HOST/mcp/officer
```

ChatGPT (or another MCP client) connects to this URL, completes OAuth, and
then sends an HTTP header like:

```http
Authorization: Bearer ACCESS_TOKEN
```

### Portal login and MCP login are separate

Logging in at `/status` or `/admin` proves that the portal works in a browser.
It does not create an MCP session for ChatGPT. ChatGPT must run its own OAuth
authorization-code + PKCE flow and the person must approve access.

### Localhost is not reachable by hosted ChatGPT

`http://localhost:8000` is reachable only from the machine running Docker.
Hosted ChatGPT cannot connect to it. Use a publicly reachable HTTPS hostname,
for example:

```text
https://sewasetu.example.in
```

For a temporary development test, use a secure tunnel such as Cloudflare Tunnel
or ngrok. Keep the tunnel running while ChatGPT is testing. Do not expose the
database or SMS gateway publicly; only expose the portal port.

## 1. Deploy with a public HTTPS URL

On the deployment machine, set the canonical public URL before starting:

```bash
export PUBLIC_BASE_URL='https://YOUR_PUBLIC_HOST'
export ADMIN_PASSWORD='use-a-long-random-password'
docker compose up --build -d --force-recreate
```

The `PUBLIC_BASE_URL` value must include the scheme and must not end with `/`.
It is used in:

- OAuth issuer (`iss`)
- OAuth discovery
- MCP resource audiences (`aud`)
- OAuth redirect and consent links

If the public URL is wrong, ChatGPT may report invalid issuer, audience, or
redirect errors.

Check that the deployment is reachable:

```bash
BASE='https://YOUR_PUBLIC_HOST'

curl -fsS "$BASE/.well-known/oauth-authorization-server"
curl -fsS "$BASE/.well-known/oauth-protected-resource/mcp/citizen"
curl -fsS "$BASE/.well-known/oauth-protected-resource/mcp/officer"
curl -fsS "$BASE/.well-known/jwks.json"
```

The protected-resource metadata should identify the matching MCP resource and
the authorization server. The authorization-server metadata should contain:

- `authorization_endpoint`
- `token_endpoint`
- `registration_endpoint`
- `jwks_uri`
- `code_challenge_methods_supported: ["S256"]`

## 2. Choose the correct MCP endpoint

### Citizen or family helper

```text
https://YOUR_PUBLIC_HOST/mcp/citizen
```

The citizen signs in with mobile number + OTP and consents to the `citizen`
scope. The citizen tools can check eligibility, create/update a draft, upload
age proof, submit, read status, and withdraw a pending application.

### Block officer

```text
https://YOUR_PUBLIC_HOST/mcp/officer
```

The officer signs in with the departmental username and password and consents
to the `officer` scope. The officer tools can list the pilot queue, inspect a
case, and approve or reject a pending case with a reason.

The two endpoints are intentionally separate. A citizen token must not work at
the officer endpoint, and an officer token must not work at the citizen
endpoint.

## 3. Add the remote MCP server in ChatGPT

The exact labels vary by ChatGPT plan and release, but the flow is generally:

1. Open ChatGPT settings.
2. Open **Connectors**, **Apps**, or **MCP/remote tools**.
3. Choose **Add custom connector** or **Add remote MCP server**.
4. Enter one of the HTTPS MCP URLs above.
5. Let ChatGPT fetch the OAuth protected-resource metadata.
6. Choose **Sign in / Connect** when ChatGPT asks for authorization.
7. Complete the Seva Setu login in the opened browser:
   - citizen: mobile number, OTP from the Seva Setu SMS channel, then consent;
   - officer: `admin` and the configured `ADMIN_PASSWORD`, then consent.
8. Return to ChatGPT and enable the connector for the conversation.

If ChatGPT connects successfully but says that actions are not appearing in
the tool registry, remove and reconnect the connector after deploying server
changes. ChatGPT may cache the MCP initialization and `tools/list` response.
Confirm that a manual MCP client receives a successful `initialize` response
followed by `tools/list` before reconnecting ChatGPT.
9. Ask ChatGPT to list available tools.

Use a separate connector for the citizen and officer endpoints. Do not give
the officer connector to a citizen-facing assistant.

If ChatGPT asks for a client ID, redirect URI, or OAuth metadata URL, use the
dynamic-registration instructions in the next section. If the ChatGPT UI
supports automatic OAuth discovery, no manual client secret should be needed.

## 4. OAuth dynamic client registration

Seva Setu exposes RFC 7591 registration at:

```text
https://YOUR_PUBLIC_HOST/oauth/register
```

ChatGPT normally performs this step itself. To test it manually, use a real
HTTPS callback supplied by your MCP client. For a local test client,
`http://localhost` callbacks are allowed.

Example:

```bash
BASE='https://YOUR_PUBLIC_HOST'
curl -i -X POST "$BASE/oauth/register" \
  -H 'Content-Type: application/json' \
  -d '{
    "client_name": "Seva Setu OAuth test client",
    "redirect_uris": ["http://localhost:8765/callback"],
    "token_endpoint_auth_method": "none"
  }'
```

Save the returned `client_id`. A public PKCE client uses
`token_endpoint_auth_method: none`.

For a hosted ChatGPT connector, the redirect URI must be the callback that
ChatGPT provides. Do not substitute an arbitrary callback. ChatGPT may use a
client metadata document instead of dynamic registration; follow the URL it
provides.

## 5. Manual OAuth authorization-code + PKCE test

This test proves the complete OAuth path independently of ChatGPT.

### 5.1 Generate a PKCE verifier and challenge

Run:

```bash
python - <<'PY'
import base64
import hashlib
import secrets

def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

verifier = b64(secrets.token_bytes(32))
challenge = b64(hashlib.sha256(verifier.encode()).digest())
print("CODE_VERIFIER=" + verifier)
print("CODE_CHALLENGE=" + challenge)
PY
```

Keep the printed `CODE_VERIFIER` private. Export both values:

```bash
export CODE_VERIFIER='paste-the-verifier-here'
export CODE_CHALLENGE='paste-the-challenge-here'
export BASE='https://YOUR_PUBLIC_HOST'
export CLIENT_ID='paste-the-client-id-from-registration'
export REDIRECT_URI='http://localhost:8765/callback'
export RESOURCE="$BASE/mcp/citizen"
```

Use `$BASE/mcp/officer` for an officer test.

### 5.2 Build the authorization URL

```bash
python - <<'PY'
import os
from urllib.parse import urlencode

query = urlencode({
    "response_type": "code",
    "client_id": os.environ["CLIENT_ID"],
    "redirect_uri": os.environ["REDIRECT_URI"],
    "scope": "citizen",
    "resource": os.environ["RESOURCE"],
    "code_challenge": os.environ["CODE_CHALLENGE"],
    "code_challenge_method": "S256",
    "state": "manual-oauth-test",
})
print(os.environ["BASE"] + "/oauth/authorize?" + query)
PY
```

Open the printed URL in a browser. Sign in:

- citizen test: enter a mobile number, read the OTP from
  `https://YOUR_PUBLIC_HOST/__gateway/`, enter the OTP, and allow access;
- officer test: enter the departmental username/password and allow access.

After approval, the browser redirects to the callback with a `code` and
`state`. Copy the `code` value before it expires.

### 5.3 Exchange the code for tokens

```bash
export AUTH_CODE='paste-the-code-from-the-callback'

curl -sS -X POST "$BASE/oauth/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=authorization_code' \
  --data-urlencode "client_id=$CLIENT_ID" \
  --data-urlencode "redirect_uri=$REDIRECT_URI" \
  --data-urlencode "code=$AUTH_CODE" \
  --data-urlencode "code_verifier=$CODE_VERIFIER" \
  --data-urlencode "resource=$RESOURCE"
```

A successful response contains:

```json
{
  "access_token": "...",
  "token_type": "Bearer",
  "expires_in": 1200,
  "refresh_token": "...",
  "scope": "citizen"
}
```

Do not paste the access or refresh token into a ticket, screenshot, commit, or
chat. Treat them like passwords.

## 6. Call MCP tools with the access token

Save the access token:

```bash
export ACCESS_TOKEN='paste-the-access-token'
```

Initialize the MCP session:

```bash
curl -sS "$BASE/mcp/citizen" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-03-26",
      "capabilities": {},
      "clientInfo": {"name": "manual-test", "version": "1.0"}
    }
  }'
```

List available tools:

```bash
curl -sS "$BASE/mcp/citizen" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

Call a read-only citizen tool:

```bash
curl -sS "$BASE/mcp/citizen" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "get_scheme_information",
      "arguments": {}
    }
  }'
```

For the officer endpoint, change the URL and call:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "get_queue",
    "arguments": {}
  }
}
```

## 7. OAuth and authorization negative tests

These tests should fail safely.

### No token

```bash
curl -i "$BASE/mcp/citizen"
```

Expected: `401 Unauthorized` and a `WWW-Authenticate` header pointing to
protected-resource metadata.

### Wrong audience

Use a valid citizen token against the officer URL:

```bash
curl -i "$BASE/mcp/officer" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Expected: `401 Unauthorized`. The token audience is the citizen resource.

### Citizen token calling an officer tool

```bash
curl -sS "$BASE/mcp/citizen" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_queue","arguments":{}}}'
```

Expected: an error saying the tool is not available on this endpoint.

### Reuse an authorization code

Repeat the token request with the same `AUTH_CODE`. Expected:

```json
{"error":"invalid_grant"}
```

Authorization codes are single-use.

### Wrong PKCE verifier

Use a different verifier during the token request. Expected:

```json
{"error":"invalid_grant","error_description":"PKCE verification failed"}
```

### Refresh-token rotation

Use the refresh token once:

```bash
export REFRESH_TOKEN='paste-refresh-token-here'
curl -sS -X POST "$BASE/oauth/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=refresh_token' \
  --data-urlencode "client_id=$CLIENT_ID" \
  --data-urlencode "refresh_token=$REFRESH_TOKEN" \
  --data-urlencode "resource=$RESOURCE"
```

The response contains a new refresh token. Reusing the old refresh token must
fail because refresh tokens rotate.

## 8. Test checklist for the assessment

### Citizen connector

- [ ] ChatGPT can discover the citizen MCP metadata.
- [ ] Citizen OAuth login opens successfully.
- [ ] The user sees consent before access is granted.
- [ ] `get_scheme_information` works.
- [ ] `check_eligibility` rejects an applicant below age 60.
- [ ] A valid draft can be submitted only with an age-proof document.
- [ ] The resulting application appears in the normal portal/admin views.
- [ ] A duplicate active application is not created.
- [ ] The citizen cannot see officer tools.

### Officer connector

- [ ] ChatGPT can discover the officer MCP metadata.
- [ ] Officer OAuth login opens successfully.
- [ ] `get_queue` returns only the pilot queue.
- [ ] The officer can inspect a case.
- [ ] Approve/reject requires a reason.
- [ ] The decision records the authenticated officer and audit note.
- [ ] A second decision on a non-pending case fails safely.
- [ ] The officer endpoint rejects a citizen token.

## 9. Common errors

### `Bearer OAuth access token required`

You opened the MCP URL directly or called it without an `Authorization` header.
Use ChatGPT's remote MCP connector or complete the manual OAuth flow above.

### `invalid_client`

The client ID is unknown, the registration was not completed, or a confidential
client omitted its client secret.

### `invalid_grant`

The code expired, was already used, the redirect URI differs, or the PKCE
verifier is wrong. Start a fresh authorization request.

### `invalid_target`

The OAuth `resource` in the token request does not exactly match the resource
used in the authorization request. Use the exact MCP URL.

### Issuer or audience error

Check that `PUBLIC_BASE_URL` is the public HTTPS URL, recreate the containers,
and start OAuth again. Do not mix `localhost` and the public hostname in one
flow.

### ChatGPT cannot reach the server

Confirm that:

1. The URL is public HTTPS, not `localhost`.
2. The deployment remains running.
3. The reverse proxy forwards POST requests and authorization headers.
4. The MCP path is not blocked by a login page or WAF.
5. Discovery URLs return JSON without a bearer token.

## 10. Security rules

- Use HTTPS for any non-local deployment.
- Never expose PostgreSQL port `5432` or SMS gateway port `8025` publicly.
- Keep `ADMIN_PASSWORD` out of source control.
- Never log or share OTPs, access tokens, refresh tokens, bank accounts, or
  uploaded documents.
- Use the citizen endpoint for citizen work and the officer endpoint for
  officer work; do not combine their credentials.
- Revoke access from the portal's connected-applications controls or call the
  OAuth revocation endpoint when testing is finished.

# Seva Setu: Simple Local Guide

This guide explains how to run the portal and how to log in.

## 1. Start the portal

Open a terminal in the project folder:

```bash
cd /workspaces/Bharat_Fellowship_Sewasetu_AI
```

Choose an admin password and start the services:

```bash
ADMIN_PASSWORD='my-admin-password' docker compose up --build -d
```

Replace `my-admin-password` with your own password. Do not use quotes inside
the password.

The Compose file publishes the local database and SMS gateway ports so the
portal works reliably in Codespaces and Docker environments where containers
cannot directly reach one another by service name.

Open the portal:

- Home: http://localhost:8000
- Citizen application: http://localhost:8000/apply
- Citizen status: http://localhost:8000/status
- Officer/admin login: http://localhost:8000/admin
- Test SMS inbox: http://localhost:8000/__gateway/
- Evaluation dashboard: http://localhost:8000/eval-dashboard
- AI assistant connection help: http://localhost:8000/agent-help

For the complete ChatGPT connection, OAuth, PKCE, MCP tool, and negative-test
instructions, read [CHATGPT_MCP_GUIDE.md](./CHATGPT_MCP_GUIDE.md).

## 2. Important: there is no signup page

There are two different login types.

### Citizen/status login

The status page does not have a separate signup button.

1. Go to http://localhost:8000/apply.
2. Enter a 10-digit mobile number.
3. Click **Send OTP**.
4. Open http://localhost:8000/__gateway/ and find the latest OTP for that
   mobile number.
5. Enter the OTP in the application page.
6. Complete and submit the pension application.
7. After successful submission, the portal creates the citizen status account.

Then use http://localhost:8000/status:

- Mobile number: the number used for the application
- Password: the applicant's date of birth in `DDMMYYYY` format

Example: a date of birth of 5 January 1956 becomes:

```text
05011956
```

The status account is created only after an application is submitted. If the
application was never submitted, status login will correctly say that the
mobile/password is incorrect.

## 3. Admin/officer login

The admin account is already built in. There is no admin signup page.

- URL: http://localhost:8000/admin
- Username: `admin`
- Password: the value supplied in `ADMIN_PASSWORD`

For example:

```bash
ADMIN_PASSWORD='sewa-2026' docker compose up --build -d
```

Then log in with:

```text
Username: admin
Password: sewa-2026
```

## 4. If you changed the password but login still fails

Docker gives the password to the app when the app container is created. A
normal browser refresh or `docker compose restart` does not change it.

Recreate the app and scheduler containers:

```bash
ADMIN_PASSWORD='sewa-2026' docker compose up --build -d --force-recreate app scheduler
```

Check the active password setting without printing the password:

```bash
docker compose config | grep ADMIN_PASSWORD
```

The output should show the password value you supplied. Keep this terminal
output private.

## 5. Use a `.env` file instead of typing the password every time

Create a file named `.env` in the project folder:

```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=sewa-2026
PUBLIC_BASE_URL=http://localhost:8000
```

Then run:

```bash
docker compose up --build -d --force-recreate
```

Do not commit `.env` to Git if it contains a real password. For a public
deployment, use a long random password and HTTPS.

## 6. Common problems

### “Mobile number or password is incorrect” on `/status`

Usually one of these is the cause:

- The application was not submitted successfully.
- The mobile number is different from the one used during application.
- The date of birth was not entered as `DDMMYYYY`.
- The application was created for a different applicant/mobile.

The status password is not the admin password.

### “Invalid credentials” on `/admin`

Use exactly:

- Username: `admin`
- Password: the current `ADMIN_PASSWORD`

If you changed `ADMIN_PASSWORD`, recreate the containers using the command in
section 4.

### OTP is not visible

Wait a few seconds, then refresh:

http://localhost:8000/__gateway/

The project uses a simulated SMS gateway. No real SMS is sent.

### MCP shows “Bearer OAuth access token required”

This is expected when you open the MCP URL directly in a browser or call it
with plain `curl`. The MCP endpoints are private agent APIs; they do not allow
anonymous access.

Use these endpoint URLs in an MCP client that supports OAuth:

- Citizen MCP: `http://localhost:8000/mcp/citizen`
- Officer MCP: `http://localhost:8000/mcp/officer`

The MCP client should discover OAuth from the endpoint, open the portal sign-in
page, and request consent:

- Citizen signs in with mobile number and OTP.
- Officer signs in with username `admin` and the configured
  `ADMIN_PASSWORD`.

Do not paste an admin password or OTP into an MCP request. The MCP client must
send the resulting access token as:

```http
Authorization: Bearer <access-token>
```

The endpoint discovery documents are:

- Citizen: `http://localhost:8000/.well-known/oauth-protected-resource/mcp/citizen`
- Officer: `http://localhost:8000/.well-known/oauth-protected-resource/mcp/officer`

You can open those discovery URLs in a browser; they do not require a token.

### Where is the AI agent?

There is no chat box inside the Seva Setu portal. The portal is the official
service and MCP server; the AI assistant is a separate application such as
Claude Code or another MCP-compatible client.

Open http://localhost:8000/agent-help for the two endpoint URLs and the login
flow. If you open `/mcp/citizen` or `/mcp/officer` directly in Chrome, the
bearer-token message is normal.

### Check whether services are running

```bash
docker compose ps
```

The `app`, `db`, `scheduler`, and `smsgw` services should be running.

View app logs:

```bash
docker compose logs --tail=100 app
```

## 7. Stop the portal

This stops the containers but keeps the database volume:

```bash
docker compose down
```

To start again with the same configured environment:

```bash
docker compose up -d
```

The database is loaded from `seed/seed.sql` the first time the database volume
is created. Existing database data is not reloaded on every restart.

## 8. If an older stack was already running

After pulling these fixes, recreate all services once:

```bash
ADMIN_PASSWORD='your-password' docker compose up --build -d --force-recreate
```

Then check:

```bash
docker compose ps
```

Open the following pages to confirm the stack is healthy:

- http://localhost:8000/apply
- http://localhost:8000/admin
- http://localhost:8000/__gateway/
- http://localhost:8000/eval-dashboard

If a page shows an empty response, inspect the app log:

```bash
docker compose logs --tail=100 app
```

# Seva Setu, agent-ready: implementation plan

## 1. Understanding of the assignment

The goal is not to build a chatbot that explains the pension scheme. The goal is
to make an AI assistant a safe, interoperable channel for the existing service:

- A citizen (or a trusted helper acting with the citizen's consent) can check
  eligibility, submit an old-age pension application, and follow its status.
- A block officer can inspect the work queue and approve or reject an application
  with a recorded reason.
- The existing Seva Setu portal remains the system of record. Applications made
  through an agent must be visible in the existing citizen and officer portals.
- The agent channel must not bypass validations, consent, identity checks,
  document requirements, duplicate-application rules, or the 15-day deemed
  approval rule.
- The citizen and officer capabilities must be exposed through separate public
  MCP endpoints. A citizen token must never expose officer tools.
- The first release should be limited to a clearly declared subset of blocks,
  making the scope safe to test and easy to explain.

The supplied portal already provides the key foundations: PostgreSQL-backed
application and audit tables, shared scheme validation in
`app/app.py`, citizen and officer web flows, simulated SMS, and OAuth 2.1
authorization with `citizen` and `officer` scopes.

## 2. Proposed architecture

### Portal (system of record)

Keep all authoritative writes in the portal's database and domain functions:

1. Add a small internal service layer around `validate_application`,
   `active_application`, `create_application`, the application status query,
   withdrawal, and officer decision logic.
2. Ensure every agent write uses parameterized SQL and the same validation path
   as the web form.
3. Add an explicit transaction around each submission or decision.
4. Add audit entries identifying the OAuth subject and the MCP client, for
   example `agent:citizen:<mobile>` or `agent:officer:<username>`, while
   preserving the human identity in the actor field.
5. Keep uploaded documents in the existing upload storage. The MCP server may
   accept a controlled document upload, but it must never treat a filename or
   agent assertion as proof that a document exists.

### Citizen MCP server

Expose a separate streamable HTTP endpoint, protected by a portal-issued OAuth
token with `scope=citizen` and an audience equal to the citizen MCP URL.
Suggested tools:

- `get_scheme_information`: return the current amount, minimum age, supported
  blocks, required fields/documents, submission deadline, and status meanings.
- `check_eligibility`: validate the supplied facts without creating an
  application; return structured errors and missing information.
- `get_my_application`: return only the authenticated citizen's own current
  application and relevant audit/status information.
- `start_application`: create a server-side draft keyed to the authenticated
  citizen, or return the existing active application. Do not accept mobile
  identity as a free-form argument.
- `update_application`: update draft fields with field-level validation and
  return remaining required fields.
- `upload_age_proof`: accept a bounded, supported document upload and associate
  it with the authenticated draft.
- `submit_application`: run the complete shared validation and duplicate check,
  create the application, and return the application number.
- `withdraw_application`: allow withdrawal only for the authenticated citizen's
  pending application, matching the portal's existing rule.

The server should return machine-readable error codes plus plain-language
messages. It should not invent an answer when the portal cannot verify a fact.
The assistant should be able to ask for one missing field at a time, which is
important for shared phones, kiosks, and users who speak in short answers.

### Officer MCP server

Expose a different streamable HTTP endpoint, protected by an OAuth token with
`scope=officer` and an audience equal to the officer MCP URL. Suggested tools:

- `get_queue`: list pending applications for the officer's permitted block(s),
  including age of application and SLA/deemed-approval risk.
- `get_application`: show the reviewable application fields and audit trail,
  but not unrelated citizens or credentials.
- `get_document`: retrieve the submitted age-proof document for review.
- `approve_application`: approve only a currently pending application and
  require a decision note; record the authenticated officer as decision maker.
- `reject_application`: reject only a currently pending application and require
  a clear reason; record the authenticated officer and reason.
- `get_application_status`: confirm the resulting status and audit entry.

The server must re-check the current database status inside the write
transaction. It must return a conflict if a different officer or the scheduler
has already decided the case. The model may summarize a case, but only the
explicit approve/reject tool call may change it.

### Authentication and authorization

- Use the portal's OAuth discovery, PKCE authorization-code flow, and consent
  pages rather than implementing a second login or handling OTP/passwords in
  the MCP servers.
- Register the two MCP servers as separate OAuth clients/resources.
- Validate `iss`, `aud`, `exp`, signature, `role`, and exact scope on every
  request. Reject a citizen token at the officer endpoint and vice versa.
- Keep access tokens short-lived and honor refresh-token/session expiry.
- Never place bank account numbers, OTPs, passwords, or access tokens in logs,
  eval pages, prompts, or error messages.
- Configure HTTPS and `PUBLIC_BASE_URL` correctly before exposing endpoints.

## 3. Deliberate block scope

Start with `Sonari` and `Rajapara`. They are enough to demonstrate the full
workflow while making the limited rollout explicit. The block allow-list must
be enforced server-side for both application submission and officer queue
access. A request for another block should receive a clear "not available
through the agent channel yet" response and should not create a draft or
application.

After the end-to-end flow is stable, expand the allow-list only by
configuration, not by changing validation behavior.

## 4. Personas and evaluation scenarios

Each eval should run through a real MCP client, use OAuth sign-in, and verify
the PostgreSQL state after the conversation. The dashboard should show the
scenario, sanitized transcript, expected state, observed state, and pass/fail
reason.

### Citizen personas

1. **Kamala Das, 70, Sonari**
   - Widow from Bhelaghat village; speaks in short, informal answers.
   - Her grandson helps on a shared phone.
   - Has a valid age proof and bank details.
   - Expected result: one `PENDING` application, correct mobile ownership,
     normalized bank/IFSC values, document path, `SUBMIT` audit entry, and an
     application number visible in the normal status portal.

2. **Amina Begum, 59, Rajapara**
   - Wants the pension urgently and says she is "almost 60".
   - Expected result: no application row and a clear minimum-age explanation.

3. **Janki Saikia, 66, Sonari**
   - Has an active application already and asks the assistant to submit again.
   - Expected result: no duplicate active application; the existing application
     number is returned.

4. **Madhab Bora, 74, Rajapara**
   - Gives a malformed IFSC, an undersized account number, and no age proof.
   - Expected result: no write; field-level errors; the assistant asks only for
     the missing/corrected information.

5. **Parul Devi, 68, an unsupported block**
   - Requests service for a block outside the pilot allow-list.
   - Expected result: no draft/application; truthful explanation and a
     recommendation to use the normal portal/counter.

6. **Rupa Das, 63, Sonari**
   - Has a valid pending application and asks to withdraw it.
   - Expected result: only her pending application changes to `WITHDRAWN`, with
     the matching audit entry; she can then start a fresh application.

### Officer personas

7. **Officer Ananya Sharma, Sonari**
   - Uses the officer endpoint to view the queue, inspect Kamala's application,
     and approve it with a reason.
   - Expected result: status `APPROVED`, `decided_by` set to the authenticated
     officer, decision timestamp present, and an audit entry containing the
     reason. The web admin portal shows the same result.

8. **Officer Ananya Sharma, concurrent decision**
   - Attempts to approve an application that was already decided or deemed
     approved.
   - Expected result: no second mutation; a conflict/status response explains
     that only pending applications can be decided.

9. **Officer Ananya Sharma, rejection**
   - Rejects a pending case with a specific reason.
   - Expected result: status `REJECTED`, recorded reason and actor, visible in
     both the officer response and the portal audit trail.

### Cross-cutting adversarial checks

- Citizen token cannot call officer tools.
- Officer token cannot read another officer's credentials or unrelated secrets.
- The model cannot approve by putting "approved" in a natural-language message;
  only the decision tool mutates state.
- Repeated submit calls are idempotent or return the existing application.
- Invalid dates, ages, block names, account numbers, IFSCs, and missing documents
  never produce a successful application.
- A portal-made application is readable through the citizen MCP status tool, and
  an MCP-made application is readable in the portal.

## 5. Eval dashboard

Add `/eval-dashboard` to the deployed portal. It should be read-only and show:

- pilot blocks and the current scheme rules;
- the persona/scenario catalog;
- latest run time and MCP client used;
- sanitized conversation or representative turns;
- database assertions checked for each scenario;
- pass/fail result and a short failure explanation;
- aggregate pass rate, grouped by citizen, officer, and safety scenario.

Do not show real seeded citizen data, access tokens, OTPs, full bank accounts,
or uploaded documents on this page. Seed dedicated eval users with synthetic
data and mask sensitive values.

## 6. Delivery sequence

1. **Baseline and contracts:** run the portal, inspect seeded data, document
   OAuth discovery, and define JSON schemas for each MCP tool.
2. **Shared service layer:** extract/reuse application reads, submission,
   withdrawal, queue, and decision operations without duplicating rules.
3. **Citizen MCP:** implement authentication, read/check tools, drafts, document
   upload, submit, and withdrawal.
4. **Officer MCP:** implement queue, case/document review, approve/reject, and
   conflict handling.
5. **Real-client tests:** exercise both endpoints with a real MCP client and
   assert database and portal visibility after every scenario.
6. **Dashboard and deployment:** add the sanitized eval dashboard, HTTPS/public
   configuration, health checks, and limited-block configuration.
7. **Assessment rehearsal:** use a fresh citizen sign-in and officer sign-in,
   test invented scenarios with a limited number of turns, and record a
   three-minute Loom walkthrough.

## 7. Three design decisions that matter most

1. **Portal-first writes:** MCP is an adapter, not a second application system.
   This prevents the agent channel from silently changing eligibility or
   creating records the counter would reject.
2. **Separate audiences and scopes:** citizen and officer MCP endpoints are
   independently authenticated and authorized. Separation reduces accidental
   disclosure and makes the security boundary understandable to assessors.
3. **Database-backed evals:** a natural-language success message is not a pass.
   Every scenario must assert the actual application, status, actor, audit trail,
   and cross-channel visibility in the database and portal.

With more time, I would add localized voice/IVR and assisted document capture
after the structured MCP workflow is proven. I would not begin with a broad
agent that can call arbitrary portal endpoints.

## 8. Submission checklist

- Public citizen MCP endpoint.
- Public officer MCP endpoint.
- Public Seva Setu portal URL.
- Assessor officer/admin credentials shared separately and rotated after the
  assessment.
- Public `/eval-dashboard` URL.
- Private `sewasetu-assistant` repository with full history and `harshnisar`
  invited.
- Repository zip including `.git`.
- Loom video of no more than three minutes covering architecture, personas,
  eval results, and changes made from those results.

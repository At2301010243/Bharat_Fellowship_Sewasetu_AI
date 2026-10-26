"""Small streamable-HTTP MCP surface for the Seva Setu portal.

The portal remains authoritative: tools call the same validation, application,
decision, and audit primitives as the HTML portal.
"""

import base64
import json
import os
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request

import app as portal
import oauth as oauth_server

agent_mcp = Blueprint("agent_mcp", __name__)
ISSUER = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

PILOT_BLOCKS = {"Sonari", "Rajapara"}
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
DOCUMENT_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}


def _endpoint(kind):
    return ISSUER + ("/mcp/citizen" if kind == "citizen" else "/mcp/officer")


def _jsonrpc(request_id, result=None, error=None):
    response = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result
    flask_response = jsonify(response)
    flask_response.headers["MCP-Protocol-Version"] = "2025-03-26"
    return flask_response


def _error(request_id, code, message, data=None):
    detail = {"code": code, "message": message}
    if data is not None:
        detail["data"] = data
    return _jsonrpc(request_id, error={"code": -32000, "message": message, "data": detail})


def _claims(kind):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None, "Bearer OAuth access token required"
    claims = oauth_server.verify_token(header[7:].strip(), _endpoint(kind))
    if not claims or claims.get("role") != kind or claims.get("scope") != kind:
        return None, "token is not authorized for this MCP endpoint"
    return claims, None


def _protected_resource_metadata(kind):
    return {
        "resource": _endpoint(kind),
        "authorization_servers": [ISSUER],
        "scopes_supported": [kind],
        "bearer_methods_supported": ["header"],
    }


@agent_mcp.get("/.well-known/oauth-protected-resource")
def protected_resource_metadata_default():
    """Backward-compatible metadata endpoint; defaults to the citizen resource."""
    return jsonify(_protected_resource_metadata("citizen"))


@agent_mcp.get("/.well-known/oauth-protected-resource/mcp/citizen")
def citizen_protected_resource_metadata():
    """RFC 9728 metadata for the citizen MCP resource."""
    return jsonify(_protected_resource_metadata("citizen"))


@agent_mcp.get("/.well-known/oauth-protected-resource/mcp/officer")
def officer_protected_resource_metadata():
    """RFC 9728 metadata for the officer MCP resource."""
    return jsonify(_protected_resource_metadata("officer"))


@agent_mcp.get("/.well-known/oauth-protected-resource/<path:resource_path>")
def protected_resource_metadata_legacy(resource_path):
    """Handle clients that request a resource-specific path not listed above."""
    kind = "officer" if resource_path == "mcp/officer" else "citizen"
    return jsonify(_protected_resource_metadata(kind))


def _subject_mobile(claims):
    prefix, value = claims["sub"].split(":", 1)
    if prefix != "citizen":
        raise ValueError("invalid citizen subject")
    return value


def _subject_officer(claims):
    prefix, value = claims["sub"].split(":", 1)
    if prefix != "officer":
        raise ValueError("invalid officer subject")
    return value


def _tool_result(value, structured=True):
    text = json.dumps(value, ensure_ascii=False, default=str)
    result = {"content": [{"type": "text", "text": text}]}
    if structured:
        result["structuredContent"] = value
    return result


def _require(args, *names):
    missing = [name for name in names if not str(args.get(name, "")).strip()]
    if missing:
        raise ValueError("missing required field(s): " + ", ".join(missing))


def _safe_data(args):
    allowed = {
        "applicant_name", "dob", "gender", "marital_status", "husband_name",
        "village", "block", "bank_account", "ifsc",
    }
    return {key: args[key] for key in allowed if key in args}


def _draft_row(cur, draft_id, mobile):
    cur.execute("SELECT id, data, doc_path FROM agent_drafts WHERE id = %s AND mobile = %s",
                (draft_id, mobile))
    row = cur.fetchone()
    if not row:
        raise ValueError("draft not found for the authenticated citizen")
    return row


def _citizen_tool(name, args, claims):
    mobile = _subject_mobile(claims)
    if name in {"start_application", "update_application", "upload_age_proof", "submit_application"}:
        portal.ensure_agent_schema()
    conn = portal.get_db()
    cur = conn.cursor()
    try:
        if name == "get_scheme_information":
            return {
                "scheme": "Old Age Pension Scheme",
                "amount_rupees_per_month": 250,
                "minimum_age": portal.MIN_AGE,
                "supported_blocks": sorted(PILOT_BLOCKS),
                "required_document": "age proof (PDF, JPG or PNG, up to 5 MB)",
                "sla_days": portal.SLA_DAYS,
                "deadline": portal.SCHEME_DEADLINE.isoformat(sep=" "),
                "statuses": ["PENDING", "APPROVED", "REJECTED", "DEEMED_APPROVED", "WITHDRAWN"],
            }
        if name == "check_eligibility":
            data = _safe_data(args)
            block = data.get("block", "").strip()
            if block and block not in PILOT_BLOCKS:
                return {"eligible": False, "errors": ["This agent channel currently serves only Sonari and Rajapara."]}
            errors, cleaned = portal.validate_application(data, args.get("doc_path", ""))
            return {"eligible": not errors, "errors": errors,
                    "normalized": {key: str(value) if value is not None else None
                                   for key, value in cleaned.items() if key != "doc_path"}}
        if name == "start_application":
            cur.execute("SELECT id FROM agent_drafts WHERE mobile = %s ORDER BY updated_at DESC LIMIT 1",
                        (mobile,))
            existing = cur.fetchone()
            if existing:
                return {"draft_id": str(existing[0]), "reused": True}
            draft_id = str(uuid.uuid4())
            now = datetime.now()
            cur.execute("INSERT INTO agent_drafts (id, mobile, data, created_at, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s)", (draft_id, mobile, json.dumps({}), now, now))
            conn.commit()
            return {"draft_id": str(draft_id), "reused": False}
        if name == "update_application":
            _require(args, "draft_id")
            row = _draft_row(cur, args["draft_id"], mobile)
            data = dict(row[1] or {})
            data.update(_safe_data(args))
            if data.get("block") and data["block"] not in PILOT_BLOCKS:
                raise ValueError("This agent channel currently serves only Sonari and Rajapara.")
            cur.execute("UPDATE agent_drafts SET data = %s, updated_at = %s WHERE id = %s AND mobile = %s",
                        (json.dumps(data), datetime.now(), args["draft_id"], mobile))
            conn.commit()
            return {"draft_id": args["draft_id"], "data": data}
        if name == "upload_age_proof":
            _require(args, "draft_id", "filename", "content_base64")
            row = _draft_row(cur, args["draft_id"], mobile)
            filename = os.path.basename(args["filename"]).lower()
            extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
            if extension not in DOCUMENT_EXTENSIONS:
                raise ValueError("document must be a PDF, JPG or PNG")
            try:
                content = base64.b64decode(args["content_base64"], validate=True)
            except (ValueError, TypeError):
                raise ValueError("content_base64 is not valid base64")
            if len(content) > MAX_DOCUMENT_BYTES:
                raise ValueError("document is larger than 5 MB")
            os.makedirs(portal.UPLOAD_DIR, exist_ok=True)
            path = os.path.join(portal.UPLOAD_DIR, "agent_%s_%s" % (mobile, filename))
            with open(path, "wb") as output:
                output.write(content)
            cur.execute("UPDATE agent_drafts SET doc_path = %s, updated_at = %s WHERE id = %s AND mobile = %s",
                        (path, datetime.now(), args["draft_id"], mobile))
            conn.commit()
            return {"draft_id": args["draft_id"], "document_received": True}
        if name == "submit_application":
            _require(args, "draft_id")
            row = _draft_row(cur, args["draft_id"], mobile)
            data = dict(row[1] or {})
            if data.get("block") not in PILOT_BLOCKS:
                raise ValueError("application block must be Sonari or Rajapara for the pilot")
            errors, cleaned = portal.validate_application(data, row[2] or "")
            if errors:
                return {"submitted": False, "errors": errors}
            existing = portal.active_application(cur, mobile)
            if existing:
                return {"submitted": False, "existing_application": {
                    "id": existing[0], "application_no": existing[1], "status": existing[2]}}
            app_id, app_no = portal.create_application(cur, mobile, cleaned)
            cur.execute("DELETE FROM agent_drafts WHERE id = %s AND mobile = %s",
                        (args["draft_id"], mobile))
            conn.commit()
            return {"submitted": True, "application_id": app_id, "application_no": app_no, "status": "PENDING"}
        if name == "get_my_application":
            cur.execute("SELECT id, application_no, applicant_name, village, block, status, "
                        "submitted_at, decided_at, decided_by FROM applications "
                        "WHERE mobile = %s ORDER BY submitted_at DESC LIMIT 1", (mobile,))
            row = cur.fetchone()
            if not row:
                return {"application": None}
            return {"application": dict(zip(
                ["id", "application_no", "applicant_name", "village", "block", "status",
                 "submitted_at", "decided_at", "decided_by"], row))}
        if name == "withdraw_application":
            _require(args, "application_id")
            cur.execute("UPDATE applications SET status='WITHDRAWN', decided_at=%s, "
                        "decided_by='APPLICANT' WHERE id=%s AND mobile=%s AND status='PENDING' "
                        "RETURNING application_no", (datetime.now(), args["application_id"], mobile))
            row = cur.fetchone()
            if not row:
                raise ValueError("only your pending application can be withdrawn")
            portal.write_audit(cur, args["application_id"], "WITHDRAW", "agent:citizen:%s" % mobile)
            conn.commit()
            return {"withdrawn": True, "application_no": row[0], "status": "WITHDRAWN"}
        raise KeyError(name)
    finally:
        cur.close()
        conn.close()


def _officer_tool(name, args, claims):
    officer = _subject_officer(claims)
    conn = portal.get_db()
    cur = conn.cursor()
    try:
        if name == "get_queue":
            cur.execute("SELECT id, application_no, applicant_name, village, block, status, submitted_at "
                        "FROM applications WHERE status='PENDING' AND block = ANY(%s) "
                        "ORDER BY submitted_at ASC LIMIT 100", (list(PILOT_BLOCKS),))
            keys = ["id", "application_no", "applicant_name", "village", "block", "status", "submitted_at"]
            return {"officer": officer, "applications": [dict(zip(keys, row)) for row in cur.fetchall()]}
        if name in ("get_application", "get_application_status"):
            _require(args, "application_id")
            cur.execute("SELECT id, application_no, applicant_name, mobile, dob, village, block, "
                        "bank_account, ifsc, status, submitted_at, decided_at, decided_by "
                        "FROM applications WHERE id=%s AND block = ANY(%s)",
                        (args["application_id"], list(PILOT_BLOCKS)))
            row = cur.fetchone()
            if not row:
                raise ValueError("application not found in the officer pilot blocks")
            keys = ["id", "application_no", "applicant_name", "mobile", "dob", "village", "block",
                    "bank_account", "ifsc", "status", "submitted_at", "decided_at", "decided_by"]
            result = {"application": dict(zip(keys, row))}
            if name == "get_application":
                cur.execute("SELECT action, actor, note, at FROM audit_log WHERE application_id=%s ORDER BY at",
                            (args["application_id"],))
                result["audit"] = [dict(zip(["action", "actor", "note", "at"], item))
                                   for item in cur.fetchall()]
            return result
        if name in ("approve_application", "reject_application"):
            _require(args, "application_id", "note")
            status = "APPROVED" if name == "approve_application" else "REJECTED"
            cur.execute("UPDATE applications SET status=%s, decided_at=%s, decided_by=%s "
                        "WHERE id=%s AND status='PENDING' AND block = ANY(%s) RETURNING application_no",
                        (status, datetime.now(), officer, args["application_id"], list(PILOT_BLOCKS)))
            row = cur.fetchone()
            if not row:
                raise ValueError("only a pending application in the pilot blocks can be decided")
            portal.write_audit(cur, args["application_id"], status, "agent:officer:%s" % officer,
                               args["note"].strip())
            conn.commit()
            return {"application_no": row[0], "status": status, "decided_by": officer}
        raise KeyError(name)
    finally:
        cur.close()
        conn.close()


CITIZEN_TOOLS = {
    "get_scheme_information", "check_eligibility", "start_application",
    "update_application", "upload_age_proof", "submit_application",
    "get_my_application", "withdraw_application",
}
OFFICER_TOOLS = {"get_queue", "get_application", "get_application_status",
                 "approve_application", "reject_application"}


def _tools(kind):
    names = CITIZEN_TOOLS if kind == "citizen" else OFFICER_TOOLS
    descriptions = {
        "get_scheme_information": "Read current scheme rules and pilot blocks.",
        "check_eligibility": "Validate facts without submitting an application.",
        "start_application": "Create or reuse the authenticated citizen's draft.",
        "update_application": "Update fields in a citizen draft.",
        "upload_age_proof": "Upload the citizen's age proof to a draft.",
        "submit_application": "Validate and submit a citizen draft.",
        "get_my_application": "Read the authenticated citizen's latest application.",
        "withdraw_application": "Withdraw the authenticated citizen's pending application.",
        "get_queue": "List pending applications in the pilot blocks.",
        "get_application": "Read an application and its audit trail.",
        "get_application_status": "Read the current application status.",
        "approve_application": "Approve a pending application with a reason.",
        "reject_application": "Reject a pending application with a reason.",
    }
    schemas = {
        "get_scheme_information": {"type": "object", "properties": {}, "additionalProperties": False},
        "check_eligibility": {"type": "object", "properties": {
            "applicant_name": {"type": "string"}, "dob": {"type": "string"},
            "village": {"type": "string"}, "block": {"type": "string"},
            "bank_account": {"type": "string"}, "ifsc": {"type": "string"},
        }},
        "start_application": {"type": "object", "properties": {}, "additionalProperties": False},
        "update_application": {"type": "object", "required": ["draft_id"], "properties": {
            "draft_id": {"type": "string"}, "applicant_name": {"type": "string"},
            "dob": {"type": "string"}, "gender": {"type": "string"},
            "marital_status": {"type": "string"}, "husband_name": {"type": "string"},
            "village": {"type": "string"}, "block": {"type": "string"},
            "bank_account": {"type": "string"}, "ifsc": {"type": "string"},
        }},
        "upload_age_proof": {"type": "object", "required": ["draft_id", "filename", "content_base64"],
                             "properties": {
                                 "draft_id": {"type": "string"}, "filename": {"type": "string"},
                                 "content_base64": {"type": "string"},
                             }},
        "submit_application": {"type": "object", "required": ["draft_id"],
                               "properties": {"draft_id": {"type": "string"}}},
        "get_my_application": {"type": "object", "properties": {}, "additionalProperties": False},
        "withdraw_application": {"type": "object", "required": ["application_id"],
                                 "properties": {"application_id": {"type": "integer"}}},
        "get_queue": {"type": "object", "properties": {}, "additionalProperties": False},
        "get_application": {"type": "object", "required": ["application_id"],
                            "properties": {"application_id": {"type": "integer"}}},
        "get_application_status": {"type": "object", "required": ["application_id"],
                                   "properties": {"application_id": {"type": "integer"}}},
        "approve_application": {"type": "object", "required": ["application_id", "note"],
                                "properties": {"application_id": {"type": "integer"},
                                               "note": {"type": "string"}}},
        "reject_application": {"type": "object", "required": ["application_id", "note"],
                               "properties": {"application_id": {"type": "integer"},
                                              "note": {"type": "string"}}},
    }
    return [{"name": name, "description": descriptions[name], "inputSchema": schemas[name]}
            for name in sorted(names)]


@agent_mcp.route("/mcp/<kind>", methods=["GET", "POST"])
def mcp(kind):
    if kind not in ("citizen", "officer"):
        return jsonify({"error": "not found"}), 404
    claims, auth_error = _claims(kind)
    if auth_error:
        response = jsonify({"error": auth_error})
        response.status_code = 401
        response.headers["WWW-Authenticate"] = (
            'Bearer resource_metadata="%s/.well-known/oauth-protected-resource/mcp/%s", '
            'scope="%s"' % (ISSUER, kind, kind)
        )
        return response
    if request.method == "GET":
        response = jsonify({"name": "seva-setu-%s-mcp" % kind, "transport": "streamable-http"})
        response.headers["MCP-Protocol-Version"] = "2025-03-26"
        return response
    body = request.get_json(silent=True) or {}
    request_id = body.get("id")
    method = body.get("method")
    if method == "initialize":
        response = _jsonrpc(request_id, {"protocolVersion": "2025-03-26",
                                         "capabilities": {"tools": {"listChanged": False}},
                                         "serverInfo": {"name": "seva-setu-%s" % kind, "version": "1.0"}})
        response.headers["MCP-Protocol-Version"] = "2025-03-26"
        return response
    if method == "notifications/initialized":
        return ("", 204)
    if method == "tools/list":
        return _jsonrpc(request_id, {"tools": _tools(kind)})
    if method != "tools/call":
        return _error(request_id, -32601, "method not found")
    params = body.get("params") or {}
    name = params.get("name")
    if name not in (CITIZEN_TOOLS if kind == "citizen" else OFFICER_TOOLS):
        return _error(request_id, -32602, "tool is not available on this endpoint")
    try:
        result = (_citizen_tool if kind == "citizen" else _officer_tool)(name, params.get("arguments") or {}, claims)
        return _jsonrpc(request_id, _tool_result(result))
    except (ValueError, KeyError) as exc:
        return _error(request_id, "INVALID_ARGUMENTS", str(exc))
    except Exception:
        portal.app.logger.exception("agent MCP tool failed: %s", name)
        return _error(request_id, "INTERNAL_ERROR", "The portal could not complete this request.")

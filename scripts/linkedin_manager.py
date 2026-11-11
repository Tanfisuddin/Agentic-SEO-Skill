#!/usr/bin/env python3
"""
LinkedIn Page Manager & Post Publisher for PaytrixOne
Handles OAuth 2.0 authorization, token persistence, and posting to LinkedIn Company Pages.

Usage:
  # 1. Get OAuth login URL (and optionally start local listener)
  python3 linkedin_manager.py --login

  # 2. Or manually exchange authorization code
  python3 linkedin_manager.py --code "YOUR_AUTH_CODE"

  # 3. Verify access to Company Page
  python3 linkedin_manager.py --verify

  # 4. Publish a post to Company Page
  python3 linkedin_manager.py --post "🚀 Announcing PaytrixOne..." --url "https://www.paytrixone.com"
"""

import os
import sys
import json
import urllib.parse
import http.server
import socketserver
import webbrowser
import requests
from pathlib import Path

# Load environment
SCRIPT_DIR = Path(__file__).resolve().parent
ENV_PATH = SCRIPT_DIR.parent / ".env"

def load_env():
    env_vars = {}
    if ENV_PATH.exists():
        with open(ENV_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().strip("'\"")
    return env_vars

def save_env_token(token):
    lines = []
    found = False
    if ENV_PATH.exists():
        with open(ENV_PATH, "r") as f:
            for line in f:
                if line.strip().startswith("LINKEDIN_ACCESS_TOKEN="):
                    lines.append(f"LINKEDIN_ACCESS_TOKEN={token}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"LINKEDIN_ACCESS_TOKEN={token}\n")
    with open(ENV_PATH, "w") as f:
        f.writelines(lines)

env = load_env()
CLIENT_ID = env.get("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = env.get("LINKEDIN_CLIENT_SECRET", "")
ORG_ID = env.get("LINKEDIN_ORG_ID", "144114603")
PERSON_URN = env.get("LINKEDIN_PERSON_URN", "urn:li:person:0Qw0lxz8Hg")
ACCESS_TOKEN = env.get("LINKEDIN_ACCESS_TOKEN", "")

# Default redirect URI (configure this in LinkedIn App Auth settings)
REDIRECT_URI = "http://localhost:8000/callback"
# Default to standard approved scopes. For company page posts, add Community Management API in Products tab.
STANDARD_SCOPES = "w_member_social openid profile email"
ORG_SCOPES = "w_member_social w_organization_social r_organization_social openid profile email"

def get_auth_url(redirect_uri=REDIRECT_URI, use_org_scope=False):
    scope = ORG_SCOPES if use_org_scope else STANDARD_SCOPES
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": "paytrixone_auth_state_secure"
    }
    return f"https://www.linkedin.com/oauth/v2/authorization?{urllib.parse.urlencode(params)}"

def exchange_code(code, redirect_uri=REDIRECT_URI):
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": redirect_uri,
    }
    resp = requests.post("https://www.linkedin.com/oauth/v2/accessToken", data=data)
    if resp.status_code == 200:
        token_info = resp.json()
        token = token_info.get("access_token")
        save_env_token(token)
        print("✅ LinkedIn Access Token successfully acquired and saved to .env!")
        return token
    else:
        print(f"❌ Failed to exchange code for token: {resp.status_code}")
        print(resp.text)
        return None

def verify_token(token=None):
    token = token or ACCESS_TOKEN
    if not token:
        print("❌ No LINKEDIN_ACCESS_TOKEN found. Run --login first.")
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": "2.0.0"
    }
    # Check current user / organization access
    resp = requests.get("https://api.linkedin.com/v2/organizationalEntityAcls?q=roleAssignee", headers=headers)
    if resp.status_code == 200:
        acls = resp.json().get("elements", [])
        orgs = [item.get("organizationalTarget") for item in acls]
        print(f"✅ Access verified! Organizations accessible: {orgs}")
        return True
    else:
        print(f"⚠️ Token test status: {resp.status_code}")
        print(resp.text)
        return False

def post_to_page(text, url=None, org_id=None, as_member=False, token=None):
    token = token or ACCESS_TOKEN
    org_id = org_id or ORG_ID
    if not token:
        print("❌ Missing LINKEDIN_ACCESS_TOKEN. Please run --login to authorize.")
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
        "LinkedIn-Version": "202401"
    }

    author = PERSON_URN if as_member else f"urn:li:organization:{org_id}"
    
    payload = {
        "author": author,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": []
        },
        "lifecycleState": "PUBLISHED"
    }

    if url:
        payload["content"] = {
            "article": {
                "source": url,
                "title": "PaytrixOne HRMS",
                "description": "Unified AI-Powered Workforce & Geofenced HRMS Platform"
            }
        }

    # First try modern REST posts endpoint
    resp = requests.post("https://api.linkedin.com/rest/posts", headers=headers, json=payload)
    
    if resp.status_code in (200, 201):
        print(f"🎉 Post published successfully to PaytrixOne Company Page! (Status: {resp.status_code})")
        post_urn = resp.headers.get("x-restli-id", "")
        if post_urn:
            print(f"Post URN: {post_urn}")
        return True

    # Fallback to UGC Posts API if REST requires newer product enrollment
    print(f"Trying fallback UGC Posts API (Status was {resp.status_code})...")
    ugc_payload = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": text
                },
                "shareMediaCategory": "ARTICLE" if url else "NONE"
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }
    if url:
        ugc_payload["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [{
            "status": "READY",
            "originalUrl": url,
            "title": {"text": "PaytrixOne HRMS — AI-Powered Workforce & Geofenced Payroll"}
        }]

    ugc_resp = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=ugc_payload)
    if ugc_resp.status_code in (200, 201):
        data = ugc_resp.json()
        print(f"🎉 Post published successfully via UGC API! Post ID: {data.get('id')}")
        return True
    else:
        print(f"❌ Failed to publish post: {ugc_resp.status_code}")
        print(ugc_resp.text)
        return False

def start_auth_server(port=8000, use_org_scope=False):
    redirect_uri = f"http://localhost:{port}/callback"
    auth_url = get_auth_url(redirect_uri, use_org_scope=use_org_scope)
    
    print("\n" + "="*70)
    print("🔑 LINKEDIN OAUTH AUTHORIZATION")
    print("="*70)
    print("\n1. Please ensure your LinkedIn Developer App has this Redirect URL:")
    print(f"   👉 {redirect_uri}")
    print("\n2. Open this link in your browser to approve permissions:")
    print(f"   👉 {auth_url}\n")
    print(f"Waiting for authorization callback on port {port}...")
    print("="*70 + "\n")

    captured_code = []

    class CallbackHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/callback":
                qs = urllib.parse.parse_qs(parsed.query)
                if "code" in qs:
                    captured_code.append(qs["code"][0])
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<h1>Authorization Successful!</h1><p>You can close this tab and return to Antigravity.</p>")
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"<h1>Authorization Failed: missing code</h1>")
            else:
                self.send_response(404)
                self.end_headers()
        def log_message(self, format, *args):
            pass  # Quiet logging

    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("localhost", port), CallbackHandler)
    server.timeout = 120
    try:
        while not captured_code:
            server.handle_request()
    finally:
        server.server_close()

    if captured_code:
        code = captured_code[0]
        print(f"Received code: {code[:12]}...")
        return exchange_code(code, redirect_uri)
    return None

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LinkedIn Page Manager & Post Publisher")
    parser.add_argument("--login", action="store_true", help="Start local OAuth listener and get auth URL")
    parser.add_argument("--auth-url", action="store_true", help="Print the OAuth URL only")
    parser.add_argument("--code", type=str, help="Exchange an authorization code manually")
    parser.add_argument("--verify", action="store_true", help="Verify access token and company page permissions")
    parser.add_argument("--post", type=str, help="Text content of the post to publish")
    parser.add_argument("--url", type=str, help="Optional link URL to attach to the post")
    parser.add_argument("--org", type=str, help="Optional organization ID override")
    parser.add_argument("--as-member", action="store_true", help="Publish as personal profile instead of company page")

    args = parser.parse_args()

    if args.auth_url:
        print(get_auth_url())
    elif args.login:
        start_auth_server()
    elif args.code:
        exchange_code(args.code)
    elif args.verify:
        verify_token()
    elif args.post:
        post_to_page(args.post, url=args.url, org_id=args.org, as_member=args.as_member)
    else:
        parser.print_help()


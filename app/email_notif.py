#!/usr/bin/env python3
"""
Système de notifications email via SMTP.

Variables d'environnement requises :
  SMTP_HOST  : ex. smtp.gmail.com
  SMTP_PORT  : ex. 587
  SMTP_USER  : adresse expéditeur
  SMTP_PASS  : mot de passe ou App Password Gmail
  EMAIL_FROM : nom affiché (optionnel, défaut = SMTP_USER)

Les abonnés sont stockés dans subscribers.json à la racine du projet.
"""

import json
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

SUBSCRIBERS_FILE = Path(__file__).parent.parent / "subscribers.json"

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USER)


def is_configured() -> bool:
    return bool(SMTP_USER and SMTP_PASS)


def load_subscribers() -> list[str]:
    if SUBSCRIBERS_FILE.exists():
        return json.loads(SUBSCRIBERS_FILE.read_text())
    return []


def save_subscribers(subscribers: list[str]) -> None:
    SUBSCRIBERS_FILE.write_text(json.dumps(subscribers, indent=2))


def add_subscriber(email: str) -> bool:
    email = email.strip().lower()
    subscribers = load_subscribers()
    if email in subscribers:
        return False
    subscribers.append(email)
    save_subscribers(subscribers)
    return True


def remove_subscriber(email: str) -> bool:
    email = email.strip().lower()
    subscribers = load_subscribers()
    if email not in subscribers:
        return False
    subscribers.remove(email)
    save_subscribers(subscribers)
    return True


def _build_html(title: str, message: str, site_url: str = "") -> str:
    link_html = ""
    if site_url:
        link_html = f"""
        <div style="margin-top:24px">
          <a href="{site_url}"
             style="background:#16a34a;color:white;padding:12px 24px;
                    border-radius:8px;text-decoration:none;font-weight:600;
                    font-size:15px">
            Voir le produit →
          </a>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f0f4f8;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 20px">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:white;border-radius:16px;overflow:hidden;
                    box-shadow:0 4px 24px rgba(0,0,0,.08)">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#0b1222,#1a2540);
                     padding:28px 32px;color:white">
            <div style="font-size:24px;margin-bottom:4px">❄️</div>
            <div style="font-size:20px;font-weight:800;letter-spacing:-.5px">
              PortaSplit Monitor
            </div>
            <div style="font-size:13px;color:#94a3b8;margin-top:4px">
              Midea MMCS-12HRN8-QRD0 · France
            </div>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:32px">
            <div style="font-size:22px;font-weight:700;color:#0f172a;
                        margin-bottom:12px;line-height:1.3">
              {title}
            </div>
            <div style="font-size:15px;color:#475569;line-height:1.7">
              {message.replace(chr(10), '<br>')}
            </div>
            {link_html}
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:16px 32px;background:#f8fafc;border-top:1px solid #e2e8f0">
            <div style="font-size:12px;color:#94a3b8">
              Vous recevez cet email car vous êtes abonné(e) aux alertes PortaSplit Monitor.
              Pour vous désabonner, répondez avec "STOP" ou visitez votre tableau de bord.
            </div>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_email(to_addresses: list[str], subject: str, html_body: str) -> bool:
    if not is_configured():
        print("  [email] SMTP non configuré (SMTP_USER/SMTP_PASS manquants)", file=sys.stderr)
        return False
    if not to_addresses:
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"PortaSplit Monitor <{EMAIL_FROM}>"
        msg["To"]      = ", ".join(to_addresses)
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(EMAIL_FROM, to_addresses, msg.as_string())

        print(f"  -> email envoyé à {len(to_addresses)} abonné(s): {subject}")
        return True
    except Exception as e:
        print(f"  [erreur email] {e}", file=sys.stderr)
        return False


def notify_subscribers(title: str, message: str, site_url: str = "") -> bool:
    subscribers = load_subscribers()
    if not subscribers:
        return False
    html = _build_html(title, message, site_url)
    return send_email(subscribers, title, html)

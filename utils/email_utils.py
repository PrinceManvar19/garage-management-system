import smtplib
import secrets
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

def generate_otp():
    code = str(secrets.randbelow(1_000_000)).zfill(6)
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    return code, code_hash

def hash_otp(code):
    return hashlib.sha256(code.encode()).hexdigest()

def send_otp_email(to_email, otp_code):
    gmail_user = os.environ['GMAIL_USER']
    gmail_pass = os.environ['GMAIL_APP_PASSWORD']

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'Your Shreeji Admin Login Code: {otp_code}'
    msg['From'] = gmail_user
    msg['To'] = to_email

    body = f"""
    <html><body style="font-family:sans-serif;padding:24px;">
    <p>Your one-time login code for <strong>Shreeji Auto Service Admin</strong> is:</p>
    <h1 style="letter-spacing:10px;font-size:2rem;color:#1a1a1a;">{otp_code}</h1>
    <p>This code expires in <strong>10 minutes</strong>.</p>
    <p style="color:#666;">Do not share this code with anyone.</p>
    </body></html>
    """
    msg.attach(MIMEText(body, 'html'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, to_email, msg.as_string())

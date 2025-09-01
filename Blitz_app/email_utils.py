import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 465
SMTP_USER = 'blitztradebot@gmail.com'
SMTP_PASS = 'zazpybzkwxyquxmk'  # 앱 비밀번호

def send_email(to, subject, html):
    msg = MIMEMultipart('alternative')
    msg['From'] = SMTP_USER
    msg['To'] = to
    msg['Subject'] = subject

    html_part = MIMEText(html, 'html')
    msg.attach(html_part)

    # SSL 연결 방식 권장 (포트 465)
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, to, msg.as_string())

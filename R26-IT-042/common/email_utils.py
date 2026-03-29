"""
R26-IT-042 — Employee Activity Monitoring System
common/email_utils.py

Centralised email utilities for sending MFA setup and system alerts.
"""

import io
import smtplib
import logging
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config.settings import settings

logger = logging.getLogger(__name__)

def send_mfa_setup_email(email: str, name: str, mfa_secret: str) -> bool:
    """
    Generate a TOTP QR code and send it to the employee's email.
    
    Returns:
        bool: True if sent successfully, False otherwise.
    """
    try:
        import qrcode
        # Ensure email is clean
        clean_email = email.strip().lower()
        
        totp_uri = f"otpauth://totp/WorkPlus:{clean_email}?secret={mfa_secret}&issuer=WorkPlus"
        qr_img = qrcode.make(totp_uri)

        buf = io.BytesIO()
        qr_img.save(buf, format="PNG")
        qr_bytes = buf.getvalue()

        smtp_host = settings.SMTP_HOST
        smtp_port = settings.SMTP_PORT
        smtp_user = settings.SMTP_USER
        smtp_pass = settings.SMTP_PASS

        if not smtp_user or not smtp_pass:
            logger.warning("SMTP credentials not set — MFA email NOT sent.")
            return False

        # Create the root container
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "WorkPlus — Your MFA Setup"
        msg["From"] = f"WorkPlus Support <{smtp_user}>"
        msg["To"] = clean_email

        # 1. Plain text version
        plain_text = f"Welcome to WorkPlus, {name}!\n\n" \
                    f"To complete your setup, please configure your Multi-Factor Authentication (MFA).\n\n" \
                    f"Manual Setup Code: {mfa_secret}\n\n" \
                    f"If you did not expect this email, please contact your administrator."
        
        msg.attach(MIMEText(plain_text, "plain"))

        # 2. HTML version with embedded image
        html = f"""
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; line-height: 1.6; background-color: #f8fafc; padding: 20px;">
            <div style="max-width: 500px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; background-color: #ffffff; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);">
                <div style="background-color: #0f172a; padding: 24px; text-align: center;">
                    <h2 style="color: #14b8a6; margin: 0; font-size: 24px; letter-spacing: 1px;">WorkPlus</h2>
                </div>
                <div style="padding: 32px;">
                    <h3 style="margin-top: 0; color: #0f172a;">Welcome to the Team, {name}!</h3>
                    <p style="font-size: 15px;">Your employee account is ready. To keep your account secure, please set up Multi-Factor Authentication (MFA) using your preferred authenticator app.</p>
                    
                    <div style="text-align: center; margin: 32px 0;">
                        <img src="cid:qrcode" style="width: 200px; height: 200px; border: 6px solid #f1f5f9; border-radius: 12px;" alt="MFA QR Code">
                        <p style="font-size: 12px; color: #64748b; margin-top: 12px;">Scan the code with Google Authenticator or Microsoft Authenticator</p>
                    </div>

                    <div style="background-color: #f1f5f9; padding: 20px; border-radius: 8px; border: 1px dashed #cbd5e1; text-align: center;">
                        <p style="margin: 0; font-size: 13px; color: #475569; margin-bottom: 8px;"><strong>Can't scan?</strong> Enter this code manually:</p>
                        <code style="display: inline-block; font-size: 18px; font-weight: bold; color: #0f172a; background: #fff; padding: 10px 20px; border-radius: 6px; border: 1px solid #e2e8f0; letter-spacing: 3px;">{mfa_secret}</code>
                    </div>

                    <p style="margin-top: 24px; font-size: 13px; color: #94a3b8; text-align: center;">If you did not request this account, please contact IT support immediately.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # We need to nest the HTML and Image inside a 'related' part 
        # because the Image is referenced by the HTML view.
        related_part = MIMEMultipart("related")
        related_part.attach(MIMEText(html, "html"))
        
        img_part = MIMEImage(qr_bytes, name="qrcode.png")
        img_part.add_header("Content-ID", "<qrcode>")
        related_part.attach(img_part)
        
        # Attach the related part to the alternative container
        msg.attach(related_part)

        # Connection and transmission with explicit error handling
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as s:
            s.ehlo()
            s.starttls()
            s.login(smtp_user, smtp_pass)
            # Use specific from/to for the envelope
            s.sendmail(smtp_user, [clean_email], msg.as_string())
        
        logger.info(f"MFA setup email successfully sent to {clean_email}")
        return True

    except smtplib.SMTPException as smtp_exc:
        logger.error(f"SMTP error sending MFA email to {email}: {smtp_exc}")
        return False
    except Exception as exc:
        logger.error(f"Unexpected error sending MFA email to {email}: {exc}", exc_info=True)
        return False

"""
Email Utility Module
Handles sending password reset emails via Gmail SMTP
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

def reset_token_reminder():
    print("🔑 Reset Token (for testing - copy this):")

def send_password_reset_email(email: str, reset_token: str, username: str) -> bool:
    """
    Send password reset email to user via Gmail SMTP.
    
    Args:
        email: User's email address
        reset_token: JWT reset token
        username: User's username for personalization
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    
    # Construct reset link
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    reset_link = f"{frontend_url}/reset-password?token={reset_token}"
    
    # Email content
    subject = "Password Reset Request - Employee Rewards System"
    
    # HTML email template
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                color: #333;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
            }}
            .button {{
                display: inline-block;
                padding: 12px 24px;
                background-color: #007bff;
                color: white;
                text-decoration: none;
                border-radius: 4px;
                margin: 20px 0;
            }}
            .token-box {{
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                padding: 15px;
                border-radius: 4px;
                margin: 20px 0;
                word-break: break-all;
                font-family: monospace;
                font-size: 12px;
            }}
            .warning {{
                background-color: #fff3cd;
                border: 1px solid #ffc107;
                padding: 10px;
                border-radius: 4px;
                margin: 20px 0;
            }}
            .footer {{
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #ddd;
                font-size: 12px;
                color: #666;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Password Reset Request</h2>
            
            <p>Hi {username},</p>
            
            <p>We received a request to reset your password for your Employee Rewards System account.</p>
            
            <p>Click the button below to reset your password:</p>
            
            <a href="{reset_link}" class="button">Reset Password</a>
            
            <p>Or copy and paste this link into your browser:</p>
            <p style="word-break: break-all; color: #007bff;">{reset_link}</p>
            
            <p><strong>For Swagger/Postman Testing:</strong></p>
            <p>Copy this token to use in the API:</p>
            <div class="token-box">
                {reset_token}
            </div>
            
            <div class="warning">
                <strong>⚠️ Important:</strong>
                <ul>
                    <li>This link will expire in 15 minutes</li>
                    <li>If you didn't request this reset, please ignore this email</li>
                    <li>Never share this link with anyone</li>
                </ul>
            </div>
            
            <div class="footer">
                <p>This is an automated email from Employee Rewards System.</p>
                <p>If you have any questions, please contact your system administrator.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    # Plain text version
    text_content = f"""
    Password Reset Request
    
    Hi {username},
    
    We received a request to reset your password for your Employee Rewards System account.
    
    Click this link to reset your password:
    {reset_link}
    
    OR copy this token to use in Swagger/Postman:
    {reset_token}
    
    IMPORTANT:
    - This link will expire in 15 minutes
    - If you didn't request this reset, please ignore this email
    - Never share this link with anyone
    
    ---
    This is an automated email from Employee Rewards System.
    If you have any questions, please contact your system administrator.
    """
    
    # Print to console for debugging
    print("=" * 80)
    print("📧 SENDING PASSWORD RESET EMAIL")
    print("=" * 80)
    print(f"To: {email}")
    print(f"Subject: {subject}")
    print("-" * 80)
    
    # Send email via Gmail SMTP
    try:
        # Get SMTP configuration from environment
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_username = os.getenv("SMTP_USERNAME")
        smtp_password = os.getenv("SMTP_PASSWORD")
        smtp_from_email = os.getenv("SMTP_FROM_EMAIL", smtp_username)
        
        # Validate configuration
        if not smtp_username or not smtp_password:
            print("❌ ERROR: SMTP credentials not configured!")
            print("   Please set SMTP_USERNAME and SMTP_PASSWORD in your .env file")
            print("\n" + "=" * 80)
            reset_token_reminder()
            print("=" * 80)
            print(reset_token)
            print("=" * 80)
            return False
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = smtp_from_email
        msg['To'] = email
        
        # Attach both plain text and HTML versions
        part1 = MIMEText(text_content, 'plain')
        part2 = MIMEText(html_content, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        print(f"Connecting to {smtp_host}:{smtp_port}...")
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            print("Logging in...")
            server.login(smtp_username, smtp_password)
            print("Sending email...")
            server.send_message(msg)
        
        print("✅ Email sent successfully!")
        print("=" * 80)
        print("🔑 Reset Token (also sent in email):")
        print("=" * 80)
        print(reset_token)
        print("=" * 80)
        print()
        
        return True
        
    except smtplib.SMTPAuthenticationError:
        print("❌ SMTP Authentication Failed!")
        print("   Check your Gmail App Password")
        print("   Make sure 2-Step Verification is enabled")
        print("\n" + "=" * 80)
        reset_token_reminder()
        print("=" * 80)
        print(reset_token)
        print("=" * 80)
        return False
        
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        print("\n" + "=" * 80)
        reset_token_reminder()
        print("=" * 80)
        print(reset_token)
        print("=" * 80)
        return False


def send_password_reset_confirmation(email: str, username: str) -> bool:
    """
    Send confirmation email after successful password reset.
    
    Args:
        email: User's email address
        username: User's username
    
    Returns:
        bool: True if email sent successfully
    """
    
    subject = "Password Successfully Reset - Employee Rewards System"
    
    # HTML version
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                color: #333;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
            }}
            .success-box {{
                background-color: #d4edda;
                border: 1px solid #c3e6cb;
                padding: 15px;
                border-radius: 4px;
                margin: 20px 0;
            }}
            .warning-box {{
                background-color: #fff3cd;
                border: 1px solid #ffc107;
                padding: 15px;
                border-radius: 4px;
                margin: 20px 0;
            }}
            .footer {{
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #ddd;
                font-size: 12px;
                color: #666;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Password Reset Confirmation</h2>
            
            <p>Hi {username},</p>
            
            <div class="success-box">
                <strong>✅ Success!</strong><br>
                Your password has been successfully reset.
            </div>
            
            <p>You can now log in to your Employee Rewards System account using your new password.</p>
            
            <div class="warning-box">
                <strong>⚠️ Security Notice:</strong><br>
                If you did not make this change, please contact your system administrator immediately.
            </div>
            
            <div class="footer">
                <p>This is an automated email from Employee Rewards System.</p>
                <p>If you have any questions, please contact your system administrator.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    # Plain text version
    text_content = f"""
    Password Reset Confirmation
    
    Hi {username},
    
    ✅ Your password has been successfully reset.
    
    You can now log in to your Employee Rewards System account using your new password.
    
    ⚠️ Security Notice:
    If you did not make this change, please contact your system administrator immediately.
    
    ---
    This is an automated email from Employee Rewards System.
    If you have any questions, please contact your system administrator.
    """
    
    # Print to console
    print("=" * 80)
    print("📧 SENDING PASSWORD RESET CONFIRMATION")
    print("=" * 80)
    print(f"To: {email}")
    print(f"Subject: {subject}")
    print("-" * 80)
    
    # Send email via Gmail SMTP
    try:
        # Get SMTP configuration
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_username = os.getenv("SMTP_USERNAME")
        smtp_password = os.getenv("SMTP_PASSWORD")
        smtp_from_email = os.getenv("SMTP_FROM_EMAIL", smtp_username)
        
        if not smtp_username or not smtp_password:
            print("⚠️ SMTP not configured - skipping confirmation email")
            print("=" * 80)
            return False
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = smtp_from_email
        msg['To'] = email
        
        part1 = MIMEText(text_content, 'plain')
        part2 = MIMEText(html_content, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
        
        print("✅ Confirmation email sent successfully!")
        print("=" * 80)
        print()
        
        return True
        
    except Exception as e:
        print(f"⚠️ Failed to send confirmation email: {e}")
        print("=" * 80)
        return False
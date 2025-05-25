# centers/utils.py
from django.core.mail import send_mail
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def send_verification_email(user, code):
    """Send verification code to the user's email."""
    subject = 'Verify Your Account'
    message = f"""
    Dear {user.username},

    Thank you for registering with the Hemodialysis Center Management System.
    Please use the following verification code to activate your account:

    Verification Code: {code}

    If you did not request this, please ignore this email.

    Best regards,
    Hemo Team
    """
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [user.email]
    
    try:
        send_mail(
            subject,
            message,
            from_email,
            recipient_list,
            fail_silently=False,
        )
        logger.info("Verification email sent to %s with code %s", user.email, code)
    except Exception as e:
        logger.error("Failed to send verification email to %s: %s", user.email, str(e))
        raise
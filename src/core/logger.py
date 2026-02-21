# src/core/logger.py
import logging
import sys
import os
import re
from logging.handlers import RotatingFileHandler

# --- 1. Create the Comprehensive Masking Formatter ---
class MaskingFormatter(logging.Formatter):
    """
    Custom formatter that automatically masks sensitive data:
    UUIDs, Emails, Phone Numbers, and Auth Tokens.
    """
    # Regex Patterns
    UUID_PATTERN = re.compile(
        r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', 
        re.IGNORECASE
    )
    EMAIL_PATTERN = re.compile(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b', 
        re.IGNORECASE
    )
    # Matches common 10-15 digit phone formats with optional country code/separators
    PHONE_PATTERN = re.compile(
        r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'
    )
    # Matches JWTs or Bearer tokens
    TOKEN_PATTERN = re.compile(
        r'(Bearer\s+)[A-Za-z0-9\-\._~\+\/]+'
    )

    def format(self, record):
        # Format the original message first
        original_msg = super().format(record)
        
        # Sequentially apply the regex substitutions
        msg = self.UUID_PATTERN.sub(self._mask_uuid, original_msg)
        msg = self.EMAIL_PATTERN.sub(self._mask_email, msg)
        msg = self.PHONE_PATTERN.sub(self._mask_phone, msg)
        msg = self.TOKEN_PATTERN.sub(self._mask_token, msg)
        
        return msg

    def _mask_uuid(self, match):
        uuid_str = match.group(0)
        # Keeps first 8 and last 4: 12345678-****-****-****-abcd
        return f"{uuid_str[:8]}-****-****-****-{uuid_str[-4:]}"

    def _mask_email(self, match):
        email_str = match.group(0)
        try:
            name, domain = email_str.split('@')
            # Keeps first character of name: j****@company.com
            masked_name = name[0] + "****" if len(name) > 1 else "****"
            return f"{masked_name}@{domain}"
        except ValueError:
            return "***@***.***"

    def _mask_phone(self, match):
        phone_str = match.group(0)
        # Masks all digits except the last 4
        digits = re.sub(r'\D', '', phone_str)
        if len(digits) >= 4:
            return f"***-***-{digits[-4:]}"
        return "********"

    def _mask_token(self, match):
        # Keeps the 'Bearer ' prefix and the first 10 chars of the token
        full_match = match.group(0)
        prefix = match.group(1)
        token_part = full_match[len(prefix):]
        if len(token_part) > 10:
            return f"{prefix}{token_part[:10]}...[MASKED_TOKEN]"
        return f"{prefix}[MASKED_TOKEN]"


# --- 2. Existing Level Filter ---
class ExactLevelFilter(logging.Filter):
    def __init__(self, level):
        self.level = level

    def filter(self, record):
        return record.levelno == self.level


def setup_logger(name: str = "app_logger"):
    logger = logging.getLogger(name)

    if logger.hasHandlers():
        return logger

    logger.setLevel(logging.DEBUG)

    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)

    # Use the new comprehensive MaskingFormatter
    formatter = MaskingFormatter(
        "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    )

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG) 
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # STRICT Debug File Handler
    debug_handler = RotatingFileHandler(
        os.path.join(log_dir, "debug.log"), maxBytes=5*1024*1024, backupCount=3
    )
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.addFilter(ExactLevelFilter(logging.DEBUG))
    debug_handler.setFormatter(formatter)
    logger.addHandler(debug_handler)

    # STRICT Warning File Handler
    warning_handler = RotatingFileHandler(
        os.path.join(log_dir, "warning.log"), maxBytes=5*1024*1024, backupCount=3
    )
    warning_handler.setLevel(logging.WARNING)
    warning_handler.addFilter(ExactLevelFilter(logging.WARNING))
    warning_handler.setFormatter(formatter)
    logger.addHandler(warning_handler)

    # STRICT Error File Handler
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, "error.log"), maxBytes=5*1024*1024, backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.addFilter(ExactLevelFilter(logging.ERROR))
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    return logger

logger = setup_logger()
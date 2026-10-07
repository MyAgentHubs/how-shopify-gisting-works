import base64
import hashlib
import hmac
import os

from gisting.shopify.order_name import canonical_order_name

EMAIL_DOMAIN = "orders.example.com"
LOCAL_PART_LENGTH = 10


class MissingSecret(RuntimeError):
    pass


def email_secret() -> str:
    secret = os.environ.get("GISTING_EMAIL_SECRET", "")
    if not secret:
        raise MissingSecret("GISTING_EMAIL_SECRET")
    return secret


def demo_email(secret: str, order_name: str) -> str:
    message = canonical_order_name(order_name).encode()
    digest = hmac.new(secret.encode(), message, hashlib.sha256).digest()
    local = base64.b32encode(digest).decode().lower()[:LOCAL_PART_LENGTH]
    return f"{local}@{EMAIL_DOMAIN}"

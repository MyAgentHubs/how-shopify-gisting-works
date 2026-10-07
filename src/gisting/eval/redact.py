import re

UNKNOWN_SLOT = "{email_unknown}"
DEMO_EMAIL = r"[a-z2-7]{10}@orders\.example\.com"


class Redactor:
    def __init__(self, emails: dict[str, str]) -> None:
        self._slots = {email.lower(): name for name, email in emails.items()}
        known = "|".join(
            re.escape(email) for email in sorted(emails.values(), key=len, reverse=True)
        )
        pattern = f"{known}|{DEMO_EMAIL}" if known else DEMO_EMAIL
        self._pattern = re.compile(pattern, re.IGNORECASE)
        self.unknown = 0

    def _replace(self, match: re.Match[str]) -> str:
        name = self._slots.get(match.group().lower())
        if name is None:
            self.unknown += 1
            return UNKNOWN_SLOT
        return f"{{{name}}}"

    def apply(self, text: str) -> str:
        return self._pattern.sub(self._replace, text)

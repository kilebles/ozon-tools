class OzonApiError(Exception):
    """Base error for Ozon API responses."""
    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


class RateLimitError(OzonApiError):
    """API returned too many requests."""


class UnexpectedResponseError(OzonApiError):
    """API returned an unexpected or unparseable response."""

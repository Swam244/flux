"""
Flux Exceptions
"""


class FluxError(Exception):
    """Base exception for all Flux errors."""
    pass


class RateLimitExceeded(FluxError):
    """
    Raised when a rate limit is exceeded.
    
    Attributes:
        key: The rate limit key that was exceeded
        retry_after: Seconds until the request can be retried
    """
    
    def __init__(self, key: str, retry_after: float = 0, message: str = None):
        self.key = key
        self.retry_after = retry_after
        
        if message is None:
            message = f"Rate limit exceeded for '{key}'"
            if retry_after > 0:
                message += f". Retry after {retry_after:.1f}s"
        
        super().__init__(message)
    
    def to_headers(self) -> dict:
        """Returns HTTP headers for rate limit responses."""
        return {
            "Retry-After": str(int(self.retry_after)),
            "X-RateLimit-Remaining": "0",
        }


class ConnectionError(FluxError):
    """Raised when Redis connection fails."""
    pass

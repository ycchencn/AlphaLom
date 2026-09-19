"""
FinFolio 异常处理模块
"""


class FinFolioException(Exception):
    """Base exception for FinFolio library"""

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class APIError(FinFolioException):
    """Raised when API request fails"""

    def __init__(self, message, status_code=None):
        self.status_code = status_code
        super().__init__(f"API Error: {message} (Status code: {status_code})")


class DataParsingError(FinFolioException):
    """Raised when data parsing fails"""

    pass


class InvalidParameterError(FinFolioException):
    """Raised when an invalid parameter is provided"""

    pass


class NetworkError(FinFolioException):
    """Raised when network-related issues occur"""

    pass


class RateLimitError(FinFolioException):
    """Raised when API rate limit is exceeded"""

    pass

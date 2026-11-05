class DomainError(Exception):
    """Base class for business-rule violations. HTTP-agnostic."""


class BackupError(DomainError):
    pass

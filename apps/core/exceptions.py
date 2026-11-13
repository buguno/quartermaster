class DomainError(Exception):
    """Base class for business-rule violations. HTTP-agnostic."""


class BackupError(DomainError):
    pass


class SetupClosed(DomainError):
    pass


class ReadOnlyAccount(DomainError):
    pass

from apps.core.exceptions import DomainError


class InvalidQuantity(DomainError):
    pass


class InsufficientStock(DomainError):
    pass


class ObjectInUse(DomainError):
    pass


class InvalidDates(DomainError):
    pass


class InvalidTransfer(DomainError):
    pass

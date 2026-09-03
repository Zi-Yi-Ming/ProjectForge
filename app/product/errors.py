from __future__ import annotations


class ProductCoreError(Exception):
    pass


class ProjectNotFoundError(ProductCoreError):
    pass


class ProjectAlreadyExistsError(ProductCoreError):
    pass


class InvalidProjectStateError(ProductCoreError):
    pass


class InvalidStateTransitionError(ProductCoreError):
    pass


class ActiveRunExistsError(ProductCoreError):
    pass


class CommandNotAllowedError(ProductCoreError):
    pass


class PersistenceError(ProductCoreError):
    pass

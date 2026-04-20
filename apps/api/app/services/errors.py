from __future__ import annotations


class ApiServiceError(Exception):
    status_code = 400


class ApiValidationError(ApiServiceError):
    status_code = 400


class ApiAuthenticationError(ApiServiceError):
    status_code = 401


class ApiNotFoundError(ApiServiceError):
    status_code = 404


class ApiConflictError(ApiServiceError):
    status_code = 409


class ApiDependencyError(ApiServiceError):
    status_code = 503

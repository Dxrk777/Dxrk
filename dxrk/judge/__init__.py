# SPDX-License-Identifier: MIT
"""External judge package: isolated verification, no silent auto-fix."""

from .verifier import NewVerifier, Verifier, VerifyResult

__all__ = [
    "NewVerifier",
    "Verifier",
    "VerifyResult",
]

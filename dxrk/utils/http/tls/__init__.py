# SPDX-License-Identifier: MIT
"""TLS configuration for dxrk.utils.http."""

from __future__ import annotations

import io
import os
import ssl
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import cast

from cryptography import x509 as crypto_x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from ..errors import (
    ErrCertKeyMismatch,
    ErrInvalidCA,
    ErrInvalidCert,
    ErrInvalidKey,
    ErrMissingCertOrKey,
    HttpError,
    _wrap,
)


class ClientAuthType(IntEnum):
    """TLS client authentication type."""

    NoClientCert = 0
    RequestClientCert = 1
    RequireAnyClientCert = 2
    VerifyClientCertIfGiven = 3
    RequireAndVerifyClientCert = 4


# tls.VersionTLS12 / VersionTLS13, mapped to ssl.TLSVersion values.
VERSION_TLS12 = ssl.TLSVersion.TLSv1_2
VERSION_TLS13 = ssl.TLSVersion.TLSv1_3

# Default cipher suites mapped to OpenSSL names (TLS 1.3 suites first).
_DEFAULT_CIPHER_SUITES = [
    "TLS_AES_256_GCM_SHA384",
    "TLS_CHACHA20_POLY1305_SHA256",
    "TLS_AES_128_GCM_SHA256",
    "ECDHE-ECDSA-AES256-GCM-SHA384",
    "ECDHE-RSA-AES256-GCM-SHA384",
    "ECDHE-ECDSA-CHACHA20-POLY1305",
    "ECDHE-RSA-CHACHA20-POLY1305",
    "ECDHE-ECDSA-AES128-GCM-SHA256",
    "ECDHE-RSA-AES128-GCM-SHA256",
]

# Default curve preferences mapped to OpenSSL names.
_DEFAULT_CURVE_PREFERENCES = ["X25519", "prime256v1", "secp384r1", "secp521r1"]


@dataclass
class TLSConfig:
    """TLS settings applied to the transport.

    ``cipher_suites``/``curve_preferences`` are stored for API parity; the
    ``ssl`` module applies them at handshake time via OpenSSL defaults, so
    the lists are informative only (fidelity note).
    """

    cert_file: str = ""
    key_file: str = ""
    cert_data: bytes = b""
    key_data: bytes = b""
    ca_file: str = ""
    ca_data: bytes = b""
    insecure_skip_verify: bool = False
    server_name: str = ""
    min_version: ssl.TLSVersion = VERSION_TLS12
    max_version: ssl.TLSVersion | None = VERSION_TLS13
    cipher_suites: list[str] = field(default_factory=lambda: list(_DEFAULT_CIPHER_SUITES))
    curve_preferences: list[str] = field(default_factory=lambda: list(_DEFAULT_CURVE_PREFERENCES))
    client_auth: ClientAuthType = ClientAuthType.NoClientCert
    root_cas: list[crypto_x509.Certificate] = field(default_factory=list)
    client_cas: list[crypto_x509.Certificate] = field(default_factory=list)

    def LoadCertKeyFromFile(self, cert_file: str, key_file: str) -> None:
        """Load a certificate/key pair from files (raises on error)."""
        try:
            with open(cert_file, "rb") as f:
                cert_data = f.read()
        except OSError as e:
            raise _wrap(str(ErrInvalidCert), e) from e
        try:
            with open(key_file, "rb") as f:
                key_data = f.read()
        except OSError as e:
            raise _wrap(str(ErrInvalidKey), e) from e
        self.cert_file = cert_file
        self.key_file = key_file
        self.cert_data = cert_data
        self.key_data = key_data

    def LoadCAFromFile(self, ca_file: str) -> None:
        """Load CA certificates from a file (raises on error)."""
        try:
            with open(ca_file, "rb") as f:
                ca_data = f.read()
        except OSError as e:
            raise _wrap(str(ErrInvalidCA), e) from e
        self.ca_file = ca_file
        self.ca_data = ca_data

    def SetCertKeyData(self, cert_data: bytes, key_data: bytes) -> None:
        """Set the certificate/key from raw PEM data (raises on error)."""
        if not cert_data or not key_data:
            raise ErrMissingCertOrKey
        if _pem_decode(cert_data) is None:
            raise ErrInvalidCert
        if _pem_decode(key_data) is None:
            raise ErrInvalidKey
        self.cert_data = cert_data
        self.key_data = key_data

    def SetCAData(self, ca_data: bytes) -> None:
        """Set CA certificates from raw PEM data (raises on error)."""
        if not ca_data:
            raise ErrInvalidCA
        if _pem_decode(ca_data) is None:
            raise ErrInvalidCA
        self.ca_data = ca_data

    def BuildTLSConfig(self) -> ssl.SSLContext:
        """Build an ``ssl.SSLContext`` from this configuration."""
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = self.min_version
        if self.max_version is not None:
            ctx.maximum_version = self.max_version
        if self.insecure_skip_verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        if self.server_name:
            ctx.check_hostname = True

        if self.cert_data and self.key_data:
            ctx.load_cert_chain(
                certfile=cast(
                    str | bytes | os.PathLike[str] | os.PathLike[bytes],
                    io.BytesIO(self.cert_data),
                ),
                keyfile=cast(
                    str | bytes | os.PathLike[str] | os.PathLike[bytes],
                    io.BytesIO(self.key_data),
                ),
            )
        elif self.cert_file and self.key_file:
            try:
                ctx.load_cert_chain(self.cert_file, self.key_file)
            except (OSError, ssl.SSLError) as e:
                raise _wrap(str(ErrCertKeyMismatch), e) from e

        if self.ca_data:
            ctx.load_verify_locations(cadata=self.ca_data.decode("utf-8", "replace"))
        elif self.ca_file:
            try:
                ctx.load_verify_locations(self.ca_file)
            except (OSError, ssl.SSLError) as e:
                raise _wrap(str(ErrInvalidCA), e) from e

        if self.root_cas:
            data = b"".join(c.public_bytes(serialization.Encoding.PEM) for c in self.root_cas)
            ctx.load_verify_locations(cadata=data.decode("utf-8", "replace"))

        if self.client_cas:
            data = b"".join(c.public_bytes(serialization.Encoding.PEM) for c in self.client_cas)
            ctx.load_verify_locations(cadata=data.decode("utf-8", "replace"))
            if self.client_auth is ClientAuthType.NoClientCert:
                self.client_auth = ClientAuthType.RequireAndVerifyClientCert
            ctx.verify_mode = ssl.CERT_REQUIRED

        return ctx

    def BuildClientTLSConfig(self) -> ssl.SSLContext:
        """Build a client TLS config (no client certificate required)."""
        ctx = self.BuildTLSConfig()
        ctx.verify_mode = ssl.CERT_NONE if self.insecure_skip_verify else ssl.CERT_REQUIRED
        return ctx

    def BuildServerTLSConfig(self) -> ssl.SSLContext:
        """Build a server TLS config; requires a certificate/key."""
        if not self.cert_data and not self.cert_file:
            raise ErrMissingCertOrKey
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = self.min_version
        if self.max_version is not None:
            ctx.maximum_version = self.max_version
        if self.cert_data and self.key_data:
            ctx.load_cert_chain(
                certfile=cast(
                    str | bytes | os.PathLike[str] | os.PathLike[bytes],
                    io.BytesIO(self.cert_data),
                ),
                keyfile=cast(
                    str | bytes | os.PathLike[str] | os.PathLike[bytes],
                    io.BytesIO(self.key_data),
                ),
            )
        elif self.cert_file and self.key_file:
            try:
                ctx.load_cert_chain(self.cert_file, self.key_file)
            except (OSError, ssl.SSLError) as e:
                raise _wrap(str(ErrCertKeyMismatch), e) from e
        if self.ca_data:
            ctx.load_verify_locations(cadata=self.ca_data.decode("utf-8", "replace"))
        if self.client_cas:
            data = b"".join(c.public_bytes(serialization.Encoding.PEM) for c in self.client_cas)
            ctx.load_verify_locations(cadata=data.decode("utf-8", "replace"))
        return ctx

    def WithMutualTLS(self, ca_data: bytes) -> TLSConfig:
        """Require and verify client certificates against ``ca_data``."""
        self.client_auth = ClientAuthType.RequireAndVerifyClientCert
        try:
            self.SetCAData(ca_data)
        except HttpError:
            pass
        return self

    def WithInsecureSkipVerify(self, skip: bool) -> TLSConfig:
        """Set whether server certificates are verified."""
        self.insecure_skip_verify = skip
        return self

    def WithServerName(self, name: str) -> TLSConfig:
        """Set the server name for SNI/hostname verification."""
        self.server_name = name
        return self

    def WithMinVersion(self, version: ssl.TLSVersion) -> TLSConfig:
        """Set the minimum TLS version."""
        self.min_version = version
        return self

    def WithCipherSuites(self, suites: list[str]) -> TLSConfig:
        """Set the cipher suites (informative; see the fidelity notes)."""
        self.cipher_suites = suites
        return self

    def Clone(self) -> TLSConfig:
        """Return a deep copy of this configuration."""
        return TLSConfig(
            cert_file=self.cert_file,
            key_file=self.key_file,
            cert_data=self.cert_data,
            key_data=self.key_data,
            ca_file=self.ca_file,
            ca_data=self.ca_data,
            insecure_skip_verify=self.insecure_skip_verify,
            server_name=self.server_name,
            min_version=self.min_version,
            max_version=self.max_version,
            cipher_suites=list(self.cipher_suites),
            curve_preferences=list(self.curve_preferences),
            client_auth=self.client_auth,
            root_cas=list(self.root_cas),
            client_cas=list(self.client_cas),
        )


def NewTLSConfig() -> TLSConfig:
    """Return a TLSConfig with the defaults (TLS 1.2+, 9 cipher suites)."""
    return TLSConfig()


def _pem_decode(data: bytes) -> bytes | None:
    """Return the DER bytes of the first PEM block, or None."""
    try:
        cert = crypto_x509.load_pem_x509_certificate(data)
        return cert.public_bytes(serialization.Encoding.DER)
    except Exception:
        return None


def ParseCertificate(pem_data: bytes) -> crypto_x509.Certificate:
    """Parse a PEM certificate (raises on error)."""
    try:
        return crypto_x509.load_pem_x509_certificate(pem_data)
    except Exception as e:
        raise _wrap(str(ErrInvalidCert), e) from e


def ParsePrivateKey(pem_data: bytes) -> object:
    """Parse a PEM private key (PKCS1/PKCS8/EC); raises on error."""
    try:
        return serialization.load_pem_private_key(pem_data, password=None)
    except Exception as e:
        raise _wrap(str(ErrInvalidKey), e) from e


def CertificateToPEM(cert: crypto_x509.Certificate) -> bytes:
    """Encode a certificate to PEM bytes."""
    return cert.public_bytes(serialization.Encoding.PEM)


def PrivateKeyToPEM(key: object) -> bytes:
    """Encode an RSA/EC private key to PKCS8 PEM; raises on other key types."""
    if not isinstance(key, (rsa.RSAPrivateKey, ec.EllipticCurvePrivateKey)):
        raise ErrInvalidKey
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def LoadSystemCertPool() -> list[crypto_x509.Certificate]:
    """Return the system certificate pool as a list (raises on error)."""
    ctx = ssl.create_default_context()
    return cast(list[crypto_x509.Certificate], ctx.get_ca_certs())


def NewCertPool(
    certs: Iterable[crypto_x509.Certificate] | None = None,
) -> list[crypto_x509.Certificate]:
    """Create a certificate pool from the given certificates."""
    return list(certs or [])


__all__ = [
    "ClientAuthType",
    "VERSION_TLS12",
    "VERSION_TLS13",
    "TLSConfig",
    "NewTLSConfig",
    "_pem_decode",
    "ParseCertificate",
    "ParsePrivateKey",
    "CertificateToPEM",
    "PrivateKeyToPEM",
    "LoadSystemCertPool",
    "NewCertPool",
    "_DEFAULT_CIPHER_SUITES",
    "_DEFAULT_CURVE_PREFERENCES",
]

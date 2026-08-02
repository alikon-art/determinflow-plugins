"""Safe environment-or-file secret loading for standalone workflow scripts."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping


MAX_SECRET_BYTES = 64 * 1024


class SecretLoadError(ValueError):
    """A configured secret file cannot be read safely."""


def _read_secret_file(path_value: str, name: str) -> str:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise SecretLoadError(
            f"{name}_FILE cannot be opened safely on this platform"
        )
    flags = os.O_RDONLY | nofollow
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = -1
    try:
        descriptor = os.open(path_value, flags)
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
            raise SecretLoadError(
                f"{name}_FILE must name one regular non-symlink file"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(MAX_SECRET_BYTES + 1)
        if len(payload) > MAX_SECRET_BYTES:
            raise SecretLoadError(f"{name}_FILE is unexpectedly large")
        value = payload.decode("utf-8").rstrip("\r\n")
    except SecretLoadError:
        raise
    except (OSError, UnicodeError) as exc:
        raise SecretLoadError(f"{name}_FILE is unreadable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not value or "\x00" in value or "\n" in value or "\r" in value:
        raise SecretLoadError(
            f"{name}_FILE must contain one non-empty text line"
        )
    return value


def read_secret(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Read an inline secret, falling back to its ``*_FILE`` counterpart."""

    values = os.environ if environ is None else environ
    inline_value = values.get(name)
    if inline_value is not None:
        return inline_value
    path_value = values.get(f"{name}_FILE", "")
    if not path_value:
        return ""
    return _read_secret_file(path_value, name)

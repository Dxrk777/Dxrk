# SPDX-License-Identifier: MIT
class Error(Exception):
    pass


class DuplicateAdapterError(Error):
    pass


class AdapterNotFoundError(Error):
    pass

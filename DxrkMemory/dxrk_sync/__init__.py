try:
    from engram import init as _init_sync
    from engram import __version__ as _version
except Exception:
    def _init_sync():
        return "dxrk_sync placeholder"
    _version = "0.0.0"

def init_sync():
    return _init_sync()

def get_version():
    return _version

__version__ = _version
__all__ = ["init_sync", "get_version", "__version__"]
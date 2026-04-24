try:
    from mempalace import init as _init_base
    from mempalace.version import version as _version
except Exception:
    def _init_base():
        return "dxrk_base placeholder"
    _version = "0.0.0"

def init_base():
    return _init_base()

def get_version():
    return _version

__version__ = _version
__all__ = ["init_base", "get_version", "__version__"]
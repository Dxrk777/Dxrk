"""Departamentos de Dxrk Enterprise."""

from .base import BaseDepartment
from .designers import DesignersDepartment
from .developers import DevelopersDepartment
from .finance import FinanceDepartment
from .legal import LegalDepartment
from .marketing import MarketingDepartment
from .small_business import SmallBusinessDepartment
from .social_media import SocialMediaDepartment

__all__ = [
    "BaseDepartment",
    "DesignersDepartment",
    "DevelopersDepartment",
    "FinanceDepartment",
    "LegalDepartment",
    "MarketingDepartment",
    "SmallBusinessDepartment",
    "SocialMediaDepartment",
]

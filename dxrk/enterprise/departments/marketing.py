"""Departamento de marketing: SEO, copywriting, campañas, leads."""

from .base import BaseDepartment


class MarketingDepartment(BaseDepartment):
    DEPARTMENT_ID = "marketing"
    DEPARTMENT_NAME = "Marketing"
    DEPARTMENT_DESCRIPTION = "SEO, copywriting, campañas, lead generation"
    SKILLS = [
        "seo_keyword_research",
        "seo_on_page_optimization",
        "seo_technical_audit",
        "seo_link_building",
        "seo_content_strategy",
        "copy_landing_pages",
        "copy_email_sequences",
        "copy_sales_pages",
        "copy_ad_creatives",
        "lead_magnet_creation",
        "lead_scoring",
        "funnel_optimization",
        "campaign_strategy",
        "campaign_budget_planning",
        "marketing_analytics",
    ]

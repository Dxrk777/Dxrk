"""Marketing Skills - 15 skills de marketing."""


from .skill_base import BaseSkill


def create_mkt_skill(name, desc, keywords):
    class S(BaseSkill):
        SKILL_NAME = name
        SKILL_DESCRIPTION = desc
        SKILL_CATEGORY = "marketing"
        KEYWORDS = keywords

        def _perform_task(self, task, context):
            return {"action": self.SKILL_NAME, "task": task}

    S.__name__ = name.replace("_", " ").title().replace(" ", "") + "Skill"
    return S


def get_all_marketing_skills() -> list[BaseSkill]:
    configs = [
        ("seo_keyword_research", "Keyword research", ["seo", "keyword"]),
        ("seo_on_page_optimization", "SEO on-page", ["seo", "onpage"]),
        ("seo_technical_audit", "Auditoría SEO", ["seo", "audit"]),
        ("seo_link_building", "Link building", ["seo", "link", "backlink"]),
        ("seo_content_strategy", "Estrategia SEO", ["seo", "content"]),
        ("copy_landing_pages", "Copy landing", ["copy", "landing"]),
        ("copy_email_sequences", "Email sequences", ["copy", "email"]),
        ("copy_sales_pages", "Sales pages", ["copy", "sales"]),
        ("copy_ad_creatives", "Ad creatives", ["copy", "ad", "creative"]),
        ("lead_magnet_creation", "Lead magnets", ["lead", "magnet"]),
        ("lead_scoring", "Lead scoring", ["lead", "score"]),
        ("funnel_optimization", "Funnel optimization", ["funnel", "conversion"]),
        ("campaign_strategy", "Campaign strategy", ["campaign", "strategy"]),
        ("campaign_budget_planning", "Budget planning", ["campaign", "budget"]),
        ("marketing_analytics", "Analytics", ["analytics", "metrics"]),
    ]
    return [create_mkt_skill(n, d, k)() for n, d, k in configs]

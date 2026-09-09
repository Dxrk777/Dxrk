"""Departamento de redes sociales: contenido, Reels, miniaturas, flujos."""

from .base import BaseDepartment


class SocialMediaDepartment(BaseDepartment):
    DEPARTMENT_ID = "social_media"
    DEPARTMENT_NAME = "Redes Sociales"
    DEPARTMENT_DESCRIPTION = "Contenido, Reels, miniaturas, flujos"
    SKILLS = [
        "content_calendar",
        "post_creation",
        "reel_creation",
        "story_creation",
        "thumbnail_design",
        "caption_writing",
        "hashtag_strategy",
        "instagram_management",
        "twitter_management",
        "linkedin_management",
        "tiktok_management",
        "youtube_management",
        "social_analytics",
        "engagement_optimization",
        "follower_growth",
        "community_management",
        "influencer_outreach",
    ]

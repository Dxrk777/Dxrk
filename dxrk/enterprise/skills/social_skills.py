"""Social Media Skills - 17 skills de redes sociales."""


from .skill_base import BaseSkill


def create_social_skill(name, desc, keywords):
    class S(BaseSkill):
        SKILL_NAME = name
        SKILL_DESCRIPTION = desc
        SKILL_CATEGORY = "social_media"
        KEYWORDS = keywords

        def _perform_task(self, task, context):
            return {"action": self.SKILL_NAME, "task": task}

    S.__name__ = name.replace("_", " ").title().replace(" ", "") + "Skill"
    return S


def get_all_social_skills() -> list[BaseSkill]:
    configs = [
        ("content_calendar", "Calendario", ["calendar", "schedule"]),
        ("post_creation", "Posts", ["post", "create"]),
        ("reel_creation", "Reels", ["reel", "video"]),
        ("story_creation", "Stories", ["story", "stories"]),
        ("thumbnail_design", "Miniaturas", ["thumbnail", "preview"]),
        ("caption_writing", "Captions", ["caption", "text"]),
        ("hashtag_strategy", "Hashtags", ["hashtag", "tag"]),
        ("instagram_management", "Instagram", ["instagram", "ig"]),
        ("twitter_management", "Twitter", ["twitter", "tweet"]),
        ("linkedin_management", "LinkedIn", ["linkedin"]),
        ("tiktok_management", "TikTok", ["tiktok"]),
        ("youtube_management", "YouTube", ["youtube"]),
        ("social_analytics", "Analytics", ["analytics", "insights"]),
        ("engagement_optimization", "Engagement", ["engagement", "likes"]),
        ("follower_growth", "Growth", ["follower", "growth"]),
        ("community_management", "Community", ["community", "moderate"]),
        ("influencer_outreach", "Influencers", ["influencer", "collab"]),
    ]
    return [create_social_skill(n, d, k)() for n, d, k in configs]

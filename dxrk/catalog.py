# SPDX-License-Identifier: MIT
from __future__ import annotations

from dxrk.models import AgentID, ComponentID, SkillID, SupportTier

__all__ = [
    "Agent",
    "Component",
    "Skill",
    "all_agents",
    "is_mvp_agent",
    "is_supported_agent",
    "mvp_agents",
    "mvp_components",
    "mvp_skills",
]


class Agent:
    def __init__(
        self,
        id: AgentID,
        name: str = "",
        tier: SupportTier = SupportTier.FULL,
        config_path: str = "",
    ) -> None:
        self.id = id
        self.name = name
        self.tier = tier
        self.config_path = config_path

    def __repr__(self) -> str:
        return f"Agent(id={self.id!r}, name={self.name!r})"


class Component:
    def __init__(self, id: ComponentID, name: str = "", description: str = "") -> None:
        self.id = id
        self.name = name
        self.description = description

    def __repr__(self) -> str:
        return f"Component(id={self.id!r}, name={self.name!r})"


class Skill:
    def __init__(
        self, id: SkillID, name: str = "", category: str = "", priority: str = ""
    ) -> None:
        self.id = id
        self.name = name
        self.category = category
        self.priority = priority

    def __repr__(self) -> str:
        return f"Skill(id={self.id!r}, name={self.name!r})"


_ALL_AGENTS = [
    Agent(
        id=AgentID.CLAUDE_CODE,
        name="Claude Code",
        tier=SupportTier.FULL,
        config_path="~/.claude",
    ),
    Agent(
        id=AgentID.OPENCODE,
        name="OpenCode",
        tier=SupportTier.FULL,
        config_path="~/.config/opencode",
    ),
    Agent(
        id=AgentID.KILOCODE,
        name="Kilo Code",
        tier=SupportTier.FULL,
        config_path="~/.config/kilo",
    ),
    Agent(
        id=AgentID.GEMINI_CLI,
        name="Gemini CLI",
        tier=SupportTier.FULL,
        config_path="~/.gemini",
    ),
    Agent(
        id=AgentID.CODEX, name="Codex", tier=SupportTier.FULL, config_path="~/.codex"
    ),
    Agent(
        id=AgentID.CURSOR, name="Cursor", tier=SupportTier.FULL, config_path="~/.cursor"
    ),
    Agent(
        id=AgentID.VSCODE_COPILOT,
        name="VS Code Copilot",
        tier=SupportTier.FULL,
        config_path="~/.copilot",
    ),
    Agent(
        id=AgentID.ANTIGRAVITY,
        name="Antigravity",
        tier=SupportTier.FULL,
        config_path="~/.gemini/antigravity",
    ),
    Agent(
        id=AgentID.WINDSURF,
        name="Windsurf",
        tier=SupportTier.FULL,
        config_path="~/.codeium/windsurf",
    ),
    Agent(
        id=AgentID.KIMI, name="Kimi Code", tier=SupportTier.FULL, config_path="~/.kimi"
    ),
    Agent(
        id=AgentID.QWEN_CODE,
        name="Qwen Code",
        tier=SupportTier.FULL,
        config_path="~/.qwen",
    ),
    Agent(
        id=AgentID.KIRO_IDE,
        name="Kiro IDE",
        tier=SupportTier.FULL,
        config_path="~/.kiro",
    ),
    Agent(
        id=AgentID.OPENCLAW,
        name="OpenClaw",
        tier=SupportTier.FULL,
        config_path="~/.openclaw",
    ),
    Agent(id=AgentID.PI, name="Pi", tier=SupportTier.FULL, config_path="~/.pi"),
]

_MVP_AGENTS = [
    Agent(
        id=AgentID.CLAUDE_CODE,
        name="Claude Code",
        tier=SupportTier.FULL,
        config_path="~/.claude",
    ),
    Agent(
        id=AgentID.OPENCODE,
        name="OpenCode",
        tier=SupportTier.FULL,
        config_path="~/.config/opencode",
    ),
]


def all_agents() -> list[Agent]:
    return list(_ALL_AGENTS)


def mvp_agents() -> list[Agent]:
    return list(_MVP_AGENTS)


def is_mvp_agent(agent: AgentID) -> bool:
    return any(a.id == agent for a in _MVP_AGENTS)


def is_supported_agent(agent: AgentID) -> bool:
    return any(a.id == agent for a in _ALL_AGENTS)


_MVP_COMPONENTS = [
    Component(
        id=ComponentID.DXRK_MEMORY,
        name="Engram",
        description="Persistent cross-session memory",
    ),
    Component(
        id=ComponentID.SDD, name="SDD", description="Spec-driven development workflow"
    ),
    Component(
        id=ComponentID.SKILLS, name="Skills", description="Curated coding skill library"
    ),
    Component(
        id=ComponentID.CONTEXT7,
        name="Context7",
        description="Latest framework and library docs",
    ),
    Component(
        id=ComponentID.PERSONA,
        name="Persona",
        description="Gentleman, neutral or custom behavior",
    ),
    Component(
        id=ComponentID.PERMISSIONS,
        name="Permissions",
        description="Security-first defaults and guardrails",
    ),
    Component(
        id=ComponentID.DXRK_GUARDIAN,
        name="GGA",
        description="Gentleman Guardian Angel AI provider switcher",
    ),
    Component(
        id=ComponentID.THEME,
        name="Theme",
        description="Gentleman Kanagawa theme overlay",
    ),
    Component(
        id=ComponentID.CLAUDE_THEME,
        name="Claude Theme",
        description="Claude Code-specific theme",
    ),
    Component(
        id=ComponentID.OPENCODE_DXRK_LOGO,
        name="OpenCode Gentle Logo",
        description="Braille rose home logo plugin",
    ),
]


def mvp_components() -> list[Component]:
    return list(_MVP_COMPONENTS)


_PRIORITY_P0 = "p0"
_PRIORITY_P0 = "p0"
_PRIORITY_P1 = "p1"
_PRIORITY_P2 = "p2"

_CAT_SDD = "sdd"
_CAT_TESTING = "testing"
_CAT_LANGUAGE = "language"
_CAT_WEB = "web"
_CAT_DEVOPS = "devops"
_CAT_AI = "ai"
_CAT_DATA = "data"
_CAT_MOBILE = "mobile"
_CAT_SECURITY = "security"
_CAT_ARCHITECTURE = "architecture"
_CAT_CLI = "cli"
_CAT_DOCUMENTATION = "documentation"
_CAT_MEDIA = "media"
_CAT_DOCUMENTS = "documents"
_CAT_BUSINESS = "business"
_CAT_WRITING = "writing"
_CAT_QUALITY = "quality"
_CAT_OBSERVABILITY = "observability"
_CAT_ANALYSIS = "analysis"
_CAT_WORKFLOW = "workflow"
_CAT_DXRK = "dxrk"

_MVP_SKILLS = [
    Skill(SkillID.SDD_INIT, "sdd-init", _CAT_SDD, _PRIORITY_P0),
    Skill(SkillID.SDD_APPLY, "sdd-apply", _CAT_SDD, _PRIORITY_P0),
    Skill(SkillID.SDD_VERIFY, "sdd-verify", _CAT_SDD, _PRIORITY_P0),
    Skill(SkillID.SDD_EXPLORE, "sdd-explore", _CAT_SDD, _PRIORITY_P0),
    Skill(SkillID.SDD_PROPOSE, "sdd-propose", _CAT_SDD, _PRIORITY_P0),
    Skill(SkillID.SDD_SPEC, "sdd-spec", _CAT_SDD, _PRIORITY_P0),
    Skill(SkillID.SDD_DESIGN, "sdd-design", _CAT_SDD, _PRIORITY_P0),
    Skill(SkillID.SDD_TASKS, "sdd-tasks", _CAT_SDD, _PRIORITY_P0),
    Skill(SkillID.SDD_ARCHIVE, "sdd-archive", _CAT_SDD, _PRIORITY_P0),
    Skill(SkillID.SDD_ONBOARD, "sdd-onboard", _CAT_SDD, _PRIORITY_P0),
    Skill(SkillID.GO_TESTING, "go-testing", _CAT_TESTING, _PRIORITY_P0),
    Skill(SkillID.SKILL_CREATOR, "skill-creator", _CAT_WORKFLOW, _PRIORITY_P0),
    Skill(SkillID.JUDGMENT_DAY, "judgment-day", _CAT_WORKFLOW, _PRIORITY_P0),
    Skill(SkillID.BRANCH_PR, "branch-pr", _CAT_WORKFLOW, _PRIORITY_P0),
    Skill(SkillID.ISSUE_CREATION, "issue-creation", _CAT_WORKFLOW, _PRIORITY_P0),
    Skill(SkillID.SKILL_REGISTRY, "skill-registry", _CAT_WORKFLOW, _PRIORITY_P0),
    Skill(SkillID.CHAINED_PR, "chained-pr", _CAT_WORKFLOW, _PRIORITY_P0),
    Skill(SkillID.COGNITIVE_DOC, "cognitive-doc-design", _CAT_WORKFLOW, _PRIORITY_P0),
    Skill(SkillID.COMMENT_WRITER, "comment-writer", _CAT_WORKFLOW, _PRIORITY_P0),
    Skill(SkillID.WORK_UNIT_COMMITS, "work-unit-commits", _CAT_WORKFLOW, _PRIORITY_P0),
    Skill(SkillID.LLM_COUNCIL, "llm-council", _CAT_ANALYSIS, _PRIORITY_P0),
    Skill(SkillID.PYTHON_PRO, "python-pro", _CAT_LANGUAGE, _PRIORITY_P1),
    Skill(SkillID.PYTHON_PATTERNS, "python-patterns", _CAT_LANGUAGE, _PRIORITY_P1),
    Skill(
        SkillID.ASYNC_PYTHON_PATTERNS,
        "async-python-patterns",
        _CAT_LANGUAGE,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.PYTHON_FASTAPI,
        "python-fastapi-development",
        _CAT_LANGUAGE,
        _PRIORITY_P1,
    ),
    Skill(SkillID.PYTHON_PACKAGING, "python-packaging", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(
        SkillID.PYTHON_PERFORMANCE,
        "python-performance-optimization",
        _CAT_LANGUAGE,
        _PRIORITY_P2,
    ),
    Skill(SkillID.PYTEST_SKILL, "pytest-skill", _CAT_TESTING, _PRIORITY_P1),
    Skill(SkillID.PYDANTIC_AI, "pydantic-ai", _CAT_LANGUAGE, _PRIORITY_P1),
    Skill(SkillID.JAVA_SCRIPT_PRO, "javascript-pro", _CAT_LANGUAGE, _PRIORITY_P1),
    Skill(
        SkillID.JAVA_SCRIPT_MASTERY, "javascript-mastery", _CAT_LANGUAGE, _PRIORITY_P1
    ),
    Skill(
        SkillID.JAVA_SCRIPT_DESIGN,
        "javascript-design-patterns",
        _CAT_LANGUAGE,
        _PRIORITY_P1,
    ),
    Skill(SkillID.NODEJS_PRO, "nodejs-pro", _CAT_LANGUAGE, _PRIORITY_P1),
    Skill(SkillID.TYPE_SCRIPT_PRO, "typescript-pro", _CAT_LANGUAGE, _PRIORITY_P0),
    Skill(SkillID.NEXTJS_PRO, "nextjs-pro", _CAT_WEB, _PRIORITY_P1),
    Skill(SkillID.RUST_PRO, "rust-pro", _CAT_LANGUAGE, _PRIORITY_P1),
    Skill(SkillID.RUST_ASYNC, "rust-async-patterns", _CAT_LANGUAGE, _PRIORITY_P1),
    Skill(
        SkillID.MEMORY_SAFETY_PATTERNS,
        "memory-safety-patterns",
        _CAT_LANGUAGE,
        _PRIORITY_P2,
    ),
    Skill(SkillID.GOLANG_PRO, "golang-pro", _CAT_LANGUAGE, _PRIORITY_P0),
    Skill(
        SkillID.GO_CONCURRENCY_PATTERNS,
        "go-concurrency-patterns",
        _CAT_LANGUAGE,
        _PRIORITY_P0,
    ),
    Skill(SkillID.GO_IN_DEPTH, "go-in-depth", _CAT_LANGUAGE, _PRIORITY_P1),
    Skill(SkillID.GO_PLAYWRIGHT, "go-playwright", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(SkillID.GO_ROD_MASTER, "go-rod-master", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(SkillID.GRPC_GOLANG, "grpc-golang", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(
        SkillID.TEMPORAL_GOLANG_PRO, "temporal-golang-pro", _CAT_LANGUAGE, _PRIORITY_P2
    ),
    Skill(SkillID.JAVA_PRO, "java-pro", _CAT_LANGUAGE, _PRIORITY_P1),
    Skill(SkillID.SPRINGBOOT_PRO, "springboot-pro", _CAT_LANGUAGE, _PRIORITY_P1),
    Skill(
        SkillID.JAVA_PERFORMANCE_TUNING,
        "java-performance-tuning",
        _CAT_LANGUAGE,
        _PRIORITY_P2,
    ),
    Skill(SkillID.CPP_PRO, "cpp-pro", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(SkillID.CPP_LOW_LATENCY, "cpp-low-latency", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(SkillID.SWIFT_PRO, "swift-pro", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(
        SkillID.SWIFT_CONCURRENCY,
        "swift-concurrency-expert",
        _CAT_LANGUAGE,
        _PRIORITY_P2,
    ),
    Skill(SkillID.SWIFTUI_EXPERT, "swiftui-expert", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(SkillID.KOTLIN_PRO, "kotlin-pro", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(
        SkillID.KOTLIN_MULTIPLATFORM,
        "kotlin-multiplatform",
        _CAT_LANGUAGE,
        _PRIORITY_P2,
    ),
    Skill(
        SkillID.ANDROID_JETPACK_COMPOSE_EXPERT,
        "android-jetpack-compose-expert",
        _CAT_MOBILE,
        _PRIORITY_P2,
    ),
    Skill(SkillID.RUBY_RAILS_PRO, "ruby-rails-pro", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(SkillID.PHP_PRO, "php-pro", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(SkillID.PHP_LARAVEL_PRO, "php-laravel-pro", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(SkillID.REACT_BEST_PRACTICES, "react-best-practices", _CAT_WEB, _PRIORITY_P1),
    Skill(SkillID.REACT_PATTERNS, "react-patterns", _CAT_WEB, _PRIORITY_P1),
    Skill(SkillID.ANGULAR_PRO, "angular-pro", _CAT_WEB, _PRIORITY_P2),
    Skill(SkillID.SVELTE_PRO, "svelte-pro", _CAT_WEB, _PRIORITY_P2),
    Skill(SkillID.VUE_PRO, "vue-pro", _CAT_WEB, _PRIORITY_P2),
    Skill(SkillID.TAILWIND_PRO, "tailwind-pro", _CAT_WEB, _PRIORITY_P1),
    Skill(SkillID.CSS_PRO, "css-pro", _CAT_WEB, _PRIORITY_P2),
    Skill(SkillID.HTML_PRO, "html-pro", _CAT_WEB, _PRIORITY_P2),
    Skill(SkillID.FRONTEND_ARCH, "frontend-architecture", _CAT_WEB, _PRIORITY_P1),
    Skill(
        SkillID.REACT_COMP_PERF, "react-component-performance", _CAT_WEB, _PRIORITY_P2
    ),
    Skill(
        SkillID.REACT_COMPONENT_PERF2,
        "react-component-performance-2",
        _CAT_WEB,
        _PRIORITY_P2,
    ),
    Skill(SkillID.DOCKER_EXPERT, "docker-expert", _CAT_DEVOPS, _PRIORITY_P0),
    Skill(
        SkillID.KUBERNETES_ARCHITECT, "kubernetes-architect", _CAT_DEVOPS, _PRIORITY_P0
    ),
    Skill(SkillID.TERRAFORM_PATTERNS, "terraform-patterns", _CAT_DEVOPS, _PRIORITY_P1),
    Skill(SkillID.AWS_ARCHITECT, "aws-architect", _CAT_DEVOPS, _PRIORITY_P1),
    Skill(SkillID.CLOUD_ARCHITECT, "cloud-architect", _CAT_DEVOPS, _PRIORITY_P1),
    Skill(
        SkillID.GITHUB_ACTIONS_ADVANCED,
        "github-actions-advanced",
        _CAT_DEVOPS,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.CI_CD_PIPELINE_BUILDER,
        "ci-cd-pipeline-builder",
        _CAT_DEVOPS,
        _PRIORITY_P1,
    ),
    Skill(SkillID.GITOPS_WORKFLOW, "gitops-workflow", _CAT_DEVOPS, _PRIORITY_P2),
    Skill(SkillID.ARGO_CD_PRO, "argocd-pro", _CAT_DEVOPS, _PRIORITY_P2),
    Skill(SkillID.HELM_CHART_BUILDER, "helm-chart-builder", _CAT_DEVOPS, _PRIORITY_P2),
    Skill(
        SkillID.HELM_CHART_BUILDER2, "helm-chart-builder-2", _CAT_DEVOPS, _PRIORITY_P2
    ),
    Skill(SkillID.AWS_LAMBDA_PRO, "aws-lambda-pro", _CAT_DEVOPS, _PRIORITY_P2),
    Skill(
        SkillID.PROMPT_ENGINEERING, "prompt-engineering-patterns", _CAT_AI, _PRIORITY_P0
    ),
    Skill(SkillID.PROMPT_ENGINEERING2, "prompt-engineering", _CAT_AI, _PRIORITY_P2),
    Skill(SkillID.AGENT_DESIGNER, "agent-designer", _CAT_AI, _PRIORITY_P0),
    Skill(SkillID.MEMORY_SYSTEMS, "memory-systems", _CAT_AI, _PRIORITY_P1),
    Skill(SkillID.LLM_APP_PATTERNS, "llm-app-patterns", _CAT_AI, _PRIORITY_P1),
    Skill(SkillID.LLM_EVALUATION, "llm-evaluation", _CAT_AI, _PRIORITY_P1),
    Skill(SkillID.RAG_ARCHITECT, "rag-architect", _CAT_AI, _PRIORITY_P1),
    Skill(SkillID.RAG_ENGINEER, "rag-engineer", _CAT_AI, _PRIORITY_P1),
    Skill(
        SkillID.AI_ENGINEERING_TOOLKIT, "ai-engineering-toolkit", _CAT_AI, _PRIORITY_P1
    ),
    Skill(SkillID.FINE_TUNING_PRO, "fine-tuning-pro", _CAT_AI, _PRIORITY_P2),
    Skill(SkillID.LANG_CHAIN_PRO, "langchain-pro", _CAT_AI, _PRIORITY_P2),
    Skill(SkillID.EMBEDDING_PRO, "embedding-pro", _CAT_AI, _PRIORITY_P2),
    Skill(SkillID.VECTOR_DB_PRO, "vector-db-pro", _CAT_AI, _PRIORITY_P2),
    Skill(SkillID.ML_OPS_PRO, "ml-ops-pro", _CAT_AI, _PRIORITY_P2),
    Skill(SkillID.COMPUTER_VISION_PRO, "computer-vision-pro", _CAT_AI, _PRIORITY_P2),
    Skill(SkillID.NLP_PRO, "nlp-pro", _CAT_AI, _PRIORITY_P2),
    Skill(SkillID.HUGGING_FACE_CLI, "hugging-face-cli", _CAT_AI, _PRIORITY_P2),
    Skill(SkillID.LANG_GRAPH, "langgraph", _CAT_AI, _PRIORITY_P2),
    Skill(SkillID.DATA_ENGINEER, "data-engineer", _CAT_DATA, _PRIORITY_P1),
    Skill(
        SkillID.DATA_PIPELINE, "data-engineering-data-pipeline", _CAT_DATA, _PRIORITY_P1
    ),
    Skill(
        SkillID.POSTGRES_BEST_PRACTICES,
        "postgres-best-practices",
        _CAT_DATA,
        _PRIORITY_P1,
    ),
    Skill(SkillID.REDIS_PRO, "redis-pro", _CAT_DATA, _PRIORITY_P2),
    Skill(SkillID.MONGO_DB_PRO, "mongodb-pro", _CAT_DATA, _PRIORITY_P2),
    Skill(SkillID.DATA_VISUALIZATION, "data-visualization", _CAT_DATA, _PRIORITY_P2),
    Skill(SkillID.DB_QUERY, "db-query", _CAT_DATA, _PRIORITY_P1),
    Skill(SkillID.MIGRATION, "migration", _CAT_DATA, _PRIORITY_P1),
    Skill(SkillID.REACT_NATIVE, "react-native", _CAT_MOBILE, _PRIORITY_P2),
    Skill(SkillID.ANDROID_DEV, "android-dev", _CAT_MOBILE, _PRIORITY_P2),
    Skill(SkillID.FLUTTER_PRO, "flutter-pro", _CAT_MOBILE, _PRIORITY_P2),
    Skill(SkillID.IOS_PRO, "ios-pro", _CAT_MOBILE, _PRIORITY_P2),
    Skill(SkillID.MOBILE_TESTING, "mobile-app-testing", _CAT_TESTING, _PRIORITY_P2),
    Skill(
        SkillID.SECURITY_SAST,
        "security-scanning-security-sast",
        _CAT_SECURITY,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.SECURITY_HARDENING,
        "security-scanning-security-hardening",
        _CAT_SECURITY,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.SECURITY_DEPENDENCIES,
        "security-scanning-security-dependencies",
        _CAT_SECURITY,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.API_SECURITY, "api-security-best-practices", _CAT_SECURITY, _PRIORITY_P1
    ),
    Skill(
        SkillID.CONTAINER_SECURITY,
        "container-security-hardening",
        _CAT_SECURITY,
        _PRIORITY_P2,
    ),
    Skill(SkillID.CLOUD_SECURITY, "cloud-security", _CAT_SECURITY, _PRIORITY_P2),
    Skill(
        SkillID.PENETRATION_TESTING, "penetration-testing", _CAT_SECURITY, _PRIORITY_P2
    ),
    Skill(SkillID.TDD_GUIDE, "tdd-guide", _CAT_TESTING, _PRIORITY_P1),
    Skill(SkillID.E2E_TESTING, "e2e-testing", _CAT_TESTING, _PRIORITY_P1),
    Skill(SkillID.K6_LOAD_TESTING, "k6-load-testing", _CAT_TESTING, _PRIORITY_P2),
    Skill(SkillID.TESTING_PATTERNS, "testing-patterns", _CAT_TESTING, _PRIORITY_P1),
    Skill(SkillID.TEST_AUTOMATOR, "test-automator", _CAT_TESTING, _PRIORITY_P2),
    Skill(SkillID.PLAYWRIGHT_PRO, "playwright-pro", _CAT_TESTING, _PRIORITY_P1),
    Skill(SkillID.CYPRESS_PRO, "cypress-pro", _CAT_TESTING, _PRIORITY_P2),
    Skill(
        SkillID.SOFTWARE_ARCHITECTURE,
        "software-architecture",
        _CAT_ARCHITECTURE,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.MICROSERVICES_PATTERNS,
        "microservices-patterns",
        _CAT_ARCHITECTURE,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.EVENT_SOURCING_ARCHITECT,
        "event-sourcing-architect",
        _CAT_ARCHITECTURE,
        _PRIORITY_P2,
    ),
    Skill(SkillID.DDD_PRO, "ddd-pro", _CAT_ARCHITECTURE, _PRIORITY_P2),
    Skill(
        SkillID.SAGA_ORCHESTRATION,
        "saga-orchestration",
        _CAT_ARCHITECTURE,
        _PRIORITY_P2,
    ),
    Skill(SkillID.BASH_PRO, "bash-pro", _CAT_CLI, _PRIORITY_P1),
    Skill(SkillID.BASH_SCRIPTING, "bash-scripting", _CAT_CLI, _PRIORITY_P1),
    Skill(SkillID.POSIX_SHELL_PRO, "posix-shell-pro", _CAT_CLI, _PRIORITY_P2),
    Skill(SkillID.AI_NATIVE_CLI, "ai-native-cli", _CAT_CLI, _PRIORITY_P2),
    Skill(SkillID.JQ, "jq", _CAT_CLI, _PRIORITY_P2),
    Skill(SkillID.API_DOCS, "api-docs", _CAT_DOCUMENTATION, _PRIORITY_P1),
    Skill(
        SkillID.DOC_GENERATION,
        "documentation-generation",
        _CAT_DOCUMENTATION,
        _PRIORITY_P1,
    ),
    Skill(SkillID.CHANGELOG_PRO, "changelog-pro", _CAT_DOCUMENTATION, _PRIORITY_P2),
    Skill(SkillID.README_PRO, "readme-pro", _CAT_DOCUMENTATION, _PRIORITY_P2),
    Skill(SkillID.IMAGE_GENERATION, "image-generation", _CAT_MEDIA, _PRIORITY_P1),
    Skill(SkillID.VIDEO_EDITING, "video-editing", _CAT_MEDIA, _PRIORITY_P2),
    Skill(SkillID.AUDIO_PROCESSING, "audio-processing", _CAT_MEDIA, _PRIORITY_P2),
    Skill(SkillID._3D_MODELING, "3d-modeling", _CAT_MEDIA, _PRIORITY_P2),
    Skill(SkillID.ALGORITHMIC_ART, "algorithmic-art", _CAT_MEDIA, _PRIORITY_P2),
    Skill(SkillID.PDF_GENERATION, "pdf-generation", _CAT_DOCUMENTS, _PRIORITY_P1),
    Skill(SkillID.WORD_DOCX, "word-docx", _CAT_DOCUMENTS, _PRIORITY_P1),
    Skill(SkillID.EXCEL_XLSX, "excel-xlsx", _CAT_DOCUMENTS, _PRIORITY_P1),
    Skill(SkillID.PPTX_DECK, "pptx-deck-creation", _CAT_DOCUMENTS, _PRIORITY_P2),
    Skill(
        SkillID.PRODUCT_MANAGEMENT, "product-management", _CAT_BUSINESS, _PRIORITY_P2
    ),
    Skill(SkillID.AGILE_SCRUM, "agile-scrum", _CAT_BUSINESS, _PRIORITY_P2),
    Skill(SkillID.OKR_TRACKING, "okr-tracking", _CAT_BUSINESS, _PRIORITY_P2),
    Skill(SkillID.TECHNICAL_WRITING, "technical-writing", _CAT_WRITING, _PRIORITY_P1),
    Skill(SkillID.COPYWRITING, "copywriting", _CAT_WRITING, _PRIORITY_P2),
    Skill(SkillID.COPYWRITING_PRO, "copywriting-pro", _CAT_WRITING, _PRIORITY_P2),
    Skill(SkillID.SEO_WRITING, "seo-writing", _CAT_WRITING, _PRIORITY_P2),
    Skill(SkillID.BLOG_WRITING, "blog-writing", _CAT_WRITING, _PRIORITY_P2),
    Skill(
        SkillID.CODE_REVIEW_CHECKLIST,
        "code-review-checklist",
        _CAT_QUALITY,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.REFACTORING_PATTERNS, "refactoring-patterns", _CAT_QUALITY, _PRIORITY_P1
    ),
    Skill(
        SkillID.ERROR_HANDLING_PATTERNS,
        "error-handling-patterns",
        _CAT_QUALITY,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.SYSTEMATIC_DEBUGGING, "systematic-debugging", _CAT_QUALITY, _PRIORITY_P1
    ),
    Skill(
        SkillID.CODE_SIMPLIFICATION, "code-simplification", _CAT_QUALITY, _PRIORITY_P2
    ),
    Skill(
        SkillID.OBSERVABILITY,
        "observability-and-instrumentation",
        _CAT_OBSERVABILITY,
        _PRIORITY_P2,
    ),
    Skill(
        SkillID.INCIDENT_RESPONDER,
        "incident-responder",
        _CAT_OBSERVABILITY,
        _PRIORITY_P2,
    ),
    Skill(SkillID.POSTMORTEM, "postmortem", _CAT_OBSERVABILITY, _PRIORITY_P2),
    Skill(
        SkillID.CHAOS_ENGINEERING, "chaos-engineering", _CAT_OBSERVABILITY, _PRIORITY_P2
    ),
    Skill(SkillID.ACCESSIBILITY, "accessibility", _CAT_WEB, _PRIORITY_P1),
    Skill(SkillID.ARCH_DECISION, "arch-decision", _CAT_ARCHITECTURE, _PRIORITY_P1),
    Skill(SkillID.CI_CD, "ci-cd", _CAT_DEVOPS, _PRIORITY_P1),
    Skill(SkillID.CODE_REVIEW, "code-review", _CAT_QUALITY, _PRIORITY_P0),
    Skill(SkillID.COMMIT_MESSAGE, "commit-message", _CAT_WORKFLOW, _PRIORITY_P0),
    Skill(SkillID.DEBUGGING, "debugging", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.DEPENDENCY, "dependency", _CAT_DEVOPS, _PRIORITY_P1),
    Skill(SkillID.DOCKER_MGMT, "docker-mgmt", _CAT_DEVOPS, _PRIORITY_P1),
    Skill(SkillID.ENV_SETUP, "env-setup", _CAT_DEVOPS, _PRIORITY_P1),
    Skill(SkillID.ERROR_HANDLING, "error-handling", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.GIT_RELEASE, "git-release", _CAT_WORKFLOW, _PRIORITY_P1),
    Skill(SkillID.LOGGING_PATTERNS, "logging-patterns", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.PERFORMANCE, "performance", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.PR_DESCRIPTION, "pr-description", _CAT_WORKFLOW, _PRIORITY_P1),
    Skill(SkillID.REFACTORING_PR, "refactoring-pr", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.SECURITY_AUDIT, "security-audit", _CAT_SECURITY, _PRIORITY_P1),
    Skill(SkillID.TEST_WRITER, "test-writer", _CAT_TESTING, _PRIORITY_P1),
    Skill(SkillID.DXRK_API_CONTENT, "dxrk-api-content", _CAT_DXRK, _PRIORITY_P0),
    Skill(SkillID.DXRK_BATCH, "dxrk-batch", _CAT_DXRK, _PRIORITY_P0),
    Skill(SkillID.DXRK_CLAUDE_API, "dxrk-claude-api", _CAT_DXRK, _PRIORITY_P0),
    Skill(SkillID.DXRK_CLAUDE_CHROME, "dxrk-claude-chrome", _CAT_DXRK, _PRIORITY_P1),
    Skill(SkillID.DXRK_DEBUG, "dxrk-debug", _CAT_DXRK, _PRIORITY_P0),
    Skill(SkillID.DXRK_DISCORD_AGENT, "dxrk-discord-agent", _CAT_DXRK, _PRIORITY_P1),
    Skill(SkillID.DXRK_DREAM, "dxrk-dream", _CAT_DXRK, _PRIORITY_P2),
    Skill(
        SkillID.DXRK_DUPLICATE_DETECT,
        "dxrk-duplicate-detection",
        _CAT_DXRK,
        _PRIORITY_P0,
    ),
    Skill(SkillID.DXRK_GHSA, "dxrk-ghsa-maintainer", _CAT_DXRK, _PRIORITY_P0),
    Skill(SkillID.DXRK_GITCRAWL, "dxrk-gitcrawl", _CAT_DXRK, _PRIORITY_P1),
    Skill(SkillID.DXRK_KEYBINDINGS, "dxrk-keybindings", _CAT_DXRK, _PRIORITY_P1),
    Skill(SkillID.DXRK_LOOP, "dxrk-loop", _CAT_DXRK, _PRIORITY_P1),
    Skill(SkillID.DXRK_LOREM_IPSUM, "dxrk-lorem-ipsum", _CAT_DXRK, _PRIORITY_P2),
    Skill(SkillID.DXRK_PARALLELS_E2E, "dxrk-parallels-e2e", _CAT_DXRK, _PRIORITY_P1),
    Skill(
        SkillID.DXRK_PARALLELS_SMOKE, "dxrk-parallels-smoke", _CAT_DXRK, _PRIORITY_P1
    ),
    Skill(
        SkillID.DXRK_PRE_RELEASE, "dxrk-pre-release-testing", _CAT_DXRK, _PRIORITY_P0
    ),
    Skill(SkillID.DXRK_PR_MAINTAINER, "dxrk-pr-maintainer", _CAT_DXRK, _PRIORITY_P0),
    Skill(SkillID.DXRK_QA_TESTING, "dxrk-qa-testing", _CAT_DXRK, _PRIORITY_P0),
    Skill(SkillID.DXRK_RELEASE, "dxrk-release-maintainer", _CAT_DXRK, _PRIORITY_P0),
    Skill(SkillID.DXRK_REMEMBER, "dxrk-remember", _CAT_DXRK, _PRIORITY_P1),
    Skill(
        SkillID.DXRK_SCHEDULE_AGENTS, "dxrk-schedule-agents", _CAT_DXRK, _PRIORITY_P1
    ),
    Skill(SkillID.DXRK_SECRET_SCAN, "dxrk-secret-scanning", _CAT_DXRK, _PRIORITY_P0),
    Skill(
        SkillID.DXRK_SECURITY_TRIAGE, "dxrk-security-triage", _CAT_DXRK, _PRIORITY_P0
    ),
    Skill(SkillID.DXRK_SIMPLIFY, "dxrk-simplify", _CAT_DXRK, _PRIORITY_P1),
    Skill(
        SkillID.DXRK_SKILL_GENERATOR, "dxrk-skill-generator", _CAT_DXRK, _PRIORITY_P1
    ),
    Skill(SkillID.DXRK_SKILLIFY, "dxrk-skillify", _CAT_DXRK, _PRIORITY_P1),
    Skill(SkillID.DXRK_STUCK, "dxrk-stuck", _CAT_DXRK, _PRIORITY_P1),
    Skill(SkillID.DXRK_TESTBOX, "dxrk-testbox", _CAT_DXRK, _PRIORITY_P0),
    Skill(SkillID.DXRK_TESTING, "dxrk-testing", _CAT_DXRK, _PRIORITY_P0),
    Skill(SkillID.DXRK_TEST_MEMORY, "dxrk-test-memory", _CAT_DXRK, _PRIORITY_P1),
    Skill(SkillID.DXRK_TEST_OPTIMIZE, "dxrk-test-optimize", _CAT_DXRK, _PRIORITY_P1),
    Skill(
        SkillID.DXRK_TEST_PERFORMANCE, "dxrk-test-performance", _CAT_DXRK, _PRIORITY_P1
    ),
    Skill(SkillID.DXRK_UPDATE_CONFIG, "dxrk-update-config", _CAT_DXRK, _PRIORITY_P1),
    Skill(SkillID.DXRK_VERIFY, "dxrk-verify", _CAT_DXRK, _PRIORITY_P0),
    Skill(SkillID.TYPE_SCRIPT_EXPERT, "typescript-expert", _CAT_LANGUAGE, _PRIORITY_P1),
    Skill(
        SkillID.NODEJS_BACKEND, "nodejs-backend-patterns", _CAT_LANGUAGE, _PRIORITY_P1
    ),
    Skill(
        SkillID.NODEJS_BEST_PRACTICES,
        "nodejs-best-practices",
        _CAT_LANGUAGE,
        _PRIORITY_P1,
    ),
    Skill(SkillID.TRPC_FULLSTACK, "trpc-fullstack", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(SkillID.DRIZZLE_ORM, "drizzle-orm-expert", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(SkillID.PRISMA_EXPERT, "prisma-expert", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(SkillID.RUBY_PRO, "ruby-pro", _CAT_LANGUAGE, _PRIORITY_P2),
    Skill(
        SkillID.PYTHON_TESTING, "python-testing-patterns", _CAT_TESTING, _PRIORITY_P1
    ),
    Skill(SkillID.ANGULAR, "angular", _CAT_WEB, _PRIORITY_P2),
    Skill(
        SkillID.ANGULAR_BEST_PRACTICES, "angular-best-practices", _CAT_WEB, _PRIORITY_P2
    ),
    Skill(SkillID.SVELTE_KIT, "sveltekit", _CAT_WEB, _PRIORITY_P2),
    Skill(SkillID.TAILWIND_PATTERNS, "tailwind-patterns", _CAT_WEB, _PRIORITY_P1),
    Skill(SkillID.REACT_STATE_MGMT, "react-state-management", _CAT_WEB, _PRIORITY_P1),
    Skill(SkillID.AWS_SERVERLESS_EDA, "aws-serverless-eda", _CAT_DEVOPS, _PRIORITY_P1),
    Skill(
        SkillID.AWS_PENETRATION, "aws-penetration-testing", _CAT_SECURITY, _PRIORITY_P2
    ),
    Skill(SkillID.AZURE_CLOUD, "azure-cloud-architect", _CAT_DEVOPS, _PRIORITY_P2),
    Skill(SkillID.DOCKER_DEVELOPMENT, "docker-development", _CAT_DEVOPS, _PRIORITY_P1),
    Skill(
        SkillID.DEPLOYMENT_PIPELINE,
        "deployment-pipeline-design",
        _CAT_DEVOPS,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.CI_CD_AND_AUTOMATION, "ci-cd-and-automation", _CAT_DEVOPS, _PRIORITY_P1
    ),
    Skill(
        SkillID.KUBERNETES_DEPLOY, "kubernetes-deployment", _CAT_DEVOPS, _PRIORITY_P1
    ),
    Skill(
        SkillID.KUBERNETES_OPERATOR, "kubernetes-operator", _CAT_DEVOPS, _PRIORITY_P2
    ),
    Skill(SkillID.SPARK_OPTIMIZATION, "spark-optimization", _CAT_DATA, _PRIORITY_P2),
    Skill(SkillID.SNOWFLAKE, "snowflake-development", _CAT_DATA, _PRIORITY_P2),
    Skill(SkillID.AI_AGENTS_ARCHITECT, "ai-agents-architect", _CAT_AI, _PRIORITY_P0),
    Skill(SkillID.AGENT_PROTOCOL, "agent-protocol", _CAT_AI, _PRIORITY_P1),
    Skill(SkillID.AGENT_MEMORY_SYSTEMS, "agent-memory-systems", _CAT_AI, _PRIORITY_P1),
    Skill(SkillID.AI_SECURITY, "ai-security", _CAT_AI, _PRIORITY_P1),
    Skill(SkillID.RAG_IMPLEMENTATION, "rag-implementation", _CAT_AI, _PRIORITY_P1),
    Skill(SkillID.PROMPT_ENGINEER, "prompt-engineer", _CAT_AI, _PRIORITY_P1),
    Skill(
        SkillID.HUGGING_FACE_TRAINER,
        "hugging-face-model-trainer",
        _CAT_AI,
        _PRIORITY_P2,
    ),
    Skill(SkillID.EMBEDDING_STRATEGIES, "embedding-strategies", _CAT_AI, _PRIORITY_P2),
    Skill(
        SkillID.LANG_CHAIN_ARCHITECT, "langchain-architecture", _CAT_AI, _PRIORITY_P2
    ),
    Skill(SkillID.DATABASE_ARCHITECT, "database-architect", _CAT_DATA, _PRIORITY_P1),
    Skill(SkillID.DATABASE_OPTIMIZER, "database-optimizer", _CAT_DATA, _PRIORITY_P1),
    Skill(SkillID.SQL_DATABASE, "sql-database-assistant", _CAT_DATA, _PRIORITY_P1),
    Skill(SkillID.POSTGRESQL, "postgresql", _CAT_DATA, _PRIORITY_P1),
    Skill(
        SkillID.POSTGRES_OPTIMIZATION,
        "postgresql-optimization",
        _CAT_DATA,
        _PRIORITY_P1,
    ),
    Skill(SkillID.SUPABASE, "supabase", _CAT_DATA, _PRIORITY_P2),
    Skill(
        SkillID.SECURITY_AND_HARDENING,
        "security-and-hardening",
        _CAT_SECURITY,
        _PRIORITY_P1,
    ),
    Skill(SkillID.SECURITY_AUDITOR, "security-auditor", _CAT_SECURITY, _PRIORITY_P1),
    Skill(
        SkillID.SECURITY_PEN_TESTING,
        "security-pen-testing",
        _CAT_SECURITY,
        _PRIORITY_P2,
    ),
    Skill(SkillID.SECURITY_GUIDANCE, "security-guidance", _CAT_SECURITY, _PRIORITY_P1),
    Skill(
        SkillID.SECURITY_BLUEBOOK,
        "security-bluebook-builder",
        _CAT_SECURITY,
        _PRIORITY_P2,
    ),
    Skill(
        SkillID.SECURITY_REQ_EXTRACT,
        "security-requirement-extraction",
        _CAT_SECURITY,
        _PRIORITY_P2,
    ),
    Skill(
        SkillID.SECRETS_MANAGEMENT, "secrets-management", _CAT_SECURITY, _PRIORITY_P1
    ),
    Skill(
        SkillID.API_SECURITY_TESTING,
        "api-security-testing",
        _CAT_SECURITY,
        _PRIORITY_P1,
    ),
    Skill(SkillID.CYPRESS_SKILL, "cypress-skill", _CAT_TESTING, _PRIORITY_P2),
    Skill(SkillID.PLAYWRIGHT_SKILL, "playwright-skill", _CAT_TESTING, _PRIORITY_P1),
    Skill(SkillID.PLAYWRIGHT_JAVA, "playwright-java", _CAT_TESTING, _PRIORITY_P2),
    Skill(
        SkillID.UNIT_TEST_GENERATE,
        "unit-testing-test-generate",
        _CAT_TESTING,
        _PRIORITY_P1,
    ),
    Skill(SkillID.TESTING_QA, "testing-qa", _CAT_TESTING, _PRIORITY_P1),
    Skill(SkillID.TDD_DRIVE, "test-driven-development", _CAT_TESTING, _PRIORITY_P1),
    Skill(SkillID.API_TEST_SUITE, "api-test-suite-builder", _CAT_TESTING, _PRIORITY_P1),
    Skill(
        SkillID.API_TEST_MOCK,
        "api-testing-observability-api-mock",
        _CAT_TESTING,
        _PRIORITY_P2,
    ),
    Skill(
        SkillID.ARCHITECTURE_PATTERNS,
        "architecture-patterns",
        _CAT_ARCHITECTURE,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.BACKEND_ARCHITECT, "backend-architect", _CAT_ARCHITECTURE, _PRIORITY_P1
    ),
    Skill(
        SkillID.DOMAIN_DRIVEN_DESIGN,
        "domain-driven-design",
        _CAT_ARCHITECTURE,
        _PRIORITY_P1,
    ),
    Skill(SkillID.DOCUMENTATION, "documentation", _CAT_DOCUMENTATION, _PRIORITY_P1),
    Skill(
        SkillID.DOCUMENTATION_ADRS,
        "documentation-and-adrs",
        _CAT_DOCUMENTATION,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.OPEN_API_SPEC,
        "openapi-spec-generator",
        _CAT_DOCUMENTATION,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.CHANGELOG_GENERATOR,
        "changelog-generator",
        _CAT_DOCUMENTATION,
        _PRIORITY_P2,
    ),
    Skill(SkillID.README, "readme", _CAT_DOCUMENTATION, _PRIORITY_P2),
    Skill(SkillID.DOCX, "docx", _CAT_DOCUMENTS, _PRIORITY_P1),
    Skill(SkillID.XLSX, "xlsx", _CAT_DOCUMENTS, _PRIORITY_P1),
    Skill(SkillID.PPTX, "pptx", _CAT_DOCUMENTS, _PRIORITY_P1),
    Skill(SkillID.PDF, "pdf", _CAT_DOCUMENTS, _PRIORITY_P1),
    Skill(SkillID.PDF_OFFICIAL, "pdf-official", _CAT_DOCUMENTS, _PRIORITY_P1),
    Skill(SkillID._3D_WEB_EXPERIENCE, "3d-web-experience", _CAT_MEDIA, _PRIORITY_P2),
    Skill(
        SkillID.THREE_JS_FUNDAMENTALS, "threejs-fundamentals", _CAT_MEDIA, _PRIORITY_P2
    ),
    Skill(SkillID.THREE_JS_ANIMATION, "threejs-animation", _CAT_MEDIA, _PRIORITY_P2),
    Skill(SkillID.AI_STUDIO_IMAGE, "ai-studio-image", _CAT_MEDIA, _PRIORITY_P2),
    Skill(SkillID.AUDIO_TRANSCRIBER, "audio-transcriber", _CAT_MEDIA, _PRIORITY_P2),
    Skill(SkillID.DEMO_VIDEO, "demo-video", _CAT_MEDIA, _PRIORITY_P2),
    Skill(
        SkillID.AGILE_PRODUCT_OWNER, "agile-product-owner", _CAT_BUSINESS, _PRIORITY_P2
    ),
    Skill(
        SkillID.PRODUCT_MANAGER_TOOL,
        "product-manager-toolkit",
        _CAT_BUSINESS,
        _PRIORITY_P2,
    ),
    Skill(
        SkillID.PRODUCT_STRATEGIST, "product-strategist", _CAT_BUSINESS, _PRIORITY_P2
    ),
    Skill(SkillID.SCRUM_MASTER, "scrum-master", _CAT_BUSINESS, _PRIORITY_P2),
    Skill(SkillID.CONTENT_HUMANIZER, "content-humanizer", _CAT_WRITING, _PRIORITY_P1),
    Skill(SkillID.DEV_REL_CONTENT, "devrel-content", _CAT_WRITING, _PRIORITY_P2),
    Skill(SkillID.SCIENTIFIC_WRITING, "scientific-writing", _CAT_WRITING, _PRIORITY_P2),
    Skill(SkillID.POSTMORTEM_WRITING, "postmortem-writing", _CAT_WRITING, _PRIORITY_P2),
    Skill(SkillID.BROOKS_LINT, "brooks-lint", _CAT_QUALITY, _PRIORITY_P2),
    Skill(SkillID.CODE_REVIEWER, "code-reviewer", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.CAVEMAN, "caveman", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.UNSLOP, "unslop", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.UNSLOP_COMMIT, "unslop-commit", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.UNSLOP_FILE, "unslop-file", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.UNSLOP_REVIEW, "unslop-review", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.GRILL_ME, "grill-me", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.GRILLING, "grilling", _CAT_QUALITY, _PRIORITY_P2),
    Skill(SkillID.GRILL_WITH_DOCS, "grill-with-docs", _CAT_QUALITY, _PRIORITY_P2),
    Skill(SkillID.HANDOFF, "handoff", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.LAST30_DAYS, "last30days", _CAT_QUALITY, _PRIORITY_P2),
    Skill(SkillID.COMMIT, "commit", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.PR_WRITER, "pr-writer", _CAT_QUALITY, _PRIORITY_P1),
    Skill(SkillID.SKILL_OPTIMIZER, "skill-optimizer", _CAT_QUALITY, _PRIORITY_P2),
    Skill(SkillID.SUPERPOWERS_LAB, "superpowers-lab", _CAT_QUALITY, _PRIORITY_P2),
    Skill(SkillID.USING_SUPERPOWERS, "using-superpowers", _CAT_QUALITY, _PRIORITY_P2),
    Skill(
        SkillID.DATADOG_AUTOMATION,
        "datadog-automation",
        _CAT_OBSERVABILITY,
        _PRIORITY_P2,
    ),
    Skill(SkillID.DEBUGGING_CODE, "debugging-code", _CAT_QUALITY, _PRIORITY_P1),
    Skill(
        SkillID.DEBUGGING_STRATEGIES, "debugging-strategies", _CAT_QUALITY, _PRIORITY_P1
    ),
    Skill(SkillID.DEBUGGING_TOOLKIT, "debugging-toolkit", _CAT_QUALITY, _PRIORITY_P1),
    Skill(
        SkillID.DEBUGGING_RECOVERY,
        "debugging-and-error-recovery",
        _CAT_QUALITY,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.PERFORMANCE_ENGINEER, "performance-engineer", _CAT_QUALITY, _PRIORITY_P1
    ),
    Skill(
        SkillID.PERFORMANCE_OPTIM,
        "performance-optimization",
        _CAT_QUALITY,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.PERFORMANCE_OPTIMIZER,
        "performance-optimizer",
        _CAT_QUALITY,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.PERFORMANCE_PROFILER, "performance-profiler", _CAT_QUALITY, _PRIORITY_P2
    ),
    Skill(
        SkillID.PERFORMANCE_PROFILING,
        "performance-profiling",
        _CAT_QUALITY,
        _PRIORITY_P2,
    ),
    Skill(SkillID.MCP_BUILDER, "mcp-builder", _CAT_DEVOPS, _PRIORITY_P1),
    Skill(SkillID.MCP_TOOL_DEVELOPER, "mcp-tool-developer", _CAT_DEVOPS, _PRIORITY_P1),
    Skill(SkillID.MCP_BUILDER_MS, "mcp-builder-ms", _CAT_DEVOPS, _PRIORITY_P2),
    Skill(SkillID.N8N_AGENTS, "n8n-agents", _CAT_DEVOPS, _PRIORITY_P2),
    Skill(SkillID.N8N_CODE_JS, "n8n-code-javascript", _CAT_DEVOPS, _PRIORITY_P2),
    Skill(SkillID.N8N_CODE_PYTHON, "n8n-code-python", _CAT_DEVOPS, _PRIORITY_P2),
    Skill(SkillID.N8N_BINARY_DATA, "n8n-binary-and-data", _CAT_DEVOPS, _PRIORITY_P2),
    Skill(SkillID.N8N_CODE_TOOL, "n8n-code-tool", _CAT_DEVOPS, _PRIORITY_P2),
    Skill(SkillID.N8N_ERROR_HANDLING, "n8n-error-handling", _CAT_DEVOPS, _PRIORITY_P2),
    Skill(SkillID.NOTION_AUTOMATION, "notion-automation", _CAT_DEVOPS, _PRIORITY_P2),
    Skill(
        SkillID.NOTION_TEMPLATE, "notion-template-business", _CAT_DEVOPS, _PRIORITY_P2
    ),
    Skill(SkillID.FIGMA_AUTOMATION, "figma-automation", _CAT_DEVOPS, _PRIORITY_P2),
    Skill(
        SkillID.GITHUB_ACTIONS_DEBUGGER,
        "github-actions-debugger",
        _CAT_DEVOPS,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.GITHUB_ACTIONS_TEMPLATES,
        "github-actions-templates",
        _CAT_DEVOPS,
        _PRIORITY_P1,
    ),
    Skill(
        SkillID.GRAFANA_DASHBOARDS,
        "grafana-dashboards",
        _CAT_OBSERVABILITY,
        _PRIORITY_P2,
    ),
    Skill(SkillID.AGENT_MEMORY_MCP, "agent-memory-mcp", _CAT_AI, _PRIORITY_P2),
    Skill(SkillID.HELIUM_MCP, "helium-mcp", _CAT_AI, _PRIORITY_P2),
    Skill(SkillID.HF_MCP, "hf-mcp", _CAT_AI, _PRIORITY_P2),
    Skill(SkillID.MERCURY_MCP, "mercury-mcp", _CAT_AI, _PRIORITY_P2),
    Skill(SkillID.ENV_GUIDE, "environment-setup-guide", _CAT_DEVOPS, _PRIORITY_P1),
    Skill(
        SkillID.ENV_SECRETS_MANAGER, "env-secrets-manager", _CAT_SECURITY, _PRIORITY_P1
    ),
    Skill(SkillID.CODEX_PROFILES, "codex-profiles", _CAT_QUALITY, _PRIORITY_P2),
    Skill(SkillID.CODEX_REVIEW, "codex-review", _CAT_QUALITY, _PRIORITY_P2),
    Skill(SkillID.CODEX_SUBAGENT, "codex-subagent", _CAT_QUALITY, _PRIORITY_P2),
    Skill(
        SkillID.CODE_REVIEW_OPT, "code-review-optimization", _CAT_QUALITY, _PRIORITY_P2
    ),
]


def mvp_skills() -> list[Skill]:
    return list(_MVP_SKILLS)

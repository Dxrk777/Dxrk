# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AgentID(str, Enum):
    CLAUDE_CODE = "claude-code"
    OPENCODE = "opencode"
    KILOCODE = "kilocode"
    GEMINI_CLI = "gemini-cli"
    CURSOR = "cursor"
    VSCODE_COPILOT = "vscode-copilot"
    CODEX = "codex"
    ANTIGRAVITY = "antigravity"
    WINDSURF = "windsurf"
    KIMI = "kimi"
    QWEN_CODE = "qwen-code"
    KIRO_IDE = "kiro-ide"
    OPENCLAW = "openclaw"
    PI = "pi"


class ComponentID(str, Enum):
    DXRK_MEMORY = "DXRK_MEMORY"
    SDD = "sdd"
    SKILLS = "skills"
    CONTEXT7 = "context7"
    MEMPALACE = "mempalace"
    PERSONA = "persona"
    PERMISSIONS = "permissions"
    DXRK_GUARDIAN = "DXRK_GUARDIAN"
    THEME = "theme"
    CLAUDE_THEME = "claude-theme"
    OPENCODE_DXRK_LOGO = "opencode-dxrk-logo"


class UninstallMode(str, Enum):
    PARTIAL = "partial"
    FULL = "full"
    FULL_REMOVE = "full-remove"
    CLEAN_INSTALL = "clean-install"


class DxrkMemoryUninstallScope(str, Enum):
    GLOBAL = "global"
    PROJECT = "project"


class SkillID(str, Enum):
    SDD_INIT = "sdd-init"
    SDD_APPLY = "sdd-apply"
    SDD_VERIFY = "sdd-verify"
    SDD_EXPLORE = "sdd-explore"
    SDD_PROPOSE = "sdd-propose"
    SDD_SPEC = "sdd-spec"
    SDD_DESIGN = "sdd-design"
    SDD_TASKS = "sdd-tasks"
    SDD_ARCHIVE = "sdd-archive"
    SDD_ONBOARD = "sdd-onboard"
    GO_TESTING = "go-testing"
    SKILL_CREATOR = "skill-creator"
    JUDGMENT_DAY = "judgment-day"
    BRANCH_PR = "branch-pr"
    ISSUE_CREATION = "issue-creation"
    SKILL_REGISTRY = "skill-registry"
    CHAINED_PR = "chained-pr"
    COGNITIVE_DOC = "cognitive-doc-design"
    COMMENT_WRITER = "comment-writer"
    WORK_UNIT_COMMITS = "work-unit-commits"
    LLM_COUNCIL = "llm-council"
    PYTHON_PRO = "python-pro"
    PYTHON_PATTERNS = "python-patterns"
    ASYNC_PYTHON_PATTERNS = "async-python-patterns"
    PYTHON_FASTAPI = "python-fastapi-development"
    PYTHON_PACKAGING = "python-packaging"
    PYTHON_PERFORMANCE = "python-performance-optimization"
    PYTEST_SKILL = "pytest-skill"
    PYDANTIC_AI = "pydantic-ai"
    JAVA_SCRIPT_PRO = "javascript-pro"
    JAVA_SCRIPT_MASTERY = "javascript-mastery"
    JAVA_SCRIPT_DESIGN = "javascript-design-patterns"
    NODEJS_PRO = "nodejs-pro"
    TYPE_SCRIPT_PRO = "typescript-pro"
    NEXTJS_PRO = "nextjs-pro"
    RUST_PRO = "rust-pro"
    RUST_ASYNC = "rust-async-patterns"
    MEMORY_SAFETY_PATTERNS = "memory-safety-patterns"
    GOLANG_PRO = "golang-pro"
    GO_CONCURRENCY_PATTERNS = "go-concurrency-patterns"
    GO_IN_DEPTH = "go-in-depth"
    GO_PLAYWRIGHT = "go-playwright"
    GO_ROD_MASTER = "go-rod-master"
    GRPC_GOLANG = "grpc-golang"
    TEMPORAL_GOLANG_PRO = "temporal-golang-pro"
    JAVA_PRO = "java-pro"
    SPRINGBOOT_PRO = "springboot-pro"
    JAVA_PERFORMANCE_TUNING = "java-performance-tuning"
    CPP_PRO = "cpp-pro"
    CPP_LOW_LATENCY = "cpp-low-latency"
    SWIFT_PRO = "swift-pro"
    SWIFT_CONCURRENCY = "swift-concurrency-expert"
    SWIFTUI_EXPERT = "swiftui-expert"
    KOTLIN_PRO = "kotlin-pro"
    KOTLIN_MULTIPLATFORM = "kotlin-multiplatform"
    ANDROID_JETPACK_COMPOSE_EXPERT = "android-jetpack-compose-expert"
    RUBY_RAILS_PRO = "ruby-rails-pro"
    PHP_PRO = "php-pro"
    PHP_LARAVEL_PRO = "php-laravel-pro"
    REACT_BEST_PRACTICES = "react-best-practices"
    REACT_PATTERNS = "react-patterns"
    ANGULAR_PRO = "angular-pro"
    SVELTE_PRO = "svelte-pro"
    VUE_PRO = "vue-pro"
    TAILWIND_PRO = "tailwind-pro"
    CSS_PRO = "css-pro"
    HTML_PRO = "html-pro"
    FRONTEND_ARCH = "frontend-architecture"
    REACT_COMP_PERF = "react-component-performance"
    DOCKER_EXPERT = "docker-expert"
    KUBERNETES_ARCHITECT = "kubernetes-architect"
    TERRAFORM_PATTERNS = "terraform-patterns"
    AWS_ARCHITECT = "aws-architect"
    CLOUD_ARCHITECT = "cloud-architect"
    GITHUB_ACTIONS_ADVANCED = "github-actions-advanced"
    CI_CD_PIPELINE_BUILDER = "ci-cd-pipeline-builder"
    GITOPS_WORKFLOW = "gitops-workflow"
    ARGO_CD_PRO = "argocd-pro"
    HELM_CHART_BUILDER = "helm-chart-builder"
    AWS_LAMBDA_PRO = "aws-lambda-pro"
    PROMPT_ENGINEERING = "prompt-engineering-patterns"
    AGENT_DESIGNER = "agent-designer"
    MEMORY_SYSTEMS = "memory-systems"
    LLM_APP_PATTERNS = "llm-app-patterns"
    LLM_EVALUATION = "llm-evaluation"
    RAG_ARCHITECT = "rag-architect"
    RAG_ENGINEER = "rag-engineer"
    AI_ENGINEERING_TOOLKIT = "ai-engineering-toolkit"
    FINE_TUNING_PRO = "fine-tuning-pro"
    LANG_CHAIN_PRO = "langchain-pro"
    EMBEDDING_PRO = "embedding-pro"
    VECTOR_DB_PRO = "vector-db-pro"
    ML_OPS_PRO = "ml-ops-pro"
    COMPUTER_VISION_PRO = "computer-vision-pro"
    NLP_PRO = "nlp-pro"
    HUGGING_FACE_CLI = "hugging-face-cli"
    LANG_GRAPH = "langgraph"
    DATA_ENGINEER = "data-engineer"
    DATA_PIPELINE = "data-engineering-data-pipeline"
    POSTGRES_BEST_PRACTICES = "postgres-best-practices"
    REDIS_PRO = "redis-pro"
    MONGO_DB_PRO = "mongodb-pro"
    DATA_VISUALIZATION = "data-visualization"
    DB_QUERY = "db-query"
    MIGRATION = "migration"
    REACT_NATIVE = "react-native"
    ANDROID_DEV = "android-dev"
    FLUTTER_PRO = "flutter-pro"
    IOS_PRO = "ios-pro"
    MOBILE_TESTING = "mobile-app-testing"
    SECURITY_SAST = "security-scanning-security-sast"
    SECURITY_HARDENING = "security-scanning-security-hardening"
    SECURITY_DEPENDENCIES = "security-scanning-security-dependencies"
    API_SECURITY = "api-security-best-practices"
    CONTAINER_SECURITY = "container-security-hardening"
    CLOUD_SECURITY = "cloud-security"
    PENETRATION_TESTING = "penetration-testing"
    TDD_GUIDE = "tdd-guide"
    E2E_TESTING = "e2e-testing"
    K6_LOAD_TESTING = "k6-load-testing"
    TESTING_PATTERNS = "testing-patterns"
    TEST_AUTOMATOR = "test-automator"
    PLAYWRIGHT_PRO = "playwright-pro"
    CYPRESS_PRO = "cypress-pro"
    SOFTWARE_ARCHITECTURE = "software-architecture"
    MICROSERVICES_PATTERNS = "microservices-patterns"
    EVENT_SOURCING_ARCHITECT = "event-sourcing-architect"
    DDD_PRO = "ddd-pro"
    SAGA_ORCHESTRATION = "saga-orchestration"
    BASH_PRO = "bash-pro"
    BASH_SCRIPTING = "bash-scripting"
    POSIX_SHELL_PRO = "posix-shell-pro"
    AI_NATIVE_CLI = "ai-native-cli"
    JQ = "jq"
    API_DOCS = "api-docs"
    DOC_GENERATION = "documentation-generation"
    CHANGELOG_PRO = "changelog-pro"
    README_PRO = "readme-pro"
    IMAGE_GENERATION = "image-generation"
    VIDEO_EDITING = "video-editing"
    AUDIO_PROCESSING = "audio-processing"
    _3D_MODELING = "3d-modeling"
    ALGORITHMIC_ART = "algorithmic-art"
    PDF_GENERATION = "pdf-generation"
    WORD_DOCX = "word-docx"
    EXCEL_XLSX = "excel-xlsx"
    PPTX_DECK = "pptx-deck-creation"
    PRODUCT_MANAGEMENT = "product-management"
    AGILE_SCRUM = "agile-scrum"
    OKR_TRACKING = "okr-tracking"
    TECHNICAL_WRITING = "technical-writing"
    COPYWRITING = "copywriting"
    SEO_WRITING = "seo-writing"
    BLOG_WRITING = "blog-writing"
    CODE_REVIEW_CHECKLIST = "code-review-checklist"
    REFACTORING_PATTERNS = "refactoring-patterns"
    ERROR_HANDLING_PATTERNS = "error-handling-patterns"
    SYSTEMATIC_DEBUGGING = "systematic-debugging"
    CODE_SIMPLIFICATION = "code-simplification"
    OBSERVABILITY = "observability-and-instrumentation"
    INCIDENT_RESPONDER = "incident-responder"
    POSTMORTEM = "postmortem"
    CHAOS_ENGINEERING = "chaos-engineering"
    ACCESSIBILITY = "accessibility"
    ARCH_DECISION = "arch-decision"
    CI_CD = "ci-cd"
    CODE_REVIEW = "code-review"
    COMMIT_MESSAGE = "commit-message"
    DEBUGGING = "debugging"
    DEPENDENCY = "dependency"
    DOCKER_MGMT = "docker-mgmt"
    ENV_SETUP = "env-setup"
    ERROR_HANDLING = "error-handling"
    GIT_RELEASE = "git-release"
    LOGGING_PATTERNS = "logging-patterns"
    PERFORMANCE = "performance"
    PR_DESCRIPTION = "pr-description"
    REFACTORING_PR = "refactoring-pr"
    SECURITY_AUDIT = "security-audit"
    TEST_WRITER = "test-writer"
    DXRK_API_CONTENT = "dxrk-api-content"
    DXRK_BATCH = "dxrk-batch"
    DXRK_CLAUDE_API = "dxrk-claude-api"
    DXRK_CLAUDE_CHROME = "dxrk-claude-chrome"
    DXRK_DEBUG = "dxrk-debug"
    DXRK_DISCORD_AGENT = "dxrk-discord-agent"
    DXRK_DREAM = "dxrk-dream"
    DXRK_DUPLICATE_DETECT = "dxrk-duplicate-detection"
    DXRK_GHSA = "dxrk-ghsa-maintainer"
    DXRK_GITCRAWL = "dxrk-gitcrawl"
    DXRK_KEYBINDINGS = "dxrk-keybindings"
    DXRK_LOOP = "dxrk-loop"
    DXRK_LOREM_IPSUM = "dxrk-lorem-ipsum"
    DXRK_PARALLELS_E2E = "dxrk-parallels-e2e"
    DXRK_PARALLELS_SMOKE = "dxrk-parallels-smoke"
    DXRK_PRE_RELEASE = "dxrk-pre-release-testing"
    DXRK_PR_MAINTAINER = "dxrk-pr-maintainer"
    DXRK_QA_TESTING = "dxrk-qa-testing"
    DXRK_RELEASE = "dxrk-release-maintainer"
    DXRK_REMEMBER = "dxrk-remember"
    DXRK_SCHEDULE_AGENTS = "dxrk-schedule-agents"
    DXRK_SECRET_SCAN = "dxrk-secret-scanning"
    DXRK_SECURITY_TRIAGE = "dxrk-security-triage"
    DXRK_SIMPLIFY = "dxrk-simplify"
    DXRK_SKILL_GENERATOR = "dxrk-skill-generator"
    DXRK_SKILLIFY = "dxrk-skillify"
    DXRK_STUCK = "dxrk-stuck"
    DXRK_TESTBOX = "dxrk-testbox"
    DXRK_TESTING = "dxrk-testing"
    DXRK_TEST_MEMORY = "dxrk-test-memory"
    DXRK_TEST_OPTIMIZE = "dxrk-test-optimize"
    DXRK_TEST_PERFORMANCE = "dxrk-test-performance"
    DXRK_UPDATE_CONFIG = "dxrk-update-config"
    DXRK_VERIFY = "dxrk-verify"
    TYPE_SCRIPT_EXPERT = "typescript-expert"
    NODEJS_BACKEND = "nodejs-backend-patterns"
    NODEJS_BEST_PRACTICES = "nodejs-best-practices"
    TRPC_FULLSTACK = "trpc-fullstack"
    DRIZZLE_ORM = "drizzle-orm-expert"
    PRISMA_EXPERT = "prisma-expert"
    RUBY_PRO = "ruby-pro"
    PYTHON_TESTING = "python-testing-patterns"
    ANGULAR = "angular"
    ANGULAR_BEST_PRACTICES = "angular-best-practices"
    SVELTE_KIT = "sveltekit"
    TAILWIND_PATTERNS = "tailwind-patterns"
    REACT_STATE_MGMT = "react-state-management"
    REACT_COMPONENT_PERF2 = "react-component-performance-2"
    AWS_SERVERLESS_EDA = "aws-serverless-eda"
    AWS_PENETRATION = "aws-penetration-testing"
    AZURE_CLOUD = "azure-cloud-architect"
    DOCKER_DEVELOPMENT = "docker-development"
    DEPLOYMENT_PIPELINE = "deployment-pipeline-design"
    CI_CD_AND_AUTOMATION = "ci-cd-and-automation"
    HELM_CHART_BUILDER2 = "helm-chart-builder-2"
    KUBERNETES_DEPLOY = "kubernetes-deployment"
    KUBERNETES_OPERATOR = "kubernetes-operator"
    SPARK_OPTIMIZATION = "spark-optimization"
    SNOWFLAKE = "snowflake-development"
    AI_AGENTS_ARCHITECT = "ai-agents-architect"
    AGENT_PROTOCOL = "agent-protocol"
    AGENT_MEMORY_SYSTEMS = "agent-memory-systems"
    AI_SECURITY = "ai-security"
    RAG_IMPLEMENTATION = "rag-implementation"
    PROMPT_ENGINEER = "prompt-engineer"
    PROMPT_ENGINEERING2 = "prompt-engineering"
    HUGGING_FACE_TRAINER = "hugging-face-model-trainer"
    EMBEDDING_STRATEGIES = "embedding-strategies"
    LANG_CHAIN_ARCHITECT = "langchain-architecture"
    DATABASE_ARCHITECT = "database-architect"
    DATABASE_OPTIMIZER = "database-optimizer"
    SQL_DATABASE = "sql-database-assistant"
    POSTGRESQL = "postgresql"
    POSTGRES_OPTIMIZATION = "postgresql-optimization"
    SUPABASE = "supabase"
    SECURITY_AND_HARDENING = "security-and-hardening"
    SECURITY_AUDITOR = "security-auditor"
    SECURITY_PEN_TESTING = "security-pen-testing"
    SECURITY_GUIDANCE = "security-guidance"
    SECURITY_BLUEBOOK = "security-bluebook-builder"
    SECURITY_REQ_EXTRACT = "security-requirement-extraction"
    SECRETS_MANAGEMENT = "secrets-management"
    API_SECURITY_TESTING = "api-security-testing"
    CYPRESS_SKILL = "cypress-skill"
    PLAYWRIGHT_SKILL = "playwright-skill"
    PLAYWRIGHT_JAVA = "playwright-java"
    UNIT_TEST_GENERATE = "unit-testing-test-generate"
    TESTING_QA = "testing-qa"
    TDD_DRIVE = "test-driven-development"
    API_TEST_SUITE = "api-test-suite-builder"
    API_TEST_MOCK = "api-testing-observability-api-mock"
    ARCHITECTURE_PATTERNS = "architecture-patterns"
    BACKEND_ARCHITECT = "backend-architect"
    DOMAIN_DRIVEN_DESIGN = "domain-driven-design"
    DOCUMENTATION = "documentation"
    DOCUMENTATION_ADRS = "documentation-and-adrs"
    OPEN_API_SPEC = "openapi-spec-generator"
    CHANGELOG_GENERATOR = "changelog-generator"
    README = "readme"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    PDF = "pdf"
    PDF_OFFICIAL = "pdf-official"
    _3D_WEB_EXPERIENCE = "3d-web-experience"
    THREE_JS_FUNDAMENTALS = "threejs-fundamentals"
    THREE_JS_ANIMATION = "threejs-animation"
    AI_STUDIO_IMAGE = "ai-studio-image"
    AUDIO_TRANSCRIBER = "audio-transcriber"
    DEMO_VIDEO = "demo-video"
    AGILE_PRODUCT_OWNER = "agile-product-owner"
    PRODUCT_MANAGER_TOOL = "product-manager-toolkit"
    PRODUCT_STRATEGIST = "product-strategist"
    SCRUM_MASTER = "scrum-master"
    CONTENT_HUMANIZER = "content-humanizer"
    DEV_REL_CONTENT = "devrel-content"
    SCIENTIFIC_WRITING = "scientific-writing"
    POSTMORTEM_WRITING = "postmortem-writing"
    COPYWRITING_PRO = "copywriting-pro"
    BROOKS_LINT = "brooks-lint"
    CODE_REVIEWER = "code-reviewer"
    CAVEMAN = "caveman"
    UNSLOP = "unslop"
    UNSLOP_COMMIT = "unslop-commit"
    UNSLOP_FILE = "unslop-file"
    UNSLOP_REVIEW = "unslop-review"
    GRILL_ME = "grill-me"
    GRILLING = "grilling"
    GRILL_WITH_DOCS = "grill-with-docs"
    HANDOFF = "handoff"
    LAST30_DAYS = "last30days"
    COMMIT = "commit"
    PR_WRITER = "pr-writer"
    SKILL_OPTIMIZER = "skill-optimizer"
    SUPERPOWERS_LAB = "superpowers-lab"
    USING_SUPERPOWERS = "using-superpowers"
    DATADOG_AUTOMATION = "datadog-automation"
    DEBUGGING_CODE = "debugging-code"
    DEBUGGING_STRATEGIES = "debugging-strategies"
    DEBUGGING_TOOLKIT = "debugging-toolkit"
    DEBUGGING_RECOVERY = "debugging-and-error-recovery"
    PERFORMANCE_ENGINEER = "performance-engineer"
    PERFORMANCE_OPTIM = "performance-optimization"
    PERFORMANCE_OPTIMIZER = "performance-optimizer"
    PERFORMANCE_PROFILER = "performance-profiler"
    PERFORMANCE_PROFILING = "performance-profiling"
    MCP_BUILDER = "mcp-builder"
    MCP_BUILDER_MS = "mcp-builder-ms"
    MCP_TOOL_DEVELOPER = "mcp-tool-developer"
    N8N_AGENTS = "n8n-agents"
    N8N_BINARY_DATA = "n8n-binary-and-data"
    N8N_CODE_JS = "n8n-code-javascript"
    N8N_CODE_PYTHON = "n8n-code-python"
    N8N_CODE_TOOL = "n8n-code-tool"
    N8N_ERROR_HANDLING = "n8n-error-handling"
    NOTION_AUTOMATION = "notion-automation"
    NOTION_TEMPLATE = "notion-template-business"
    FIGMA_AUTOMATION = "figma-automation"
    GITHUB_ACTIONS_DEBUGGER = "github-actions-debugger"
    GITHUB_ACTIONS_TEMPLATES = "github-actions-templates"
    GRAFANA_DASHBOARDS = "grafana-dashboards"
    AGENT_MEMORY_MCP = "agent-memory-mcp"
    HELIUM_MCP = "helium-mcp"
    HF_MCP = "hf-mcp"
    MERCURY_MCP = "mercury-mcp"
    ENV_GUIDE = "environment-setup-guide"
    ENV_SECRETS_MANAGER = "env-secrets-manager"
    CODEX_PROFILES = "codex-profiles"
    CODEX_REVIEW = "codex-review"
    CODEX_SUBAGENT = "codex-subagent"
    CODE_REVIEW_OPT = "code-review-optimization"

class ClaudeModelAlias(str, Enum):
    OPUS = "opus"
    SONNET = "sonnet"
    HAIKU = "haiku"

    def valid(self) -> bool:
        return self in (
            ClaudeModelAlias.OPUS,
            ClaudeModelAlias.SONNET,
            ClaudeModelAlias.HAIKU,
        )


def claude_model_preset_balanced() -> dict[str, ClaudeModelAlias]:
    return {
        "orchestrator": ClaudeModelAlias.OPUS,
        "sdd-explore": ClaudeModelAlias.SONNET,
        "sdd-propose": ClaudeModelAlias.OPUS,
        "sdd-spec": ClaudeModelAlias.SONNET,
        "sdd-design": ClaudeModelAlias.OPUS,
        "sdd-tasks": ClaudeModelAlias.SONNET,
        "sdd-apply": ClaudeModelAlias.SONNET,
        "sdd-verify": ClaudeModelAlias.SONNET,
        "sdd-archive": ClaudeModelAlias.HAIKU,
        "default": ClaudeModelAlias.SONNET,
    }


def claude_model_preset_performance() -> dict[str, ClaudeModelAlias]:
    return {
        "orchestrator": ClaudeModelAlias.OPUS,
        "sdd-explore": ClaudeModelAlias.SONNET,
        "sdd-propose": ClaudeModelAlias.OPUS,
        "sdd-spec": ClaudeModelAlias.SONNET,
        "sdd-design": ClaudeModelAlias.OPUS,
        "sdd-tasks": ClaudeModelAlias.SONNET,
        "sdd-apply": ClaudeModelAlias.SONNET,
        "sdd-verify": ClaudeModelAlias.OPUS,
        "sdd-archive": ClaudeModelAlias.HAIKU,
        "default": ClaudeModelAlias.SONNET,
    }


def claude_model_preset_economy() -> dict[str, ClaudeModelAlias]:
    return {
        "orchestrator": ClaudeModelAlias.SONNET,
        "sdd-explore": ClaudeModelAlias.SONNET,
        "sdd-propose": ClaudeModelAlias.SONNET,
        "sdd-spec": ClaudeModelAlias.SONNET,
        "sdd-design": ClaudeModelAlias.SONNET,
        "sdd-tasks": ClaudeModelAlias.SONNET,
        "sdd-apply": ClaudeModelAlias.SONNET,
        "sdd-verify": ClaudeModelAlias.SONNET,
        "sdd-archive": ClaudeModelAlias.HAIKU,
        "default": ClaudeModelAlias.SONNET,
    }


class PersonaID(str, Enum):
    DXRK = "dxrk"
    NEUTRAL = "neutral"
    CUSTOM = "custom"


class SystemPromptStrategy(int, Enum):
    MARKDOWN_SECTIONS = 0
    FILE_REPLACE = 1
    APPEND_TO_FILE = 2
    INSTRUCTIONS_FILE = 3
    JINJA_MODULES = 4
    STEERING_FILE = 5


class MCPStrategy(int, Enum):
    SEPARATE_MCP_FILES = 0
    MERGE_INTO_SETTINGS = 1
    MCP_CONFIG_FILE = 2
    TOML_FILE = 3


class PresetID(str, Enum):
    FULL_DXRK = "full-dxrk"
    ECOSYSTEM_ONLY = "ecosystem-only"
    MINIMAL = "minimal"
    CUSTOM = "custom"


class SDDModeID(str, Enum):
    SINGLE = "single"
    MULTI = "multi"


class SDDProfileStrategyID(str, Enum):
    GENERATED_MULTI = "generated-multi"
    EXTERNAL_SINGLE_ACTIVE = "external-single-active"


class OpenCodeCommunityPluginID(str, Enum):
    SUB_AGENT_STATUSLINE = "sub-agent-statusline"
    SDD_ENGRAM_PLUGIN = "sdd-DXRK_MEMORY-plugin"


class SupportTier(str, Enum):
    FULL = "full"


class PlanStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunResult(str, Enum):
    SKIPPED = "skipped"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class ModelAssignment:
    provider_id: str = ""
    model_id: str = ""

    def full_id(self) -> str:
        return f"{self.provider_id}/{self.model_id}"


@dataclass
class Profile:
    name: str = ""
    orchestrator_model: ModelAssignment = field(default_factory=ModelAssignment)
    phase_assignments: dict[str, ModelAssignment] = field(default_factory=dict)


@dataclass
class Selection:
    agents: list[AgentID] = field(default_factory=list)
    components: list[ComponentID] = field(default_factory=list)
    skills: list[SkillID] = field(default_factory=list)
    persona: PersonaID = PersonaID.DXRK
    preset: PresetID = PresetID.FULL_DXRK
    sdd_mode: SDDModeID = SDDModeID.SINGLE
    sdd_profile_strategy: SDDProfileStrategyID = SDDProfileStrategyID.GENERATED_MULTI
    strict_tdd: bool = False
    model_assignments: dict[str, ModelAssignment] = field(default_factory=dict)
    claude_model_assignments: dict[str, str] = field(default_factory=dict)
    kiro_model_assignments: dict[str, str] = field(default_factory=dict)
    profiles: list[Profile] = field(default_factory=list)
    opencode_plugins: list[OpenCodeCommunityPluginID] = field(default_factory=list)

    def has_agent(self, agent_id: AgentID) -> bool:
        return agent_id in self.agents

    def has_component(self, component_id: ComponentID) -> bool:
        return component_id in self.components


@dataclass
class SyncOverrides:
    model_assignments: dict[str, ModelAssignment] | None = None
    claude_model_assignments: dict[str, str] | None = None
    kiro_model_assignments: dict[str, str] | None = None
    sdd_mode: SDDModeID | None = None
    sdd_profile_strategy: SDDProfileStrategyID | None = None
    strict_tdd: bool | None = None
    profiles: list[Profile] = field(default_factory=list)


@dataclass
class PlanStep:
    id: str = ""
    name: str = ""
    status: PlanStatus = PlanStatus.PENDING
    result: RunResult = RunResult.SKIPPED
    error: str = ""


@dataclass
class Plan:
    id: str = ""
    selection: Selection = field(default_factory=Selection)
    status: PlanStatus = PlanStatus.PENDING
    steps: list[PlanStep] = field(default_factory=list)


# Shorthand aliases
AgentClaudeCode = AgentID.CLAUDE_CODE
AgentOpenCode = AgentID.OPENCODE
AgentKilocode = AgentID.KILOCODE
AgentGeminiCLI = AgentID.GEMINI_CLI
AgentCursor = AgentID.CURSOR
AgentVSCodeCopilot = AgentID.VSCODE_COPILOT
AgentCodex = AgentID.CODEX
AgentAntigravity = AgentID.ANTIGRAVITY
AgentWindsurf = AgentID.WINDSURF
AgentKimi = AgentID.KIMI
AgentQwenCode = AgentID.QWEN_CODE
AgentKiroIDE = AgentID.KIRO_IDE
AgentOpenClaw = AgentID.OPENCLAW
AgentPi = AgentID.PI

AGENTS = [
    AgentClaudeCode,
    AgentOpenCode,
    AgentKilocode,
    AgentGeminiCLI,
    AgentCursor,
    AgentVSCodeCopilot,
    AgentCodex,
    AgentAntigravity,
    AgentWindsurf,
    AgentKimi,
    AgentQwenCode,
    AgentKiroIDE,
    AgentOpenClaw,
    AgentPi,
]

ComponentEngram = ComponentID.DXRK_MEMORY
ComponentSDD = ComponentID.SDD
ComponentSkills = ComponentID.SKILLS
ComponentContext7 = ComponentID.CONTEXT7
ComponentPersona = ComponentID.PERSONA
ComponentPermission = ComponentID.PERMISSIONS
ComponentGGA = ComponentID.DXRK_GUARDIAN
ComponentTheme = ComponentID.THEME
ComponentClaudeTheme = ComponentID.CLAUDE_THEME
ComponentOpenCodeDxrkLogo = ComponentID.OPENCODE_DXRK_LOGO

COMPONENTS = [
    ComponentEngram,
    ComponentSDD,
    ComponentSkills,
    ComponentContext7,
    ComponentPersona,
    ComponentPermission,
    ComponentGGA,
    ComponentTheme,
    ComponentClaudeTheme,
    ComponentOpenCodeDxrkLogo,
]

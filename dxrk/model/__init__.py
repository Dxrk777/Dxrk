# SPDX-License-Identifier: MIT
"""Agent model registry and selection types"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Dict, List, Optional

_logger = logging.getLogger("dxrk.model")

# ── Agents ────────────────────────────────────────────────────────────────

AgentID = str

AgentClaudeCode: AgentID = "claude-code"
AgentOpenCode: AgentID = "opencode"
AgentKilocode: AgentID = "kilocode"
AgentGeminiCLI: AgentID = "gemini-cli"
AgentCursor: AgentID = "cursor"
AgentVSCodeCopilot: AgentID = "vscode-copilot"
AgentCodex: AgentID = "codex"
AgentAntigravity: AgentID = "antigravity"
AgentWindsurf: AgentID = "windsurf"
AgentKimi: AgentID = "kimi"
AgentQwenCode: AgentID = "qwen-code"
AgentKiroIDE: AgentID = "kiro-ide"
AgentOpenClaw: AgentID = "openclaw"
AgentPi: AgentID = "pi"
AgentAider: AgentID = "aider"
AgentCline: AgentID = "cline"
AgentRooCode: AgentID = "roo-code"
AgentContinue: AgentID = "continue"
AgentJunie: AgentID = "junie"
AgentAmazonQ: AgentID = "amazon-q"
AgentOpenHands: AgentID = "openhands"
AgentZedAI: AgentID = "zed-ai"
AgentCopilot: AgentID = "github-copilot"
AgentDevin: AgentID = "devin"
AgentCody: AgentID = "cody"
AgentTabnine: AgentID = "tabnine"
AgentReplit: AgentID = "replit"
AgentVoid: AgentID = "void"
AgentHermes: AgentID = "hermes"
AgentAmp: AgentID = "amp"
AgentTrae: AgentID = "trae"
AgentConductor: AgentID = "conductor"
AgentRunCell: AgentID = "runcell"
AgentLoopoperators: AgentID = "looperators"
AgentPearAI: AgentID = "pearai"
AgentBolt: AgentID = "bolt"
AgentLovable: AgentID = "lovable"
AgentV0: AgentID = "v0"
AgentBlackbox: AgentID = "blackbox"
AgentQodo: AgentID = "qodo"
AgentJetBrains: AgentID = "jetbrains"
AgentZCode: AgentID = "zcode"

# ── Support tiers ─────────────────────────────────────────────────────────

SupportTier = str

# TierFull — the agent receives all ecosystem features: SDD orchestrator,
# skill files, MCP servers, system prompt, and sub-agent delegation.
TierFull: SupportTier = "full"

# ── Components ────────────────────────────────────────────────────────────

ComponentID = str

ComponentDxrkMemory: ComponentID = "dxrk-memory"
ComponentSDD: ComponentID = "sdd"
ComponentSkills: ComponentID = "skills"
ComponentContext7: ComponentID = "context7"
ComponentPersona: ComponentID = "persona"
ComponentPermission: ComponentID = "permissions"
ComponentDxrkGuardian: ComponentID = "dxrk-guardian"
ComponentTheme: ComponentID = "theme"
ComponentClaudeTheme: ComponentID = "claude-theme"
ComponentOpenCodeDxrkLogo: ComponentID = "opencode-dxrk-logo"
ComponentChecker: ComponentID = "checker"
ComponentInternalMCPServer: ComponentID = "internal-mcp-server"

# ── Uninstall modes ───────────────────────────────────────────────────────

UninstallMode = str

UninstallModePartial: UninstallMode = "partial"
UninstallModeFull: UninstallMode = "full"
UninstallModeFullRemove: UninstallMode = "full-remove"
UninstallModeCleanInstall: UninstallMode = "clean-install"

# ── Dxrk memory uninstall scope ───────────────────────────────────────────

DxrkMemoryUninstallScope = str

DxrkMemoryUninstallScopeGlobal: DxrkMemoryUninstallScope = "global"
DxrkMemoryUninstallScopeProject: DxrkMemoryUninstallScope = "project"

# ── Skills: SDD core ──────────────────────────────────────────────────────

SkillID = str

SkillSDDInit: SkillID = "sdd-init"
SkillSDDApply: SkillID = "sdd-apply"
SkillSDDVerify: SkillID = "sdd-verify"
SkillSDDExplore: SkillID = "sdd-explore"
SkillSDDPropose: SkillID = "sdd-propose"
SkillSDDSpec: SkillID = "sdd-spec"
SkillSDDDesign: SkillID = "sdd-design"
SkillSDDTasks: SkillID = "sdd-tasks"
SkillSDDArchive: SkillID = "sdd-archive"
SkillSDDOnboard: SkillID = "sdd-onboard"
SkillGoTesting: SkillID = "go-testing"
SkillCreator: SkillID = "skill-creator"
SkillJudgmentDay: SkillID = "judgment-day"
SkillBranchPR: SkillID = "branch-pr"
SkillIssueCreation: SkillID = "issue-creation"
SkillSkillRegistry: SkillID = "skill-registry"
SkillChainedPR: SkillID = "chained-pr"
SkillCognitiveDoc: SkillID = "cognitive-doc-design"
SkillCommentWriter: SkillID = "comment-writer"
SkillWorkUnitCommits: SkillID = "work-unit-commits"
SkillLLMCouncil: SkillID = "llm-council"

# ── Skills: programming languages ─────────────────────────────────────────

SkillPythonPro: SkillID = "python-pro"
SkillPythonPatterns: SkillID = "python-patterns"
SkillAsyncPythonPatterns: SkillID = "async-python-patterns"
SkillPythonFastAPI: SkillID = "python-fastapi-development"
SkillPythonPackaging: SkillID = "python-packaging"
SkillPythonPerformance: SkillID = "python-performance-optimization"
SkillPytestSkill: SkillID = "pytest-skill"
SkillPydanticAI: SkillID = "pydantic-ai"
SkillJavaScriptPro: SkillID = "javascript-pro"
SkillJavaScriptMastery: SkillID = "javascript-mastery"
SkillJavaScriptDesignPatterns: SkillID = "javascript-design-patterns"
SkillNodejsPro: SkillID = "nodejs-pro"
SkillTypeScriptPro: SkillID = "typescript-pro"
SkillNextjsPro: SkillID = "nextjs-pro"
SkillRustPro: SkillID = "rust-pro"
SkillRustAsyncPatterns: SkillID = "rust-async-patterns"
SkillMemorySafetyPatterns: SkillID = "memory-safety-patterns"
SkillGolangPro: SkillID = "golang-pro"
SkillGoConcurrencyPatterns: SkillID = "go-concurrency-patterns"
SkillGoInDepth: SkillID = "go-in-depth"
SkillGoPlaywright: SkillID = "go-playwright"
SkillGoRodMaster: SkillID = "go-rod-master"
SkillGrpcGolang: SkillID = "grpc-golang"
SkillTemporalGolangPro: SkillID = "temporal-golang-pro"
SkillJavaPro: SkillID = "java-pro"
SkillSpringbootPro: SkillID = "springboot-pro"
SkillJavaPerformanceTuning: SkillID = "java-performance-tuning"
SkillCppPro: SkillID = "cpp-pro"
SkillCppLowLatency: SkillID = "cpp-low-latency"
SkillSwiftPro: SkillID = "swift-pro"
SkillSwiftConcurrencyExpert: SkillID = "swift-concurrency-expert"
SkillSwiftUIExpert: SkillID = "swiftui-expert"
SkillKotlinPro: SkillID = "kotlin-pro"
SkillKotlinMultiplatform: SkillID = "kotlin-multiplatform"
SkillAndroidJetpackCompose: SkillID = "android-jetpack-compose-expert"
SkillRubyRailsPro: SkillID = "ruby-rails-pro"
SkillPhpPro: SkillID = "php-pro"
SkillPhpLaravelPro: SkillID = "php-laravel-pro"

# ── Skills: web / frontend ────────────────────────────────────────────────

SkillReactBestPractices: SkillID = "react-best-practices"
SkillReactPatterns: SkillID = "react-patterns"
SkillAngularPro: SkillID = "angular-pro"
SkillSveltePro: SkillID = "svelte-pro"
SkillVuePro: SkillID = "vue-pro"
SkillTailwindPro: SkillID = "tailwind-pro"
SkillCssPro: SkillID = "css-pro"
SkillHtmlPro: SkillID = "html-pro"
SkillFrontendArchitecture: SkillID = "frontend-architecture"
SkillReactComponentPerformance: SkillID = "react-component-performance"

# ── Skills: devops / cloud ────────────────────────────────────────────────

SkillDockerExpert: SkillID = "docker-expert"
SkillKubernetesArchitect: SkillID = "kubernetes-architect"
SkillTerraformPatterns: SkillID = "terraform-patterns"
SkillAwsArchitect: SkillID = "aws-architect"
SkillCloudArchitect: SkillID = "cloud-architect"
SkillGithubActionsAdvanced: SkillID = "github-actions-advanced"
SkillCiCdPipelineBuilder: SkillID = "ci-cd-pipeline-builder"
SkillGitopsWorkflow: SkillID = "gitops-workflow"
SkillArgocdPro: SkillID = "argocd-pro"
SkillHelmChartBuilder: SkillID = "helm-chart-builder"
SkillAwsLambdaPro: SkillID = "aws-lambda-pro"

# ── Skills: ai / ml ───────────────────────────────────────────────────────

SkillPromptEngineeringPatterns: SkillID = "prompt-engineering-patterns"
SkillAgentDesigner: SkillID = "agent-designer"
SkillMemorySystems: SkillID = "memory-systems"
SkillLlmAppPatterns: SkillID = "llm-app-patterns"
SkillLlmEvaluation: SkillID = "llm-evaluation"
SkillRagArchitect: SkillID = "rag-architect"
SkillRagEngineer: SkillID = "rag-engineer"
SkillAiEngineeringToolkit: SkillID = "ai-engineering-toolkit"
SkillFineTuningPro: SkillID = "fine-tuning-pro"
SkillLangchainPro: SkillID = "langchain-pro"
SkillEmbeddingPro: SkillID = "embedding-pro"
SkillVectorDbPro: SkillID = "vector-db-pro"
SkillMlOpsPro: SkillID = "ml-ops-pro"
SkillComputerVisionPro: SkillID = "computer-vision-pro"
SkillNlpPro: SkillID = "nlp-pro"
SkillHuggingFaceCli: SkillID = "hugging-face-cli"
SkillLanggraph: SkillID = "langgraph"

# ── Skills: data ──────────────────────────────────────────────────────────

SkillDataEngineer: SkillID = "data-engineer"
SkillDataEngineeringPipeline: SkillID = "data-engineering-data-pipeline"
SkillPostgresBestPractices: SkillID = "postgres-best-practices"
SkillRedisPro: SkillID = "redis-pro"
SkillMongodbPro: SkillID = "mongodb-pro"
SkillDataVisualization: SkillID = "data-visualization"
SkillDbQuery: SkillID = "db-query"
SkillMigration: SkillID = "migration"

# ── Skills: mobile ────────────────────────────────────────────────────────

SkillReactNative: SkillID = "react-native"
SkillAndroidDev: SkillID = "android-dev"
SkillFlutterPro: SkillID = "flutter-pro"
SkillIosPro: SkillID = "ios-pro"
SkillMobileAppTesting: SkillID = "mobile-app-testing"

# ── Skills: security ──────────────────────────────────────────────────────

SkillSecuritySast: SkillID = "security-scanning-security-sast"
SkillSecurityHardening: SkillID = "security-scanning-security-hardening"
SkillSecurityDependencies: SkillID = "security-scanning-security-dependencies"
SkillApiSecurityBestPractices: SkillID = "api-security-best-practices"
SkillContainerSecurity: SkillID = "container-security-hardening"
SkillCloudSecurity: SkillID = "cloud-security"
SkillPenetrationTesting: SkillID = "penetration-testing"

# ── Skills: testing ───────────────────────────────────────────────────────

SkillTddGuide: SkillID = "tdd-guide"
SkillE2eTesting: SkillID = "e2e-testing"
SkillK6LoadTesting: SkillID = "k6-load-testing"
SkillTestingPatterns: SkillID = "testing-patterns"
SkillTestAutomator: SkillID = "test-automator"
SkillPlaywrightPro: SkillID = "playwright-pro"
SkillCypressPro: SkillID = "cypress-pro"

# ── Skills: architecture ──────────────────────────────────────────────────

SkillSoftwareArchitecture: SkillID = "software-architecture"
SkillMicroservicesPatterns: SkillID = "microservices-patterns"
SkillEventSourcingArchitect: SkillID = "event-sourcing-architect"
SkillDddPro: SkillID = "ddd-pro"
SkillSagaOrchestration: SkillID = "saga-orchestration"

# ── Skills: cli / terminal ────────────────────────────────────────────────

SkillBashPro: SkillID = "bash-pro"
SkillBashScripting: SkillID = "bash-scripting"
SkillPosixShellPro: SkillID = "posix-shell-pro"
SkillAiNativeCli: SkillID = "ai-native-cli"
SkillJq: SkillID = "jq"

# ── Skills: documentation ─────────────────────────────────────────────────

SkillApiDocs: SkillID = "api-docs"
SkillDocumentationGeneration: SkillID = "documentation-generation"
SkillChangelogPro: SkillID = "changelog-pro"
SkillReadmePro: SkillID = "readme-pro"

# ── Skills: images / media ────────────────────────────────────────────────

SkillImageGeneration: SkillID = "image-generation"
SkillVideoEditing: SkillID = "video-editing"
SkillAudioProcessing: SkillID = "audio-processing"
Skill3dModeling: SkillID = "3d-modeling"
SkillAlgorithmicArt: SkillID = "algorithmic-art"

# ── Skills: pdf / documents ───────────────────────────────────────────────

SkillPdfGeneration: SkillID = "pdf-generation"
SkillWordDocx: SkillID = "word-docx"
SkillExcelXlsx: SkillID = "excel-xlsx"
SkillPptxDeckCreation: SkillID = "pptx-deck-creation"

# ── Skills: business ──────────────────────────────────────────────────────

SkillProductManagement: SkillID = "product-management"
SkillAgileScrum: SkillID = "agile-scrum"
SkillOkrTracking: SkillID = "okr-tracking"

# ── Skills: writing ───────────────────────────────────────────────────────

SkillTechnicalWriting: SkillID = "technical-writing"
SkillCopywriting: SkillID = "copywriting"
SkillSeoWriting: SkillID = "seo-writing"
SkillBlogWriting: SkillID = "blog-writing"

# ── Skills: code quality ──────────────────────────────────────────────────

SkillCodeReviewChecklist: SkillID = "code-review-checklist"
SkillRefactoringPatterns: SkillID = "refactoring-patterns"
SkillErrorHandlingPatterns: SkillID = "error-handling-patterns"
SkillSystematicDebugging: SkillID = "systematic-debugging"
SkillCodeSimplification: SkillID = "code-simplification"

# ── Skills: observability ─────────────────────────────────────────────────

SkillObservability: SkillID = "observability-and-instrumentation"
SkillIncidentResponder: SkillID = "incident-responder"
SkillPostmortem: SkillID = "postmortem"
SkillChaosEngineering: SkillID = "chaos-engineering"

# ── Skills: workflow extras ───────────────────────────────────────────────

SkillAccessibility: SkillID = "accessibility"
SkillArchDecision: SkillID = "arch-decision"
SkillCiCd: SkillID = "ci-cd"
SkillCodeReview: SkillID = "code-review"
SkillCommitMessage: SkillID = "commit-message"
SkillDebugging: SkillID = "debugging"
SkillDependency: SkillID = "dependency"
SkillDockerMgmt: SkillID = "docker-mgmt"
SkillEnvSetup: SkillID = "env-setup"
SkillErrorHandling: SkillID = "error-handling"
SkillGitRelease: SkillID = "git-release"
SkillLoggingPatterns: SkillID = "logging-patterns"
SkillPerformance: SkillID = "performance"
SkillPrDescription: SkillID = "pr-description"
SkillRefactoringPr: SkillID = "refactoring-pr"
SkillSecurityAudit: SkillID = "security-audit"
SkillTestWriter: SkillID = "test-writer"

# ── Skills: dxrk-specific ─────────────────────────────────────────────────

SkillDxrkApiContent: SkillID = "dxrk-api-content"
SkillDxrkBatch: SkillID = "dxrk-batch"
SkillDxrkClaudeApi: SkillID = "dxrk-claude-api"
SkillDxrkClaudeChrome: SkillID = "dxrk-claude-chrome"
SkillDxrkDebug: SkillID = "dxrk-debug"
SkillDxrkDiscordAgent: SkillID = "dxrk-discord-agent"
SkillDxrkDream: SkillID = "dxrk-dream"
SkillDxrkDuplicateDetection: SkillID = "dxrk-duplicate-detection"
SkillDxrkGhsaMaintainer: SkillID = "dxrk-ghsa-maintainer"
SkillDxrkGitcrawl: SkillID = "dxrk-gitcrawl"
SkillDxrkKeybindings: SkillID = "dxrk-keybindings"
SkillDxrkLoop: SkillID = "dxrk-loop"
SkillDxrkLoremIpsum: SkillID = "dxrk-lorem-ipsum"
SkillDxrkParallelsE2e: SkillID = "dxrk-parallels-e2e"
SkillDxrkParallelsSmoke: SkillID = "dxrk-parallels-smoke"
SkillDxrkPreReleaseTesting: SkillID = "dxrk-pre-release-testing"
SkillDxrkPrMaintainer: SkillID = "dxrk-pr-maintainer"
SkillDxrkQaTesting: SkillID = "dxrk-qa-testing"
SkillDxrkReleaseMaintainer: SkillID = "dxrk-release-maintainer"
SkillDxrkRemember: SkillID = "dxrk-remember"
SkillDxrkScheduleAgents: SkillID = "dxrk-schedule-agents"
SkillDxrkSecretScanning: SkillID = "dxrk-secret-scanning"
SkillDxrkSecurityTriage: SkillID = "dxrk-security-triage"
SkillDxrkSimplify: SkillID = "dxrk-simplify"
SkillDxrkSkillGenerator: SkillID = "dxrk-skill-generator"
SkillDxrkSkillify: SkillID = "dxrk-skillify"
SkillDxrkStuck: SkillID = "dxrk-stuck"
SkillDxrkTestbox: SkillID = "dxrk-testbox"
SkillDxrkTesting: SkillID = "dxrk-testing"
SkillDxrkTestMemory: SkillID = "dxrk-test-memory"
SkillDxrkTestOptimize: SkillID = "dxrk-test-optimize"
SkillDxrkTestPerformance: SkillID = "dxrk-test-performance"
SkillDxrkUpdateConfig: SkillID = "dxrk-update-config"
SkillDxrkVerify: SkillID = "dxrk-verify"

# ── Skills: additional languages ──────────────────────────────────────────

SkillTypeScriptExpert: SkillID = "typescript-expert"
SkillNodejsBackendPatterns: SkillID = "nodejs-backend-patterns"
SkillNodejsBestPractices: SkillID = "nodejs-best-practices"
SkillTrpcFullstack: SkillID = "trpc-fullstack"
SkillDrizzleOrmExpert: SkillID = "drizzle-orm-expert"
SkillPrismaExpert: SkillID = "prisma-expert"
SkillRubyPro: SkillID = "ruby-pro"
SkillPythonTestingPatterns: SkillID = "python-testing-patterns"

# ── Skills: additional web ────────────────────────────────────────────────

SkillAngular: SkillID = "angular"
SkillAngularBestPractices: SkillID = "angular-best-practices"
SkillSveltekit: SkillID = "sveltekit"
SkillTailwindPatterns: SkillID = "tailwind-patterns"
SkillReactStateManagement: SkillID = "react-state-management"
SkillReactComponentPerformance2: SkillID = "react-component-performance-2"

# ── Skills: additional devops / cloud ─────────────────────────────────────

SkillAwsServerlessEda: SkillID = "aws-serverless-eda"
SkillAwsPenetrationTesting: SkillID = "aws-penetration-testing"
SkillAzureCloudArchitect: SkillID = "azure-cloud-architect"
SkillDockerDevelopment: SkillID = "docker-development"
SkillDeploymentPipelineDesign: SkillID = "deployment-pipeline-design"
SkillCiCdAndAutomation: SkillID = "ci-cd-and-automation"
SkillHelmChartBuilder2: SkillID = "helm-chart-builder-2"
SkillKubernetesDeployment: SkillID = "kubernetes-deployment"
SkillKubernetesOperator: SkillID = "kubernetes-operator"
SkillSparkOptimization: SkillID = "spark-optimization"
SkillSnowflakeDevelopment: SkillID = "snowflake-development"

# ── Skills: additional ai / ml ────────────────────────────────────────────

SkillAiAgentsArchitect: SkillID = "ai-agents-architect"
SkillAgentProtocol: SkillID = "agent-protocol"
SkillAgentMemorySystems: SkillID = "agent-memory-systems"
SkillAiSecurity: SkillID = "ai-security"
SkillRagImplementation: SkillID = "rag-implementation"
SkillPromptEngineer: SkillID = "prompt-engineer"
SkillPromptEngineering: SkillID = "prompt-engineering"
SkillHuggingFaceModelTrainer: SkillID = "hugging-face-model-trainer"
SkillEmbeddingStrategies: SkillID = "embedding-strategies"
SkillLangchainArchitecture: SkillID = "langchain-architecture"

# ── Skills: additional data ───────────────────────────────────────────────

SkillDatabaseArchitect: SkillID = "database-architect"
SkillDatabaseOptimizer: SkillID = "database-optimizer"
SkillSqlDatabaseAssistant: SkillID = "sql-database-assistant"
SkillPostgresql: SkillID = "postgresql"
SkillPostgresqlOptimization: SkillID = "postgresql-optimization"
SkillSupabase: SkillID = "supabase"

# ── Skills: additional security ───────────────────────────────────────────

SkillSecurityAndHardening: SkillID = "security-and-hardening"
SkillSecurityAuditor: SkillID = "security-auditor"
SkillSecurityPenTesting: SkillID = "security-pen-testing"
SkillSecurityGuidance: SkillID = "security-guidance"
SkillSecurityBluebookBuilder: SkillID = "security-bluebook-builder"
SkillSecurityRequirementExtraction: SkillID = "security-requirement-extraction"
SkillSecretsManagement: SkillID = "secrets-management"
SkillApiSecurityTesting: SkillID = "api-security-testing"

# ── Skills: additional testing ────────────────────────────────────────────

SkillCypressSkill: SkillID = "cypress-skill"
SkillPlaywrightSkill: SkillID = "playwright-skill"
SkillPlaywrightJava: SkillID = "playwright-java"
SkillUnitTestingTestGenerate: SkillID = "unit-testing-test-generate"
SkillTestingQa: SkillID = "testing-qa"
SkillTestDrivenDevelopment: SkillID = "test-driven-development"
SkillApiTestSuiteBuilder: SkillID = "api-test-suite-builder"
SkillApiTestingObservabilityApiMock: SkillID = "api-testing-observability-api-mock"

# ── Skills: additional architecture ───────────────────────────────────────

SkillArchitecturePatterns: SkillID = "architecture-patterns"
SkillBackendArchitect: SkillID = "backend-architect"
SkillDomainDrivenDesign: SkillID = "domain-driven-design"

# ── Skills: additional documentation ──────────────────────────────────────

SkillDocumentation: SkillID = "documentation"
SkillDocumentationAndAdrs: SkillID = "documentation-and-adrs"
SkillOpenapiSpecGenerator: SkillID = "openapi-spec-generator"
SkillChangelogGenerator: SkillID = "changelog-generator"
SkillReadme: SkillID = "readme"
SkillDocx: SkillID = "docx"
SkillXlsx: SkillID = "xlsx"
SkillPptx: SkillID = "pptx"
SkillPdf: SkillID = "pdf"
SkillPdfOfficial: SkillID = "pdf-official"

# ── Skills: additional media ──────────────────────────────────────────────

Skill3dWebExperience: SkillID = "3d-web-experience"
SkillThreejsFundamentals: SkillID = "threejs-fundamentals"
SkillThreejsAnimation: SkillID = "threejs-animation"
SkillAiStudioImage: SkillID = "ai-studio-image"
SkillAudioTranscriber: SkillID = "audio-transcriber"
SkillDemoVideo: SkillID = "demo-video"

# ── Skills: additional business / writing ─────────────────────────────────

SkillAgileProductOwner: SkillID = "agile-product-owner"
SkillProductManagerToolkit: SkillID = "product-manager-toolkit"
SkillProductStrategist: SkillID = "product-strategist"
SkillScrumMaster: SkillID = "scrum-master"
SkillContentHumanizer: SkillID = "content-humanizer"
SkillDevrelContent: SkillID = "devrel-content"
SkillScientificWriting: SkillID = "scientific-writing"
SkillPostmortemWriting: SkillID = "postmortem-writing"
SkillCopywritingPro: SkillID = "copywriting-pro"

# ── Skills: additional code quality ───────────────────────────────────────

SkillBrooksLint: SkillID = "brooks-lint"
SkillCodeReviewer: SkillID = "code-reviewer"
SkillCaveman: SkillID = "caveman"
SkillUnslop: SkillID = "unslop"
SkillUnslopCommit: SkillID = "unslop-commit"
SkillUnslopFile: SkillID = "unslop-file"
SkillUnslopReview: SkillID = "unslop-review"
SkillGrillMe: SkillID = "grill-me"
SkillGrilling: SkillID = "grilling"
SkillGrillWithDocs: SkillID = "grill-with-docs"
SkillHandoff: SkillID = "handoff"
SkillLast30Days: SkillID = "last30days"
SkillCommit: SkillID = "commit"
SkillPrWriter: SkillID = "pr-writer"
SkillSkillOptimizer: SkillID = "skill-optimizer"
SkillSuperpowersLab: SkillID = "superpowers-lab"
SkillUsingSuperpowers: SkillID = "using-superpowers"

# ── Skills: additional observability / debugging ──────────────────────────

SkillDatadogAutomation: SkillID = "datadog-automation"
SkillDebuggingCode: SkillID = "debugging-code"
SkillDebuggingStrategies: SkillID = "debugging-strategies"
SkillDebuggingToolkit: SkillID = "debugging-toolkit"
SkillDebuggingAndErrorRecovery: SkillID = "debugging-and-error-recovery"
SkillPerformanceEngineer: SkillID = "performance-engineer"
SkillPerformanceOptimization: SkillID = "performance-optimization"
SkillPerformanceOptimizer: SkillID = "performance-optimizer"
SkillPerformanceProfiler: SkillID = "performance-profiler"
SkillPerformanceProfiling: SkillID = "performance-profiling"

# ── Skills: mcp / n8n / notion / figma ────────────────────────────────────

SkillMcpBuilder: SkillID = "mcp-builder"
SkillMcpBuilderMs: SkillID = "mcp-builder-ms"
SkillMcpToolDeveloper: SkillID = "mcp-tool-developer"
SkillN8nAgents: SkillID = "n8n-agents"
SkillN8nBinaryAndData: SkillID = "n8n-binary-and-data"
SkillN8nCodeJavascript: SkillID = "n8n-code-javascript"
SkillN8nCodePython: SkillID = "n8n-code-python"
SkillN8nCodeTool: SkillID = "n8n-code-tool"
SkillN8nErrorHandling: SkillID = "n8n-error-handling"
SkillNotionAutomation: SkillID = "notion-automation"
SkillNotionTemplateBusiness: SkillID = "notion-template-business"
SkillFigmaAutomation: SkillID = "figma-automation"
SkillGithubActionsDebugger: SkillID = "github-actions-debugger"
SkillGithubActionsTemplates: SkillID = "github-actions-templates"
SkillGrafanaDashboards: SkillID = "grafana-dashboards"
SkillAgentMemoryMcp: SkillID = "agent-memory-mcp"
SkillHeliumMcp: SkillID = "helium-mcp"
SkillHfMcp: SkillID = "hf-mcp"
SkillMercuryMcp: SkillID = "mercury-mcp"

# ── Skills: environment / dx ──────────────────────────────────────────────

SkillEnvironmentSetupGuide: SkillID = "environment-setup-guide"
SkillEnvSecretsManager: SkillID = "env-secrets-manager"
SkillCodexProfiles: SkillID = "codex-profiles"
SkillCodexReview: SkillID = "codex-review"
SkillCodexSubagent: SkillID = "codex-subagent"
SkillCodeReviewOptimization: SkillID = "code-review-optimization"

# ── Personas ──────────────────────────────────────────────────────────────

PersonaID = str

PersonaDxrk: PersonaID = "dxrk"
PersonaNeutral: PersonaID = "neutral"
PersonaCustom: PersonaID = "custom"

# ── System prompt strategies ──────────────────────────────────────────────


class SystemPromptStrategy(IntEnum):
    # Markdown sections with <!-- dxrk:ID --> markers (Claude Code CLAUDE.md).
    MARKDOWN_SECTIONS = 0
    # OpenCode AGENTS.md full-file replace.
    FILE_REPLACE = 1
    APPEND_TO_FILE = 2
    # .instructions.md sidecar file.
    INSTRUCTIONS_FILE = 3
    # Jinja modules (Kimi KIMI.md).
    JINJA_MODULES = 4
    # Kiro steering file, always included via frontmatter.
    STEERING_FILE = 5


StrategyMarkdownSections = SystemPromptStrategy.MARKDOWN_SECTIONS
StrategyFileReplace = SystemPromptStrategy.FILE_REPLACE
StrategyAppendToFile = SystemPromptStrategy.APPEND_TO_FILE
StrategyInstructionsFile = SystemPromptStrategy.INSTRUCTIONS_FILE
StrategyJinjaModules = SystemPromptStrategy.JINJA_MODULES
StrategySteeringFile = SystemPromptStrategy.STEERING_FILE

# ── MCP strategies ────────────────────────────────────────────────────────


class MCPStrategy(IntEnum):
    # Separate file per MCP server (~/.claude/mcp/context7.json).
    SEPARATE_MCP_FILES = 0
    # Merge into settings (~/.config/opencode/opencode.json, Gemini CLI).
    MERGE_INTO_SETTINGS = 1
    # MCP config file (~/.cursor/mcp.json).
    MCP_CONFIG_FILE = 2
    # TOML file (~/.codex/config.toml).
    TOML_FILE = 3


StrategySeparateMCPFiles = MCPStrategy.SEPARATE_MCP_FILES
StrategyMergeIntoSettings = MCPStrategy.MERGE_INTO_SETTINGS
StrategyMCPConfigFile = MCPStrategy.MCP_CONFIG_FILE
StrategyTOMLFile = MCPStrategy.TOML_FILE

# ── Presets ───────────────────────────────────────────────────────────────

PresetID = str

PresetFullDxrk: PresetID = "full-dxrk"
PresetEcosystemOnly: PresetID = "ecosystem-only"
PresetMinimal: PresetID = "minimal"
PresetCustom: PresetID = "custom"

# ── SDD modes and profile strategies ──────────────────────────────────────

SDDModeID = str

SDDModeSingle: SDDModeID = "single"
SDDModeMulti: SDDModeID = "multi"

SDDProfileStrategyID = str

# Generated-multi is the default and backward-compatible strategy.
SDDProfileStrategyGeneratedMulti: SDDProfileStrategyID = "generated-multi"
SDDProfileStrategyExternalSingleActive: SDDProfileStrategyID = "external-single-active"

# ── OpenCode community plugins ────────────────────────────────────────────

OpenCodeCommunityPluginID = str

OpenCodePluginSubAgentStatusline: OpenCodeCommunityPluginID = "sub-agent-statusline"
OpenCodePluginSDDDxrkMemoryManage: OpenCodeCommunityPluginID = "sdd-dxrk-memory-plugin"
OpenCodePluginDxrkLogo: OpenCodeCommunityPluginID = "dxrk-logo"

# ── Claude model aliases ──────────────────────────────────────────────────


class ClaudeModelAlias(StrEnum):
    """Semantic model alias used to assign models to SDD phases."""

    OPUS = "opus"
    SONNET = "sonnet"
    HAIKU = "haiku"

    def __str__(self) -> str:
        return f"{self.__class__.__name__}.{self.name}"

    def valid(self) -> bool:
        return self in (
            ClaudeModelAlias.OPUS,
            ClaudeModelAlias.SONNET,
            ClaudeModelAlias.HAIKU,
        )


ClaudeModelOpus: ClaudeModelAlias = ClaudeModelAlias.OPUS
ClaudeModelSonnet: ClaudeModelAlias = ClaudeModelAlias.SONNET
ClaudeModelHaiku: ClaudeModelAlias = ClaudeModelAlias.HAIKU

claude_model_default_key = "default"

_CLAUDE_MODEL_KEYS = (
    SkillSDDExplore,
    SkillSDDPropose,
    SkillSDDSpec,
    SkillSDDDesign,
    SkillSDDTasks,
    SkillSDDApply,
    SkillSDDVerify,
    SkillSDDArchive,
    claude_model_default_key,
)


def claude_model_preset_balanced() -> dict[str, ClaudeModelAlias]:
    return {
        SkillSDDExplore: ClaudeModelSonnet,
        SkillSDDPropose: ClaudeModelOpus,
        SkillSDDSpec: ClaudeModelSonnet,
        SkillSDDDesign: ClaudeModelOpus,
        SkillSDDTasks: ClaudeModelSonnet,
        SkillSDDApply: ClaudeModelSonnet,
        SkillSDDVerify: ClaudeModelSonnet,
        SkillSDDArchive: ClaudeModelHaiku,
        claude_model_default_key: ClaudeModelSonnet,
    }


def claude_model_preset_performance() -> dict[str, ClaudeModelAlias]:
    return {
        SkillSDDExplore: ClaudeModelSonnet,
        SkillSDDPropose: ClaudeModelOpus,
        SkillSDDSpec: ClaudeModelSonnet,
        SkillSDDDesign: ClaudeModelOpus,
        SkillSDDTasks: ClaudeModelSonnet,
        SkillSDDApply: ClaudeModelSonnet,
        SkillSDDVerify: ClaudeModelOpus,
        SkillSDDArchive: ClaudeModelHaiku,
        claude_model_default_key: ClaudeModelSonnet,
    }


def claude_model_preset_economy() -> dict[str, ClaudeModelAlias]:
    return {
        SkillSDDExplore: ClaudeModelSonnet,
        SkillSDDPropose: ClaudeModelSonnet,
        SkillSDDSpec: ClaudeModelSonnet,
        SkillSDDDesign: ClaudeModelSonnet,
        SkillSDDTasks: ClaudeModelSonnet,
        SkillSDDApply: ClaudeModelSonnet,
        SkillSDDVerify: ClaudeModelSonnet,
        SkillSDDArchive: ClaudeModelHaiku,
        claude_model_default_key: ClaudeModelSonnet,
    }


def kiro_model_id(alias: ClaudeModelAlias) -> str:
    """Map a Claude alias to the Kiro model key (no provider prefix)."""
    if alias == ClaudeModelOpus:
        return "claude-opus-4.6"
    if alias == ClaudeModelHaiku:
        return "claude-haiku-4.5"
    return "claude-sonnet-4.6"


# ── Model assignment ──────────────────────────────────────────────────────


@dataclass
class ModelAssignment:
    """A concrete provider/model pairing used by an agent or sub-agent."""

    ProviderID: str
    ModelID: str
    # Empty means the provider default; otherwise low|medium|high.
    Effort: str = ""

    def full_id(self) -> str:
        return f"{self.ProviderID}/{self.ModelID}"


@dataclass
class Profile:
    """A named SDD orchestrator profile with optional per-phase assignments."""

    Name: str
    OrchestratorModel: ModelAssignment
    PhaseAssignments: dict[str, ModelAssignment] = field(default_factory=dict)


@dataclass
class Selection:
    """The full set of agents, components, skills and model assignments for an install."""

    Agents: list[AgentID]
    Components: list[ComponentID]
    Skills: list[SkillID]
    Persona: PersonaID
    Preset: PresetID
    SDDMode: SDDModeID
    SDDProfileStrategy: SDDProfileStrategyID
    StrictTDD: bool = False
    ModelAssignments: dict[str, ModelAssignment] = field(default_factory=dict)
    ClaudeModelAssignments: dict[str, ClaudeModelAlias] = field(default_factory=dict)
    KiroModelAssignments: dict[str, ClaudeModelAlias] = field(default_factory=dict)
    Profiles: list[Profile] = field(default_factory=list)
    OpenCodePlugins: list[OpenCodeCommunityPluginID] = field(default_factory=list)

    def has_agent(self, agent: AgentID) -> bool:
        for candidate in self.Agents:
            if candidate == agent:
                return True
        return False

    def has_component(self, component: ComponentID) -> bool:
        for candidate in self.Components:
            if candidate == component:
                return True
        return False


@dataclass
class SyncOverrides:
    """Runtime overrides applied during a TUI sync; None/empty mean "keep defaults"."""

    TargetAgents: list[AgentID] = field(default_factory=list)
    ModelAssignments: dict[str, ModelAssignment] | None = None
    ClaudeModelAssignments: dict[str, ClaudeModelAlias] | None = None
    KiroModelAssignments: dict[str, ClaudeModelAlias] | None = None
    SDDMode: SDDModeID = ""
    SDDProfileStrategy: SDDProfileStrategyID = ""
    StrictTDD: bool | None = None
    Profiles: list[Profile] = field(default_factory=list)


PlanStatusPending: str = "pending"
PlanStatusRunning: str = "running"
PlanStatusSucceeded: str = "succeeded"
PlanStatusFailed: str = "failed"

RunResultSkipped: str = "skipped"
RunResultSuccess: str = "success"
RunResultFailed: str = "failed"


@dataclass
class PlanStep:
    """A single step inside an install plan."""

    ID: str
    Name: str
    Status: str
    Result: str
    Error: str = ""


@dataclass
class Plan:
    """An ordered install plan made of selection plus steps."""

    ID: str
    Selection: Selection
    Status: str
    Steps: list[PlanStep] = field(default_factory=list)

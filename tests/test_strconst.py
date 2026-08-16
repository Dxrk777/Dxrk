
import dxrk.strconst as sc

EXPECTED = {
    "StrAbsolutePathToTheSourceFile": "Absolute path to the source file",
    "StrActive": "active",
    "StrArray": "array",
    "StrArticle": "article",
    "StrAssignedTo": "assigned_to",
    "StrAssistant": "assistant",
    "StrCancelled": "cancelled",
    "StrClaude": "claude",
    "StrClaudeSonnet420250514": "claude-sonnet-4-20250514",
    "StrClientId": "client_id",
    "StrCodeVerifier": "code_verifier",
    "StrCompleted": "completed",
    "StrContent": "content",
    "StrConversation": "conversation",
    "StrCount": "count",
    "StrCreatedAt": "created_at",
    "StrCritical": "critical",
    "StrDeepgram": "deepgram",
    "StrDescription": "description",
    "StrEfficiency": "efficiency",
    "StrEnabled": "enabled",
    "StrEndChar": "end_char",
    "StrEnvironmentId": "environment_id",
    "StrError": "error",
    "StrExecute": "Execute",
    "StrFailed": "failed",
    "StrFilePath": "file_path",
    "StrFiles": "files",
    "StrFormat": "format",
    "StrGrantType": "grant_type",
    "StrInteger": "integer",
    "StrItems": "items",
    "StrJavascript": "javascript",
    "StrListfiles": "ListFiles",
    "StrLocal": "local",
    "StrMarkdown": "markdown",
    "StrMedium": "MEDIUM",
    "StrMedium2": "medium",
    "StrMinimum": "minimum",
    "StrNormal": "normal",
    "StrObject": "object",
    "StrOpenai": "openai",
    "StrPattern": "pattern",
    "StrPdf": "%PDF-",
    "StrPending": "pending",
    "StrPriority": "priority",
    "StrProgress": "progress",
    "StrProject": "project",
    "StrProperties": "properties",
    "StrQuery": "query",
    "StrRedirectUri": "redirect_uri",
    "StrRefreshToken": "refresh_token",
    "StrRequired": "required",
    "StrResult": "result",
    "StrRunning": "running",
    "StrScript": "script",
    "StrSizeBytes": "size_bytes",
    "StrStartChar": "start_char",
    "StrStatus": "status",
    "StrStatusCode": "status_code",
    "StrStderr": "stderr",
    "StrStdout": "stdout",
    "StrString": "string",
    "StrSuccess": "success",
    "StrSystem": "system",
    "StrTaskId": "task_id",
    "StrTextdocument": "textDocument",
    "StrTimeout": "timeout",
    "StrTitle": "title",
    "StrTodoread": "TodoRead",
    "StrToolResult": "tool_result",
    "StrToolUse": "tool_use",
    "StrTruncated": "truncated",
    "StrUnknown": "unknown",
    "StrUrgent": "urgent",
    "StrVersion": "version",
    "StrWebfetch": "WebFetch",
    "StrWebsearch": "WebSearch",
    "StrWorkId": "work_id",
    "StrStartLine": "start_line",
    "StrEndLine": "end_line",
    "StrPython": "python",
    "StrStyle": "style",
    "StrWrite": "Write",
}


def test_all_strconst_values_match_go():
    for name, expected in EXPECTED.items():
        assert getattr(sc, name) == expected


def test_no_missing_or_extra_constants():
    defined = {n for n in dir(sc) if n.startswith("Str") and not n.startswith("Str__")}
    assert defined == set(EXPECTED)


def test_constants_are_str():
    for name in EXPECTED:
        assert isinstance(getattr(sc, name), str)

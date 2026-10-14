# SPDX-License-Identifier: MIT
"""Fluent builder for conversation messages."""

from __future__ import annotations

from datetime import UTC, datetime

from dxrk.utils.messages_model import Content, ContentType, ImageData, Message, Role, ToolResultData, ToolUseData


class MessageBuilder:
    """a fluent API for building messages."""

    def __init__(self, msg: Message) -> None:
        self.msg = msg

    def with_id(self, id: str) -> MessageBuilder:
        self.msg.id = id
        return self

    # Backwards-compatible alias (Go-style name).
    WithID = with_id

    def with_timestamp(self, ts: datetime) -> MessageBuilder:
        self.msg.timestamp = ts
        return self

    # Backwards-compatible alias (Go-style name).
    WithTimestamp = with_timestamp

    def with_model(self, model: str) -> MessageBuilder:
        self.msg.model = model
        return self

    # Backwards-compatible alias (Go-style name).
    WithModel = with_model

    def with_token_count(self, n: int) -> MessageBuilder:
        self.msg.token_count = n
        return self

    # Backwards-compatible alias (Go-style name).
    WithTokenCount = with_token_count

    def with_stop_reason(self, reason: str) -> MessageBuilder:
        self.msg.stop_reason = reason
        return self

    # Backwards-compatible alias (Go-style name).
    WithStopReason = with_stop_reason

    def with_metadata(self, key: str, value: object) -> MessageBuilder:
        self.msg.metadata[key] = value
        return self

    # Backwards-compatible alias (Go-style name).
    WithMetadata = with_metadata

    def text(self, text: str) -> MessageBuilder:
        self.msg.contents.append(Content(type=ContentType.ContentText, text=text))
        return self

    # Backwards-compatible alias (Go-style name).
    Text = text

    def image(self, media_type: str, data: str) -> MessageBuilder:
        self.msg.contents.append(
            Content(
                type=ContentType.ContentImage,
                image=ImageData(source="base64", media_type=media_type, data=data),
            )
        )
        return self

    # Backwards-compatible alias (Go-style name).
    Image = image

    def image_url(self, url: str, media_type: str) -> MessageBuilder:
        self.msg.contents.append(
            Content(
                type=ContentType.ContentImage,
                image=ImageData(source="url", media_type=media_type, data=url),
            )
        )
        return self

    # Backwards-compatible alias (Go-style name).
    ImageURL = image_url

    def tool_use(
        self, id: str, name: str, input: dict[str, object] | None = None
    ) -> MessageBuilder:
        data = input if input is not None else {}
        self.msg.contents.append(
            Content(
                type=ContentType.ContentToolUse,
                tool_use=ToolUseData(id=id, name=name, input=data),
            )
        )
        return self

    # Backwards-compatible alias (Go-style name).
    ToolUse = tool_use

    def tool_result(
        self, tool_use_id: str, content: str, is_error: bool
    ) -> MessageBuilder:
        self.msg.contents.append(
            Content(
                type=ContentType.ContentToolResult,
                tool_result=ToolResultData(
                    tool_use_id=tool_use_id, content=content, is_error=is_error
                ),
            )
        )
        return self

    # Backwards-compatible alias (Go-style name).
    ToolResult = tool_result

    def build(self) -> Message:
        return self.msg

    # Backwards-compatible alias (Go-style name).
    Build = build


def new_message(role: Role) -> MessageBuilder:
    """Start building a message with the given role."""
    return MessageBuilder(
        Message(
            role=role,
            timestamp=datetime.now(UTC),
            contents=[],
            metadata={},
        )
    )

# Backwards-compatible alias (Go-style name).
NewMessage = new_message

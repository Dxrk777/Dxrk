# SPDX-License-Identifier: MIT
"""Fluent builder for conversation messages."""

from __future__ import annotations

from datetime import UTC, datetime

from dxrk.utils.messages_model import Content, ContentType, ImageData, Message, Role, ToolResultData, ToolUseData


class MessageBuilder:
    """a fluent API for building messages."""

    def __init__(self, msg: Message) -> None:
        self.msg = msg

    def WithID(self, id: str) -> MessageBuilder:
        self.msg.id = id
        return self

    def WithTimestamp(self, ts: datetime) -> MessageBuilder:
        self.msg.timestamp = ts
        return self

    def WithModel(self, model: str) -> MessageBuilder:
        self.msg.model = model
        return self

    def WithTokenCount(self, n: int) -> MessageBuilder:
        self.msg.token_count = n
        return self

    def WithStopReason(self, reason: str) -> MessageBuilder:
        self.msg.stop_reason = reason
        return self

    def WithMetadata(self, key: str, value: object) -> MessageBuilder:
        self.msg.metadata[key] = value
        return self

    def Text(self, text: str) -> MessageBuilder:
        self.msg.contents.append(Content(type=ContentType.ContentText, text=text))
        return self

    def Image(self, media_type: str, data: str) -> MessageBuilder:
        self.msg.contents.append(
            Content(
                type=ContentType.ContentImage,
                image=ImageData(source="base64", media_type=media_type, data=data),
            )
        )
        return self

    def ImageURL(self, url: str, media_type: str) -> MessageBuilder:
        self.msg.contents.append(
            Content(
                type=ContentType.ContentImage,
                image=ImageData(source="url", media_type=media_type, data=url),
            )
        )
        return self

    def ToolUse(
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

    def ToolResult(
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

    def Build(self) -> Message:
        return self.msg


def NewMessage(role: Role) -> MessageBuilder:
    """Start building a message with the given role."""
    return MessageBuilder(
        Message(
            role=role,
            timestamp=datetime.now(UTC),
            contents=[],
            metadata={},
        )
    )

from __future__ import annotations

from guildbridge.models import (
    Channel,
    CommunityTemplate,
    PermissionOverwrite,
    Role,
    TemplatePrivacy,
    TemplateSource,
)
from guildbridge.privacy import (
    REDACTED_VALUE,
    is_private_metadata_key,
    redact_template,
    sanitize_secret_text,
)


def test_redact_removes_private_metadata_and_user_overwrites() -> None:
    template = CommunityTemplate(
        name="Private-ish",
        privacy=TemplatePrivacy(exports_members=True, exports_messages=True, stores_tokens=True),
        metadata={"token": "secret", "public": "ok"},
        roles=[Role(id="everyone", name="@everyone", metadata={"owner_id": "123", "safe": True})],
        channels=[
            Channel(
                id="chan",
                name="general",
                metadata={"last_message_id": "abc", "topic_source": "safe"},
                permission_overwrites=[
                    PermissionOverwrite(target_type="role", target_id="everyone", allow=["view_channel"]),
                    PermissionOverwrite(target_type="role", target_id="user_overwrite_abcd", deny=["view_channel"]),
                ],
            )
        ],
    )

    redacted = redact_template(template)

    assert redacted.privacy.exports_members is False
    assert redacted.privacy.exports_messages is False
    assert redacted.privacy.stores_tokens is False
    assert "token" not in redacted.metadata
    assert redacted.metadata["public"] == "ok"
    assert "owner_id" not in redacted.roles[0].metadata
    assert "last_message_id" not in redacted.channels[0].metadata
    assert len(redacted.channels[0].permission_overwrites) == 1


def test_redact_removes_nested_secret_metadata_keys_and_sanitizes_values() -> None:
    template = CommunityTemplate(
        name="Nested",
        description="Public description token='description-secret'",
        source=TemplateSource(
            platform="discord",
            id_hash="123456789012345678",
            note="failed with Authorization: Bearer source-secret",
        ),
        metadata={
            "headers": {
                "Authorization": "Bearer root-secret",
                "safe_header": "ok",
            },
            "apiResponse": [
                {"clientSecret": "secret-value"},
                {"safe": "token='inline-secret' still keeps the safe key"},
                {"refresh-token": "refresh-secret"},
            ],
            "raw_provider_id": "987654321",
            "public": {"note": "Authorization: Bot nested-secret"},
        },
        channels=[
            Channel(
                id="chan",
                name="general",
                topic="Deploy with access_token=topic-secret",
                metadata={
                    "Set-Cookie": "session=secret",
                    "matrix_join_rule": "public",
                    "copied_log": "Bearer abcdefghijklmnop",
                },
            )
        ],
        warnings=["provider failed with bot_token=warning-secret"],
    )

    redacted = redact_template(template)

    assert redacted.description == f"Public description token='{REDACTED_VALUE}'"
    assert redacted.source.id_hash != "123456789012345678"
    assert redacted.source.note == f"failed with Authorization: Bearer {REDACTED_VALUE}"
    assert "Authorization" not in redacted.metadata["headers"]
    assert redacted.metadata["headers"]["safe_header"] == "ok"
    assert "clientSecret" not in redacted.metadata["apiResponse"][0]
    assert redacted.metadata["apiResponse"][1]["safe"] == f"token='{REDACTED_VALUE}' still keeps the safe key"
    assert "refresh-token" not in redacted.metadata["apiResponse"][2]
    assert "raw_provider_id" not in redacted.metadata
    assert redacted.metadata["public"]["note"] == f"Authorization: Bot {REDACTED_VALUE}"
    assert "Set-Cookie" not in redacted.channels[0].metadata
    assert redacted.channels[0].metadata["matrix_join_rule"] == "public"
    assert redacted.channels[0].metadata["copied_log"] == f"Bearer {REDACTED_VALUE}"
    assert redacted.channels[0].topic == f"Deploy with access_token={REDACTED_VALUE}"
    assert redacted.warnings[0] == f"provider failed with bot_token={REDACTED_VALUE}"


def test_redaction_helpers_recognize_common_secret_shapes() -> None:
    assert is_private_metadata_key("clientSecret") is True
    assert is_private_metadata_key("refresh-token") is True
    assert is_private_metadata_key("raw_provider_id") is True
    assert is_private_metadata_key("matrix_join_rule") is False

    text = "Authorization: Bearer aaa token=bbb cookie:ccc"
    sanitized = sanitize_secret_text(text)
    assert "aaa" not in sanitized
    assert "bbb" not in sanitized
    assert "ccc" not in sanitized
    assert sanitized.count(REDACTED_VALUE) == 3

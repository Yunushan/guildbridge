from __future__ import annotations

from guildbridge.models import Channel, CommunityTemplate, PermissionOverwrite, Role, TemplatePrivacy
from guildbridge.privacy import redact_template


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

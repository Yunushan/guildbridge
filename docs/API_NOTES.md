# API Notes

Provider APIs change. GuildBridge keeps platform logic isolated in provider adapters so maintainers can edit routes, payloads, and permission maps quickly.

## Discord

- REST base URL defaults to `https://discord.com/api/v10`.
- Discord imports require an existing target guild ID.
- Server template export supports a Discord template URL or code.

## Fluxer

- API base URL defaults to `https://api.fluxer.app/v1`.
- Set `FLUXER_API_BASE` for self-hosted Fluxer.
- The API is Discord-like but not Discord; do not assume every Discord field is accepted.

## Stoat

- API base URL defaults to `https://api.stoat.chat`.
- Set `STOAT_API_BASE` for self-hosted or compatible deployments.
- The Stoat provider currently follows Stoat/Revolt-style server, role, and channel endpoints. Keep this adapter easy to patch as the API evolves.

## Spacebar

- API base URL defaults to `https://api.spacebar.chat/api/v9`.
- Set `SPACEBAR_API_BASE` and `SPACEBAR_BOT_TOKEN`.
- Spacebar targets Discord client-server API compatibility, so this adapter reuses Discord-style guild, role, channel, and permission payloads against a configurable Spacebar instance.

## Daccord

- API base URL defaults to `http://localhost:3000/api/v1`.
- Set `DACCORD_API_BASE`, `DACCORD_BOT_TOKEN` or `DACCORD_TOKEN`, and optionally `DACCORD_AUTH_SCHEME`.
- The provider uses Daccord space, role, channel, and channel-permission routes. Permission strings are mapped through `DACCORD_TO_NEUTRAL` / `NEUTRAL_TO_DACCORD`.

## Matrix / Element

- Element is a Matrix client; the provider talks to the Matrix Client-Server API.
- Matrix spaces model categories/servers best.
- Matrix rooms model text-like channels best.
- Discord-style global roles do not map 1:1 without member IDs.

## Rocket.Chat

- API base URL defaults to `http://localhost:3000/api/v1`.
- Set `ROCKET_CHAT_API_BASE`, `ROCKET_CHAT_AUTH_TOKEN`, and `ROCKET_CHAT_USER_ID`.
- The provider uses Rocket.Chat REST headers `X-Auth-Token` and `X-User-Id`.
- Exports rooms/channels and workspace roles; messages, users, subscriptions, and direct messages are not exported.
- Imports text-like rooms through channel/group create endpoints. Workspace/room permission parity is best-effort because Rocket.Chat role permissions are not identical to Discord-style channel overwrites.

## Mumble / Murmur

- API base URL defaults to `http://localhost:64738/api/v1`, but this must be an admin API bridge, not the Mumble voice protocol itself.
- Set `MUMBLE_API_BASE` and `MUMBLE_API_TOKEN`.
- The provider expects server, group, channel, and ACL management routes from the configured bridge.
- Exports groups, channels, and ACL-like allow/deny entries; live users, registrations, certificates, voice state, and text messages are not exported.

## Mattermost

- API base URL defaults to `http://localhost:8065/api/v4`.
- Set `MATTERMOST_API_BASE` and `MATTERMOST_TOKEN` or `MATTERMOST_PERSONAL_ACCESS_TOKEN`.
- The provider uses Mattermost API v4 team and channel endpoints. Mattermost does not create arbitrary Discord-style roles during normal channel import; those role intents are preserved as warnings/metadata.

## Zulip

- API base URL defaults to `https://chat.zulip.org/api/v1`.
- Set `ZULIP_API_BASE`, `ZULIP_EMAIL`, and `ZULIP_API_KEY`.
- Zulip uses Basic auth with `email:api_key` and form-encoded request bodies for channel subscription/user-group creation routes.
- The provider exports channels and user groups; topics, subscriptions, users, messages, and private DMs are not exported.

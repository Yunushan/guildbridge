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

## Matrix / Element

- Element is a Matrix client; the provider talks to the Matrix Client-Server API.
- Matrix spaces model categories/servers best.
- Matrix rooms model text-like channels best.
- Discord-style global roles do not map 1:1 without member IDs.

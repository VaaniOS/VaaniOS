"""
Explicit principal maps from configuration (ADR-022).

Both the HTTP API (``VAANIFLOW_API_TOKENS``: bearer token → principal) and the
Telegram adapter (``TELEGRAM_PRINCIPALS``: Telegram user id → principal) use the
same JSON shape::

    {"<key>": {"actor_id": "<uuid>", "name": "<display name>", "roles": ["OWNER", ...]}}

A malformed map raises: misconfigured authentication must not silently open or
close. Roles come only from the map, never from the key or any other metadata.
"""

import json
from uuid import UUID

from vaaniflow.domain.models.principal import Principal, Role


def parse_principal_map(
    raw: str, *, source: str, authentication_method: str
) -> dict[str, Principal]:
    """Parse ``raw`` into ``{key: Principal}``; raise ValueError naming ``source``."""
    try:
        entries = json.loads(raw)
        if not isinstance(entries, dict):
            raise TypeError("expected a JSON object")
        principals: dict[str, Principal] = {}
        for key, spec in entries.items():
            if not isinstance(spec, dict):
                raise TypeError(f"entry {key!r} must be an object")
            roles = spec["roles"]
            if not isinstance(roles, list) or not roles:
                raise TypeError(f"entry {key!r} must list at least one role")
            principals[str(key)] = Principal(
                principal_id=UUID(str(spec["actor_id"])),
                display_name=str(spec["name"]),
                roles=[Role(r) for r in roles],
                authentication_method=authentication_method,
            )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"{source} is not a valid principal map: {exc}") from exc
    return principals

"""Slack message markup patterns and entity collection."""

import re
from dataclasses import dataclass, field


# Slack markup patterns (pre-compiled for performance)
USER_MENTION = re.compile(r'<@([UW][A-Z0-9]+)(?:\|[^>]*)?>')
CHANNEL_LINK = re.compile(r'<#([C][A-Z0-9]+)(?:\|([^>]*))?>')
URL_LINK = re.compile(r'<(https?://[^|>]+)(?:\|([^>]+))?>')
SPECIAL_MENTION = re.compile(r'<!(here|channel|everyone)(?:\|[^>]*)?>')
TEAM_MENTION = re.compile(r'<!subteam\^([A-Z0-9]+)(?:\|([^>]+))?>')
HTML_ENTITY = re.compile(r'&(amp|lt|gt|nbsp|quot);')

# HTML entity mappings
HTML_ENTITIES = {
    'amp': '&',
    'lt': '<',
    'gt': '>',
    'nbsp': ' ',
    'quot': '"',
}


@dataclass
class CollectedEntities:
    """Entities extracted from text that need resolution."""

    user_ids: set[str] = field(default_factory=set)
    channel_ids: set[str] = field(default_factory=set)

    def merge(self, other: 'CollectedEntities') -> None:
        """Merge another collection into this one."""
        self.user_ids |= other.user_ids
        self.channel_ids |= other.channel_ids

    def __bool__(self) -> bool:
        """True if any entities need resolution."""
        return bool(self.user_ids or self.channel_ids)


def collect_entities(text: str | None) -> CollectedEntities:
    """Extract all entity IDs that need resolution from text.

    Args:
        text: Raw Slack message text with markup.

    Returns:
        CollectedEntities with user_ids and channel_ids to resolve.
    """
    entities = CollectedEntities()
    if not text:
        return entities

    # Collect user mentions: <@U123ABC> or <@U123ABC|name>
    for match in USER_MENTION.finditer(text):
        entities.user_ids.add(match.group(1))

    # Collect channel references without explicit names: <#C123>
    # (if name is provided like <#C123|general>, we don't need to resolve)
    for match in CHANNEL_LINK.finditer(text):
        if not match.group(2):  # No explicit name provided
            entities.channel_ids.add(match.group(1))

    return entities


def format_text(text: str | None, users: dict[str, str], channels: dict[str, str]) -> str:
    """Format Slack markup to human-readable text.

    Args:
        text: Raw Slack message text.
        users: Mapping of user_id -> display_name.
        channels: Mapping of channel_id -> name.

    Returns:
        Formatted text with resolved mentions.
    """
    if not text:
        return ''

    result = text

    # Replace user mentions: <@U123> -> @username
    def replace_user(match: re.Match) -> str:
        user_id = match.group(1)
        name = users.get(user_id, user_id)
        return f'@{name}'

    result = USER_MENTION.sub(replace_user, result)

    # Replace channel links: <#C123|name> -> #name or <#C123> -> #resolved_name
    def replace_channel(match: re.Match) -> str:
        channel_id = match.group(1)
        explicit_name = match.group(2)
        if explicit_name:
            return f'#{explicit_name}'
        name = channels.get(channel_id, channel_id)
        return f'#{name}'

    result = CHANNEL_LINK.sub(replace_channel, result)

    # Replace URLs: <url|label> -> label or <url> -> url
    def replace_url(match: re.Match) -> str:
        url = match.group(1)
        label = match.group(2)
        return label if label else url

    result = URL_LINK.sub(replace_url, result)

    # Replace special mentions: <!here> -> @here
    result = SPECIAL_MENTION.sub(r'@\1', result)

    # Replace team mentions: <!subteam^S123|@team> -> @team
    def replace_team(match: re.Match) -> str:
        label = match.group(2)
        return label if label else '@team'

    result = TEAM_MENTION.sub(replace_team, result)

    # Decode HTML entities: &amp; -> &
    def replace_entity(match: re.Match) -> str:
        entity = match.group(1)
        return HTML_ENTITIES.get(entity, match.group(0))

    result = HTML_ENTITY.sub(replace_entity, result)

    return result

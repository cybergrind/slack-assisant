"""Preferences tool for managing user preferences and memories."""

from typing import Any

from slack_assistant.agent.tools.base import BaseTool
from slack_assistant.preferences import EmojiPattern, PreferenceStorage, UserFact, UserRule
from slack_assistant.preferences.models import normalize_emoji_name


class PreferencesTool(BaseTool):
    """Tool for managing user preferences and remembered facts."""

    def __init__(self, storage: 'PreferenceStorage'):
        self._storage = storage

    @property
    def name(self) -> str:
        return 'manage_preferences'

    @property
    def description(self) -> str:
        return """Manage user preferences, remembered facts, and emoji communication patterns.

Actions:
- get_all: Get all preferences, rules, facts, and emoji patterns
- add_rule: Add a prioritization rule (e.g., "always highlight messages from @boss")
- remove_rule: Remove a rule by ID
- add_fact: Remember a fact (e.g., "user needs to follow up with John by Friday")
- remove_fact: Remove a fact by ID
- add_emoji_pattern: Store an emoji meaning (e.g., "eyes" means "seen", marks_as_handled=true)
- remove_emoji_pattern: Remove an emoji pattern by ID
- get_emoji_patterns: Get all emoji patterns

Use this to:
- Remember important things the user tells you
- Customize their prioritization experience
- Track their emoji communication patterns (when they tell you "I use 👀 to mean I've seen something")"""

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            'type': 'object',
            'properties': {
                'action': {
                    'type': 'string',
                    'enum': [
                        'get_all',
                        'add_rule',
                        'remove_rule',
                        'add_fact',
                        'remove_fact',
                        'add_emoji_pattern',
                        'remove_emoji_pattern',
                        'get_emoji_patterns',
                    ],
                    'description': 'Action to perform',
                },
                'content': {
                    'type': 'string',
                    'description': 'Content for add_rule or add_fact actions',
                },
                'id': {
                    'type': 'string',
                    'description': 'ID for remove_rule, remove_fact, or remove_emoji_pattern actions',
                },
                'emoji': {
                    'type': 'string',
                    'description': 'Emoji name without colons (e.g., "eyes") for emoji pattern actions',
                },
                'meaning': {
                    'type': 'string',
                    'description': 'What the emoji means (e.g., "acknowledged", "will review later")',
                },
                'marks_as_handled': {
                    'type': 'boolean',
                    'description': 'If true, items with this reaction are considered handled and get lower priority',
                },
                'priority_adjustment': {
                    'type': 'integer',
                    'description': 'Priority adjustment from -2 to +2 (default 0)',
                },
            },
            'required': ['action'],
        }

    async def execute(
        self,
        action: str,
        content: str | None = None,
        id: str | None = None,
        emoji: str | None = None,
        meaning: str | None = None,
        marks_as_handled: bool = False,
        priority_adjustment: int = 0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute preference management action.

        Args:
            action: Action to perform.
            content: Content for add actions.
            id: ID for remove actions.
            emoji: Emoji name for emoji pattern actions.
            meaning: Emoji meaning for add_emoji_pattern.
            marks_as_handled: Whether emoji marks item as handled.
            priority_adjustment: Priority adjustment (-2 to +2).

        Returns:
            Action result.
        """
        prefs = self._storage.load()

        if action == 'get_all':
            return {
                'rules': [{'id': r.id, 'description': r.description, 'created_at': r.created_at} for r in prefs.rules],
                'facts': [{'id': f.id, 'content': f.content, 'created_at': f.created_at} for f in prefs.facts],
                'emoji_patterns': [
                    {
                        'id': p.id,
                        'emoji': p.emoji,
                        'meaning': p.meaning,
                        'marks_as_handled': p.marks_as_handled,
                        'priority_adjustment': p.priority_adjustment,
                    }
                    for p in prefs.emoji_patterns
                ],
            }

        elif action == 'add_rule':
            if not content:
                return {'error': 'content is required for add_rule'}
            rule = UserRule(description=content)
            prefs.rules.append(rule)
            self._storage.save(prefs)
            return {'success': True, 'rule': {'id': rule.id, 'description': rule.description}}

        elif action == 'remove_rule':
            if not id:
                return {'error': 'id is required for remove_rule'}
            original_count = len(prefs.rules)
            prefs.rules = [r for r in prefs.rules if r.id != id]
            if len(prefs.rules) < original_count:
                self._storage.save(prefs)
                return {'success': True, 'removed_id': id}
            return {'success': False, 'error': f'Rule with id {id} not found'}

        elif action == 'add_fact':
            if not content:
                return {'error': 'content is required for add_fact'}
            fact = UserFact(content=content)
            prefs.facts.append(fact)
            self._storage.save(prefs)
            return {'success': True, 'fact': {'id': fact.id, 'content': fact.content}}

        elif action == 'remove_fact':
            if not id:
                return {'error': 'id is required for remove_fact'}
            original_count = len(prefs.facts)
            prefs.facts = [f for f in prefs.facts if f.id != id]
            if len(prefs.facts) < original_count:
                self._storage.save(prefs)
                return {'success': True, 'removed_id': id}
            return {'success': False, 'error': f'Fact with id {id} not found'}

        elif action == 'add_emoji_pattern':
            if not emoji:
                return {'error': 'emoji is required for add_emoji_pattern'}
            if not meaning:
                return {'error': 'meaning is required for add_emoji_pattern'}

            # Normalize emoji name to Slack format (underscores, lowercase, no colons)
            normalized_emoji = normalize_emoji_name(emoji)

            # Check if pattern already exists (using normalized name)
            existing = prefs.get_emoji_pattern(normalized_emoji)
            if existing:
                # Update existing pattern
                existing.meaning = meaning
                existing.marks_as_handled = marks_as_handled
                existing.priority_adjustment = max(-2, min(2, priority_adjustment))
                self._storage.save(prefs)
                return {
                    'success': True,
                    'updated': True,
                    'emoji_pattern': {
                        'id': existing.id,
                        'emoji': existing.emoji,
                        'meaning': existing.meaning,
                        'marks_as_handled': existing.marks_as_handled,
                        'priority_adjustment': existing.priority_adjustment,
                    },
                }

            # Create new pattern with normalized emoji name
            pattern = EmojiPattern(
                emoji=normalized_emoji,
                meaning=meaning,
                marks_as_handled=marks_as_handled,
                priority_adjustment=max(-2, min(2, priority_adjustment)),
            )
            prefs.emoji_patterns.append(pattern)
            self._storage.save(prefs)
            return {
                'success': True,
                'emoji_pattern': {
                    'id': pattern.id,
                    'emoji': pattern.emoji,
                    'meaning': pattern.meaning,
                    'marks_as_handled': pattern.marks_as_handled,
                    'priority_adjustment': pattern.priority_adjustment,
                },
            }

        elif action == 'remove_emoji_pattern':
            if not id:
                return {'error': 'id is required for remove_emoji_pattern'}
            original_count = len(prefs.emoji_patterns)
            prefs.emoji_patterns = [p for p in prefs.emoji_patterns if p.id != id]
            if len(prefs.emoji_patterns) < original_count:
                self._storage.save(prefs)
                return {'success': True, 'removed_id': id}
            return {'success': False, 'error': f'Emoji pattern with id {id} not found'}

        elif action == 'get_emoji_patterns':
            return {
                'emoji_patterns': [
                    {
                        'id': p.id,
                        'emoji': p.emoji,
                        'meaning': p.meaning,
                        'marks_as_handled': p.marks_as_handled,
                        'priority_adjustment': p.priority_adjustment,
                    }
                    for p in prefs.emoji_patterns
                ],
                'acknowledgment_emojis': prefs.get_acknowledgment_emojis(),
            }

        else:
            return {'error': f'Unknown action: {action}'}

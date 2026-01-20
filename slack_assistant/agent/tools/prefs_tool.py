"""Preferences tool for managing user preferences and memories."""

from typing import Any

from slack_assistant.agent.tools.base import BaseTool
from slack_assistant.preferences import PreferenceStorage, UserFact, UserRule


class PreferencesTool(BaseTool):
    """Tool for managing user preferences and remembered facts."""

    def __init__(self, storage: 'PreferenceStorage'):
        self._storage = storage

    @property
    def name(self) -> str:
        return 'manage_preferences'

    @property
    def description(self) -> str:
        return """Manage user preferences and remembered facts.
Actions:
- get_all: Get all preferences, rules, and facts
- add_rule: Add a prioritization rule (e.g., "always highlight messages from @boss")
- remove_rule: Remove a rule by ID
- add_fact: Remember a fact (e.g., "user needs to follow up with John by Friday")
- remove_fact: Remove a fact by ID

Use this to remember important things the user tells you and to customize their experience."""

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            'type': 'object',
            'properties': {
                'action': {
                    'type': 'string',
                    'enum': ['get_all', 'add_rule', 'remove_rule', 'add_fact', 'remove_fact'],
                    'description': 'Action to perform',
                },
                'content': {
                    'type': 'string',
                    'description': 'Content for add_rule or add_fact actions',
                },
                'id': {
                    'type': 'string',
                    'description': 'ID for remove_rule or remove_fact actions',
                },
            },
            'required': ['action'],
        }

    async def execute(
        self,
        action: str,
        content: str | None = None,
        id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute preference management action.

        Args:
            action: Action to perform.
            content: Content for add actions.
            id: ID for remove actions.

        Returns:
            Action result.
        """
        prefs = self._storage.load()

        if action == 'get_all':
            return {
                'rules': [{'id': r.id, 'description': r.description, 'created_at': r.created_at} for r in prefs.rules],
                'facts': [{'id': f.id, 'content': f.content, 'created_at': f.created_at} for f in prefs.facts],
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

        else:
            return {'error': f'Unknown action: {action}'}

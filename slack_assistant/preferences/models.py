"""Preference models."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class UserRule(BaseModel):
    """A user-defined prioritization rule."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class UserFact(BaseModel):
    """A remembered fact about the user or their tasks."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    content: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class UserPreferences(BaseModel):
    """Complete user preferences."""

    rules: list[UserRule] = Field(default_factory=list)
    facts: list[UserFact] = Field(default_factory=list)

    def get_rules_text(self) -> str:
        """Get rules as formatted text for prompts."""
        if not self.rules:
            return 'No custom rules defined.'

        lines = ['Custom prioritization rules:']
        for rule in self.rules:
            lines.append(f'- {rule.description}')
        return '\n'.join(lines)

    def get_facts_text(self) -> str:
        """Get facts as formatted text for prompts."""
        if not self.facts:
            return 'No remembered facts.'

        lines = ['Remembered facts:']
        for fact in self.facts:
            lines.append(f'- {fact.content}')
        return '\n'.join(lines)

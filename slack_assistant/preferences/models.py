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


class EmojiPattern(BaseModel):
    """A user's emoji usage pattern for acknowledgment detection."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    emoji: str  # e.g., "eyes", "white_check_mark"
    meaning: str  # e.g., "acknowledged", "will review"
    marks_as_handled: bool = False  # If True, items with this reaction are LOW priority
    priority_adjustment: int = Field(default=0, ge=-2, le=2)  # -2 to +2
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class UserPreferences(BaseModel):
    """Complete user preferences."""

    rules: list[UserRule] = Field(default_factory=list)
    facts: list[UserFact] = Field(default_factory=list)
    emoji_patterns: list[EmojiPattern] = Field(default_factory=list)

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

    def get_emoji_patterns_text(self) -> str:
        """Get emoji patterns as formatted text for prompts."""
        if not self.emoji_patterns:
            return 'No emoji patterns defined.'

        lines = ['Your emoji communication patterns:']
        for pattern in self.emoji_patterns:
            handled_note = ' (marks as handled)' if pattern.marks_as_handled else ''
            lines.append(f'- :{pattern.emoji}: means "{pattern.meaning}"{handled_note}')
        return '\n'.join(lines)

    def get_acknowledgment_emojis(self) -> list[str]:
        """Get list of emojis that mark items as handled.

        Returns:
            List of emoji names (without colons).
        """
        return [p.emoji for p in self.emoji_patterns if p.marks_as_handled]

    def get_emoji_pattern(self, emoji: str) -> EmojiPattern | None:
        """Get emoji pattern by emoji name.

        Args:
            emoji: Emoji name (without colons).

        Returns:
            EmojiPattern or None if not found.
        """
        for pattern in self.emoji_patterns:
            if pattern.emoji == emoji:
                return pattern
        return None

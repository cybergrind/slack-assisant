"""Tests for the agent module."""

import tempfile
from pathlib import Path

import pytest

from slack_assistant.agent.conversation import ConversationManager
from slack_assistant.agent.llm.models import LLMResponse, ToolCall
from slack_assistant.agent.tools.base import BaseTool, ToolRegistry
from slack_assistant.preferences import PreferenceStorage, UserFact, UserPreferences, UserRule


class TestConversationManager:
    """Tests for ConversationManager."""

    def test_add_user_message(self):
        manager = ConversationManager()
        manager.add_user_message('Hello')

        messages = manager.build_messages()
        assert len(messages) == 1
        assert messages[0]['role'] == 'user'
        assert messages[0]['content'] == 'Hello'

    def test_add_assistant_message_text_only(self):
        manager = ConversationManager()
        manager.add_assistant_message('Hi there!')

        messages = manager.build_messages()
        assert len(messages) == 1
        assert messages[0]['role'] == 'assistant'
        assert messages[0]['content'] == [{'type': 'text', 'text': 'Hi there!'}]

    def test_add_assistant_message_with_tool_calls(self):
        manager = ConversationManager()
        tool_calls = [{'id': 'tc_123', 'name': 'get_status', 'input': {'hours_back': 24}}]
        manager.add_assistant_message('Let me check...', tool_calls)

        messages = manager.build_messages()
        assert len(messages) == 1
        content = messages[0]['content']
        assert len(content) == 2
        assert content[0]['type'] == 'text'
        assert content[1]['type'] == 'tool_use'
        assert content[1]['id'] == 'tc_123'
        assert content[1]['name'] == 'get_status'

    def test_add_tool_result(self):
        manager = ConversationManager()
        manager.add_tool_result('tc_123', {'status': 'ok'})

        messages = manager.build_messages()
        assert len(messages) == 1
        assert messages[0]['role'] == 'user'
        assert messages[0]['content'][0]['type'] == 'tool_result'
        assert messages[0]['content'][0]['tool_use_id'] == 'tc_123'

    def test_clear(self):
        manager = ConversationManager()
        manager.add_user_message('Hello')
        manager.add_assistant_message('Hi!')
        manager.clear()

        assert manager.build_messages() == []

    def test_trim_old_messages(self):
        manager = ConversationManager(max_messages=3)
        manager.add_user_message('Message 1')
        manager.add_assistant_message('Response 1')
        manager.add_user_message('Message 2')
        manager.add_assistant_message('Response 2')  # This should trigger trimming

        messages = manager.build_messages()
        assert len(messages) == 3
        # First message should be trimmed
        assert messages[0]['content'] == [{'type': 'text', 'text': 'Response 1'}]

    def test_get_summary(self):
        manager = ConversationManager()
        manager.add_user_message('Hello')
        manager.add_assistant_message('Hi!')
        manager.add_user_message('How are you?')

        summary = manager.get_summary()
        assert '3 messages' in summary
        assert '2 user' in summary
        assert '1 assistant' in summary


class TestLLMModels:
    """Tests for LLM models."""

    def test_tool_call_creation(self):
        tc = ToolCall(id='tc_123', name='get_status', input={'hours_back': 24})
        assert tc.id == 'tc_123'
        assert tc.name == 'get_status'
        assert tc.input == {'hours_back': 24}

    def test_llm_response_text_only(self):
        response = LLMResponse(text='Hello', tool_calls=None, stop_reason='end_turn')
        assert response.text == 'Hello'
        assert not response.has_tool_calls

    def test_llm_response_with_tool_calls(self):
        tc = ToolCall(id='tc_123', name='get_status', input={})
        response = LLMResponse(text=None, tool_calls=[tc], stop_reason='tool_use')
        assert response.has_tool_calls
        assert len(response.tool_calls) == 1


class MockTool(BaseTool):
    """Mock tool for testing."""

    @property
    def name(self) -> str:
        return 'mock_tool'

    @property
    def description(self) -> str:
        return 'A mock tool for testing'

    @property
    def input_schema(self) -> dict:
        return {'type': 'object', 'properties': {'param': {'type': 'string'}}}

    async def execute(self, **kwargs):
        return {'result': 'success', **kwargs}


class TestToolRegistry:
    """Tests for ToolRegistry."""

    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = MockTool()
        registry.register(tool)

        retrieved = registry.get('mock_tool')
        assert retrieved is tool

    def test_get_nonexistent(self):
        registry = ToolRegistry()
        assert registry.get('nonexistent') is None

    def test_get_all(self):
        registry = ToolRegistry()
        tool1 = MockTool()
        registry.register(tool1)

        all_tools = registry.get_all()
        assert len(all_tools) == 1
        assert tool1 in all_tools

    def test_get_tool_definitions(self):
        registry = ToolRegistry()
        registry.register(MockTool())

        definitions = registry.get_tool_definitions()
        assert len(definitions) == 1
        assert definitions[0]['name'] == 'mock_tool'
        assert 'description' in definitions[0]
        assert 'input_schema' in definitions[0]

    @pytest.mark.asyncio
    async def test_execute(self):
        registry = ToolRegistry()
        registry.register(MockTool())

        result = await registry.execute('mock_tool', param='test')
        assert result['result'] == 'success'
        assert result['param'] == 'test'

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        registry = ToolRegistry()

        with pytest.raises(ValueError, match='Unknown tool'):
            await registry.execute('unknown')


class TestPreferenceStorage:
    """Tests for PreferenceStorage."""

    def test_load_nonexistent_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = PreferenceStorage(Path(tmpdir))
            prefs = storage.load()
            assert prefs.rules == []
            assert prefs.facts == []

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = PreferenceStorage(Path(tmpdir))

            prefs = UserPreferences()
            prefs.rules.append(UserRule(description='Always highlight @boss'))
            prefs.facts.append(UserFact(content='Meeting on Friday'))

            storage.save(prefs)

            loaded = storage.load()
            assert len(loaded.rules) == 1
            assert loaded.rules[0].description == 'Always highlight @boss'
            assert len(loaded.facts) == 1
            assert loaded.facts[0].content == 'Meeting on Friday'

    def test_get_rules_text_empty(self):
        prefs = UserPreferences()
        assert prefs.get_rules_text() == 'No custom rules defined.'

    def test_get_rules_text_with_rules(self):
        prefs = UserPreferences()
        prefs.rules.append(UserRule(description='Rule 1'))
        prefs.rules.append(UserRule(description='Rule 2'))

        text = prefs.get_rules_text()
        assert 'Rule 1' in text
        assert 'Rule 2' in text

    def test_get_facts_text_empty(self):
        prefs = UserPreferences()
        assert prefs.get_facts_text() == 'No remembered facts.'

    def test_get_facts_text_with_facts(self):
        prefs = UserPreferences()
        prefs.facts.append(UserFact(content='Important fact'))

        text = prefs.get_facts_text()
        assert 'Important fact' in text

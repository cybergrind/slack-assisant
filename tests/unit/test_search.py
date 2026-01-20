"""Tests for search service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from slack_assistant.services.search import SearchService


class TestVectorSearch:
    """Tests for vector search functionality."""

    @pytest.fixture
    def mock_client(self):
        client = MagicMock()
        client.get_message_link = MagicMock(return_value='https://slack.com/archives/C123/p123')
        return client

    @pytest.fixture
    def mock_repository(self):
        return MagicMock()

    @pytest.fixture
    def mock_embedding_service(self):
        service = MagicMock()
        service.generate_embedding = AsyncMock(return_value=[0.1, 0.2, 0.3] * 128)  # 384 dims
        return service

    @pytest.mark.asyncio
    async def test_vector_search_formats_embedding_correctly(
        self, mock_client, mock_repository, mock_embedding_service
    ):
        """Test that vector search formats embedding as pgvector string."""
        search = SearchService(mock_client, mock_repository, mock_embedding_service)

        with patch('slack_assistant.services.search.get_session') as mock_get_session:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.fetchall = MagicMock(return_value=[])
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock()

            await search._vector_search('test query', limit=5)

            # Verify execute was called
            mock_session.execute.assert_called_once()
            call_args = mock_session.execute.call_args
            params = call_args[0][1]  # Second positional arg is params dict

            # Embedding should be formatted as pgvector string
            assert 'embedding' in params
            assert params['embedding'].startswith('[')
            assert params['embedding'].endswith(']')
            assert ',' in params['embedding']
            # Verify it contains the expected values
            assert '0.1' in params['embedding']
            assert '0.2' in params['embedding']
            assert '0.3' in params['embedding']

    @pytest.mark.asyncio
    async def test_vector_search_returns_empty_when_no_embedding(self, mock_client, mock_repository):
        """Test that vector search returns empty list when embedding generation fails."""
        mock_embedding_service = MagicMock()
        mock_embedding_service.generate_embedding = AsyncMock(return_value=None)

        search = SearchService(mock_client, mock_repository, mock_embedding_service)
        results = await search._vector_search('test query', limit=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_vector_search_returns_empty_without_service(self, mock_client, mock_repository):
        """Test that vector search returns empty list when no embedding service."""
        search = SearchService(mock_client, mock_repository, embedding_service=None)
        results = await search._vector_search('test query', limit=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_vector_search_query_uses_cast_syntax(self, mock_client, mock_repository, mock_embedding_service):
        """Test that vector search uses CAST syntax instead of :: for type casting."""
        search = SearchService(mock_client, mock_repository, mock_embedding_service)

        with patch('slack_assistant.services.search.get_session') as mock_get_session:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.fetchall = MagicMock(return_value=[])
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock()

            await search._vector_search('test query', limit=5)

            # Verify the SQL statement uses CAST syntax
            call_args = mock_session.execute.call_args
            stmt = call_args[0][0]  # First positional arg is the statement
            sql_text = str(stmt)

            # Should use CAST(:embedding AS vector) instead of :embedding::vector
            assert 'CAST(:embedding AS vector)' in sql_text
            assert '::vector' not in sql_text

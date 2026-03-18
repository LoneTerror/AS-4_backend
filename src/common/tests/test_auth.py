import pytest
from src.common.auth import CurrentUser, get_current_user

class TestAuthCommon:

    def test_current_user_initialization(self):
        """Test that the CurrentUser data class initializes properties correctly."""
        user = CurrentUser(id="test-123", roles=["EMPLOYEE", "MANAGER"])
        
        assert user.id == "test-123"
        assert user.roles == ["EMPLOYEE", "MANAGER"]

    @pytest.mark.asyncio
    async def test_get_current_user(self):
        """Test the temporary hard-coded user generation."""
        user = await get_current_user()
        
        assert isinstance(user, CurrentUser)
        assert user.id == "110e8400-e29b-41d4-a716-446655440000"
        assert user.roles == ["SUPER_ADMIN"]
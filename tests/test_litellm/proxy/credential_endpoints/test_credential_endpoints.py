"""
Tests for credential management endpoints.
"""
import os
import sys
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.insert(0, os.path.abspath("../../../.."))

from litellm.types.utils import CredentialItem
from litellm.proxy.credential_endpoints.endpoints import CredentialHelperUtils


class TestCredentialHelperUtils:
    """Tests for CredentialHelperUtils class."""

    def test_encrypt_credential_values_does_not_modify_original(self):
        """
        Test that encrypt_credential_values() returns a NEW CredentialItem 
        and does NOT modify the original credential object.
        
        This is critical because after creation, the unencrypted credential
        should be added to litellm.credential_list, not the encrypted version.
        """
        # Create a credential with sensitive values
        original_credential = CredentialItem(
            credential_name="test-credential",
            credential_values={
                "api_key": "sk-test-key-12345",
                "api_base": "https://api.example.com",
            },
            credential_info={"custom_llm_provider": "openai"},
        )
        
        # Store original values for comparison
        original_api_key = original_credential.credential_values["api_key"]
        original_api_base = original_credential.credential_values["api_base"]
        
        # Mock encrypt_value_helper to return predictable encrypted values
        with patch(
            "litellm.proxy.credential_endpoints.endpoints.encrypt_value_helper"
        ) as mock_encrypt:
            mock_encrypt.side_effect = lambda v: f"ENCRYPTED_{v}"
            
            # Call the encrypt method
            encrypted_credential = CredentialHelperUtils.encrypt_credential_values(
                original_credential
            )
        
        # Verify the original credential was NOT modified
        assert original_credential.credential_values["api_key"] == original_api_key
        assert original_credential.credential_values["api_base"] == original_api_base
        
        # Verify a NEW credential was returned with encrypted values
        assert encrypted_credential is not original_credential
        assert encrypted_credential.credential_values["api_key"] == f"ENCRYPTED_{original_api_key}"
        assert encrypted_credential.credential_values["api_base"] == f"ENCRYPTED_{original_api_base}"
        
        # Verify credential metadata was preserved
        assert encrypted_credential.credential_name == original_credential.credential_name
        assert encrypted_credential.credential_info == original_credential.credential_info

    def test_encrypt_credential_values_preserves_all_fields(self):
        """
        Test that encrypt_credential_values() preserves all fields from the original credential.
        """
        original_credential = CredentialItem(
            credential_name="my-azure-credential",
            credential_values={
                "api_key": "my-secret-key",
                "api_base": "https://my-resource.openai.azure.com",
                "api_version": "2024-02-01",
            },
            credential_info={
                "custom_llm_provider": "azure",
                "description": "Test Azure credential",
            },
        )
        
        with patch(
            "litellm.proxy.credential_endpoints.endpoints.encrypt_value_helper"
        ) as mock_encrypt:
            mock_encrypt.side_effect = lambda v: f"ENC_{v}"
            
            encrypted_credential = CredentialHelperUtils.encrypt_credential_values(
                original_credential
            )
        
        # All credential_values should be encrypted
        assert encrypted_credential.credential_values["api_key"] == "ENC_my-secret-key"
        assert encrypted_credential.credential_values["api_base"] == "ENC_https://my-resource.openai.azure.com"
        assert encrypted_credential.credential_values["api_version"] == "ENC_2024-02-01"
        
        # credential_name and credential_info should be preserved as-is
        assert encrypted_credential.credential_name == "my-azure-credential"
        assert encrypted_credential.credential_info == {
            "custom_llm_provider": "azure",
            "description": "Test Azure credential",
        }

    def test_encrypt_credential_values_empty_values(self):
        """Test encryption handles empty credential_values dict."""
        original_credential = CredentialItem(
            credential_name="empty-credential",
            credential_values={},
            credential_info={"custom_llm_provider": "openai"},
        )
        
        with patch(
            "litellm.proxy.credential_endpoints.endpoints.encrypt_value_helper"
        ) as mock_encrypt:
            encrypted_credential = CredentialHelperUtils.encrypt_credential_values(
                original_credential
            )
        
        # Should return a new credential with empty values
        assert encrypted_credential is not original_credential
        assert encrypted_credential.credential_values == {}
        mock_encrypt.assert_not_called()


class TestMaskedValueFiltering:
    """Tests for masked value detection and filtering.
    
    These tests ensure that masked values (like "sk****45") are not 
    accidentally saved when editing credentials, which would overwrite
    the real API keys.
    """

    def test_is_masked_value_detects_four_asterisks(self):
        """Test that is_masked_value detects values with four asterisks."""
        assert CredentialHelperUtils.is_masked_value("sk****45") is True
        assert CredentialHelperUtils.is_masked_value("ab****cd") is True
        assert CredentialHelperUtils.is_masked_value("****") is True
        assert CredentialHelperUtils.is_masked_value("prefix****suffix") is True

    def test_is_masked_value_detects_three_asterisks(self):
        """Test that is_masked_value detects values with three asterisks."""
        assert CredentialHelperUtils.is_masked_value("sk***45") is True
        assert CredentialHelperUtils.is_masked_value("***") is True
        assert CredentialHelperUtils.is_masked_value("abc***xyz") is True

    def test_is_masked_value_allows_real_values(self):
        """Test that is_masked_value allows real API keys."""
        assert CredentialHelperUtils.is_masked_value("sk-test-key-12345") is False
        assert CredentialHelperUtils.is_masked_value("AIzaSyD-real-api-key") is False
        assert CredentialHelperUtils.is_masked_value("https://api.example.com") is False
        assert CredentialHelperUtils.is_masked_value("my-secret-value") is False
        # Single or double asterisks are fine (could be in valid values)
        assert CredentialHelperUtils.is_masked_value("test*value") is False
        assert CredentialHelperUtils.is_masked_value("test**value") is False

    def test_is_masked_value_handles_non_strings(self):
        """Test that is_masked_value handles non-string values."""
        assert CredentialHelperUtils.is_masked_value(None) is False
        assert CredentialHelperUtils.is_masked_value(123) is False
        assert CredentialHelperUtils.is_masked_value({"key": "value"}) is False
        assert CredentialHelperUtils.is_masked_value(["list"]) is False

    def test_filter_masked_values_removes_masked(self):
        """Test that filter_masked_values removes masked values."""
        credential_values = {
            "api_key": "sk****45",  # Masked - should be filtered
            "api_base": "https://api.example.com",  # Not masked - should keep
            "token": "ab***cd",  # Masked - should be filtered
            "api_version": "2024-01-01",  # Not masked - should keep
        }
        
        filtered = CredentialHelperUtils.filter_masked_values(credential_values)
        
        assert "api_key" not in filtered
        assert "token" not in filtered
        assert filtered["api_base"] == "https://api.example.com"
        assert filtered["api_version"] == "2024-01-01"

    def test_filter_masked_values_keeps_all_real_values(self):
        """Test that filter_masked_values keeps all real values."""
        credential_values = {
            "api_key": "sk-real-api-key-12345",
            "api_base": "https://api.openai.com/v1",
            "organization": "org-12345",
        }
        
        filtered = CredentialHelperUtils.filter_masked_values(credential_values)
        
        assert filtered == credential_values

    def test_filter_masked_values_handles_empty_dict(self):
        """Test that filter_masked_values handles empty dict."""
        filtered = CredentialHelperUtils.filter_masked_values({})
        assert filtered == {}


class TestUpdateDbCredentialMaskedValues:
    """Tests for update_db_credential function with masked values."""

    def test_update_db_credential_skips_masked_api_key(self):
        """
        Test that update_db_credential preserves existing API key
        when the update contains a masked value.
        
        This is the main bug fix - editing a credential in the UI
        should not overwrite the real API key with "sk****45".
        """
        from litellm.proxy.credential_endpoints.endpoints import update_db_credential
        
        # Existing credential in DB (decrypted)
        db_credential = CredentialItem(
            credential_name="my-openai-cred",
            credential_values={
                "api_key": "ENCRYPTED_sk-real-api-key-12345",
                "api_base": "ENCRYPTED_https://api.openai.com/v1",
            },
            credential_info={"custom_llm_provider": "openai"},
        )
        
        # Update from UI with masked api_key (user didn't change it)
        updated_patch = CredentialItem(
            credential_name="my-openai-cred",
            credential_values={
                "api_key": "sk****45",  # This is the masked value from UI
                "api_base": "https://api.new-base.com",  # User changed this
            },
            credential_info={"custom_llm_provider": "openai"},
        )
        
        with patch(
            "litellm.proxy.credential_endpoints.endpoints.encrypt_value_helper"
        ) as mock_encrypt:
            mock_encrypt.side_effect = lambda v: f"ENCRYPTED_{v}"
            
            merged = update_db_credential(db_credential, updated_patch)
        
        # api_key should NOT be updated (masked value was filtered)
        # It should retain the original encrypted value
        assert merged.credential_values["api_key"] == "ENCRYPTED_sk-real-api-key-12345"
        
        # api_base SHOULD be updated (it was a real value)
        assert merged.credential_values["api_base"] == "ENCRYPTED_https://api.new-base.com"

    def test_update_db_credential_updates_real_api_key(self):
        """
        Test that update_db_credential correctly updates the API key
        when user provides a new real value.
        """
        from litellm.proxy.credential_endpoints.endpoints import update_db_credential
        
        db_credential = CredentialItem(
            credential_name="my-cred",
            credential_values={
                "api_key": "ENCRYPTED_old-key",
            },
            credential_info={"custom_llm_provider": "anthropic"},
        )
        
        # User provides a new, real API key
        updated_patch = CredentialItem(
            credential_name="my-cred",
            credential_values={
                "api_key": "sk-new-real-api-key-67890",  # Real new value
            },
            credential_info={"custom_llm_provider": "anthropic"},
        )
        
        with patch(
            "litellm.proxy.credential_endpoints.endpoints.encrypt_value_helper"
        ) as mock_encrypt:
            mock_encrypt.side_effect = lambda v: f"ENCRYPTED_{v}"
            
            merged = update_db_credential(db_credential, updated_patch)
        
        # api_key SHOULD be updated with the new encrypted value
        assert merged.credential_values["api_key"] == "ENCRYPTED_sk-new-real-api-key-67890"


class TestInMemoryCredentialSync:
    """Tests for in-memory credential synchronization."""

    def test_update_in_memory_credential_preserves_unmodified_values(self):
        """
        Test that _update_in_memory_credential preserves existing values
        when only some fields are updated.
        """
        from litellm.proxy.credential_endpoints.endpoints import _update_in_memory_credential
        
        existing = CredentialItem(
            credential_name="test-cred",
            credential_values={
                "api_key": "sk-real-key-12345",
                "api_base": "https://api.openai.com/v1",
                "organization": "org-123",
            },
            credential_info={"custom_llm_provider": "openai"},
        )
        
        # Only update api_base, leave api_key empty/masked
        patch = CredentialItem(
            credential_name="test-cred",
            credential_values={
                "api_key": "sk****45",  # Masked - should be ignored
                "api_base": "https://api.new-base.com",  # Real update
            },
            credential_info={"custom_llm_provider": "openai"},
        )
        
        updated = _update_in_memory_credential(existing, patch)
        
        # api_key should be preserved (masked value filtered)
        assert updated.credential_values["api_key"] == "sk-real-key-12345"
        # api_base should be updated
        assert updated.credential_values["api_base"] == "https://api.new-base.com"
        # organization should be preserved (not in patch)
        assert updated.credential_values["organization"] == "org-123"

    def test_update_in_memory_credential_updates_real_values(self):
        """
        Test that _update_in_memory_credential correctly updates 
        when user provides real new values.
        """
        from litellm.proxy.credential_endpoints.endpoints import _update_in_memory_credential
        
        existing = CredentialItem(
            credential_name="test-cred",
            credential_values={
                "api_key": "old-key",
            },
            credential_info={"custom_llm_provider": "anthropic"},
        )
        
        patch = CredentialItem(
            credential_name="test-cred",
            credential_values={
                "api_key": "new-real-key",  # Real new value
            },
            credential_info={"custom_llm_provider": "anthropic", "description": "Updated"},
        )
        
        updated = _update_in_memory_credential(existing, patch)
        
        assert updated.credential_values["api_key"] == "new-real-key"
        assert updated.credential_info["description"] == "Updated"

    def test_update_in_memory_credential_does_not_modify_original(self):
        """
        Test that _update_in_memory_credential returns a NEW object
        and does not modify the original.
        """
        from litellm.proxy.credential_endpoints.endpoints import _update_in_memory_credential
        
        existing = CredentialItem(
            credential_name="test-cred",
            credential_values={"api_key": "original-key"},
            credential_info={"custom_llm_provider": "openai"},
        )
        
        patch = CredentialItem(
            credential_name="test-cred",
            credential_values={"api_key": "new-key"},
            credential_info={},
        )
        
        updated = _update_in_memory_credential(existing, patch)
        
        # Original should NOT be modified
        assert existing.credential_values["api_key"] == "original-key"
        # New object should have updated values
        assert updated.credential_values["api_key"] == "new-key"
        assert updated is not existing











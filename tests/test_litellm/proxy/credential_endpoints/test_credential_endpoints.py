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


"""
CRUD endpoints for storing reusable credentials.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Path

import litellm
from litellm._logging import verbose_proxy_logger
from litellm.litellm_core_utils.credential_accessor import CredentialAccessor
from litellm.litellm_core_utils.litellm_logging import _get_masked_values
from litellm.proxy._types import CommonProxyErrors, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.common_utils.encrypt_decrypt_utils import encrypt_value_helper
from litellm.proxy.utils import handle_exception_on_proxy, jsonify_object
from litellm.types.utils import CreateCredentialItem, CredentialItem

router = APIRouter()


class CredentialHelperUtils:
    @staticmethod
    def is_masked_value(value: str) -> bool:
        """
        Check if a value appears to be masked (contains asterisks pattern).
        
        Masked values look like: "sk****45" or "abc***xyz"
        These should NOT be saved as they would overwrite real credentials.
        """
        if not isinstance(value, str):
            return False
        # Check for common masking patterns (3+ consecutive asterisks)
        return "****" in value or "***" in value

    @staticmethod
    def filter_masked_values(credential_values: dict) -> dict:
        """
        Filter out masked values from credential_values dict.
        
        This prevents accidentally overwriting real credentials with masked placeholders
        when editing credentials in the UI.
        """
        filtered = {}
        for key, value in credential_values.items():
            if CredentialHelperUtils.is_masked_value(value):
                verbose_proxy_logger.debug(
                    f"Skipping masked value for key '{key}' - will keep existing value"
                )
                continue
            filtered[key] = value
        return filtered

    @staticmethod
    def encrypt_credential_values(credential: CredentialItem) -> CredentialItem:
        """
        Encrypt values in credential.credential_values for DB storage.
        
        Returns a NEW CredentialItem with encrypted values - does NOT modify the original.
        """
        encrypted_credential_values = {}
        for key, value in credential.credential_values.items():
            encrypted_credential_values[key] = encrypt_value_helper(value)
        
        # Return a NEW CredentialItem - don't modify the original!
        return CredentialItem(
            credential_name=credential.credential_name,
            credential_values=encrypted_credential_values,
            credential_info=credential.credential_info,
        )


@router.post(
    "/credentials",
    dependencies=[Depends(user_api_key_auth)],
    tags=["credential management"],
)
async def create_credential(
    request: Request,
    fastapi_response: Response,
    credential: CreateCredentialItem,
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    [BETA] endpoint. This might change unexpectedly.
    Stores credential in DB.
    Reloads credentials in memory.
    """
    from litellm.proxy.proxy_server import llm_router, prisma_client

    try:
        if prisma_client is None:
            raise HTTPException(
                status_code=500,
                detail={"error": CommonProxyErrors.db_not_connected_error.value},
            )
        if credential.model_id:
            if llm_router is None:
                raise HTTPException(
                    status_code=500,
                    detail="LLM router not found. Please ensure you have a valid router instance.",
                )
            # get model from router
            model = llm_router.get_deployment(credential.model_id)
            if model is None:
                raise HTTPException(status_code=404, detail="Model not found")
            credential_values = llm_router.get_deployment_credentials(
                credential.model_id
            )
            if credential_values is None:
                raise HTTPException(status_code=404, detail="Model not found")
            credential.credential_values = credential_values

        if credential.credential_values is None:
            raise HTTPException(
                status_code=400,
                detail="Credential values are required. Unable to infer credential values from model ID.",
            )
        processed_credential = CredentialItem(
            credential_name=credential.credential_name,
            credential_values=credential.credential_values,
            credential_info=credential.credential_info,
        )
        encrypted_credential = CredentialHelperUtils.encrypt_credential_values(
            processed_credential
        )
        credentials_dict = encrypted_credential.model_dump()
        credentials_dict_jsonified = jsonify_object(credentials_dict)
        await prisma_client.db.litellm_credentialstable.create(
            data={
                **credentials_dict_jsonified,
                "created_by": user_api_key_dict.user_id,
                "updated_by": user_api_key_dict.user_id,
            }
        )

        ## ADD TO LITELLM ##
        CredentialAccessor.upsert_credentials([processed_credential])

        return {"success": True, "message": "Credential created successfully"}
    except Exception as e:
        verbose_proxy_logger.exception(e)
        raise handle_exception_on_proxy(e)


@router.get(
    "/credentials",
    dependencies=[Depends(user_api_key_auth)],
    tags=["credential management"],
)
async def get_credentials(
    request: Request,
    fastapi_response: Response,
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    [BETA] endpoint. This might change unexpectedly.
    """
    try:
        masked_credentials = [
            {
                "credential_name": credential.credential_name,
                "credential_values": _get_masked_values(credential.credential_values),
                "credential_info": credential.credential_info,
            }
            for credential in litellm.credential_list
        ]
        return {"success": True, "credentials": masked_credentials}
    except Exception as e:
        return handle_exception_on_proxy(e)


@router.get(
    "/credentials/by_name/{credential_name:path}",
    dependencies=[Depends(user_api_key_auth)],
    tags=["credential management"],
    response_model=CredentialItem,
)
@router.get(
    "/credentials/by_model/{model_id}",
    dependencies=[Depends(user_api_key_auth)],
    tags=["credential management"],
    response_model=CredentialItem,
)
async def get_credential(
    request: Request,
    fastapi_response: Response,
    credential_name: str = Path(..., description="The credential name, percent-decoded; may contain slashes"),
    model_id: Optional[str] = None,
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    [BETA] endpoint. This might change unexpectedly.
    """
    from litellm.proxy.proxy_server import llm_router

    try:
        if model_id:
            if llm_router is None:
                raise HTTPException(status_code=500, detail="LLM router not found")
            model = llm_router.get_deployment(model_id)
            if model is None:
                raise HTTPException(status_code=404, detail="Model not found")
            credential_values = llm_router.get_deployment_credentials(model_id)
            if credential_values is None:
                raise HTTPException(status_code=404, detail="Model not found")
            masked_credential_values = _get_masked_values(
                credential_values,
                unmasked_length=4,
                number_of_asterisks=4,
            )
            credential = CredentialItem(
                credential_name="{}-credential-{}".format(model.model_name, model_id),
                credential_values=masked_credential_values,
                credential_info={},
            )
            # return credential object
            return credential
        elif credential_name:
            for credential in litellm.credential_list:
                if credential.credential_name == credential_name:
                    masked_credential = CredentialItem(
                        credential_name=credential.credential_name,
                        credential_values=_get_masked_values(
                            credential.credential_values,
                            unmasked_length=4,
                            number_of_asterisks=4,
                        ),
                        credential_info=credential.credential_info,
                    )
                    return masked_credential
            raise HTTPException(
                status_code=404,
                detail="Credential not found. Got credential name: " + credential_name,
            )
        else:
            raise HTTPException(
                status_code=404, detail="Credential name or model ID required"
            )
    except Exception as e:
        verbose_proxy_logger.exception(e)
        raise handle_exception_on_proxy(e)


@router.delete(
    "/credentials/{credential_name:path}",
    dependencies=[Depends(user_api_key_auth)],
    tags=["credential management"],
)
async def delete_credential(
    request: Request,
    fastapi_response: Response,
    credential_name: str = Path(..., description="The credential name, percent-decoded; may contain slashes"),
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    [BETA] endpoint. This might change unexpectedly.
    """
    from litellm.proxy.proxy_server import prisma_client

    try:
        if prisma_client is None:
            raise HTTPException(
                status_code=500,
                detail={"error": CommonProxyErrors.db_not_connected_error.value},
            )
        await prisma_client.db.litellm_credentialstable.delete(
            where={"credential_name": credential_name}
        )

        ## DELETE FROM LITELLM ##
        litellm.credential_list = [
            cred
            for cred in litellm.credential_list
            if cred.credential_name != credential_name
        ]
        return {"success": True, "message": "Credential deleted successfully"}
    except Exception as e:
        return handle_exception_on_proxy(e)


def update_db_credential(
    db_credential: CredentialItem, updated_patch: CredentialItem
) -> CredentialItem:
    """
    Update a credential in the DB.
    
    Handles masked values properly - if a value appears masked (contains ****),
    it will be skipped and the existing value will be preserved.
    """
    merged_credential = CredentialItem(
        credential_name=db_credential.credential_name,
        credential_info=db_credential.credential_info,
        credential_values=db_credential.credential_values,
    )

    # Filter out masked values BEFORE encrypting
    # This prevents overwriting real credentials with masked placeholders
    filtered_credential_values = CredentialHelperUtils.filter_masked_values(
        updated_patch.credential_values
    )
    
    # Create a new CredentialItem with filtered values for encryption
    filtered_patch = CredentialItem(
        credential_name=updated_patch.credential_name,
        credential_values=filtered_credential_values,
        credential_info=updated_patch.credential_info,
    )
    
    encrypted_credential = CredentialHelperUtils.encrypt_credential_values(
        filtered_patch
    )
    # update model name
    if encrypted_credential.credential_name:
        merged_credential.credential_name = encrypted_credential.credential_name

    # update litellm params
    if encrypted_credential.credential_values:
        # Encrypt any sensitive values (masked values already filtered out)
        encrypted_params = {
            k: v for k, v in encrypted_credential.credential_values.items()
        }

        merged_credential.credential_values.update(encrypted_params)

    # update model info
    if encrypted_credential.credential_info:
        """Update credential info"""
        if "credential_info" not in merged_credential.credential_info:
            merged_credential.credential_info = {}
        merged_credential.credential_info.update(encrypted_credential.credential_info)

    return merged_credential


def _get_in_memory_credential(credential_name: str) -> CredentialItem:
    """Get the current unencrypted credential from in-memory list."""
    for cred in litellm.credential_list:
        if cred.credential_name == credential_name:
            return cred
    raise HTTPException(status_code=404, detail="Credential not found in memory.")


def _update_in_memory_credential(
    existing_credential: CredentialItem, 
    updated_patch: CredentialItem
) -> CredentialItem:
    """
    Update an in-memory credential with new values.
    
    Handles masked values properly - masked values are filtered out.
    Returns a NEW CredentialItem with updated values (unencrypted).
    """
    # Start with a copy of existing values
    updated_values = existing_credential.credential_values.copy()
    
    # Filter out masked values from the patch
    filtered_patch_values = CredentialHelperUtils.filter_masked_values(
        updated_patch.credential_values
    )
    
    # Apply non-masked updates
    updated_values.update(filtered_patch_values)
    
    # Update credential info if provided
    updated_info = existing_credential.credential_info.copy()
    if updated_patch.credential_info:
        updated_info.update(updated_patch.credential_info)
    
    return CredentialItem(
        credential_name=existing_credential.credential_name,
        credential_values=updated_values,
        credential_info=updated_info,
    )


@router.patch(
    "/credentials/{credential_name:path}",
    dependencies=[Depends(user_api_key_auth)],
    tags=["credential management"],
)
async def update_credential(
    request: Request,
    fastapi_response: Response,
    credential: CredentialItem,
    credential_name: str = Path(..., description="The credential name, percent-decoded; may contain slashes"),
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    [BETA] endpoint. This might change unexpectedly.
    
    Updates credential in DB and syncs to in-memory list.
    Models using this credential will immediately see the new values.
    """
    from litellm.proxy.proxy_server import prisma_client

    try:
        if prisma_client is None:
            raise HTTPException(
                status_code=500,
                detail={"error": CommonProxyErrors.db_not_connected_error.value},
            )
        db_credential = await prisma_client.db.litellm_credentialstable.find_unique(
            where={"credential_name": credential_name},
        )
        if db_credential is None:
            raise HTTPException(status_code=404, detail="Credential not found in DB.")
        
        # Update DB with encrypted values
        merged_credential = update_db_credential(db_credential, credential)
        credential_object_jsonified = jsonify_object(merged_credential.model_dump())
        await prisma_client.db.litellm_credentialstable.update(
            where={"credential_name": credential_name},
            data={
                **credential_object_jsonified,
                "updated_by": user_api_key_dict.user_id,
            },
        )
        
        # Sync to in-memory list so models immediately see the update
        # Get the current unencrypted credential and apply updates
        existing_credential = _get_in_memory_credential(credential_name)
        updated_credential = _update_in_memory_credential(existing_credential, credential)
        CredentialAccessor.upsert_credentials([updated_credential])
        
        return {"success": True, "message": "Credential updated successfully"}
    except Exception as e:
        return handle_exception_on_proxy(e)

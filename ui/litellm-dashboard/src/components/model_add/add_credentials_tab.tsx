import React, { useEffect, useState } from "react";
import { Form, Button, Tooltip, Typography, Select as AntdSelect, Modal } from "antd";
import type { UploadProps } from "antd/es/upload";
import { Providers, providerLogoMap } from "../provider_info_helpers";
import ProviderSpecificFields from "../add_model/provider_specific_fields";
import { TextInput } from "@tremor/react";
import { CredentialItem } from "../networking";
const { Title, Link } = Typography;

interface AddCredentialsModalProps {
  isVisible: boolean;
  onCancel: () => void;
  onAddCredential: (values: any) => void;
  onUpdateCredential: (values: any) => void;
  uploadProps: UploadProps;
  addOrEdit: "add" | "edit";
  existingCredential: CredentialItem | null;
}

const AddCredentialsModal: React.FC<AddCredentialsModalProps> = ({
  isVisible,
  onCancel,
  onAddCredential,
  onUpdateCredential,
  uploadProps,
  addOrEdit,
  existingCredential,
}) => {
  const [form] = Form.useForm();
  const [selectedProvider, setSelectedProvider] = useState<Providers>(Providers.OpenAI);
  const [showAdvancedSettings, setShowAdvancedSettings] = useState(false);

  const handleSubmit = (values: any) => {
    const filteredValues = Object.entries(values).reduce((acc, [key, value]) => {
      if (value !== "" && value !== undefined && value !== null) {
        acc[key] = value;
      }
      return acc;
    }, {} as any);
    if (addOrEdit === "add") {
      onAddCredential(filteredValues);
    } else {
      onUpdateCredential(filteredValues);
    }
    form.resetFields();
  };

  // Helper to check if a value is masked (contains asterisks pattern)
  const isMaskedValue = (value: any): boolean => {
    if (typeof value !== "string") return false;
    return value.includes("****") || value.includes("***");
  };

  // Filter out masked values from credential values for edit mode
  const getNonSensitiveValues = (credentialValues: Record<string, any>) => {
    const sensitiveKeys = ["api_key", "token", "secret", "password", "authorization"];
    const result: Record<string, any> = {};
    
    for (const [key, value] of Object.entries(credentialValues)) {
      const isKeyLikelySensitive = sensitiveKeys.some(sk => key.toLowerCase().includes(sk));
      // Skip sensitive keys or any masked values
      if (isKeyLikelySensitive || isMaskedValue(value)) {
        continue;
      }
      result[key] = value;
    }
    return result;
  };

  useEffect(() => {
    if (existingCredential) {
      // Don't pre-fill sensitive fields (like api_key) with masked values
      // User should leave them blank to keep existing, or enter new value
      const nonSensitiveValues = getNonSensitiveValues(existingCredential.credential_values || {});
      
      form.setFieldsValue({
        credential_name: existingCredential.credential_name,
        custom_llm_provider: existingCredential.credential_info.custom_llm_provider,
        // Only set non-sensitive values that aren't masked
        ...nonSensitiveValues,
      });
      setSelectedProvider(existingCredential.credential_info.custom_llm_provider as Providers);
    }
  }, [existingCredential]);

  return (
    <Modal
      title={addOrEdit === "add" ? "Add New Credential" : "Edit Credential"}
      visible={isVisible}
      onCancel={() => {
        onCancel();
        form.resetFields();
      }}
      footer={null}
      width={600}
    >
      <Form form={form} onFinish={handleSubmit} layout="vertical">
        {/* Credential Name */}
        <Form.Item
          label="Credential Name:"
          name="credential_name"
          rules={[{ required: true, message: "Credential name is required" }]}
          initialValue={existingCredential?.credential_name}
        >
          <TextInput
            placeholder="Enter a friendly name for these credentials"
            disabled={existingCredential?.credential_name ? true : false}
          />
        </Form.Item>

        {/* Provider Selection */}
        <Form.Item
          rules={[{ required: true, message: "Required" }]}
          label="Provider:"
          name="custom_llm_provider"
          tooltip="Helper to auto-populate provider specific fields"
        >
          <AntdSelect
            showSearch
            onChange={(value) => {
              setSelectedProvider(value as Providers);
              form.setFieldValue("custom_llm_provider", value);
            }}
          >
            {Object.entries(Providers).map(([providerEnum, providerDisplayName]) => (
              <AntdSelect.Option key={providerEnum} value={providerEnum}>
                <div className="flex items-center space-x-2">
                  <img
                    src={providerLogoMap[providerDisplayName]}
                    alt={`${providerEnum} logo`}
                    className="w-5 h-5"
                    onError={(e) => {
                      const target = e.target as HTMLImageElement;
                      const parent = target.parentElement;
                      if (parent) {
                        const fallbackDiv = document.createElement("div");
                        fallbackDiv.className =
                          "w-5 h-5 rounded-full bg-gray-200 flex items-center justify-center text-xs";
                        fallbackDiv.textContent = providerDisplayName.charAt(0);
                        parent.replaceChild(fallbackDiv, target);
                      }
                    }}
                  />
                  <span>{providerDisplayName}</span>
                </div>
              </AntdSelect.Option>
            ))}
          </AntdSelect>
        </Form.Item>

        {/* Hint for edit mode */}
        {addOrEdit === "edit" && (
          <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-md">
            <p className="text-sm text-blue-700">
              <strong>Note:</strong> Leave sensitive fields (like API Key) blank to keep the existing value.
              Only fill in fields you want to update.
            </p>
          </div>
        )}

        <ProviderSpecificFields selectedProvider={selectedProvider} uploadProps={uploadProps} />

        {/* Modal Footer */}
        <div className="flex justify-between items-center">
          <Tooltip title="Get help on our github">
            <Link href="https://github.com/BerriAI/litellm/issues">Need Help?</Link>
          </Tooltip>

          <div>
            <Button
              onClick={() => {
                onCancel();
                form.resetFields();
              }}
              style={{ marginRight: 10 }}
            >
              Cancel
            </Button>
            <Button htmlType="submit">{addOrEdit === "add" ? "Add Credential" : "Update Credential"}</Button>
          </div>
        </div>
      </Form>
    </Modal>
  );
};

export default AddCredentialsModal;

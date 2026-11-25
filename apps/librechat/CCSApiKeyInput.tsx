// Adapted from CC Switch ApiKeyInput.tsx; provenance and license: CCS-UPSTREAM.md.
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Eye, EyeOff } from 'lucide-react';

interface ApiKeyInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  required?: boolean;
  label?: string;
  id?: string;
  labelAside?: ReactNode;
  hint?: ReactNode;
}

export default function ApiKeyInput({
  value, onChange, placeholder, disabled = false, required = false,
  label = 'API Key', id = 'apiKey', labelAside, hint,
}: ApiKeyInputProps) {
  const [showKey, setShowKey] = useState(false);
  useEffect(() => { if (!value) setShowKey(false); }, [value]);

  return (
    <div className="ccs-key-field">
      <div className="ccs-key-heading">
        <label htmlFor={id}>{label}</label>
        {labelAside}
      </div>
      <div className="ccs-key-control">
        <input
          type={showKey ? 'text' : 'password'}
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder ?? '粘贴提供方的 API Key'}
          disabled={disabled}
          required={required}
          aria-required={required || undefined}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
        />
        {!disabled && value && (
          <button
            type="button"
            onClick={() => setShowKey(!showKey)}
            aria-label={showKey ? '隐藏 API Key' : '显示 API Key'}
            aria-pressed={showKey}
          >
            {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        )}
      </div>
      {hint && <p className="demo-muted">{hint}</p>}
    </div>
  );
}

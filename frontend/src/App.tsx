import React, { useState } from 'react';

export default function App() {
  const [copied, setCopied] = useState(false);

  const copyCommand = () => {
    navigator.clipboard.writeText('python3 -m bridge.server');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        background: '#09090b',
        color: '#f4f4f5',
        fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px 16px',
        boxSizing: 'border-box',
        width: '100%',
      }}
    >
      {/* Container matching mobile p2p dashboard max-width */}
      <div
        style={{
          width: '100%',
          maxWidth: 400,
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
          boxSizing: 'border-box',
        }}
      >
        {/* Header - from docs/index.html */}
        <header
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '2px 0 6px 0',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: '#22c55e',
                boxShadow: '0 0 8px rgba(34, 197, 94, 0.35)',
              }}
            />
            <span style={{ fontSize: 14, fontWeight: 600, letterSpacing: '-0.01em', color: '#f4f4f5' }}>
              Prompt Bridge
            </span>
          </div>

          <div
            style={{
              fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
              fontSize: 9.5,
              fontWeight: 600,
              borderRadius: 12,
              padding: '2px 7px',
              letterSpacing: '0.02em',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              color: '#22c55e',
              background: 'rgba(34, 197, 94, 0.12)',
              border: '1px solid rgba(34, 197, 94, 0.3)',
            }}
          >
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'currentColor' }} />
            P2P E2EE
          </div>
        </header>

        {/* Connection Status Banner - Borrowed directly from .conn-status-banner in docs/index.html */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            background: '#141417',
            border: '1px solid #27272a',
            borderRadius: 12,
            padding: '12px 14px',
          }}
        >
          <div
            style={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: '#22c55e',
              boxShadow: '0 0 10px rgba(34, 197, 94, 0.35)',
              flexShrink: 0,
            }}
          />
          <div>
            <div style={{ fontSize: 13.5, fontWeight: 600, color: '#f4f4f5' }}>
              P2P Encrypted Tunnel
            </div>
            <div style={{ fontSize: 11.5, color: '#8e8e93', marginTop: 1 }}>
              Direct End-to-End Encrypted Relay
            </div>
          </div>
        </div>

        {/* Target Support Chips */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            flexWrap: 'wrap',
          }}
        >
          {['AGY', 'Claude', 'Codex', 'OpenCode', 'Zsh'].map((agent) => (
            <span
              key={agent}
              style={{
                fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
                fontSize: 11,
                fontWeight: 500,
                color: '#a1a1aa',
                background: '#141417',
                border: '1px solid #27272a',
                borderRadius: 8,
                padding: '4px 10px',
              }}
            >
              {agent}
            </span>
          ))}
        </div>

        {/* Connection Details List - Borrowed directly from .conn-details-list in docs/index.html */}
        <div
          style={{
            background: '#141417',
            border: '1px solid #27272a',
            borderRadius: 12,
            padding: '4px 12px',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '9px 0',
              borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
              fontSize: 12.5,
            }}
          >
            <span style={{ color: '#8e8e93' }}>Security</span>
            <span style={{ color: '#f4f4f5', fontWeight: 500, fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace', fontSize: 11 }}>
              CTR-HMAC-SHA256 (E2EE)
            </span>
          </div>

          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '9px 0',
              borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
              fontSize: 12.5,
            }}
          >
            <span style={{ color: '#8e8e93' }}>Relay Broker</span>
            <span style={{ color: '#f4f4f5', fontWeight: 500, fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace', fontSize: 11 }}>
              broker.emqx.io:8084
            </span>
          </div>

          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '9px 0',
              borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
              fontSize: 12.5,
            }}
          >
            <span style={{ color: '#8e8e93' }}>Injection Method</span>
            <span style={{ color: '#f4f4f5', fontWeight: 500, fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace', fontSize: 11 }}>
              os.write(master_fd)
            </span>
          </div>

          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '9px 0',
              fontSize: 12.5,
            }}
          >
            <span style={{ color: '#8e8e93' }}>Daemon Port</span>
            <span style={{ color: '#f4f4f5', fontWeight: 500, fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace', fontSize: 11 }}>
              127.0.0.1:8765
            </span>
          </div>
        </div>

        {/* Start Daemon Command Snippet */}
        <div
          onClick={copyCommand}
          style={{
            background: '#141417',
            border: '1px solid #27272a',
            borderRadius: 10,
            padding: '10px 14px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
            fontSize: 12,
            cursor: 'pointer',
            transition: 'border-color 0.15s ease',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.borderColor = '#52525b')}
          onMouseLeave={(e) => (e.currentTarget.style.borderColor = '#27272a')}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: '#22c55e' }}>$</span>
            <span style={{ color: '#f4f4f5' }}>python3 -m bridge.server</span>
          </div>
          <span style={{ fontSize: 11, color: copied ? '#22c55e' : '#71717a' }}>
            {copied ? 'Copied' : 'Copy'}
          </span>
        </div>
      </div>
    </div>
  );
}

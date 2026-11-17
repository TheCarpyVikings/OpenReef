'use client';

import { useState, type FormEvent } from 'react';
import { apiFetch, withIngressPath } from '@/lib/api-fetch';

export default function LoginPage() {
    const [secret, setSecret] = useState('');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);

    async function login(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setBusy(true);
        setError('');
        try {
            const response = await apiFetch('/api/auth/session', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ secret }),
            });
            setSecret('');
            if (response.ok) { window.location.assign(withIngressPath('/')); return; }
            setError(response.status === 429 ? 'Too many attempts. Wait a minute and try again.'
                : response.status === 503 ? 'Dashboard authentication needs to be configured on the server.'
                    : 'Sign-in failed. Check your access secret and try again.');
        } catch {
            setError('Unable to reach the dashboard. Please try again.');
        } finally { setBusy(false); }
    }

    return <main style={{ maxWidth: 420, margin: '15vh auto', padding: 24 }}>
        <h1>Sign in to OpenReef</h1>
        <p>Enter the access secret configured for this dashboard.</p>
        <form onSubmit={login} style={{ display: 'grid', gap: 16, marginTop: 24 }}>
            <label htmlFor="access-secret">Access secret</label>
            <input id="access-secret" type="password" autoComplete="current-password" required
                maxLength={256} value={secret} onChange={(event) => setSecret(event.target.value)} />
            <button type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
            {error && <p role="alert">{error}</p>}
        </form>
    </main>;
}

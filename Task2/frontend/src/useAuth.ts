import { useState, useEffect } from 'react';

const AUTH_API_URL = process.env.AUTH_APP_URL || 'http://localhost:3001';

interface AuthState {
    authenticated: boolean;
    loading: boolean;
}

export function useAuth(): AuthState & { login: () => void; logout: () => void } {
    const [state, setState] = useState<AuthState>({ authenticated: false, loading: true });

    useEffect(() => {
        fetch(`${AUTH_API_URL}/auth/me`, { credentials: 'include' })
            .then((res) => {
                setState({ authenticated: res.ok, loading: false });
            })
            .catch(() => {
                setState({ authenticated: false, loading: false });
            });
    }, []);

    const login = () => {
        window.location.href = `${AUTH_API_URL}/auth/login`;
    };

    const logout = () => {
        window.location.href = `${AUTH_API_URL}/auth/logout`;
    };

    return { ...state, login, logout };
}
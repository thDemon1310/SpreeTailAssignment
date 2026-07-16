import { createContext, useContext, useState, useEffect } from 'react';
import api from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const triggerRefresh = () => {
    setRefreshTrigger(prev => prev + 1);
  };

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    const username = localStorage.getItem('username');
    const userId = localStorage.getItem('user_id');
    
    if (token && username) {
      const parsedId = userId ? parseInt(userId, 10) : null;
      setUser({ id: parsedId, username });
      
      // Fetch full details asynchronously to refresh user ID if missing
      api.get('/auth/me/')
        .then(({ data }) => {
          localStorage.setItem('user_id', data.id);
          setUser(data);
        })
        .catch(() => {});
    }
    setLoading(false);
  }, []);

  const login = async (username, accessToken, refreshToken) => {
    localStorage.setItem('access_token', accessToken);
    localStorage.setItem('refresh_token', refreshToken);
    localStorage.setItem('username', username);
    setUser({ username });

    try {
      const { data } = await api.get('/auth/me/');
      localStorage.setItem('user_id', data.id);
      setUser(data);
    } catch (err) {
      console.error('Failed to fetch user details during login:', err);
    }
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('username');
    localStorage.removeItem('user_id');
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refreshTrigger, triggerRefresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}

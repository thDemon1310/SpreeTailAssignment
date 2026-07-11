import { useAuth } from '../context/AuthContext';
import './Dashboard.css';

export default function DashboardPage() {
  const { user } = useAuth();

  return (
    <div className="dashboard">
      <div className="page-header">
        <h1>Welcome back, {user?.username} 👋</h1>
        <p className="page-subtitle">Here&apos;s your expense overview</p>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'hsla(250, 80%, 60%, 0.12)', color: 'hsl(250, 80%, 65%)' }}>📊</div>
          <div className="stat-info">
            <span className="stat-label">Total Groups</span>
            <span className="stat-value">—</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'hsla(160, 70%, 45%, 0.12)', color: 'hsl(160, 70%, 45%)' }}>💰</div>
          <div className="stat-info">
            <span className="stat-label">Total Expenses</span>
            <span className="stat-value">—</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'hsla(35, 90%, 55%, 0.12)', color: 'hsl(35, 90%, 55%)' }}>⚖️</div>
          <div className="stat-info">
            <span className="stat-label">You Owe</span>
            <span className="stat-value">—</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'hsla(280, 70%, 55%, 0.12)', color: 'hsl(280, 70%, 55%)' }}>🤝</div>
          <div className="stat-info">
            <span className="stat-label">Owed to You</span>
            <span className="stat-value">—</span>
          </div>
        </div>
      </div>

      <div className="dashboard-placeholder">
        <p>Expense data will appear here once groups and expenses are created.</p>
      </div>
    </div>
  );
}

import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api/client';
import './Dashboard.css';

export default function DashboardPage() {
  const { user, refreshTrigger } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [stats, setStats] = useState({
    totalGroups: 0,
    totalExpenses: 0,
    youOwe: 0,
    owedToYou: 0,
  });
  const [groups, setGroups] = useState([]);
  const [balances, setBalances] = useState({}); // groupId -> user balance in that group

  useEffect(() => {
    fetchDashboardData();
  }, [refreshTrigger, user?.id]);

  const fetchDashboardData = async () => {
    setLoading(true);
    setError('');
    try {
      // 1. Resolve user ID if missing from local state
      let currentUserId = user?.id;
      if (!currentUserId && localStorage.getItem('access_token')) {
        const { data: meData } = await api.get('/auth/me/');
        currentUserId = meData.id;
      }

      // 2. Fetch groups
      const { data: groupsData } = await api.get('/groups/');
      setGroups(groupsData);

      let totalExpensesCount = 0;
      let totalYouOweSum = 0;
      let totalOwedToYouSum = 0;
      const groupBalancesMap = {};

      // 3. Query details in parallel for each group
      if (groupsData.length > 0) {
        await Promise.all(
          groupsData.map(async (group) => {
            // Fetch expenses
            const { data: expensesData } = await api.get(`/groups/${group.id}/expenses/`);
            totalExpensesCount += expensesData.length;

            // Fetch balances
            const { data: balancesData } = await api.get(`/groups/${group.id}/balances/`);
            
            if (currentUserId && balancesData[currentUserId]) {
              const userBal = parseFloat(balancesData[currentUserId]);
              groupBalancesMap[group.id] = userBal;
              if (userBal < 0) {
                totalYouOweSum += Math.abs(userBal);
              } else if (userBal > 0) {
                totalOwedToYouSum += userBal;
              }
            } else {
              groupBalancesMap[group.id] = 0;
            }
          })
        );
      }

      setBalances(groupBalancesMap);
      setStats({
        totalGroups: groupsData.length,
        totalExpenses: totalExpensesCount,
        youOwe: totalYouOweSum,
        owedToYou: totalOwedToYouSum,
      });
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
      setError('Could not load overview statistics.');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <div className="page dashboard"><p>Loading overview stats...</p></div>;
  }

  return (
    <div className="dashboard">
      <div className="page-header">
        <h1>Welcome back, {user?.username} 👋</h1>
        <p className="page-subtitle">Here&apos;s your expense overview</p>
      </div>

      {error && <div className="error-banner mb-4">{error}</div>}

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'hsla(250, 80%, 60%, 0.12)', color: 'hsl(250, 80%, 65%)' }}>📊</div>
          <div className="stat-info">
            <span className="stat-label">Total Groups</span>
            <span className="stat-value">{stats.totalGroups}</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'hsla(160, 70%, 45%, 0.12)', color: 'hsl(160, 70%, 45%)' }}>💰</div>
          <div className="stat-info">
            <span className="stat-label">Total Expenses</span>
            <span className="stat-value">{stats.totalExpenses}</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'hsla(35, 90%, 55%, 0.12)', color: 'hsl(35, 90%, 55%)' }}>⚖️</div>
          <div className="stat-info">
            <span className="stat-label">You Owe</span>
            <span className="stat-value">INR {stats.youOwe.toFixed(2)}</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'hsla(280, 70%, 55%, 0.12)', color: 'hsl(280, 70%, 55%)' }}>🤝</div>
          <div className="stat-info">
            <span className="stat-label">Owed to You</span>
            <span className="stat-value">INR {stats.owedToYou.toFixed(2)}</span>
          </div>
        </div>
      </div>

      {stats.totalGroups === 0 ? (
        <div className="dashboard-placeholder">
          <p>Expense data will appear here once groups and expenses are created.</p>
        </div>
      ) : (
        <div className="dashboard-sections fade-in">
          <h2>Your Groups Summary</h2>
          <div className="group-cards-grid">
            {groups.map(group => {
              const userBal = balances[group.id] || 0;
              const balClass = userBal > 0 ? 'positive' : (userBal < 0 ? 'negative' : 'neutral');
              return (
                <div key={group.id} className="group-card-item">
                  <div className="group-card-header">
                    <h3>{group.name}</h3>
                    <p className="group-card-desc">{group.description || 'No description provided.'}</p>
                  </div>
                  <div className="group-card-footer">
                    <span className="group-card-bal-label">Your Balance</span>
                    <span className={`group-card-bal-val ${balClass}`}>
                      {userBal > 0 ? '+' : ''}{userBal.toFixed(2)} INR
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

(async () => {
  try {
    const base = 'http://localhost:4001/api/v1';
    const adminEmail = 'admin@trustpay.africa';
    const adminPassword = 'AdminPass123!';

    const post = async (path, body) => {
      const res = await fetch(`${base}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      return res.json().catch(() => null);
    };

    const get = async (path, token) => {
      const res = await fetch(`${base}${path}`, {
        method: 'GET',
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      return res.json().catch(() => null);
    };

    const login = await post('/auth/login', { email: adminEmail, password: adminPassword });
    const token = login.data.accessToken;
    const docs = await get('/transactions/txn-1/documents', token);
    console.log('documents:', JSON.stringify(docs, null, 2));
  } catch (e) {
    console.error(e);
    process.exit(1);
  }
})();

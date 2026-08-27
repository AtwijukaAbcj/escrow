(async () => {
  try {
    const base = 'http://localhost:4001/api/v1';
    const adminEmail = 'admin@trustpay.africa';
    const adminPassword = 'AdminPass123!';

    const post = async (path, body, token) => {
      const res = await fetch(`${base}${path}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      });
      return res.json().catch(() => null);
    };

    const login = await post('/auth/login', { email: adminEmail, password: adminPassword });
    if (!login || !login.data) throw new Error('Admin login failed');
    const token = login.data.accessToken;
    console.log('Admin token acquired');

    const upload = await post('/transactions/txn-1/documents', { name: 'Proof of Ownership', type: 'title' }, token);
    console.log('Upload response:', JSON.stringify(upload, null, 2));
  } catch (e) {
    console.error(e);
    process.exit(1);
  }
})();

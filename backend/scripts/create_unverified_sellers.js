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

    const sellerEmails = ['pending.user.1@example.com','pending.user.2@example.com','pending.user.3@example.com'];
    for (const email of sellerEmails) {
      const res = await post('/transactions', { buyerId: 'party-1', sellerEmail: email, sellerName: email.split('@')[0], description: 'Test tx creating seller ' + email, value: 1000 }, token);
      console.log('Created txn for', email, '=>', JSON.stringify(res));
    }

    console.log('Done');
  } catch (e) {
    console.error(e);
    process.exit(1);
  }
})();

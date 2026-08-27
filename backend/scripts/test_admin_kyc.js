const fetch = require('node-fetch');

const BASE = 'http://localhost:4001/api/v1';

async function login() {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'admin@trustpay.africa', password: 'AdminPass123!' }),
  });
  const json = await res.json();
  return json.data;
}

(async () => {
  try {
    const tokens = await login();
    console.log('Admin logged in.');
    const pendingRes = await fetch(`${BASE}/kyc/pending`, { headers: { Authorization: `Bearer ${tokens.accessToken}` } });
    console.log('Status:', pendingRes.status);
    const text = await pendingRes.text();
    console.log('Body:', text.slice(0, 1000));
    if (pending.data && pending.data.length > 0) {
      for (const p of pending.data) {
        const docsRes = await fetch(`${BASE}/kyc/participant/${p.id}/documents`, { headers: { Authorization: `Bearer ${tokens.accessToken}` } });
        const docs = await docsRes.json();
        console.log(`Docs for ${p.id}:`, JSON.stringify(docs, null, 2));
      }
    } else {
      console.log('No pending participants found.');
    }
  } catch (e) {
    console.error('Error:', e);
  }
})();

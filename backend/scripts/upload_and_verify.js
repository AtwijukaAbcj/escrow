(async () => {
  try {
    const base = 'http://localhost:4001/api/v1';

    // Buyer credentials created earlier
    const buyerEmail = 'seed.buyer.login.1786557688245@example.com';
    const buyerPassword = 'BuyerPass123!';

    // Admin credentials
    const adminEmail = 'admin@trustpay.africa';
    const adminPassword = 'AdminPass123!';

    // Helper
    const post = async (path, body, token) => {
      const res = await fetch(`${base}${path}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      });
      const json = await res.json().catch(() => null);
      return { status: res.status, json };
    };

    const get = async (path, token) => {
      const res = await fetch(`${base}${path}`, {
        method: 'GET',
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      const json = await res.json().catch(() => null);
      return { status: res.status, json };
    };

    // Login buyer
    const loginBuyer = await post('/auth/login', { email: buyerEmail, password: buyerPassword });
    if (!loginBuyer.json || !loginBuyer.json.data) throw new Error('Buyer login failed: ' + JSON.stringify(loginBuyer));
    const buyerToken = loginBuyer.json.data.accessToken;
    console.log('Buyer logged in');

    // Upload a document to txn-1
    const uploadRes = await post('/transactions/txn-1/documents', { name: 'ID Front', type: 'id' }, buyerToken);
    console.log('Upload response', uploadRes.status, JSON.stringify(uploadRes.json));
    if (!uploadRes.json || !uploadRes.json.data) throw new Error('Upload failed');
    const doc = uploadRes.json.data;

    // Login admin
    const loginAdmin = await post('/auth/login', { email: adminEmail, password: adminPassword });
    if (!loginAdmin.json || !loginAdmin.json.data) throw new Error('Admin login failed');
    const adminToken = loginAdmin.json.data.accessToken;
    console.log('Admin logged in');

    // Verify the document
    const verifyRes = await post(`/transactions/txn-1/documents/${doc.id}/verify`, { status: 'verified', comment: 'Matches ID' }, adminToken);
    console.log('Verify response', verifyRes.status, JSON.stringify(verifyRes.json));

    // Fetch documents list
    const docsList = await get('/transactions/txn-1/documents', adminToken);
    console.log('Documents list', JSON.stringify(docsList.json, null, 2));

    process.exit(0);
  } catch (e) {
    console.error(e);
    process.exit(1);
  }
})();

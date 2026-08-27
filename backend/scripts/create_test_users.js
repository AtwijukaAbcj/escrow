(async () => {
  try {
    const now = Date.now();
    const base = 'http://localhost:4001/api/v1';
    const buyerEmail = `seed.buyer.login.${now}@example.com`;
    const sellerEmail = `seed.seller.login.${now}@example.com`;

    const buyer = {
      tenantId: 'default-tenant',
      accountType: 'individual',
      email: buyerEmail,
      phoneNumber: '+256700000100',
      name: 'Seed Buyer Login',
      roles: ['buyer'],
      password: 'BuyerPass123!'
    };

    const seller = {
      tenantId: 'default-tenant',
      accountType: 'individual',
      email: sellerEmail,
      phoneNumber: '+256700000101',
      name: 'Seed Seller Login',
      roles: ['seller'],
      password: 'SellerPass123!'
    };

    const reg = async (p) => {
      const res = await fetch(`${base}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(p),
      });
      return res.json();
    };

    const bres = await reg(buyer);
    const sres = await reg(seller);
    console.log('buyerReg', JSON.stringify(bres));
    console.log('sellerReg', JSON.stringify(sres));

    const verify = async (id) => {
      const res = await fetch(`${base}/kyc/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ partyId: id }),
      });
      return res.json();
    };

    await verify(bres.data.id);
    await verify(sres.data.id);

    console.log('\nCreated credentials:');
    console.log('Buyer:', buyerEmail, 'Password: BuyerPass123!');
    console.log('Seller:', sellerEmail, 'Password: SellerPass123!');
  } catch (e) {
    console.error('error', e);
    process.exit(1);
  }
})();

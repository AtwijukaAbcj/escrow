import { Router } from 'express';
import { registerUser, authenticateUser, refreshAuthToken, revokeRefreshToken } from '../services/authService';
import { readUsers } from '../infra/storage';
import { parties } from '../data';

const router = Router();

router.post('/register', async (req, res) => {
  try {
    const user = await registerUser(req.body);
    res.status(201).json({ data: { id: user.id, email: user.email, name: user.name, tenantId: user.tenantId, roles: user.roles } });
  } catch (error) {
    res.status(400).json({ error: String(error) });
  }
});

router.post('/login', async (req, res) => {
  try {
    const tokens = await authenticateUser(req.body);
    const users = readUsers();
    const user = users.find((item) => item.email === req.body.email);
    const party = user ? parties.find((item) => item.email === user.email) : undefined;
    const hasBuyerSellerRole = user?.roles.some((role: string) => role === 'buyer' || role === 'seller');
    const kycRequired = Boolean(hasBuyerSellerRole && (!party || !party.kycVerified));

    res.json({ data: { ...tokens, kycRequired } });
  } catch (error) {
    res.status(401).json({ error: String(error) });
  }
});

router.post('/refresh', (req, res) => {
  try {
    const tokens = refreshAuthToken(req.body.refreshToken);
    res.json({ data: tokens });
  } catch (error) {
    res.status(401).json({ error: String(error) });
  }
});

router.post('/logout', (req, res) => {
  try {
    revokeRefreshToken(req.body.refreshToken);
    res.json({ data: { message: 'Logged out' } });
  } catch (error) {
    res.status(400).json({ error: String(error) });
  }
});

export default router;

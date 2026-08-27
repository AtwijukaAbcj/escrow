import path from 'path';
import dotenv from 'dotenv';

const envPath = path.resolve(__dirname, '../.env');
dotenv.config({ path: envPath });

const parseOrigins = (value?: string) => {
  if (!value) {
    return ['http://localhost:5173', 'http://localhost:5174', 'http://localhost:5175', 'http://localhost:5176'];
  }
  return value
    .split(',')
    .map((origin) => origin.trim())
    .filter(Boolean);
};

export const config = {
  port: Number(process.env.PORT || 4001),
  jwtSecret: process.env.JWT_SECRET || 'change-this-secret-in-production',
  jwtExpiresIn: process.env.JWT_EXPIRES_IN || '15m',
  refreshTokenExpiresInDays: Number(process.env.REFRESH_TOKEN_DAYS || 30),
  databaseFile: process.env.DATABASE_FILE || path.resolve(process.cwd(), 'data/trustpay.sqlite'),
  frontendOrigins: parseOrigins(process.env.FRONTEND_ORIGIN),
  rateLimitWindowMs: 15 * 60 * 1000,
  rateLimitMaxRequests: 200,
};

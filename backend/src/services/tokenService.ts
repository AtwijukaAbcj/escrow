import jwt, { SignOptions } from 'jsonwebtoken';
import { v4 as uuid } from 'uuid';
import { config } from '../config';
import { RefreshToken } from '../domain/models/user';

export interface JwtPayload {
  sub: string;
  tenantId: string;
  roles: string[];
  tokenId: string;
}

export const createAccessToken = (payload: JwtPayload): string => {
  const options: SignOptions = { expiresIn: config.jwtExpiresIn as SignOptions['expiresIn'] };
  return jwt.sign(payload, config.jwtSecret, options);
};

export const verifyAccessToken = (token: string): JwtPayload => {
  return jwt.verify(token, config.jwtSecret) as JwtPayload;
};

export const createRefreshToken = (userId: string): RefreshToken => {
  const expiresAt = new Date(Date.now() + config.refreshTokenExpiresInDays * 24 * 60 * 60 * 1000).toISOString();
  return {
    token: uuid(),
    userId,
    expiresAt,
    createdAt: new Date().toISOString(),
  };
};

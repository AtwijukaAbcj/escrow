import { v4 as uuid } from 'uuid';
import { User, RefreshToken, UserRole } from '../domain/models/user';
import { hashPassword, comparePassword } from './passwordService';
import { createAccessToken, createRefreshToken, JwtPayload } from './tokenService';
import { readUsers, writeUsers, readRefreshTokens, writeRefreshTokens } from '../infra/storage';
import { parties, Party } from '../data';

const getUsers = (): User[] => readUsers();
const getRefreshTokens = (): RefreshToken[] => readRefreshTokens();

export interface RegisterRequest {
  tenantId?: string;
  accountType: 'individual' | 'business';
  email: string;
  phoneNumber: string;
  name: string;
  companyName?: string;
  registrationNumber?: string;
  roles?: string[];
  password: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export const registerUser = async (payload: RegisterRequest): Promise<User> => {
  const users = getUsers();
  if (users.some((user) => user.email === payload.email)) {
    throw new Error('Email already registered');
  }

  if (!payload.email || !payload.phoneNumber || !payload.name || !payload.password) {
    throw new Error('Please provide your account details');
  }

  const passwordHash = await hashPassword(payload.password);
  const defaultTenantId = payload.tenantId || 'default-tenant';
  const selectedRoles = (payload.roles ?? []).filter((role) => ['buyer', 'seller'].includes(role)) as UserRole[];
  const defaultRoles: UserRole[] = payload.accountType === 'business' ? ['BUSINESS_OWNER'] : ['ROLE_USER'];
  const assignedRoles: UserRole[] = selectedRoles.length ? selectedRoles : defaultRoles;
  const displayName = payload.accountType === 'business' ? payload.companyName || payload.name : payload.name;

  const user: User = {
    id: uuid(),
    tenantId: defaultTenantId,
    email: payload.email,
    phoneNumber: payload.phoneNumber,
    name: displayName,
    passwordHash,
    roles: assignedRoles,
    isEmailVerified: false,
    isPhoneVerified: false,
    mfaEnabled: false,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };

  users.push(user);
  writeUsers(users);

  const partyRole = assignedRoles.find((role) => role === 'buyer' || role === 'seller') as 'buyer' | 'seller' | undefined;
  if (partyRole) {
    const existingParty = parties.find((party) => party.id === user.id);
    if (!existingParty) {
      parties.push({
        id: user.id,
        name: displayName,
        role: partyRole,
        email: user.email,
        phone: user.phoneNumber,
        kycVerified: false,
      });
    }
  }

  return user;
};

export const authenticateUser = async (payload: LoginRequest): Promise<{ accessToken: string; refreshToken: string }> => {
  const users = getUsers();
  const user = users.find((item) => item.email === payload.email);
  if (!user) {
    throw new Error('Invalid credentials');
  }

  const validPassword = await comparePassword(payload.password, user.passwordHash);
  if (!validPassword) {
    throw new Error('Invalid credentials');
  }

  const jwtPayload: JwtPayload = {
    sub: user.id,
    tenantId: user.tenantId,
    roles: user.roles,
    tokenId: uuid(),
  };

  const accessToken = createAccessToken(jwtPayload);
  const refreshToken = createRefreshToken(user.id);
  const refreshTokens = getRefreshTokens();
  refreshTokens.push(refreshToken);
  writeRefreshTokens(refreshTokens);

  return { accessToken, refreshToken: refreshToken.token };
};

export const refreshAuthToken = (token: string): { accessToken: string; refreshToken: string } => {
  const refreshTokens = getRefreshTokens();
  const stored = refreshTokens.find((item) => item.token === token && !item.revokedAt);
  if (!stored) {
    throw new Error('Invalid refresh token');
  }
  if (new Date(stored.expiresAt) < new Date()) {
    throw new Error('Refresh token expired');
  }

  const users = getUsers();
  const user = users.find((item) => item.id === stored.userId);
  if (!user) {
    throw new Error('Invalid token owner');
  }

  const jwtPayload: JwtPayload = {
    sub: user.id,
    tenantId: user.tenantId,
    roles: user.roles,
    tokenId: uuid(),
  };

  const accessToken = createAccessToken(jwtPayload);
  const newRefreshToken = createRefreshToken(user.id);
  stored.revokedAt = new Date().toISOString();
  stored.replacedByToken = newRefreshToken.token;
  refreshTokens.push(newRefreshToken);
  writeRefreshTokens(refreshTokens);

  return { accessToken, refreshToken: newRefreshToken.token };
};

export const revokeRefreshToken = (token: string): void => {
  const refreshTokens = getRefreshTokens();
  const stored = refreshTokens.find((item) => item.token === token);
  if (!stored) {
    throw new Error('Refresh token not found');
  }
  stored.revokedAt = new Date().toISOString();
  writeRefreshTokens(refreshTokens);
};

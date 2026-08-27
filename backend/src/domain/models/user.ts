export type UserRole =
  | 'system_admin'
  | 'compliance_officer'
  | 'buyer'
  | 'seller'
  | 'business'
  | 'lawyer'
  | 'surveyor'
  | 'engineer'
  | 'inspector'
  | 'marketplace'
  | 'bank'
  | 'customer_support'
  | 'dispute_officer'
  | 'finance_officer'
  | 'developer'
  | 'api_client'
  | 'ROLE_USER'
  | 'BUSINESS_OWNER';

export interface User {
  id: string;
  tenantId: string;
  email: string;
  phoneNumber: string;
  name: string;
  passwordHash: string;
  roles: UserRole[];
  isEmailVerified: boolean;
  isPhoneVerified: boolean;
  mfaEnabled: boolean;
  mfaSecret?: string;
  createdAt: string;
  updatedAt: string;
}

export interface RefreshToken {
  token: string;
  userId: string;
  expiresAt: string;
  createdAt: string;
  revokedAt?: string;
  replacedByToken?: string;
}

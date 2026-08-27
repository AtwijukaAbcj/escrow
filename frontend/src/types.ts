export type UserRole = 'buyer' | 'seller' | 'inspector';

export interface Party {
  id: string;
  name: string;
  role: UserRole;
  email: string;
  phone: string;
  kycVerified: boolean;
}

export type TransactionStatus =
  | 'draft'
  | 'pending_payment'
  | 'escrowed'
  | 'verifying'
  | 'completed'
  | 'disputed'
  | 'cancelled';

export interface Contract {
  id: string;
  title: string;
  description: string;
  terms: string;
  signedByBuyer: boolean;
  signedBySeller: boolean;
  createdAt: string;
}

export interface Milestone {
  id: string;
  title: string;
  amount: number;
  completed: boolean;
}

export interface Transaction {
  id: string;
  buyerId: string;
  sellerId: string;
  description: string;
  value: number;
  status: TransactionStatus;
  contract: Contract;
  milestones: Milestone[];
  escrowBalance: number;
  createdAt: string;
}

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
  kycRequired?: boolean;
}

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

export interface TransactionParticipant {
  id: string;
  displayName: string;
  email: string;
  accountType: string;
  kycStatus: string;
  role: UserRole;
}

export interface KycParticipant {
  id: string;
  name: string;
  accountType: string;
  identityVerification: string;
  businessVerification: string;
  overallStatus: string;
  restrictions: string[];
}

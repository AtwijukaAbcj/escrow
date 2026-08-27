export type UserRole = 'buyer' | 'seller' | 'inspector';

export interface Party {
  id: string;
  name: string;
  role: UserRole;
  email: string;
  phone: string;
  kycVerified: boolean;
  verificationHistory?: Array<{ id: string; timestamp: string; actorId?: string; action: string; comment?: string; method?: string }>;
}

export type TransactionStatus =
  | 'draft'
  | 'awaiting_acceptance'
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

export interface TransactionEvent {
  timestamp: string;
  actorId?: string;
  action: string;
  details?: string;
}

export type DocumentStatus = 'pending' | 'submitted' | 'verified' | 'rejected' | 'flagged';

export interface Document {
  id: string;
  name: string;
  type: string;
  uploadedBy?: string;
  status: DocumentStatus;
  comment?: string;
  verifiedBy?: string;
  verifiedAt?: string;
  createdAt: string;
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
  documents?: Document[];
  escrowBalance: number;
  createdAt: string;
  events?: TransactionEvent[];
}

const now = () => new Date().toISOString();

import { readParties, readTransactions } from './infra/storage';

const persistedParties = readParties();
const persistedTransactions = readTransactions();

export const parties: Party[] = persistedParties && persistedParties.length > 0 ? persistedParties : [
  {
    id: 'party-1',
    name: 'Amina Kyalo',
    role: 'buyer',
    email: 'amina@example.com',
    phone: '+256700000001',
    kycVerified: true,
  },
  {
    id: 'party-2',
    name: 'Samuel Okello',
    role: 'seller',
    email: 'samuel@example.com',
    phone: '+256700000002',
    kycVerified: true,
  },
];

export const transactions: Transaction[] = persistedTransactions && persistedTransactions.length > 0 ? persistedTransactions : [
  {
    id: 'txn-1',
    buyerId: 'party-1',
    sellerId: 'party-2',
    description: 'Vehicle purchase escrow for Toyota Prado',
    value: 140000000,
    status: 'pending_payment',
    contract: {
      id: 'contract-1',
      title: 'Vehicle Purchase Agreement',
      description: 'Buyer deposits funds to escrow while seller verifies vehicle ownership documents.',
      terms: 'Seller provides authentic vehicle documents and completes ownership transfer before funds are released.',
      signedByBuyer: false,
      signedBySeller: false,
      createdAt: now(),
    },
    milestones: [
      { id: 'ms-1', title: 'Vehicle documents verified', amount: 42000000, completed: false },
      { id: 'ms-2', title: 'Ownership transfer initiated', amount: 84000000, completed: false },
      { id: 'ms-3', title: 'Vehicle delivered and approved', amount: 14000000, completed: false },
    ],
    escrowBalance: 0,
    createdAt: now(),
    events: [
      { timestamp: now(), action: 'created', details: 'Seed transaction created' },
    ],
  },
];

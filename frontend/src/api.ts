import { Party, Transaction, AuthTokens, RegisterRequest, LoginRequest, KycParticipant, TransactionParticipant } from './types';

const BASE = 'http://localhost:4001/api/v1';
const AUTH_STORAGE_KEY = 'trustpay-auth-tokens';

const getStoredAuthTokens = (): AuthTokens | null => {
  const stored = localStorage.getItem(AUTH_STORAGE_KEY);
  return stored ? (JSON.parse(stored) as AuthTokens) : null;
};

const setStoredAuthTokens = (tokens: AuthTokens | null): void => {
  if (tokens) {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(tokens));
  } else {
    localStorage.removeItem(AUTH_STORAGE_KEY);
  }
};

async function unauthedRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.error || 'Request failed');
  }
  return res.json();
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const authTokens = getStoredAuthTokens();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string>),
  };
  if (authTokens?.accessToken) {
    headers.Authorization = `Bearer ${authTokens.accessToken}`;
  }

  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers,
  });

  if (res.ok) {
    return res.json();
  }

  if (res.status === 401 && authTokens?.refreshToken) {
    try {
      const refreshed = await refreshToken(authTokens.refreshToken);
      setStoredAuthTokens(refreshed);
      const retryHeaders = {
        ...headers,
        Authorization: `Bearer ${refreshed.accessToken}`,
      };
      const retryRes = await fetch(`${BASE}${path}`, {
        ...init,
        headers: retryHeaders,
      });
      if (retryRes.ok) {
        return retryRes.json();
      }
      const body = await retryRes.json().catch(() => null);
      throw new Error(body?.error || 'Request failed');
    } catch {
      setStoredAuthTokens(null);
      throw new Error('Session expired. Please sign in again.');
    }
  }

  const body = await res.json().catch(() => null);
  throw new Error(body?.error || 'Request failed');
}

export const fetchTransactionParticipants = async (userIds?: string[]): Promise<TransactionParticipant[]> => {
  const query = userIds && userIds.length > 0 ? `?userIds=${userIds.join(',')}` : '';
  const response = await request<{ data: TransactionParticipant[] }>(`/users/transaction-participants${query}`);
  return response.data;
};

export const fetchKycParticipants = async (userIds?: string[]): Promise<KycParticipant[]> => {
  const query = userIds && userIds.length > 0 ? `?userIds=${userIds.join(',')}` : '';
  const response = await request<{ data: KycParticipant[] }>(`/kyc/participants${query}`);
  return response.data;
};

export const fetchPendingKycParticipants = async (page = 1, pageSize = 10, query = '') => {
  const params = new URLSearchParams();
  params.set('page', String(page));
  params.set('pageSize', String(pageSize));
  if (query) params.set('q', query);
  const response = await request<{ data: any[]; meta?: { total: number; page: number; pageSize: number } }>(`/kyc/pending?${params.toString()}`);
  return { items: response.data, meta: response.meta };
};

export const fetchParticipantKycDocuments = async (participantId: string) => {
  const response = await request<{ data: { transactionId: string; document: any }[] }>(`/kyc/participant/${participantId}/documents`);
  return response.data;
};

export const fetchParticipantKycProfile = async (participantId: string) => {
  const response = await request<{ data: { party: any; documents: { transactionId: string; document: any }[]; relatedTransactions: any[] } }>(`/kyc/participant/${participantId}/profile`);
  return response.data;
};

export const unverifyParticipant = async (participantId: string, comment?: string) => {
  const response = await request<{ data: any }>(`/kyc/participant/${participantId}/unverify`, {
    method: 'POST',
    body: JSON.stringify({ comment }),
  });
  return response.data;
};

export const autoVerifyParticipantNin = async (participantId: string, nin: string, name?: string) => {
  const response = await request<{ data: any }>(`/kyc/participant/${participantId}/auto-verify`, {
    method: 'POST',
    body: JSON.stringify({ nin, name }),
  });
  return response.data;
};

export const fetchTransactions = async (): Promise<Transaction[]> => {
  const response = await request<{ data: Transaction[] }>('/transactions');
  return response.data;
};

export const fetchTransactionById = async (transactionId: string): Promise<Transaction> => {
  const response = await request<{ data: Transaction }>(`/transactions/${transactionId}`);
  return response.data;
};

export const fetchParties = async (): Promise<Party[]> => {
  const response = await request<{ data: Party[] }>('/parties');
  return response.data;
};

export const createTransaction = async (payload: { buyerId?: string; sellerId?: string; sellerEmail?: string; sellerName?: string; description: string; value: number }): Promise<Transaction> => {
  const response = await request<{ data: Transaction }>('/transactions', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data;
};

export const registerUser = async (payload: RegisterRequest): Promise<void> => {
  await unauthedRequest('/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
};

export const loginUser = async (payload: LoginRequest): Promise<AuthTokens> => {
  const response = await unauthedRequest<{ data: AuthTokens }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  const tokens = response.data;
  setStoredAuthTokens(tokens);
  return tokens;
};

export const refreshToken = async (refreshToken: string): Promise<AuthTokens> => {
  const response = await unauthedRequest<{ data: AuthTokens }>('/auth/refresh', {
    method: 'POST',
    body: JSON.stringify({ refreshToken }),
  });
  const tokens = response.data;
  setStoredAuthTokens(tokens);
  return tokens;
};

export const logoutUser = async (refreshToken: string): Promise<void> => {
  await unauthedRequest('/auth/logout', {
    method: 'POST',
    body: JSON.stringify({ refreshToken }),
  });
  setStoredAuthTokens(null);
};

export const verifyKyc = async (partyId: string, comment?: string): Promise<Party> => {
  const response = await request<{ data: Party }>('/kyc/verify', {
    method: 'POST',
    body: JSON.stringify({ partyId, comment }),
  });
  return response.data;
};

export const depositTransaction = async (transactionId: string, amount: number): Promise<Transaction> => {
  const response = await request<{ data: Transaction }>(`/transactions/${transactionId}/deposit`, {
    method: 'POST',
    body: JSON.stringify({ amount }),
  });
  return response.data;
};

export const refundTransaction = async (transactionId: string, amount?: number): Promise<Transaction> => {
  const response = await request<{ data: Transaction }>(`/transactions/${transactionId}/refund`, {
    method: 'POST',
    body: JSON.stringify({ amount }),
  });
  return response.data;
};

export const reconcilePayments = async (): Promise<{ totalTransactions: number; totalEscrow: number; completed: number; disputed: number }> => {
  const response = await request<{ data: { totalTransactions: number; totalEscrow: number; completed: number; disputed: number } }>('/payments/reconcile', {
    method: 'POST',
  });
  return response.data;
};

export const completeMilestone = async (transactionId: string, milestoneId: string): Promise<Transaction> => {
  const response = await request<{ data: Transaction }>(`/transactions/${transactionId}/milestones/${milestoneId}/complete`, {
    method: 'POST',
  });
  return response.data;
};

export const releaseTransaction = async (transactionId: string): Promise<Transaction> => {
  const response = await request<{ data: Transaction }>(`/transactions/${transactionId}/release`, {
    method: 'POST',
  });
  return response.data;
};

export const disputeTransaction = async (transactionId: string): Promise<Transaction> => {
  const response = await request<{ data: Transaction }>(`/transactions/${transactionId}/dispute`, {
    method: 'POST',
  });
  return response.data;
};

export const signContract = async (contractId: string, role: 'buyer' | 'seller'): Promise<Transaction> => {
  const response = await request<{ data: Transaction }>(`/contracts/${contractId}/sign`, {
    method: 'POST',
    body: JSON.stringify({ role }),
  });
  return response.data;
};

export const fetchTransactionDocuments = async (transactionId: string) => {
  const response = await request<{ data: any[] }>(`/transactions/${transactionId}/documents`);
  return response.data;
};

export const uploadTransactionDocument = async (transactionId: string, payload: { name: string; type: string }) => {
  const response = await request<{ data: any }>(`/transactions/${transactionId}/documents`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data;
};

export const uploadTransactionDocumentFile = async (transactionId: string, file: File, type?: string) => {
  const authTokens = getStoredAuthTokens();
  const form = new FormData();
  form.append('file', file);
  if (type) form.append('type', type);

  const headers: any = {};
  if (authTokens?.accessToken) headers.Authorization = `Bearer ${authTokens.accessToken}`;

  const res = await fetch(`${BASE}/transactions/${transactionId}/documents/upload`, {
    method: 'POST',
    headers,
    body: form,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.error || 'Upload failed');
  }

  return res.json().then((r) => r.data);
};

export const verifyTransactionDocument = async (transactionId: string, docId: string, payload: { status: 'verified' | 'rejected' | 'flagged'; comment?: string }) => {
  const response = await request<{ data: any }>(`/transactions/${transactionId}/documents/${docId}/verify`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data;
};

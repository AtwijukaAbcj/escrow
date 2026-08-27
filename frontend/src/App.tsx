import { useEffect, useState } from 'react';
import { Transaction, Party, AuthTokens, RegisterRequest, LoginRequest, KycParticipant, TransactionParticipant } from './types';
import {
  completeMilestone,
  createTransaction,
  depositTransaction,
  disputeTransaction,
  fetchKycParticipants,
  fetchTransactionParticipants,
  fetchTransactions,
  loginUser,
  logoutUser,
  registerUser,
  releaseTransaction,
  refundTransaction,
  reconcilePayments,
  signContract,
  verifyKyc,
  uploadTransactionDocumentFile,
} from './api';

const AUTH_STORAGE_KEY = 'trustpay-auth-tokens';

const decodeJwtRoles = (accessToken?: string): string[] => {
  if (!accessToken) {
    return [];
  }

  const parts = accessToken.split('.');
  if (parts.length < 2) {
    return [];
  }

  try {
    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const normalized = payload.padEnd(Math.ceil(payload.length / 4) * 4, '=');
    const decoded = JSON.parse(atob(normalized));
    const roles = decoded.roles ?? decoded.role ?? [];
    return Array.isArray(roles) ? roles : [roles];
  } catch {
    return [];
  }
};

const decodeJwtPayload = (accessToken?: string): any => {
  if (!accessToken) return {};
  try {
    const parts = accessToken.split('.');
    if (parts.length < 2) return {};
    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const normalized = payload.padEnd(Math.ceil(payload.length / 4) * 4, '=');
    return JSON.parse(atob(normalized));
  } catch {
    return {};
  }
};

function App() {
  const [parties, setParties] = useState<Party[]>([]);
  const [kycParticipants, setKycParticipants] = useState<KycParticipant[]>([]);
  const [pendingKyc, setPendingKyc] = useState<any[]>([]);
  const [pendingKycPage, setPendingKycPage] = useState(1);
  const [pendingKycPageSize, setPendingKycPageSize] = useState(10);
  const [pendingKycTotal, setPendingKycTotal] = useState(0);
  const [pendingKycQuery, setPendingKycQuery] = useState('');
  const [adminKycDocs, setAdminKycDocs] = useState<Array<{ transactionId: string; document: any }>>([]);
  const [currentKycProfile, setCurrentKycProfile] = useState<any | null>(null);
  const [verificationHistory, setVerificationHistory] = useState<any[]>([]);
  const [selectedKycParticipant, setSelectedKycParticipant] = useState<string | null>(null);
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditTxn, setAuditTxn] = useState<Transaction | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [participantsError, setParticipantsError] = useState<string | null>(null);
  const [kycError, setKycError] = useState<string | null>(null);
  const [transactionsError, setTransactionsError] = useState<string | null>(null);
  const [creationError, setCreationError] = useState<string | null>(null);
  const [loadingParticipants, setLoadingParticipants] = useState(false);
  const [loadingKyc, setLoadingKyc] = useState(false);
  const [loadingTransactions, setLoadingTransactions] = useState(false);
  const [creatingTransaction, setCreatingTransaction] = useState(false);
  const [newTransaction, setNewTransaction] = useState({ buyerId: '', sellerId: '', sellerEmail: '', sellerName: '', description: '', value: 0 });
  const [depositAmounts, setDepositAmounts] = useState<Record<string, number>>({});
  const [kycDocUploaded, setKycDocUploaded] = useState(false);
  const [kycSubmitted, setKycSubmitted] = useState(false);
  const [kycActionMessage, setKycActionMessage] = useState<string | null>(null);
  const [kycFormType, setKycFormType] = useState<'individual' | 'business' | 'transaction'>('individual');
  const [individualKyc, setIndividualKyc] = useState<any>({});
  const [businessKyc, setBusinessKyc] = useState<any>({});
  const [transactionKyc, setTransactionKyc] = useState<any>({});
  const [authTokens, setAuthTokens] = useState<AuthTokens | null>(() => {
    const stored = localStorage.getItem(AUTH_STORAGE_KEY);
    return stored ? (JSON.parse(stored) as AuthTokens) : null;
  });
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [authForm, setAuthForm] = useState<RegisterRequest & { password: string; confirmPassword: string; accountType: 'individual' | 'business' }>({
    accountType: 'individual',
    email: '',
    phoneNumber: '',
    name: '',
    companyName: '',
    registrationNumber: '',
    roles: [],
    password: '',
    confirmPassword: '',
  });

  const [activeModule, setActiveModule] = useState('Dashboard');
  const [activeSubmodule, setActiveSubmodule] = useState('Overview');
  const [requiresKyc, setRequiresKyc] = useState(false);

  const userRoles = decodeJwtRoles(authTokens?.accessToken);
  const canAccessAdmin = userRoles.some((role) => ['system_admin', 'compliance_officer', 'dispute_officer', 'finance_officer'].includes(role));
  const isBuyer = userRoles.includes('buyer');
  const isSeller = userRoles.includes('seller');
  const jwtPayload = decodeJwtPayload(authTokens?.accessToken);
  const currentUserId = jwtPayload?.sub ?? jwtPayload?.id ?? jwtPayload?.userId ?? null;

  const baseModuleNavigation = [
    { title: 'Dashboard', items: [] },
    { title: 'Transactions', items: ['Create', 'Active', 'Completed', 'Archived'] },
    { title: 'Escrow', items: ['Active', 'Funding', 'Releases', 'Refunds'] },
    { title: 'Participants', items: ['Individuals', 'Businesses', 'Buyers', 'Sellers'] },
    { title: 'Verification', items: ['Identity KYC', 'Business KYC', 'Documents', 'Risk Reviews'] },
    { title: 'Contracts', items: ['Templates', 'Drafts', 'Pending Signatures', 'Signed'] },
    { title: 'Payments', items: ['Deposits', 'Releases', 'Refunds', 'Reconciliation'] },
    { title: 'Disputes', items: [] },
    { title: 'Reports', items: [] },
    { title: 'API & Integrations', items: [] },
    { title: 'Settings', items: [] },
  ];

  // Determine visible modules based on roles
  const buyerModuleNavigation = [
    { title: 'Dashboard', items: [] },
    { title: 'My Transactions', items: [] },
    { title: 'My Escrows', items: [] },
    { title: 'Contracts', items: [] },
    { title: 'Payments', items: [] },
    { title: 'Deliveries', items: [] },
    { title: 'KYC', items: [] },
    { title: 'Disputes', items: [] },
    { title: 'Notifications', items: [] },
    { title: 'Settings', items: [] },
  ];

  const sellerModuleNavigation = [
    { title: 'Dashboard', items: [] },
    { title: 'KYC', items: [] },
    { title: 'My Sales', items: [] },
    { title: 'Contracts', items: [] },
    { title: 'Deliveries', items: [] },
    { title: 'Milestones', items: [] },
    { title: 'Payments Received', items: [] },
    { title: 'Disputes', items: [] },
    { title: 'Documents', items: [] },
    { title: 'Settings', items: [] },
  ];

  const visibleModuleNavigation = (() => {
    if (canAccessAdmin) return baseModuleNavigation;
    if (isSeller) return sellerModuleNavigation;
    if (isBuyer) return buyerModuleNavigation;
    return [{ title: 'Dashboard', items: [] }, { title: 'Settings', items: [] }];
  })();

  const moduleNavigation = visibleModuleNavigation;
  const kycModuleName = isBuyer || isSeller ? 'KYC' : 'Verification';
  const handleGoToKyc = () => {
    setActiveModule(kycModuleName);
    setActiveSubmodule('Overview');
  };

  const moduleIcons: Record<string, string> = {
    Dashboard: '🏠',
    Transactions: '🔁',
    Escrow: '🛡️',
    Participants: '👥',
    Verification: '✅',
    KYC: '🪪',
    Contracts: '📄',
    Payments: '💳',
    Disputes: '⚖️',
    Reports: '📊',
    'API & Integrations': '🔌',
    Settings: '⚙️',
  };

  const itemIcons: Record<string, string> = {
    Create: '🆕',
    Active: '▶️',
    Completed: '✅',
    Archived: '🗄️',
    Funding: '💰',
    Releases: '🚀',
    Refunds: '🔄',
    Individuals: '👤',
    Businesses: '🏢',
    Buyers: '🛒',
    Sellers: '🏷️',
    'Identity KYC': '🪪',
    'Business KYC': '🧾',
    Documents: '📑',
    'Risk Reviews': '⚠️',
    Templates: '📄',
    Drafts: '✍️',
    'Pending Signatures': '🖊️',
    Signed: '✅',
    Deposits: '💵',
    Reconciliation: '🔍',
  };

  // add icons for buyer view modules
  moduleIcons['My Transactions'] = '💼';
  moduleIcons['My Escrows'] = '💰';
  moduleIcons['Deliveries'] = '📦';
  moduleIcons['Notifications'] = '🔔';

  // seller icons
  moduleIcons['KYC'] = '🪪';
  moduleIcons['My Sales'] = '🛒';
  moduleIcons['Milestones'] = '🏁';
  moduleIcons['Payments Received'] = '💵';
  moduleIcons['Documents'] = '📁';

  const getModuleIcon = (title: string) => moduleIcons[title] ?? '•';
  const getItemIcon = (item: string) => itemIcons[item] ?? '•';

  const handleModuleChange = (module: string, submodule?: string) => {
    setActiveModule(module);
    if (submodule) {
      setActiveSubmodule(submodule);
      return;
    }

    const group = moduleNavigation.find((item) => item.title === module);
    if (group?.items?.length) {
      setActiveSubmodule(group.items[0]);
    } else {
      setActiveSubmodule('Overview');
    }
  };

  const activeSection = activeModule === 'Dashboard' ? 'Overview' : activeSubmodule;

  useEffect(() => {
    if (authTokens) {
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(authTokens));
    } else {
      localStorage.removeItem(AUTH_STORAGE_KEY);
    }
  }, [authTokens]);

  useEffect(() => {
    if (!authTokens) {
      setRequiresKyc(false);
      return;
    }

    if (authTokens.kycRequired) {
      setRequiresKyc(true);
      setActiveModule(kycModuleName);
      setActiveSubmodule('Overview');
      return;
    }

    setRequiresKyc(false);
    if (isSeller) {
      setActiveModule('Dashboard');
      setActiveSubmodule('Overview');
    } else if (isBuyer) {
      setActiveModule('Dashboard');
      setActiveSubmodule('Overview');
    } else if (canAccessAdmin) {
      setActiveModule('Dashboard');
      setActiveSubmodule('Overview');
    }
  }, [authTokens, canAccessAdmin, isBuyer, isSeller, kycModuleName]);

  const loadParticipants = async () => {
    setLoadingParticipants(true);
    setParticipantsError(null);
    try {
      const userIds = (isBuyer || isSeller) && currentUserId ? [currentUserId] : undefined;
      const partiesData = await fetchTransactionParticipants(userIds);
      setParties(partiesData.map((item) => ({
        id: item.id,
        name: item.displayName,
        role: item.role as 'buyer' | 'seller' | 'inspector',
        email: item.email,
        phone: '',
        kycVerified: item.kycStatus === 'Verified',
      })));
      setParticipantsError(null);
    } catch (err) {
      const msg = String(err);
      setParticipantsError(msg);
      if (msg.toLowerCase().includes('auth') || msg.toLowerCase().includes('session')) {
        setAuthTokens(null);
      }
    } finally {
      setLoadingParticipants(false);
    }
  };

  const loadKyc = async (selectedUserIds: string[] = []) => {
    setLoadingKyc(true);
    setKycError(null);
    try {
      const userIds = (isBuyer || isSeller) && currentUserId ? [currentUserId] : selectedUserIds.length ? selectedUserIds : undefined;
      const kycData = await fetchKycParticipants(userIds);
      setKycParticipants(kycData);
      setKycError(null);
    } catch (err) {
      const msg = String(err);
      setKycError(msg);
      if (msg.toLowerCase().includes('auth') || msg.toLowerCase().includes('session')) {
        setAuthTokens(null);
      }
    } finally {
      setLoadingKyc(false);
    }
  };

  const loadTransactions = async () => {
    setLoadingTransactions(true);
    setTransactionsError(null);
    try {
      const txnsData = await fetchTransactions();
      setTransactions(txnsData);
      setTransactionsError(null);
    } catch (err) {
      const msg = String(err);
      setTransactionsError(msg);
      if (msg.toLowerCase().includes('auth') || msg.toLowerCase().includes('session')) {
        setAuthTokens(null);
      }
    } finally {
      setLoadingTransactions(false);
    }
  };

  useEffect(() => {
    if (!authTokens) {
      return;
    }
    loadParticipants();
    loadTransactions();
    loadKyc();
    if (canAccessAdmin) loadPendingKyc();
  }, [authTokens, currentUserId, isBuyer, isSeller]);

  const loadPendingKyc = async (page = pendingKycPage, pageSize = pendingKycPageSize, query = pendingKycQuery) => {
    try {
      const resp = await fetchPendingKycParticipants(page, pageSize, query);
      setPendingKyc(resp.items ?? []);
      setPendingKycTotal(resp.meta?.total ?? 0);
      setPendingKycPage(resp.meta?.page ?? page);
      setPendingKycPageSize(resp.meta?.pageSize ?? pageSize);
    } catch (e) {
      // ignore for now
    }
  };

  const openParticipantKyc = async (participantId: string) => {
    try {
      setSelectedKycParticipant(participantId);
      const profile = await fetchParticipantKycProfile(participantId);
      setCurrentKycProfile(profile.party ?? null);
      setAdminKycDocs(profile.documents ?? []);
      setVerificationHistory(profile.party?.verificationHistory ?? []);
      // keep related txns handy
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };

  const openAuditForTransaction = async (transactionId: string) => {
    try {
      const txn = await fetchTransactionById(transactionId);
      setAuditTxn(txn);
      setAuditOpen(true);
    } catch (e) {
      setError(String(e));
    }
  };

  const closeAudit = () => {
    setAuditOpen(false);
    setAuditTxn(null);
  };

  const handleAutoVerify = async (participantId: string) => {
    try {
      const nin = prompt('Enter participant NIN (14 digits) for auto-check');
      if (!nin) return;
      const nameInput = prompt('Enter participant name to match (optional, improves accuracy)');
      const result = await autoVerifyParticipantNin(participantId, nin, nameInput || undefined);
      setError(null);
      // refresh lists
      await loadPendingKyc();
      await loadKyc();
      alert(`Auto-verify result: ${result.result}\nChecks: ${JSON.stringify(result.checks)}`);
    } catch (e) {
      setError(String(e));
    }
  };

  const exportAuditCsv = (txn: Transaction) => {
    try {
      const rows: string[] = [];
      const headers = ['type', 'timestamp', 'actorId', 'action', 'details', 'docId', 'docName', 'docType', 'status', 'fileUrl', 'comment', 'verifiedBy', 'verifiedAt'];
      rows.push(headers.join(','));

      // events
      (txn.events ?? []).forEach((ev) => {
        const row = [
          'event',
          JSON.stringify(ev.timestamp || ''),
          JSON.stringify(ev.actorId || ''),
          JSON.stringify(ev.action || ''),
          JSON.stringify(ev.details || ''),
          '', '', '', '', '', '', '', '',
        ];
        rows.push(row.join(','));
      });

      // documents
      (txn.documents ?? []).forEach((d: any) => {
        const row = [
          'document',
          JSON.stringify(d.createdAt || ''),
          JSON.stringify(d.uploadedBy || ''),
          JSON.stringify('document'),
          JSON.stringify(d.name || ''),
          JSON.stringify(d.id || ''),
          JSON.stringify(d.name || ''),
          JSON.stringify(d.type || ''),
          JSON.stringify(d.status || ''),
          JSON.stringify(d.fileUrl || ''),
          JSON.stringify(d.comment || ''),
          JSON.stringify(d.verifiedBy || ''),
          JSON.stringify(d.verifiedAt || ''),
        ];
        rows.push(row.join(','));
      });

      const csv = rows.join('\n');
      const blob = new Blob([csv], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `audit-${txn.id}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(String(e));
    }
  };

  const loadAllData = async () => {
    await Promise.all([loadParticipants(), loadTransactions(), loadKyc()]);
  };

  const updateTransaction = (updated: Transaction) => {
    setTransactions((current) => current.map((txn) => (txn.id === updated.id ? updated : txn)));
  };

  const handleCreate = async () => {
    setCreatingTransaction(true);
    setCreationError(null);
    try {
      const transaction = await createTransaction(newTransaction);
      setTransactions((current) => [...current, transaction]);
      setNewTransaction({ buyerId: '', sellerId: '', description: '', value: 0 });
      setCreationError(null);
    } catch (e) {
      const msg = String(e);
      setCreationError(msg);
      if (msg.toLowerCase().includes('auth') || msg.toLowerCase().includes('session')) {
        setAuthTokens(null);
      }
    } finally {
      setCreatingTransaction(false);
    }
  };

  const handleRegister = async () => {
    try {
      if (authForm.password !== authForm.confirmPassword) {
        setError('Passwords do not match.');
        return;
      }

      const payload: RegisterRequest = {
        tenantId: 'default-tenant',
        accountType: authForm.accountType,
        email: authForm.email,
        phoneNumber: authForm.phoneNumber,
        name: authForm.accountType === 'business' ? authForm.companyName || authForm.name : authForm.name,
        companyName: authForm.accountType === 'business' ? authForm.companyName : undefined,
        registrationNumber: authForm.accountType === 'business' ? authForm.registrationNumber : undefined,
        roles: authForm.roles && authForm.roles.length ? authForm.roles : undefined,
        password: authForm.password,
      };
      await registerUser(payload);
      setAuthMode('login');
      setError('Registration complete. Please log in.');
    } catch (e) {
      setError(String(e));
    }
  };

  const handleLogin = async () => {
    try {
      const payload: LoginRequest = { email: authForm.email, password: authForm.password };
      const tokens = await loginUser(payload);
      setAuthTokens(tokens);
      if (tokens.kycRequired) {
        setError('Your buyer/seller account requires KYC verification before full access.');
      } else {
        setError(null);
      }
    } catch (e) {
      setError(String(e));
    }
  };

  const handleLogout = async () => {
    if (!authTokens) {
      return;
    }

    try {
      await logoutUser(authTokens.refreshToken);
    } catch {
      // ignore logout errors
    }
    setAuthTokens(null);
    setTransactions([]);
    setParties([]);
    setKycParticipants([]);
    setParticipantsError(null);
    setKycError(null);
    setTransactionsError(null);
    setCreationError(null);
  };

  const handleVerify = async (partyId: string) => {
    try {
      const comment = prompt('Optional justification/comment for verification (recommended)');
      const updated = await verifyKyc(partyId, comment || undefined);
      setParties((current) => current.map((party) => (party.id === updated.id ? updated : party)));
      setKycParticipants((current) => current.map((item) => (item.id === updated.id ? {
        ...item,
        identityVerification: 'Verified',
        overallStatus: 'Verified',
      } : item)));
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleKycFileChange = (which: 'individual' | 'business' | 'transaction', key: string, file: File | null) => {
    if (which === 'individual') setIndividualKyc((s: any) => ({ ...s, [key]: file }));
    if (which === 'business') setBusinessKyc((s: any) => ({ ...s, [key]: file }));
    if (which === 'transaction') setTransactionKyc((s: any) => ({ ...s, [key]: file }));
  };

  const handleSubmitKycForm = async () => {
    // Basic client-side submission flow: mark submitted and show feedback.
    setKycSubmitted(true);
    setKycActionMessage('KYC submitted for review. We will notify you when verification completes.');
    // Optionally send files/metadata to backend when ready. For now we simulate submission.
  };

  const handleUploadKycDocument = () => {
    setKycDocUploaded(true);
    setKycActionMessage('ID documents uploaded successfully. You can now submit your KYC for review.');
  };

  const handleSubmitKyc = async () => {
    if (!currentUserId) {
      setKycActionMessage('Unable to submit KYC without a valid user session.');
      return;
    }

    if (!kycDocUploaded) {
      setKycActionMessage('Please upload your verification documents before submitting.');
      return;
    }

    try {
      setKycSubmitted(true);
      setKycActionMessage('Submitting verification for review...');
      const updated = await verifyKyc(currentUserId);
      setParties((current) => current.map((party) => (party.id === updated.id ? updated : party)));
      setKycParticipants((current) => current.map((item) => (item.id === updated.id ? {
        ...item,
        identityVerification: 'Verified',
        overallStatus: 'Verified',
      } : item)));
      setKycActionMessage('Your KYC is verified. Full access has been granted.');
      setRequiresKyc(false);
    } catch (e) {
      setKycActionMessage(String(e));
    }
  };

  const handleDeposit = async (transactionId: string) => {
    try {
      const amount = depositAmounts[transactionId] ?? 0;
      const updated = await depositTransaction(transactionId, amount);
      updateTransaction(updated);
      setDepositAmounts((current) => ({ ...current, [transactionId]: 0 }));
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleUploadDocument = async (transactionId: string) => {
    try {
      const name = prompt('Document name (e.g., ID front)');
      if (!name) return;
      const type = prompt('Document type (e.g., id, proof_of_address)') || 'other';

      // prompt user to select a file — if a file is chosen, upload it; otherwise send metadata-only
      const fileInput = document.createElement('input');
      fileInput.type = 'file';
      fileInput.accept = '*/*';
      fileInput.style.display = 'none';
      document.body.appendChild(fileInput);
      const filePromise: Promise<File | null> = new Promise((resolve) => {
        fileInput.onchange = () => {
          const f = fileInput.files && fileInput.files[0];
          resolve(f ?? null);
        };
        fileInput.click();
      });
      const file = await filePromise;
      if (file) {
        await uploadTransactionDocumentFile(transactionId, file, type);
      } else {
        await uploadTransactionDocument(transactionId, { name, type });
      }
      // reload transactions to pick up new document
      await loadTransactions();
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleVerifyDocument = async (transactionId: string, docId: string) => {
    try {
      const status = prompt('Set status: verified, rejected, flagged');
      if (!status) return;
      const comment = prompt('Optional comment');
      const updated = await verifyTransactionDocument(transactionId, docId, { status: status as any, comment: comment || undefined });
      // reload transactions
      await loadTransactions();
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleCompleteMilestone = async (transactionId: string, milestoneId: string) => {
    try {
      const updated = await completeMilestone(transactionId, milestoneId);
      updateTransaction(updated);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleRelease = async (transactionId: string) => {
    try {
      const updated = await releaseTransaction(transactionId);
      updateTransaction(updated);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleDispute = async (transactionId: string) => {
    try {
      const updated = await disputeTransaction(transactionId);
      updateTransaction(updated);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleRefund = async (transactionId: string) => {
    try {
      const updated = await refundTransaction(transactionId);
      updateTransaction(updated);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleSign = async (contractId: string, role: 'buyer' | 'seller') => {
    try {
      const updated = await signContract(contractId, role);
      updateTransaction(updated);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };

  const renderModuleContent = () => {
    if (activeModule === 'Dashboard') {
      const totalUsers = parties.length;
      const buyerCount = parties.filter((party) => party.role === 'buyer').length;
      const sellerCount = parties.filter((party) => party.role === 'seller').length;
      const businessCount = parties.filter((party) => party.role === 'business').length;
      const verifiedCount = parties.filter((party) => party.kycVerified).length;
      const pendingCount = totalUsers - verifiedCount;
      const totalTransactions = transactions.length;
      const activeCount = transactions.filter((txn) => txn.status !== 'completed' && txn.status !== 'cancelled').length;
      const completedCount = transactions.filter((txn) => txn.status === 'completed').length;
      const disputedCount = transactions.filter((txn) => txn.status === 'disputed').length;
      const pendingPaymentCount = transactions.filter((txn) => txn.status === 'pending_payment').length;
      const escrowTotal = transactions.reduce((total, txn) => total + (txn.escrowBalance ?? 0), 0);
      const recentTransactions = transactions.slice(0, 4);

      return (
        <>
          <section className="panel dashboard-summary-panel">
            <div>
              <p className="eyebrow">TrustPay overview</p>
              <h2>Performance dashboard</h2>
              <p className="dashboard-intro-text">A quick view of escrow health, KYC progress, and transaction flow across your platform.</p>
            </div>
            <div className="dashboard-header-actions">
              <button type="button" onClick={loadAllData}>Refresh</button>
              <button type="button">Export report</button>
            </div>
          </section>

          <div className="dashboard-kpi-grid">
            <article className="kpi-card">
              <p className="kpi-label">Active escrows</p>
              <h3>{activeCount}</h3>
              <p>{pendingPaymentCount} pending payment</p>
            </article>
            <article className="kpi-card">
              <p className="kpi-label">Transactions</p>
              <h3>{totalTransactions}</h3>
              <p>{completedCount} completed</p>
            </article>
            <article className="kpi-card">
              <p className="kpi-label">KYC verified</p>
              <h3>{verifiedCount}</h3>
              <p>{pendingCount} review needed</p>
            </article>
            <article className="kpi-card">
              <p className="kpi-label">Escrow balance</p>
              <h3>UGX {escrowTotal.toLocaleString()}</h3>
              <p>{disputedCount} disputes open</p>
            </article>
          </div>

          <div className="dashboard-grid">
            <section className="panel chart-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Transaction trend</p>
                  <h3>Recent transaction volume</h3>
                </div>
                <div className="small-pill">Last 30 days</div>
              </div>
              <div className="line-chart-placeholder">
                <div className="line-chart-bar line-chart-bar--a" />
                <div className="line-chart-bar line-chart-bar--b" />
                <div className="line-chart-bar line-chart-bar--c" />
                <div className="line-chart-bar line-chart-bar--d" />
                <div className="line-chart-bar line-chart-bar--e" />
              </div>
            </section>

            <section className="panel status-panel">
              <div className="status-block">
                <h4>{totalUsers}</h4>
                <p>Total participants</p>
              </div>
              <div className="status-block">
                <h4>{buyerCount}</h4>
                <p>Buyers</p>
              </div>
              <div className="status-block">
                <h4>{sellerCount}</h4>
                <p>Sellers</p>
              </div>
              <div className="status-block">
                <h4>{businessCount}</h4>
                <p>Business accounts</p>
              </div>
            </section>
          </div>

          <div className="dashboard-grid dashboard-bottom-grid">
            <section className="panel recent-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Live feed</p>
                  <h3>Recent transactions</h3>
                </div>
                <button type="button">View all</button>
              </div>
              <div className="recent-list">
                {recentTransactions.length === 0 ? (
                  <p>No recent transactions available.</p>
                ) : (
                  recentTransactions.map((txn) => {
                    const buyer = parties.find((party) => party.id === txn.buyerId);
                    const seller = parties.find((party) => party.id === txn.sellerId);
                    return (
                      <div className="recent-item" key={txn.id}>
                        <div>
                          <strong>{txn.description}</strong>
                          <p>{buyer?.name ?? txn.buyerId} → {seller?.name ?? txn.sellerId}</p>
                        </div>
                        <div>
                          <span className={`status-pill status-pill--${txn.status.replace(/\s+/g, '-').toLowerCase()}`}>{txn.status}</span>
                          <p>UGX {txn.value.toLocaleString()}</p>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </section>

            <section className="panel stats-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">KYC pipeline</p>
                  <h3>Verification summary</h3>
                </div>
              </div>
              <div className="stats-grid">
                <div className="stat-card">
                  <p>Verified</p>
                  <strong>{verifiedCount}</strong>
                </div>
                <div className="stat-card">
                  <p>Pending</p>
                  <strong>{pendingCount}</strong>
                </div>
                <div className="stat-card">
                  <p>Loaded records</p>
                  <strong>{kycParticipants.length}</strong>
                </div>
              </div>
              <div className="progress-line">
                <div className="progress-fill" style={{ width: `${kycParticipants.length ? (verifiedCount / kycParticipants.length) * 100 : 0}%` }} />
              </div>
              <p className="progress-note">{kycParticipants.length ? Math.round((verifiedCount / kycParticipants.length) * 100) : 0}% of current KYC records verified</p>
            </section>
          </div>
        </>
      );
    }

    if (activeModule === 'Transactions') {
      if (activeSubmodule === 'Create') {
        const selectedBuyer = parties.find((p) => p.id === newTransaction.buyerId);
        const selectedSeller = parties.find((p) => p.id === newTransaction.sellerId);
        const buyerVerified = !!selectedBuyer?.kycVerified;
        const sellerVerified = !!selectedSeller?.kycVerified;
        const canCreate = !!(newTransaction.buyerId && newTransaction.sellerId && newTransaction.description && newTransaction.value > 0 && buyerVerified && sellerVerified);

        return (
          <section className="panel">
            <h2>Create a new escrow transaction</h2>
            {participantsError && (
              <div>
                <p className="error">Unable to load participants: {participantsError}</p>
                <button onClick={() => loadParticipants()}>Retry</button>
              </div>
            )}
            {loadingParticipants && <p>Loading participants...</p>}
            <div className="form-grid">
              <label>
                Buyer
                <select value={newTransaction.buyerId} onChange={(e) => setNewTransaction({ ...newTransaction, buyerId: e.target.value })}>
                  <option value="">Select buyer</option>
                  {parties.filter((party) => party.role === 'buyer').map((party) => (
                    <option value={party.id} key={party.id}>{party.name}</option>
                  ))}
                </select>
              </label>
              <label>
                Seller (choose existing or invite by email)
                <select value={newTransaction.sellerId} onChange={(e) => setNewTransaction({ ...newTransaction, sellerId: e.target.value, sellerEmail: '' })}>
                  <option value="">Select seller</option>
                  {parties.filter((party) => party.role === 'seller').map((party) => (
                    <option value={party.id} key={party.id}>{party.name}</option>
                  ))}
                </select>
              </label>
              <label>
                Seller email (invite)
                <input value={newTransaction.sellerEmail} onChange={(e) => setNewTransaction({ ...newTransaction, sellerEmail: e.target.value, sellerId: '' })} placeholder="seller@example.com" />
              </label>
              <label>
                Seller name (optional)
                <input value={newTransaction.sellerName} onChange={(e) => setNewTransaction({ ...newTransaction, sellerName: e.target.value })} placeholder="Seller name" />
              </label>
              <label>
                Description
                <input value={newTransaction.description} onChange={(e) => setNewTransaction({ ...newTransaction, description: e.target.value })} />
              </label>
              <label>
                Value (UGX)
                <input type="number" min="1" value={newTransaction.value} onChange={(e) => setNewTransaction({ ...newTransaction, value: Number(e.target.value) })} />
              </label>
            </div>
            {creationError && <p className="error">Transaction creation failed: {creationError}</p>}
                {!buyerVerified || (!sellerVerified && !newTransaction.sellerEmail) ? (
                  <p className="error">Both buyer and seller must have verified KYC before creating a transaction (or invite seller by email).</p>
                ) : null}
            <button onClick={handleCreate} disabled={creatingTransaction || loadingParticipants || !canCreate}>
              {creatingTransaction ? 'Creating…' : 'Create Transaction'}
            </button>
          </section>
        );
      }

      if (activeSubmodule === 'Active') {
        return (
          <section className="panel">
            <h2>Active transactions</h2>
            {loadingTransactions && <p>Loading active transactions...</p>}
            {transactionsError && (
              <div>
                <p className="error">Unable to load transactions: {transactionsError}</p>
                <button onClick={() => loadTransactions()}>Retry</button>
              </div>
            )}
            <div className="transaction-grid">
              {transactions.filter((txn) => txn.status !== 'completed' && txn.status !== 'cancelled').map((txn) => {
                const buyer = parties.find((party) => party.id === txn.buyerId);
                const seller = parties.find((party) => party.id === txn.sellerId);
                const depositValue = depositAmounts[txn.id] ?? 0;
                return (
                  <article className="card" key={txn.id}>
                    <h3>{txn.description}</h3>
                    <p><strong>Status:</strong> {txn.status}</p>
                    <p><strong>Value:</strong> UGX {txn.value.toLocaleString()}</p>
                    <p><strong>Escrow balance:</strong> UGX {Number(txn.escrowBalance ?? 0).toLocaleString()}</p>
                    <p><strong>Buyer:</strong> {buyer?.name ?? txn.buyerId}</p>
                    <p><strong>Seller:</strong> {seller?.name ?? txn.sellerId}</p>

                    <div style={{ marginTop: 12 }}>
                      <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <span>Deposit (UGX)</span>
                        <input type="number" min="0" value={depositValue} onChange={(e) => setDepositAmounts((cur) => ({ ...cur, [txn.id]: Number(e.target.value) }))} style={{ padding: '6px 8px', borderRadius: 8, border: '1px solid rgba(148,163,184,0.3)', width: 120 }} />
                        <button onClick={() => handleDeposit(txn.id)} disabled={depositValue <= 0}>Deposit</button>
                      </label>
                    </div>

                    {txn.milestones && txn.milestones.length > 0 && (
                      <div style={{ marginTop: 12 }}>
                        <p style={{ margin: '6px 0 8px' }}><strong>Milestones</strong></p>
                        <div style={{ display: 'grid', gap: 8 }}>
                          {txn.milestones.map((ms) => (
                            <div key={ms.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, padding: 8, borderRadius: 8, background: '#fff' }}>
                              <div>
                                <div style={{ fontWeight: 700 }}>{ms.title}</div>
                                <div style={{ fontSize: 12, color: '#475569' }}>UGX {ms.amount.toLocaleString()}</div>
                              </div>
                              <div>
                                {ms.completed ? (
                                  <span style={{ color: '#047857', fontWeight: 700 }}>Completed</span>
                                ) : (
                                  <button onClick={() => handleCompleteMilestone(txn.id, ms.id)}>Complete</button>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                      <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <button
                        onClick={() => handleRelease(txn.id)}
                        disabled={
                          txn.escrowBalance < txn.value ||
                          !txn.contract.signedByBuyer ||
                          !txn.contract.signedBySeller ||
                          !txn.milestones.every((ms) => ms.completed)
                        }
                      >
                        Release
                      </button>
                        <button onClick={() => openAuditForTransaction(txn.id)}>View audit</button>
                      <button onClick={() => handleDispute(txn.id)} disabled={txn.status === 'completed' || txn.status === 'cancelled'}>Raise dispute</button>
                      <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                        <div style={{ fontSize: 12, color: '#475569' }}>
                          Contract: {txn.contract.signedByBuyer && txn.contract.signedBySeller ? 'Fully signed' : 'Pending signatures'}
                        </div>
                        <button onClick={() => handleSign(txn.contract.id, 'buyer')} disabled={!userRoles.includes('buyer') || txn.contract.signedByBuyer}>{txn.contract.signedByBuyer ? 'Buyer signed' : 'Sign as buyer'}</button>
                        <button onClick={() => handleSign(txn.contract.id, 'seller')} disabled={!userRoles.includes('seller') || txn.contract.signedBySeller}>{txn.contract.signedBySeller ? 'Seller signed' : 'Sign as seller'}</button>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        );
      }

      if (activeSubmodule === 'Completed') {
        return (
          <section className="panel">
            <h2>Completed transactions</h2>
            <div className="transaction-grid">
              {transactions.filter((txn) => txn.status === 'completed').map((txn) => (
                <article className="card" key={txn.id}>
                  <h3>{txn.description}</h3>
                  <p><strong>Value:</strong> UGX {txn.value.toLocaleString()}</p>
                  <p><strong>Status:</strong> {txn.status}</p>
                </article>
              ))}
            </div>
          </section>
        );
      }

      return (
        <section className="panel">
          <h2>{activeSubmodule}</h2>
          <p>Module content is loading. Select a transaction submodule to continue.</p>
        </section>
      );
    }

    if (activeModule === 'Payments') {
      const sub = activeSubmodule || 'Deposits';
      const deposits = transactions.filter((t) => t.status === 'escrowed' || t.status === 'pending_payment' || t.status === 'verifying');
      return (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Payments</p>
              <h2>Manage platform payments</h2>
            </div>
            <div className="small-pill">{sub}</div>
          </div>

          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <button onClick={() => handleModuleChange('Payments', 'Deposits')}>Deposits</button>
            <button onClick={() => handleModuleChange('Payments', 'Releases')}>Releases</button>
            <button onClick={() => handleModuleChange('Payments', 'Refunds')}>Refunds</button>
            <button onClick={() => handleModuleChange('Payments', 'Reconciliation')}>Reconciliation</button>
          </div>

          {activeSubmodule === 'Deposits' && (
            <div>
              <h3>Pending deposits</h3>
              {deposits.length === 0 ? <p>No pending deposits.</p> : (
                <div className="transaction-grid">
                  {deposits.map((txn) => (
                    <article className="card" key={txn.id}>
                      <h3>{txn.description}</h3>
                      <p><strong>Value:</strong> UGX {txn.value.toLocaleString()}</p>
                      <p><strong>Escrow balance:</strong> UGX {Number(txn.escrowBalance ?? 0).toLocaleString()}</p>
                      <div style={{ marginTop: 12 }}>
                        <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                          <span>Deposit (UGX)</span>
                          <input id={`dep-${txn.id}`} type="number" min="0" defaultValue={0} style={{ padding: '6px 8px', borderRadius: 8, border: '1px solid rgba(148,163,184,0.3)', width: 120 }} />
                          <button onClick={() => {
                            const el = document.getElementById(`dep-${txn.id}`) as HTMLInputElement | null;
                            if (!el) return;
                            const amt = Number(el.value || 0);
                            if (amt > 0) depositTransaction(txn.id, amt).then(updateTransaction).catch((e) => setError(String(e)));
                          }}>Deposit</button>
                        </label>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeSubmodule === 'Releases' && (
            <div>
              <h3>Ready to release</h3>
              <div className="transaction-grid">
                {transactions.filter((t) => t.status === 'escrowed' || t.status === 'verifying').map((txn) => (
                  <article className="card" key={txn.id}>
                    <h3>{txn.description}</h3>
                    <p><strong>Escrow balance:</strong> UGX {Number(txn.escrowBalance ?? 0).toLocaleString()}</p>
                    <div style={{ marginTop: 12 }}>
                      <button onClick={() => releaseTransaction(txn.id).then(updateTransaction).catch((e) => setError(String(e)))} disabled={txn.escrowBalance < txn.value}>Release</button>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}

          {activeSubmodule === 'Refunds' && (
            <div>
              <h3>Process refunds</h3>
              <div className="transaction-grid">
                {transactions.map((txn) => (
                  <article className="card" key={txn.id}>
                    <h3>{txn.description}</h3>
                    <p><strong>Escrow balance:</strong> UGX {Number(txn.escrowBalance ?? 0).toLocaleString()}</p>
                    <div style={{ marginTop: 12 }}>
                      <button onClick={() => refundTransaction(txn.id).then(updateTransaction).catch((e) => setError(String(e)))} disabled={!(txn.escrowBalance > 0)}>Refund full</button>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}

          {activeSubmodule === 'Reconciliation' && (
            <div>
              <h3>Reconciliation</h3>
              <button onClick={async () => {
                try {
                  const summary = await reconcilePayments();
                  setError(null);
                  alert(JSON.stringify(summary, null, 2));
                } catch (e) {
                  setError(String(e));
                }
              }}>Run reconciliation</button>
            </div>
          )}
        </section>
      );
    }

    if (activeModule === 'My Transactions') {
      const myTxns = currentUserId ? transactions.filter((t) => t.buyerId === currentUserId || t.sellerId === currentUserId) : [];
      return (
        <section className="panel">
          <h2>My Transactions</h2>
          {myTxns.length === 0 ? <p>No transactions found.</p> : (
            <div className="transaction-grid">
              {myTxns.map((txn) => (
                <article className="card" key={txn.id}>
                  <h3>{txn.description}</h3>
                  <p><strong>Status:</strong> {txn.status}</p>
                  <p><strong>Value:</strong> UGX {txn.value.toLocaleString()}</p>
                </article>
              ))}
            </div>
          )}
        </section>
      );
    }

    if (activeModule === 'My Escrows') {
      const myEscrows = currentUserId ? transactions.filter((t) => t.buyerId === currentUserId || t.sellerId === currentUserId) : [];
      return (
        <section className="panel">
          <h2>My Escrows</h2>
          {myEscrows.length === 0 ? <p>No active escrows found.</p> : (
            <div className="transaction-grid">
              {myEscrows.map((txn) => (
                <article className="card" key={txn.id}>
                  <h3>{txn.description}</h3>
                  <p><strong>Escrow balance:</strong> UGX {Number(txn.escrowBalance ?? 0).toLocaleString()}</p>
                  <p><strong>Status:</strong> {txn.status}</p>
                </article>
              ))}
            </div>
          )}
        </section>
      );
    }

    if (activeModule === 'My Sales' || activeModule === 'My Sales') {
      const mySales = currentUserId ? transactions.filter((t) => t.sellerId === currentUserId) : [];
      return (
        <section className="panel">
          <h2>My Sales</h2>
          {mySales.length === 0 ? <p>No sales found.</p> : (
            <div className="transaction-grid">
              {mySales.map((txn) => (
                <article className="card" key={txn.id}>
                  <h3>{txn.description}</h3>
                  <p><strong>Value:</strong> UGX {txn.value.toLocaleString()}</p>
                  <p><strong>Status:</strong> {txn.status}</p>
                </article>
              ))}
            </div>
          )}
        </section>
      );
    }

    if (activeModule === 'Payments Received') {
      const payments = currentUserId ? transactions.filter((t) => t.sellerId === currentUserId && t.status === 'completed') : [];
      return (
        <section className="panel">
          <h2>Payments Received</h2>
          {payments.length === 0 ? <p>No received payments yet.</p> : (
            <div className="transaction-grid">
              {payments.map((txn) => (
                <article className="card" key={txn.id}>
                  <h3>{txn.description}</h3>
                  <p><strong>Amount:</strong> UGX {txn.value.toLocaleString()}</p>
                  <p><strong>Date:</strong> {new Date(txn.createdAt).toLocaleDateString()}</p>
                </article>
              ))}
            </div>
          )}
        </section>
      );
    }

    if (activeModule === 'Participants') {
      const filterBy = activeSubmodule.toLowerCase();
      const filtered = parties.filter((party) => {
        if (activeSubmodule === 'Individuals') return party.role !== 'business';
        if (activeSubmodule === 'Businesses') return party.role === 'business';
        if (activeSubmodule === 'Buyers') return party.role === 'buyer';
        if (activeSubmodule === 'Sellers') return party.role === 'seller';
        return true;
      });

      return (
        <section className="panel">
          <h2>{activeSubmodule}</h2>
          {filtered.length === 0 ? (
            <p>No participants available for this view.</p>
          ) : (
            <div className="participant-grid">
              {filtered.map((participant) => (
                <div className="card" key={participant.id}>
                  <h3>{participant.name}</h3>
                  <p><strong>Role:</strong> {participant.role}</p>
                  <p><strong>Email:</strong> {participant.email}</p>
                  <p><strong>KYC:</strong> {participant.kycVerified ? 'Verified' : 'Pending'}</p>
                </div>
              ))}
            </div>
          )}
        </section>
      );
    }

    if (activeModule === 'Verification' || activeModule === 'KYC') {
      const kycTitle = activeModule === 'KYC' ? 'Buyer / Seller KYC' : activeSubmodule;
      const currentParticipant = currentUserId ? kycParticipants.find((participant) => participant.id === currentUserId) : undefined;

      return (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{kycTitle}</p>
              <h2>{isBuyer || isSeller ? 'KYC verification for your account' : 'Verification dashboard'}</h2>
            </div>
            <button type="button" onClick={() => loadKyc(currentUserId ? [currentUserId] : [])}>Refresh</button>
          </div>

          {loadingKyc && <p>Loading verification data...</p>}
          {kycError && (
            <div>
              <p className="error">Unable to load verification data: {kycError}</p>
              <button onClick={() => loadKyc(currentUserId ? [currentUserId] : [])}>Retry</button>
            </div>
          )}

          {isBuyer || isSeller ? (
            <div className="kyc-card-grid">
              <article className="kyc-card">
                <div className="kyc-card-header">
                  <div>
                    <p className="eyebrow">Your KYC status</p>
                    <h3>{currentParticipant?.name ?? 'Your profile'}</h3>
                  </div>
                  <span className={`status-pill status-pill--${currentParticipant?.overallStatus?.toLowerCase() ?? 'pending'}`}>
                    {currentParticipant?.overallStatus ?? 'Pending'}
                  </span>
                </div>

                <div className="kyc-summary-list">
                  <div>
                    <p>Account type</p>
                    <strong>{currentParticipant?.accountType ?? 'User account'}</strong>
                  </div>
                  <div>
                    <p>Identity verification</p>
                    <strong>{currentParticipant?.identityVerification ?? 'Pending'}</strong>
                  </div>
                  <div>
                    <p>Business verification</p>
                    <strong>{currentParticipant?.businessVerification ?? (currentParticipant?.accountType === 'business' ? 'Pending' : 'Not applicable')}</strong>
                  </div>
                </div>

                {/* Top action buttons removed — use per-form submit buttons below */}

                <div className="kyc-form">
                  <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                    <button onClick={() => setKycFormType('individual')} disabled={kycFormType === 'individual'}>Individual</button>
                    <button onClick={() => setKycFormType('business')} disabled={kycFormType === 'business'}>Business</button>
                    <button onClick={() => setKycFormType('transaction')} disabled={kycFormType === 'transaction'}>Transaction</button>
                  </div>

                  {kycFormType === 'individual' && (
                    <div>
                      <h4>Personal information</h4>
                      <div className="form-grid">
                        <label>First name<input value={individualKyc.firstName ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, firstName: e.target.value }))} /></label>
                        <label>Middle name<input value={individualKyc.middleName ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, middleName: e.target.value }))} /></label>
                        <label>Last name<input value={individualKyc.lastName ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, lastName: e.target.value }))} /></label>
                        <label>Date of birth<input type="date" value={individualKyc.dob ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, dob: e.target.value }))} /></label>
                        <label>Gender<input value={individualKyc.gender ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, gender: e.target.value }))} /></label>
                        <label>Nationality<input value={individualKyc.nationality ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, nationality: e.target.value }))} /></label>
                        <label>National ID / Passport<input value={individualKyc.idNumber ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, idNumber: e.target.value }))} /></label>
                        <label>TIN<input value={individualKyc.tin ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, tin: e.target.value }))} /></label>
                        <label>Occupation<input value={individualKyc.occupation ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, occupation: e.target.value }))} /></label>
                        <label>Employer<input value={individualKyc.employer ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, employer: e.target.value }))} /></label>
                      </div>

                      <h4>Contact</h4>
                      <div className="form-grid">
                        <label>Mobile number<input value={individualKyc.mobile ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, mobile: e.target.value }))} /></label>
                        <label>Email<input value={individualKyc.email ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, email: e.target.value }))} /></label>
                        <label>Residential address<input value={individualKyc.address ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, address: e.target.value }))} /></label>
                        <label>District<input value={individualKyc.district ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, district: e.target.value }))} /></label>
                        <label>City<input value={individualKyc.city ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, city: e.target.value }))} /></label>
                        <label>Country<input value={individualKyc.country ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, country: e.target.value }))} /></label>
                        <label>Postal address<input value={individualKyc.postal ?? ''} onChange={(e) => setIndividualKyc((s:any) => ({ ...s, postal: e.target.value }))} /></label>
                      </div>

                      <h4>Identity verification</h4>
                      <div className="form-grid">
                        <label>National ID (Front)<input type="file" onChange={(e) => handleKycFileChange('individual', 'idFront', e.target.files?.[0] ?? null)} /></label>
                        <label>National ID (Back)<input type="file" onChange={(e) => handleKycFileChange('individual', 'idBack', e.target.files?.[0] ?? null)} /></label>
                        <label>Passport (Optional)<input type="file" onChange={(e) => handleKycFileChange('individual', 'passport', e.target.files?.[0] ?? null)} /></label>
                        <label>Driving permit (Optional)<input type="file" onChange={(e) => handleKycFileChange('individual', 'driving', e.target.files?.[0] ?? null)} /></label>
                      </div>

                      <h4>Selfie & address</h4>
                      <div className="form-grid">
                        <label>Live selfie<input type="file" onChange={(e) => handleKycFileChange('individual', 'selfie', e.target.files?.[0] ?? null)} /></label>
                        <label>Address proof (Utility bill / Bank statement)<input type="file" onChange={(e) => handleKycFileChange('individual', 'addressProof', e.target.files?.[0] ?? null)} /></label>
                      </div>

                      <div style={{ marginTop: 12 }}>
                        <button onClick={handleSubmitKycForm}>Submit Individual KYC</button>
                      </div>
                    </div>
                  )}

                    {txn.documents && txn.documents.length > 0 && (
                      <div style={{ marginTop: 12 }}>
                        <p style={{ margin: '6px 0 8px' }}><strong>Documents</strong></p>
                        <div style={{ display: 'grid', gap: 8 }}>
                          {txn.documents.map((doc: any) => (
                            <div key={doc.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, padding: 8, borderRadius: 8, background: '#fff' }}>
                              <div>
                                <div style={{ fontWeight: 700 }}>{doc.name}</div>
                                <div style={{ fontSize: 12, color: '#475569' }}>{doc.type} • {doc.status}</div>
                                {doc.comment && <div style={{ fontSize: 12, color: '#b91c1c' }}>Note: {doc.comment}</div>}
                              </div>
                              <div>
                                <button onClick={() => handleUploadDocument(txn.id)}>Upload</button>
                                {(userRoles.includes('system_admin') || userRoles.includes('inspector')) && (
                                  <button onClick={() => handleVerifyDocument(txn.id, doc.id)}>Verify</button>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    <div style={{ marginTop: 12 }}>
                      <button onClick={() => handleUploadDocument(txn.id)}>Upload document</button>
                    </div>

                  {kycFormType === 'business' && (
                    <div>
                      <h4>Business details</h4>
                      <div className="form-grid">
                        <label>Business name<input value={businessKyc.name ?? ''} onChange={(e) => setBusinessKyc((s:any) => ({ ...s, name: e.target.value }))} /></label>
                        <label>Trading name<input value={businessKyc.tradingName ?? ''} onChange={(e) => setBusinessKyc((s:any) => ({ ...s, tradingName: e.target.value }))} /></label>
                        <label>Registration number<input value={businessKyc.regNumber ?? ''} onChange={(e) => setBusinessKyc((s:any) => ({ ...s, regNumber: e.target.value }))} /></label>
                        <label>TIN<input value={businessKyc.tin ?? ''} onChange={(e) => setBusinessKyc((s:any) => ({ ...s, tin: e.target.value }))} /></label>
                        <label>Business type<input value={businessKyc.type ?? ''} onChange={(e) => setBusinessKyc((s:any) => ({ ...s, type: e.target.value }))} /></label>
                        <label>Industry<input value={businessKyc.industry ?? ''} onChange={(e) => setBusinessKyc((s:any) => ({ ...s, industry: e.target.value }))} /></label>
                        <label>Country<input value={businessKyc.country ?? ''} onChange={(e) => setBusinessKyc((s:any) => ({ ...s, country: e.target.value }))} /></label>
                        <label>Website<input value={businessKyc.website ?? ''} onChange={(e) => setBusinessKyc((s:any) => ({ ...s, website: e.target.value }))} /></label>
                      </div>

                      <h4>Registration documents</h4>
                      <div className="form-grid">
                        <label>Certificate of incorporation<input type="file" onChange={(e) => handleKycFileChange('business', 'incorp', e.target.files?.[0] ?? null)} /></label>
                        <label>Memorandum & Articles<input type="file" onChange={(e) => handleKycFileChange('business', 'memorandum', e.target.files?.[0] ?? null)} /></label>
                        <label>Trading license<input type="file" onChange={(e) => handleKycFileChange('business', 'license', e.target.files?.[0] ?? null)} /></label>
                        <label>Tax certificate<input type="file" onChange={(e) => handleKycFileChange('business', 'tax', e.target.files?.[0] ?? null)} /></label>
                      </div>

                      <div style={{ marginTop: 12 }}>
                        <button onClick={handleSubmitKycForm}>Submit Business KYC</button>
                      </div>
                    </div>
                  )}

                  {kycFormType === 'transaction' && (
                    <div>
                      <h4>Transaction-based KYC</h4>
                      <div className="form-grid">
                        <label>Transaction description<input value={transactionKyc.description ?? ''} onChange={(e) => setTransactionKyc((s:any) => ({ ...s, description: e.target.value }))} /></label>
                        <label>Value (UGX)<input value={transactionKyc.value ?? ''} onChange={(e) => setTransactionKyc((s:any) => ({ ...s, value: e.target.value }))} /></label>
                        <label>Source of funds<input value={transactionKyc.source ?? ''} onChange={(e) => setTransactionKyc((s:any) => ({ ...s, source: e.target.value }))} /></label>
                        <label>Supporting document<input type="file" onChange={(e) => handleKycFileChange('transaction', 'support', e.target.files?.[0] ?? null)} /></label>
                      </div>
                      <div style={{ marginTop: 12 }}>
                        <button onClick={handleSubmitKycForm}>Submit Transaction KYC</button>
                      </div>
                    </div>
                  )}

                </div>

                <div className="kyc-note">
                  <p>{kycActionMessage ?? 'Upload your documents, then submit the review request. Once verified, you can complete buyer/seller transactions.'}</p>
                </div>
              </article>

              <article className="kyc-help-card">
                <h3>What you need</h3>
                <ul>
                  <li>Government-issued ID</li>
                  <li>Proof of address</li>
                  <li>{currentParticipant?.accountType === 'business' ? 'Company registration documents' : 'Business ownership documentation if applicable'}</li>
                </ul>
                <p>Once you submit the review, the platform will verify your information and update your KYC status.</p>
              </article>
            </div>
          ) : (
            <div className="participant-grid">
              {canAccessAdmin ? (
                <div>
                  <h3>Pending KYC participants</h3>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
                    <input placeholder="Search name or email" value={pendingKycQuery} onChange={(e) => setPendingKycQuery(e.target.value)} style={{ padding: '6px 8px', borderRadius: 6, border: '1px solid rgba(148,163,184,0.3)' }} />
                    <button onClick={() => loadPendingKyc(1, pendingKycPageSize, pendingKycQuery)}>Search</button>
                    <div style={{ marginLeft: 'auto' }}>
                      <small>Showing {(pendingKycPage - 1) * pendingKycPageSize + 1}–{Math.min(pendingKycPage * pendingKycPageSize, pendingKycTotal)} of {pendingKycTotal}</small>
                    </div>
                  </div>
                  {pendingKyc.length === 0 ? <p>No pending KYC.</p> : (
                    <div className="participant-grid">
                      {pendingKyc.map((p) => (
                        <div className="card" key={p.id}>
                          <h3>{p.name}</h3>
                          <p><strong>Email:</strong> {p.email}</p>
                          <p><strong>Role:</strong> {p.role}</p>
                            <div style={{ display: 'flex', gap: 8 }}>
                            <button onClick={() => openParticipantKyc(p.id)}>Open</button>
                            <button onClick={() => handleAutoVerify(p.id)}>Auto-verify (NIN)</button>
                            <button onClick={() => handleVerify(p.id)}>Mark verified</button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12 }}>
                    <button disabled={pendingKycPage <= 1} onClick={() => loadPendingKyc(pendingKycPage - 1, pendingKycPageSize, pendingKycQuery)}>Prev</button>
                    <span>Page {pendingKycPage}</span>
                    <button disabled={pendingKycPage * pendingKycPageSize >= pendingKycTotal} onClick={() => loadPendingKyc(pendingKycPage + 1, pendingKycPageSize, pendingKycQuery)}>Next</button>
                    <select value={pendingKycPageSize} onChange={(e) => { const s = Number(e.target.value); setPendingKycPageSize(s); loadPendingKyc(1, s, pendingKycQuery); }} style={{ marginLeft: 'auto' }}>
                      <option value={5}>5</option>
                      <option value={10}>10</option>
                      <option value={25}>25</option>
                    </select>
                  </div>

                  {selectedKycParticipant && (
                    <div style={{ marginTop: 12 }}>
                      <h4>Documents for participant</h4>
                      {adminKycDocs.length === 0 ? <p>No documents found for this participant.</p> : (
                        <div style={{ display: 'grid', gap: 8 }}>
                          {adminKycDocs.map((entry) => (
                            <div key={entry.document.id} className="card">
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div>
                                  <strong>{entry.document.name}</strong>
                                  <div style={{ fontSize: 12 }}>{entry.document.type} • {entry.document.status}</div>
                                  {entry.document.fileUrl && <div><a href={entry.document.fileUrl} target="_blank" rel="noreferrer">View file</a></div>}
                                  {entry.document.comment && <div style={{ fontSize: 12, color: '#b91c1c' }}>Note: {entry.document.comment}</div>}
                                </div>
                                <div style={{ display: 'flex', gap: 8 }}>
                                  <button onClick={() => handleVerifyDocument(entry.transactionId, entry.document.id)}>Verify</button>
                                  <button onClick={() => handleVerifyDocument(entry.transactionId, entry.document.id)}>Reject</button>
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                      {currentKycProfile && (
                        <div style={{ marginTop: 12 }} className="card">
                          <h4>Profile</h4>
                          <p><strong>Name:</strong> {currentKycProfile.name}</p>
                          <p><strong>Email:</strong> {currentKycProfile.email}</p>
                          <p><strong>Role:</strong> {currentKycProfile.role}</p>
                          <p><strong>KYC verified:</strong> {currentKycProfile.kycVerified ? 'Yes' : 'No'}</p>
                          <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                            <button onClick={() => handleVerify(currentKycProfile.id)}>Verify KYC</button>
                            <button onClick={() => handleAutoVerify(currentKycProfile.id)}>Auto-verify (NIN)</button>
                          </div>
                        </div>
                      )}
                      {verificationHistory.length > 0 && (
                        <div style={{ marginTop: 12 }} className="card">
                          <h4>Verification History</h4>
                          <ol>
                            {verificationHistory.slice().reverse().map((h: any) => (
                              <li key={h.id} style={{ marginBottom: 6 }}>
                                <div style={{ fontSize: 12, color: '#475569' }}>{new Date(h.timestamp).toLocaleString()} • {h.actorId ?? 'system'}</div>
                                <div style={{ fontWeight: 700 }}>{h.action} {h.method ? `(${h.method})` : ''}</div>
                                {h.comment && <div style={{ fontSize: 13 }}>{h.comment}</div>}
                              </li>
                            ))}
                          </ol>
                          <div style={{ marginTop: 8 }}>
                            <button onClick={async () => {
                              const comment = prompt('Reason for unverifying participant (required)');
                              if (!comment) return alert('Comment required to unverify');
                              try {
                                await unverifyParticipant(currentKycProfile.id, comment);
                                // refresh profile
                                await openParticipantKyc(currentKycProfile.id);
                                await loadPendingKyc();
                                alert('Participant unverified and event recorded.');
                              } catch (e) {
                                setError(String(e));
                              }
                            }}>Unverify</button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <div className="participant-grid">
                  {kycParticipants.map((participant) => (
                    <div className="card" key={participant.id}>
                      <h3>{participant.name}</h3>
                      <p><strong>Account type:</strong> {participant.accountType}</p>
                      <p><strong>Overall status:</strong> {participant.overallStatus}</p>
                      <button type="button" onClick={() => handleVerify(participant.id)} disabled={participant.overallStatus === 'Verified'}>
                        {participant.overallStatus === 'Verified' ? 'Verified' : 'Verify KYC'}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
      );
    }

    if (activeModule === 'Escrow') {
      const escrowSubmodule = activeSubmodule || 'Active';
      const activeEscrows = transactions.filter((txn) => txn.status !== 'completed' && txn.status !== 'cancelled');
      const fundingEscrows = transactions.filter((txn) => txn.status === 'pending_payment');
      const releaseEscrows = transactions.filter((txn) => txn.status === 'escrowed' || txn.status === 'verifying');
      const refundEscrows = transactions.filter((txn) => txn.escrowBalance > 0);

      const renderEscrowCards = (items: Transaction[]) => (
        <div className="transaction-grid">
          {items.length === 0 ? (
            <p>No escrow transactions available for this view.</p>
          ) : (
            items.map((txn) => {
              const buyer = parties.find((party) => party.id === txn.buyerId);
              const seller = parties.find((party) => party.id === txn.sellerId);
              const depositValue = depositAmounts[txn.id] ?? 0;
              return (
                <article className="card" key={txn.id}>
                  <h3>{txn.description}</h3>
                  <p><strong>Status:</strong> {txn.status}</p>
                  <p><strong>Value:</strong> UGX {txn.value.toLocaleString()}</p>
                  <p><strong>Escrow balance:</strong> UGX {Number(txn.escrowBalance ?? 0).toLocaleString()}</p>
                  <p><strong>Buyer:</strong> {buyer?.name ?? txn.buyerId}</p>
                  <p><strong>Seller:</strong> {seller?.name ?? txn.sellerId}</p>
                  <div style={{ marginTop: 12, display: 'grid', gap: 10 }}>
                    {txn.milestones && txn.milestones.length > 0 && (
                      <div>
                        <p style={{ margin: '6px 0 8px', fontWeight: 700 }}>Milestones</p>
                        <div style={{ display: 'grid', gap: 8 }}>
                          {txn.milestones.map((ms) => (
                            <div key={ms.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, padding: 8, borderRadius: 8, background: '#fff' }}>
                              <div>
                                <div style={{ fontWeight: 700 }}>{ms.title}</div>
                                <div style={{ fontSize: 12, color: '#475569' }}>UGX {ms.amount.toLocaleString()}</div>
                              </div>
                              <div>
                                {ms.completed ? (
                                  <span style={{ color: '#047857', fontWeight: 700 }}>Completed</span>
                                ) : (
                                  <button onClick={() => handleCompleteMilestone(txn.id, ms.id)}>Complete</button>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {(escrowSubmodule === 'Active' || escrowSubmodule === 'Funding') && (
                      <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <span>Deposit (UGX)</span>
                        <input
                          type="number"
                          min="0"
                          value={depositValue}
                          onChange={(e) => setDepositAmounts((cur) => ({ ...cur, [txn.id]: Number(e.target.value) }))}
                          style={{ padding: '6px 8px', borderRadius: 8, border: '1px solid rgba(148,163,184,0.3)', width: 120 }}
                        />
                        <button onClick={() => handleDeposit(txn.id)} disabled={depositValue <= 0}>Deposit</button>
                      </label>
                    )}

                    {escrowSubmodule === 'Releases' && (
                      <button
                        onClick={() => handleRelease(txn.id)}
                        disabled={
                          txn.escrowBalance < txn.value ||
                          !txn.contract.signedByBuyer ||
                          !txn.contract.signedBySeller ||
                          !txn.milestones.every((ms) => ms.completed)
                        }
                      >
                        Release escrow
                      </button>
                    )}

                    {escrowSubmodule === 'Refunds' && (
                      <button onClick={() => handleRefund(txn.id)} disabled={!(txn.escrowBalance > 0)}>
                        Refund full
                      </button>
                    )}

                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <div style={{ fontSize: 12, color: '#475569' }}>
                        Contract: {txn.contract.signedByBuyer && txn.contract.signedBySeller ? 'Fully signed' : 'Pending signatures'}
                      </div>
                      <button onClick={() => handleSign(txn.contract.id, 'buyer')} disabled={!userRoles.includes('buyer') || txn.contract.signedByBuyer}>{txn.contract.signedByBuyer ? 'Buyer signed' : 'Sign as buyer'}</button>
                      <button onClick={() => handleSign(txn.contract.id, 'seller')} disabled={!userRoles.includes('seller') || txn.contract.signedBySeller}>{txn.contract.signedBySeller ? 'Seller signed' : 'Sign as seller'}</button>
                    </div>
                  </div>
                </article>
              );
            })
          )}
        </div>
      );
      
      return (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Escrow</p>
              <h2>{escrowSubmodule}</h2>
            </div>
            <div className="small-pill">{escrowSubmodule}</div>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 18 }}>
            {['Active', 'Funding', 'Releases', 'Refunds'].map((item) => (
              <button
                type="button"
                key={item}
                onClick={() => handleModuleChange('Escrow', item)}
                style={{
                  borderRadius: 14,
                  padding: '12px 18px',
                  border: '1px solid rgba(148,163,184,0.3)',
                  background: escrowSubmodule === item ? '#eff6ff' : 'transparent',
                  color: escrowSubmodule === item ? '#1e3a8a' : '#475569',
                  cursor: 'pointer',
                }}
              >
                {item}
              </button>
            ))}
          </div>

          {loadingTransactions && <p>Loading escrow transactions...</p>}
          {transactionsError && (
            <div>
              <p className="error">Unable to load escrow transactions: {transactionsError}</p>
              <button onClick={() => loadTransactions()}>Retry</button>
            </div>
          )}

          {escrowSubmodule === 'Active' && renderEscrowCards(activeEscrows)}
          {escrowSubmodule === 'Funding' && renderEscrowCards(fundingEscrows)}
          {escrowSubmodule === 'Releases' && renderEscrowCards(releaseEscrows)}
          {escrowSubmodule === 'Refunds' && renderEscrowCards(refundEscrows)}
        </section>
      );
    }

    return (
      <section className="panel">
        <h2>{activeModule}</h2>
        <p>This area is reserved for the {activeModule} module.</p>
      </section>
    );
  };

  if (!authTokens) {
    const isBusiness = authForm.accountType === 'business';
    const authTitle = authMode === 'register'
      ? isBusiness
        ? 'Register your company'
        : 'Create your account'
      : 'Welcome back';
    const authSubtext = authMode === 'register'
      ? isBusiness
        ? 'Use your company details to register and start secure escrow transactions.'
        : 'Create a personal account to buy and sell with confidence.'
      : 'Sign in to access your dashboard and active transactions.';

    return (
      <div className="auth-page">
        <aside className="auth-hero">
          <div className="auth-hero-content">
            <div className="brand-mark">T</div>
            <p className="eyebrow">Secure Escrow</p>
            <h1>{authTitle}</h1>
            <p>{authSubtext}</p>
            {authMode === 'register' && (
              <div className="auth-hero-links">
                <button type="button" className={authForm.accountType === 'business' ? 'active' : ''} onClick={() => setAuthForm({ ...authForm, accountType: 'business' })}>
                  Company
                </button>
                <button type="button" className={authForm.accountType === 'individual' ? 'active' : ''} onClick={() => setAuthForm({ ...authForm, accountType: 'individual' })}>
                  Individual
                </button>
              </div>
            )}
          </div>
        </aside>

        <section className="auth-card">
          <div className="auth-card-header">
            <div className="auth-card-tabs">
              <button type="button" className={authMode === 'login' ? 'active-tab' : ''} onClick={() => setAuthMode('login')}>
                Login
              </button>
              <button type="button" className={authMode === 'register' ? 'active-tab' : ''} onClick={() => setAuthMode('register')}>
                Register
              </button>
            </div>
          </div>

          {error && <p className="error">{error}</p>}

          {authMode === 'register' ? (
            <div className="auth-form">
              <div className="account-type-toggle">
                <button type="button" className={authForm.accountType === 'individual' ? 'active' : ''} onClick={() => setAuthForm({ ...authForm, accountType: 'individual' })}>
                  Individual
                </button>
                <button type="button" className={authForm.accountType === 'business' ? 'active' : ''} onClick={() => setAuthForm({ ...authForm, accountType: 'business' })}>
                  Company
                </button>
              </div>
              <div className="form-grid">
                <label>
                  {isBusiness ? 'Company name' : 'Full name'}
                  <input value={authForm.name} onChange={(e) => setAuthForm({ ...authForm, name: e.target.value })} />
                </label>
                {isBusiness && (
                  <label>
                    Registration number
                    <input value={authForm.registrationNumber} onChange={(e) => setAuthForm({ ...authForm, registrationNumber: e.target.value })} />
                  </label>
                )}
                <label>
                  Role(s)
                  <div className="role-options">
                    <label>
                      <input type="checkbox" checked={authForm.roles?.includes('buyer')} onChange={(e) => {
                        const next = new Set(authForm.roles || []);
                        if (e.target.checked) next.add('buyer'); else next.delete('buyer');
                        setAuthForm({ ...authForm, roles: Array.from(next) });
                      }} />
                      Buyer
                    </label>
                    <label>
                      <input type="checkbox" checked={authForm.roles?.includes('seller')} onChange={(e) => {
                        const next = new Set(authForm.roles || []);
                        if (e.target.checked) next.add('seller'); else next.delete('seller');
                        setAuthForm({ ...authForm, roles: Array.from(next) });
                      }} />
                      Seller
                    </label>
                  </div>
                </label>
                <label>
                  Email
                  <input type="email" value={authForm.email} onChange={(e) => setAuthForm({ ...authForm, email: e.target.value })} />
                </label>
                <label>
                  Phone number
                  <input value={authForm.phoneNumber} onChange={(e) => setAuthForm({ ...authForm, phoneNumber: e.target.value })} />
                </label>
                <label>
                  Password
                  <input type="password" value={authForm.password} onChange={(e) => setAuthForm({ ...authForm, password: e.target.value })} />
                </label>
                <label>
                  Confirm password
                  <input type="password" value={authForm.confirmPassword} onChange={(e) => setAuthForm({ ...authForm, confirmPassword: e.target.value })} />
                </label>
              </div>
            </div>
          ) : (
            <div className="auth-form">
              <div className="form-grid">
                <label>
                  Email
                  <input type="email" value={authForm.email} onChange={(e) => setAuthForm({ ...authForm, email: e.target.value })} />
                </label>
                <label>
                  Password
                  <input type="password" value={authForm.password} onChange={(e) => setAuthForm({ ...authForm, password: e.target.value })} />
                </label>
              </div>
            </div>
          )}

          <button className="submit-button" onClick={authMode === 'register' ? handleRegister : handleLogin}>
            {authMode === 'register' ? 'Create Account' : 'Sign In'}
          </button>
        </section>
      </div>
    );
  }

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-mark">T</div>
          <div className="brand-info">
            <span>TrustPay</span>
          </div>
        </div>
        <nav className="sidebar-nav">
          {moduleNavigation.map((group) => (
            <button
              key={group.title}
              title={group.title}
              className={`sidebar-icon ${activeModule === group.title ? 'active' : ''}`}
              onClick={() => handleModuleChange(group.title)}
            >
              <span>{getModuleIcon(group.title)}</span>
            </button>
          ))}
        </nav>
      </aside>

      <main className="app-shell">
        <header>
          <div className="header-row">
            <div className="header-title">
              <h1>TrustPay Africa</h1>
            </div>
            <button className="signout-button" onClick={handleLogout} title="Sign out">
              <span>↩</span>
            </button>
          </div>
          {(isBuyer || isSeller) && (
            <div className="top-kyc-banner">
              <div>
                <h3>KYC action</h3>
                <p>{requiresKyc ? 'Your account requires verification before full access.' : 'Complete KYC to unlock buyer/seller operations.'}</p>
              </div>
              <button type="button" className="top-kyc-button" onClick={handleGoToKyc}>
                Go to KYC
              </button>
            </div>
          )}
        </header>

        {(() => {
          try {
            return renderModuleContent();
          } catch (e) {
            return (
              <section className="panel">
                <h2>UI error</h2>
                <p className="error">An error occurred while rendering the interface: {String(e)}</p>
                <p>Please check the browser console for details.</p>
              </section>
            );
          }
        })()}
      </main>
    </div>
  );
}

export default App;

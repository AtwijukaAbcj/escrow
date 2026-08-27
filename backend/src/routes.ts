import { Router } from 'express';
import { parties, transactions, Transaction } from './data';
import { writeTransactions, writeParties } from './infra/storage';
import { v4 as uuid } from 'uuid';
import { authenticateJWT, authorizeRoles } from './middleware/authMiddleware';
import multer from 'multer';
import { uploadsDir } from './infra/storage';

const fileUpload = multer({ dest: uploadsDir() });
export const createRouter = () => {
  const router = Router();

  router.use(authenticateJWT);

  router.get('/health', (_req, res) => res.json({ status: 'ok' }));

  router.get('/parties', (_req, res) => res.json({ data: parties }));

  router.get('/users/transaction-participants', (req, res) => {
    const userIds = (req.query.userIds as string | undefined)?.split(',').filter(Boolean);
    let selected = parties;
    if (userIds && userIds.length > 0) {
      selected = parties.filter((party) => userIds.includes(party.id));
    }
    const response = selected.map((party) => ({
      id: party.id,
      displayName: party.name,
      email: party.email,
      accountType: party.role === 'inspector' ? 'Business' : 'Individual',
      kycStatus: party.kycVerified ? 'Verified' : 'Pending',
      role: party.role,
    }));
    return res.json({ data: response });
  });

  router.get('/kyc/participants', (req, res) => {
    const userIds = (req.query.userIds as string | undefined)?.split(',').filter(Boolean);
    let selected = parties;
    if (userIds && userIds.length > 0) {
      selected = parties.filter((party) => userIds.includes(party.id));
    }

    const response = selected.map((party) => ({
      id: party.id,
      name: party.name,
      accountType: party.role === 'inspector' ? 'Business' : 'Individual',
      identityVerification: party.kycVerified ? 'Verified' : 'Pending',
      businessVerification: party.role === 'inspector' ? (party.kycVerified ? 'Verified' : 'Pending') : 'Not applicable',
      overallStatus: party.kycVerified ? 'Verified' : 'Pending',
      restrictions: [],
    }));

    return res.json({ data: response });
  });

  // Admin: list pending KYC participants with optional search and pagination
  router.get('/kyc/pending', authorizeRoles('system_admin', 'inspector'), (req, res) => {
    const q = ((req.query.q as string) || '').toLowerCase().trim();
    const page = Math.max(1, Number(req.query.page) || 1);
    const pageSize = Math.min(100, Math.max(1, Number(req.query.pageSize) || 10));

    let list = parties.filter((p) => !p.kycVerified);
    if (q) {
      list = list.filter((p) => (p.name || '').toLowerCase().includes(q) || (p.email || '').toLowerCase().includes(q));
    }

    const total = list.length;
    const start = (page - 1) * pageSize;
    const items = list.slice(start, start + pageSize).map((party) => ({ id: party.id, name: party.name, email: party.email, role: party.role }));

    return res.json({ data: items, meta: { total, page, pageSize } });
  });

  // Mock NIRA auto-verify for a participant using NIN (simulated)
  router.post('/kyc/participant/:id/auto-verify', authorizeRoles('system_admin', 'inspector'), (req, res) => {
    const participantId = req.params.id;
    const { nin, name } = req.body as { nin?: string; name?: string };
    const party = parties.find((p) => p.id === participantId);
    if (!party) return res.status(404).json({ error: 'Participant not found' });
    if (!nin) return res.status(400).json({ error: 'NIN is required' });

    const ninValid = /^\d{14}$/.test(nin);

    // Name matching: normalize and compute token overlap (Jaccard). If no name provided, skip name matching.
    const normalize = (s: string) => s.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();
    const tokens = (s: string) => (s ? Array.from(new Set(s.split(' ').filter(Boolean))) : []);
    let nameMatch = true;
    if (name && name.trim()) {
      const provided = normalize(name);
      const registered = normalize(party.name || '');
      const pTokens = tokens(provided);
      const rTokens = tokens(registered);
      const intersection = pTokens.filter((t) => rTokens.includes(t)).length;
      const union = Array.from(new Set([...pTokens, ...rTokens])).length || 1;
      const jaccard = intersection / union;
      nameMatch = jaccard >= 0.5;
    }

    const valid = ninValid && nameMatch;
    party.kycVerified = valid;
    party.verificationHistory = party.verificationHistory ?? [];
    party.verificationHistory.push({ id: uuid(), timestamp: new Date().toISOString(), actorId: (req as any).user?.sub, action: 'auto_kyc_check', comment: `NIN:${ninValid ? 'ok' : 'bad'}; name:${name ? (nameMatch ? 'ok' : 'mismatch') : 'skipped'}`, method: 'nira' });
    writeParties(parties);

    // Attach an event to transactions mentioning the verification (if any transaction exists for the party)
    for (const txn of transactions) {
      if (txn.buyerId === participantId || txn.sellerId === participantId) {
        txn.events = txn.events ?? [];
        txn.events.push({
          timestamp: new Date().toISOString(),
          actorId: (req as any).user?.sub,
          action: 'auto_kyc_check',
          details: `NIN:${ninValid ? 'ok' : 'bad'}; name:${name ? (nameMatch ? 'ok' : 'mismatch') : 'skipped'}; overall:${valid ? 'passed' : 'failed'}`,
        });
      }
    }
    writeTransactions(transactions);

    return res.json({ data: { id: party.id, name: party.name, kycVerified: party.kycVerified, result: valid ? 'verified' : 'rejected', checks: { ninValid, nameMatch } } });
  });

  // Admin: undo/unverify a participant's KYC with optional comment
  router.post('/kyc/participant/:id/unverify', authorizeRoles('system_admin', 'inspector'), (req, res) => {
    const participantId = req.params.id;
    const { comment } = req.body as { comment?: string };
    const party = parties.find((p) => p.id === participantId);
    if (!party) return res.status(404).json({ error: 'Participant not found' });
    party.kycVerified = false;
    party.verificationHistory = party.verificationHistory ?? [];
    party.verificationHistory.push({ id: uuid(), timestamp: new Date().toISOString(), actorId: (req as any).user?.sub, action: 'manual_kyc_unverified', comment: comment || 'Unverified by admin', method: 'manual' });
    // attach event for transactions
    for (const txn of transactions) {
      if (txn.buyerId === participantId || txn.sellerId === participantId) {
        txn.events = txn.events ?? [];
        txn.events.push({ timestamp: new Date().toISOString(), actorId: (req as any).user?.sub, action: 'manual_kyc_unverified', details: comment || 'Unverified by admin' });
      }
    }
    writeParties(parties);
    writeTransactions(transactions);
    return res.json({ data: party });
  });

  // Admin: fetch all documents uploaded by a participant across transactions
  router.get('/kyc/participant/:id/documents', authorizeRoles('system_admin', 'inspector'), (req, res) => {
    const participantId = req.params.id;
    const docs: Array<{ transactionId: string; document: any }> = [];
    for (const txn of transactions) {
      const txDocs = (txn.documents ?? []).filter((d: any) => d.uploadedBy === participantId);
      for (const d of txDocs) docs.push({ transactionId: txn.id, document: d });
    }
    return res.json({ data: docs });
  });

  // Admin: fetch participant KYC profile with documents and related transactions/events
  router.get('/kyc/participant/:id/profile', authorizeRoles('system_admin', 'inspector'), (req, res) => {
    const participantId = req.params.id;
    const party = parties.find((p) => p.id === participantId);
    if (!party) return res.status(404).json({ error: 'Participant not found' });

    const documents: Array<{ transactionId: string; document: any }> = [];
    const relatedTransactions: Array<any> = [];
    for (const txn of transactions) {
      const txDocs = (txn.documents ?? []).filter((d: any) => d.uploadedBy === participantId);
      for (const d of txDocs) documents.push({ transactionId: txn.id, document: d });
      if (txn.buyerId === participantId || txn.sellerId === participantId) {
        relatedTransactions.push({ id: txn.id, description: txn.description, status: txn.status, value: txn.value, events: txn.events ?? [] });
      }
    }

    return res.json({ data: { party, documents, relatedTransactions } });
  });

  router.post('/kyc/verify', (req, res) => {
    const { partyId, comment } = req.body as { partyId: string; comment?: string };
    const party = parties.find((item) => item.id === partyId);
    if (!party) {
      return res.status(404).json({ error: 'Party not found' });
    }
    party.kycVerified = true;
    // record an audit event on any related transactions
    for (const txn of transactions) {
      if (txn.buyerId === partyId || txn.sellerId === partyId) {
        txn.events = txn.events ?? [];
        txn.events.push({ timestamp: new Date().toISOString(), actorId: (req as any).user?.sub, action: 'manual_kyc_verified', details: comment ?? 'Verified by admin' });
      }
    }
    writeParties(parties);
    writeTransactions(transactions);
    return res.json({ data: party });
  });

  router.get('/transactions', (req, res) => {
    const status = req.query.status as string | undefined;
    if (status === 'active') {
      const activeStatuses: Transaction['status'][] = ['pending_payment', 'escrowed', 'verifying'];
      return res.json({ data: transactions.filter((txn) => activeStatuses.includes(txn.status)) });
    }
    return res.json({ data: transactions });
  });

  router.get('/transactions/:id', (req, res) => {
    const transaction = transactions.find((item) => item.id === req.params.id);
    if (!transaction) {
      return res.status(404).json({ error: 'Transaction not found' });
    }
    return res.json({ data: transaction });
  });

  router.post('/transactions', (req, res) => {
    const { buyerId, sellerId, sellerEmail, sellerName, description, value } = req.body as {
      buyerId?: string;
      sellerId?: string;
      sellerEmail?: string;
      sellerName?: string;
      description: string;
      value: number;
    };

    if (!description || value === undefined || value === null) {
      return res.status(400).json({ error: 'Missing required transaction fields' });
    }

    // If caller is not a platform admin, enforce buyerId to be the current user
    const callerId = (req as any).user?.sub as string | undefined;
    const callerRoles = (req as any).user?.roles as string[] | undefined;
    const isAdmin = callerRoles?.includes('system_admin');
    let finalBuyerId = buyerId;
    if (!isAdmin) {
      if (!callerId) return res.status(401).json({ error: 'Authentication required' });
      finalBuyerId = callerId;
    }
    if (value <= 0) {
      return res.status(400).json({ error: 'Amount must be greater than zero' });
    }

    const buyer = parties.find((item) => item.id === finalBuyerId);
    let seller = sellerId ? parties.find((item) => item.id === sellerId) : undefined;
    // If seller not provided but email given, find or create party
    if (!seller && sellerEmail) {
      seller = parties.find((p) => p.email === sellerEmail);
      if (!seller) {
        const newPartyId = uuid();
        seller = {
          id: newPartyId,
          name: sellerName || sellerEmail,
          role: 'seller',
          email: sellerEmail,
          phone: '',
          kycVerified: false,
        };
        parties.push(seller);
      }
    }
    if (!buyer || !seller) {
      return res.status(400).json({ error: 'Selected buyer or seller is not eligible' });
    }
    if (!buyer.kycVerified) {
      return res.status(400).json({ error: 'Buyer must have verified KYC' });
    }
    // Seller may be unverified; in that case put transaction into awaiting_acceptance if seller just created or not verified

    const newTransaction: Transaction = {
      id: uuid(),
      buyerId: finalBuyerId!,
      sellerId: seller.id,
      description,
      value,
      status: seller.kycVerified ? 'pending_payment' : 'awaiting_acceptance',
      contract: {
        id: uuid(),
        title: 'TrustPay Escrow Contract',
        description,
        terms: 'Funds remain in escrow until all milestones are completed and approved.',
        signedByBuyer: false,
        signedBySeller: false,
        createdAt: new Date().toISOString(),
      },
      milestones: [
        { id: uuid(), title: 'Document verification', amount: Math.round(value * 0.5), completed: false },
        { id: uuid(), title: 'Milestone approval', amount: Math.round(value * 0.3), completed: false },
        { id: uuid(), title: 'Final release', amount: Math.round(value * 0.2), completed: false },
      ],
      escrowBalance: 0,
      createdAt: new Date().toISOString(),
      events: [{ timestamp: new Date().toISOString(), actorId: callerId, action: 'created', details: 'Transaction created' }],
    };

    transactions.push(newTransaction);
    writeTransactions(transactions);
    return res.status(201).json({ data: newTransaction });
  });

  // Invite seller endpoint (create or assign seller by email)
  router.post('/transactions/:id/invite', (req, res) => {
    const { id } = req.params;
    const { email, name } = req.body as { email: string; name?: string };
    const txn = transactions.find((t) => t.id === id);
    if (!txn) return res.status(404).json({ error: 'Transaction not found' });
    if (!email) return res.status(400).json({ error: 'Email is required' });
    let seller = parties.find((p) => p.email === email);
    if (!seller) {
      seller = { id: uuid(), name: name || email, role: 'seller', email, phone: '', kycVerified: false };
      parties.push(seller);
      writeParties(parties);
    }
    txn.sellerId = seller.id;
    txn.status = seller.kycVerified ? txn.status : 'awaiting_acceptance';
    txn.events = txn.events ?? [];
    txn.events.push({ timestamp: new Date().toISOString(), actorId: (req as any).user?.sub, action: 'invited_seller', details: `Invited seller ${email}` });
    writeTransactions(transactions);
    return res.json({ data: txn });
  });

  // Seller accepts transaction
  router.post('/transactions/:id/accept', (req, res) => {
    const { id } = req.params;
    const txn = transactions.find((t) => t.id === id);
    if (!txn) return res.status(404).json({ error: 'Transaction not found' });
    const caller = (req as any).user?.sub;
    if (!caller) return res.status(401).json({ error: 'Authentication required' });
    if (caller !== txn.sellerId && !( (req as any).user?.roles?.includes('system_admin') )) return res.status(403).json({ error: 'Only the assigned seller may accept this transaction' });
    txn.status = 'pending_payment';
    txn.events = txn.events ?? [];
    txn.events.push({ timestamp: new Date().toISOString(), actorId: caller, action: 'accepted', details: 'Seller accepted the transaction' });
    writeTransactions(transactions);
    return res.json({ data: txn });
  });

  // Seller rejects transaction
  router.post('/transactions/:id/reject', (req, res) => {
    const { id } = req.params;
    const { reason } = req.body as { reason?: string };
    const txn = transactions.find((t) => t.id === id);
    if (!txn) return res.status(404).json({ error: 'Transaction not found' });
    const caller = (req as any).user?.sub;
    if (!caller) return res.status(401).json({ error: 'Authentication required' });
    if (caller !== txn.sellerId && !( (req as any).user?.roles?.includes('system_admin') )) return res.status(403).json({ error: 'Only the assigned seller may reject this transaction' });
    txn.status = 'cancelled';
    txn.events = txn.events ?? [];
    txn.events.push({ timestamp: new Date().toISOString(), actorId: caller, action: 'rejected', details: reason || 'Seller rejected the transaction' });
    writeTransactions(transactions);
    return res.json({ data: txn });
  });

  // Admin-only: seed verified buyer/seller participants for testing
  router.post('/seed/participants', authorizeRoles('system_admin'), (req, res) => {
    const { count = 5 } = req.body as { count?: number };
    const created: typeof parties = [];
    for (let i = 0; i < count; i++) {
      const buyer = {
        id: uuid(),
        name: `Seed Buyer ${Date.now()}-${i}`,
        role: 'buyer' as const,
        email: `seed.buyer.${Date.now()}${i}@example.com`,
        phone: '',
        kycVerified: true,
      };
      const seller = {
        id: uuid(),
        name: `Seed Seller ${Date.now()}-${i}`,
        role: 'seller' as const,
        email: `seed.seller.${Date.now()}${i}@example.com`,
        phone: '',
        kycVerified: true,
      };
        parties.push(buyer, seller);
        created.push(buyer, seller);
      }
      writeParties(parties);
      return res.json({ data: created });
  });

  router.post('/transactions/:id/deposit', (req, res) => {
    const { id } = req.params;
    const { amount } = req.body as { amount: number };
    const txn = transactions.find((item) => item.id === id);
    if (!txn) {
      return res.status(404).json({ error: 'Transaction not found' });
    }
    if (txn.status === 'completed' || txn.status === 'cancelled') {
      return res.status(400).json({ error: 'Cannot deposit into a completed or cancelled transaction' });
    }
    if (amount <= 0) {
      return res.status(400).json({ error: 'Deposit amount must be positive' });
    }
    txn.escrowBalance += amount;
    txn.status = 'escrowed';
    writeTransactions(transactions);
    return res.json({ data: txn });
  });

  // Documents: upload metadata for a transaction (simulates file upload)
  router.post('/transactions/:id/documents', (req, res) => {
    const { id } = req.params;
    const { name, type } = req.body as { name: string; type: string };
    const txn = transactions.find((t) => t.id === id);
    if (!txn) return res.status(404).json({ error: 'Transaction not found' });
    if (!name || !type) return res.status(400).json({ error: 'Missing document name or type' });
    const doc = {
      id: uuid(),
      name,
      type,
      uploadedBy: (req as any).user?.sub,
      status: 'submitted' as const,
      createdAt: new Date().toISOString(),
    };
    txn.documents = txn.documents ?? [];
    txn.documents.push(doc as any);
    txn.events = txn.events ?? [];
    txn.events.push({ timestamp: new Date().toISOString(), actorId: (req as any).user?.sub, action: 'document_uploaded', details: name });
    writeTransactions(transactions);
    return res.status(201).json({ data: doc });
  });

  // File upload: accept a file and store it on disk, attaching URL to document
  router.post('/transactions/:id/documents/upload', fileUpload.single('file'), (req, res) => {
    const { id } = req.params;
    const txn = transactions.find((t) => t.id === id);
    if (!txn) return res.status(404).json({ error: 'Transaction not found' });
    if (!req.file) return res.status(400).json({ error: 'No file uploaded' });
    const { originalname, filename } = req.file as any;
    const doc = {
      id: uuid(),
      name: originalname,
      type: (req.body.type as string) || 'file',
      uploadedBy: (req as any).user?.sub,
      status: 'submitted' as const,
      fileUrl: `/uploads/${filename}`,
      createdAt: new Date().toISOString(),
    } as any;
    txn.documents = txn.documents ?? [];
    txn.documents.push(doc as any);
    txn.events = txn.events ?? [];
    txn.events.push({ timestamp: new Date().toISOString(), actorId: (req as any).user?.sub, action: 'document_uploaded', details: originalname });
    writeTransactions(transactions);
    return res.status(201).json({ data: doc });
  });

  router.get('/transactions/:id/documents', (req, res) => {
    const { id } = req.params;
    const txn = transactions.find((t) => t.id === id);
    if (!txn) return res.status(404).json({ error: 'Transaction not found' });
    return res.json({ data: txn.documents ?? [] });
  });

  // Verify a specific document (inspector or admin)
  router.post('/transactions/:id/documents/:docId/verify', authorizeRoles('system_admin', 'inspector'), (req, res) => {
    const { id, docId } = req.params;
    const { status, comment } = req.body as { status: 'verified' | 'rejected' | 'flagged'; comment?: string };
    const txn = transactions.find((t) => t.id === id);
    if (!txn) return res.status(404).json({ error: 'Transaction not found' });
    const doc = (txn.documents ?? []).find((d) => d.id === docId);
    if (!doc) return res.status(404).json({ error: 'Document not found' });
    doc.status = status;
    doc.comment = comment;
    doc.verifiedBy = (req as any).user?.sub;
    doc.verifiedAt = new Date().toISOString();
    txn.events = txn.events ?? [];
    txn.events.push({ timestamp: new Date().toISOString(), actorId: (req as any).user?.sub, action: 'document_verified', details: `${doc.name} => ${status}` });
    writeTransactions(transactions);
    return res.json({ data: doc });
  });

  router.post('/transactions/:id/milestones/:milestoneId/complete', (req, res) => {
    const { id, milestoneId } = req.params;
    const txn = transactions.find((item) => item.id === id);
    if (!txn) {
      return res.status(404).json({ error: 'Transaction not found' });
    }
    const milestone = txn.milestones.find((item) => item.id === milestoneId);
    if (!milestone) {
      return res.status(404).json({ error: 'Milestone not found' });
    }
    milestone.completed = true;
    const allComplete = txn.milestones.every((item) => item.completed);
    txn.status = allComplete ? 'verifying' : 'escrowed';
    writeTransactions(transactions);
    return res.json({ data: txn });
  });

  router.post('/transactions/:id/release', (req, res) => {
    const { id } = req.params;
    const txn = transactions.find((item) => item.id === id);
    if (!txn) {
      return res.status(404).json({ error: 'Transaction not found' });
    }
    if (txn.status === 'completed' || txn.status === 'cancelled') {
      return res.status(400).json({ error: 'Transaction is already finalized' });
    }
    if (txn.escrowBalance < txn.value) {
      return res.status(400).json({ error: 'Insufficient escrow balance' });
    }
    if (!txn.contract.signedByBuyer || !txn.contract.signedBySeller) {
      return res.status(400).json({ error: 'Contract must be signed by both parties before release' });
    }
    if (!txn.milestones.every((item) => item.completed)) {
      return res.status(400).json({ error: 'All milestones must be completed before release' });
    }
    txn.status = 'completed';
    writeTransactions(transactions);
    return res.json({ data: txn });
  });

  router.post('/transactions/:id/dispute', (req, res) => {
    const { id } = req.params;
    const txn = transactions.find((item) => item.id === id);
    if (!txn) {
      return res.status(404).json({ error: 'Transaction not found' });
    }
    if (txn.status === 'completed' || txn.status === 'cancelled') {
      return res.status(400).json({ error: 'Cannot dispute a finalized transaction' });
    }
    txn.status = 'disputed';
    writeTransactions(transactions);
    return res.json({ data: txn });
  });

  // Refund endpoint - returns the transaction with status updated to 'cancelled' and escrowBalance reduced
  router.post('/transactions/:id/refund', (req, res) => {
    const { id } = req.params;
    const { amount } = req.body as { amount?: number };
    const txn = transactions.find((item) => item.id === id);
    if (!txn) {
      return res.status(404).json({ error: 'Transaction not found' });
    }
    const refundAmount = typeof amount === 'number' ? amount : txn.escrowBalance;
    if (refundAmount <= 0) {
      return res.status(400).json({ error: 'Refund amount must be positive' });
    }
    if (refundAmount > txn.escrowBalance) {
      return res.status(400).json({ error: 'Refund amount exceeds escrow balance' });
    }
    txn.escrowBalance -= refundAmount;
    txn.status = 'cancelled';
    writeTransactions(transactions);
    return res.json({ data: txn });
  });

  // Simple payments reconciliation endpoint — returns summary of transactions and totals
  router.post('/payments/reconcile', (_req, res) => {
    const totalTransactions = transactions.length;
    const totalEscrow = transactions.reduce((s, t) => s + (t.escrowBalance ?? 0), 0);
    const completed = transactions.filter((t) => t.status === 'completed').length;
    const disputed = transactions.filter((t) => t.status === 'disputed').length;
    return res.json({ data: { totalTransactions, totalEscrow, completed, disputed } });
  });

  router.post('/contracts/:id/sign', (req, res) => {
    const { id } = req.params;
    const { role } = req.body as { role: 'buyer' | 'seller' };
    const txn = transactions.find((item) => item.contract.id === id);
    if (!txn) {
      return res.status(404).json({ error: 'Contract not found' });
    }
    if (txn.status === 'completed' || txn.status === 'cancelled') {
      return res.status(400).json({ error: 'Cannot sign a finalized contract' });
    }
    if (role === 'buyer') txn.contract.signedByBuyer = true;
    if (role === 'seller') txn.contract.signedBySeller = true;
    writeTransactions(transactions);
    return res.json({ data: txn });
  });

  return router;
};

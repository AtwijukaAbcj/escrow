import fs from 'fs';
import path from 'path';

const storageRoot = path.resolve(__dirname, '..', '..', 'data');

if (!fs.existsSync(storageRoot)) {
  fs.mkdirSync(storageRoot, { recursive: true });
}

const readJson = <T>(filename: string, defaultValue: T): T => {
  const filePath = path.join(storageRoot, filename);
  if (!fs.existsSync(filePath)) {
    fs.writeFileSync(filePath, JSON.stringify(defaultValue, null, 2));
    return defaultValue;
  }
  const raw = fs.readFileSync(filePath, 'utf8');
  return JSON.parse(raw) as T;
};

const writeJson = <T>(filename: string, data: T): void => {
  const filePath = path.join(storageRoot, filename);
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
};

export const readUsers = () => readJson('users.json', [] as any[]);
export const writeUsers = (data: any[]) => writeJson('users.json', data);
export const readRefreshTokens = () => readJson('refreshTokens.json', [] as any[]);
export const writeRefreshTokens = (data: any[]) => writeJson('refreshTokens.json', data);

export const readParties = () => readJson('parties.json', [] as any[]);
export const writeParties = (data: any[]) => writeJson('parties.json', data);

export const readTransactions = () => readJson('transactions.json', [] as any[]);
export const writeTransactions = (data: any[]) => writeJson('transactions.json', data);

export const uploadsDir = () => {
  const dir = path.join(storageRoot, 'uploads');
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  return dir;
};

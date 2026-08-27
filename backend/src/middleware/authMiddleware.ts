import { Request, Response, NextFunction } from 'express';
import { verifyAccessToken } from '../services/tokenService';

export interface AuthRequest extends Request {
  user?: ReturnType<typeof verifyAccessToken>;
}

export const authenticateJWT = (req: AuthRequest, res: Response, next: NextFunction) => {
  const authorization = req.headers.authorization;
  if (!authorization || !authorization.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Authentication required' });
  }

  try {
    const token = authorization.replace('Bearer ', '');
    req.user = verifyAccessToken(token);
    next();
  } catch (error) {
    return res.status(401).json({ error: 'Invalid or expired token' });
  }
};

export const authorizeRoles = (...allowedRoles: string[]) => {
  return (req: AuthRequest, res: Response, next: NextFunction) => {
    if (!req.user) {
      return res.status(401).json({ error: 'Authentication required' });
    }
    const hasRole = req.user.roles.some((role) => allowedRoles.includes(role));
    if (!hasRole) {
      return res.status(403).json({ error: 'Forbidden' });
    }
    next();
  };
};

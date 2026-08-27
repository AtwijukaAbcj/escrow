import express from 'express';
import path from 'path';
import cors from 'cors';
import dotenv from 'dotenv';
import authRoutes from './routes/auth';
import { createRouter } from './routes';
import { config } from './config';

dotenv.config();

const app = express();
const port = config.port;

// During local development allow CORS from the frontend origins (and relax if needed)
if (process.env.NODE_ENV === 'production') {
  app.use(cors({ origin: (origin, callback) => {
    if (!origin || config.frontendOrigins.includes(origin)) {
      callback(null, true);
    } else {
      callback(new Error('Not allowed by CORS'));
    }
  } }));
} else {
  app.use(cors());
}
app.use(express.json());

// Serve uploaded files
app.use('/uploads', express.static(path.join(__dirname, '..', 'data', 'uploads')));

app.use('/api/v1/auth', authRoutes);
app.use('/api/v1', createRouter());

app.get('/', (_req, res) => {
  res.json({ message: 'TrustPay Africa API is running' });
});

app.listen(port, () => {
  console.log(`Backend running on http://localhost:${port}`);
});

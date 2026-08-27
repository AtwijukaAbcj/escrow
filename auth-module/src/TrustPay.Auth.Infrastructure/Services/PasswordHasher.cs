using System;
using System.Security.Cryptography;
using TrustPay.Auth.Common.Interfaces;

namespace TrustPay.Auth.Infrastructure.Services
{
    public class PasswordHasher : IPasswordHasher
    {
        private const int IterationCount = 150_000;
        private const int SaltSize = 16;
        private const int KeySize = 32;

        public string Hash(string password)
        {
            if (string.IsNullOrWhiteSpace(password))
            {
                throw new ArgumentException("Password is required.", nameof(password));
            }

            var salt = RandomNumberGenerator.GetBytes(SaltSize);
            using var algorithm = new Rfc2898DeriveBytes(password, salt, IterationCount, HashAlgorithmName.SHA256);
            var hash = algorithm.GetBytes(KeySize);
            return $"{IterationCount}.{Convert.ToBase64String(salt)}.{Convert.ToBase64String(hash)}";
        }

        public bool Verify(string password, string hash)
        {
            if (string.IsNullOrWhiteSpace(password))
            {
                return false;
            }

            var parts = hash.Split('.', 3);
            if (parts.Length != 3 || !int.TryParse(parts[0], out var iterations))
            {
                return false;
            }

            var salt = Convert.FromBase64String(parts[1]);
            var expectedHash = Convert.FromBase64String(parts[2]);
            using var algorithm = new Rfc2898DeriveBytes(password, salt, iterations, HashAlgorithmName.SHA256);
            var actualHash = algorithm.GetBytes(expectedHash.Length);
            return CryptographicOperations.FixedTimeEquals(actualHash, expectedHash);
        }
    }
}

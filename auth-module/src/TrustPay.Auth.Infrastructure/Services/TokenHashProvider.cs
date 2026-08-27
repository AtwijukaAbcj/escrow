using System;
using System.Security.Cryptography;
using TrustPay.Auth.Common.Interfaces;

namespace TrustPay.Auth.Infrastructure.Services
{
    public class TokenHashProvider : ITokenHashProvider
    {
        public string Hash(string token)
        {
            if (string.IsNullOrWhiteSpace(token))
            {
                throw new ArgumentException("Token is required.", nameof(token));
            }

            using var sha256 = SHA256.Create();
            var bytes = sha256.ComputeHash(System.Text.Encoding.UTF8.GetBytes(token));
            return Convert.ToBase64String(bytes);
        }

        public bool Verify(string token, string hash)
        {
            if (string.IsNullOrWhiteSpace(token) || string.IsNullOrWhiteSpace(hash))
            {
                return false;
            }

            var computed = Hash(token);
            return CryptographicOperations.FixedTimeEquals(
                System.Text.Encoding.UTF8.GetBytes(computed),
                System.Text.Encoding.UTF8.GetBytes(hash));
        }
    }
}

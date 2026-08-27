using System;
using TrustPay.Auth.Domain.ValueObjects;

namespace TrustPay.Auth.Domain.Entities
{
    public sealed class RefreshToken
    {
        public RefreshTokenId Id { get; private set; }
        public UserId UserId { get; private set; }
        public string TokenHash { get; private set; }
        public DateTime ExpiresAtUtc { get; private set; }
        public bool IsRevoked { get; private set; }

        private RefreshToken()
        {
            Id = default!;
            UserId = default!;
            TokenHash = string.Empty;
            ExpiresAtUtc = default;
        }

        private RefreshToken(RefreshTokenId id, UserId userId, string tokenHash, DateTime expiresAtUtc)
        {
            Id = id;
            UserId = userId;
            TokenHash = tokenHash;
            ExpiresAtUtc = expiresAtUtc;
            IsRevoked = false;
        }

        public static RefreshToken Create(UserId userId, string tokenHash, DateTime expiresAtUtc)
        {
            if (string.IsNullOrWhiteSpace(tokenHash))
            {
                throw new ArgumentException("Token hash is required.", nameof(tokenHash));
            }

            return new RefreshToken(RefreshTokenId.New(), userId, tokenHash, expiresAtUtc);
        }

        public void Revoke()
        {
            IsRevoked = true;
        }
    }
}

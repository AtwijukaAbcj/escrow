using System;

namespace TrustPay.Auth.Domain.ValueObjects
{
    public sealed class RefreshTokenId
    {
        public Guid Value { get; }

        private RefreshTokenId(Guid value)
        {
            Value = value;
        }

        public static RefreshTokenId New() => new RefreshTokenId(Guid.NewGuid());

        public static RefreshTokenId FromGuid(Guid id)
        {
            if (id == Guid.Empty)
            {
                throw new ArgumentException("RefreshTokenId cannot be empty.", nameof(id));
            }
            return new RefreshTokenId(id);
        }

        public override string ToString() => Value.ToString();

        public override bool Equals(object? obj) => obj is RefreshTokenId other && Value.Equals(other.Value);

        public override int GetHashCode() => Value.GetHashCode();
    }
}

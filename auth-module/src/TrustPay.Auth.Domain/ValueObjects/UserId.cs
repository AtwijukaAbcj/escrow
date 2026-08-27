using System;

namespace TrustPay.Auth.Domain.ValueObjects
{
    public sealed class UserId
    {
        public Guid Value { get; }

        private UserId(Guid value)
        {
            Value = value;
        }

        public static UserId New() => new UserId(Guid.NewGuid());

        public static UserId FromGuid(Guid id)
        {
            if (id == Guid.Empty)
            {
                throw new ArgumentException("UserId cannot be empty.", nameof(id));
            }
            return new UserId(id);
        }

        public override string ToString() => Value.ToString();

        public override bool Equals(object? obj) => obj is UserId other && Value.Equals(other.Value);

        public override int GetHashCode() => Value.GetHashCode();
    }
}

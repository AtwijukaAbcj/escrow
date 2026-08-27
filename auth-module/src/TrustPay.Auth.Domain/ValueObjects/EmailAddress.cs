using System;

namespace TrustPay.Auth.Domain.ValueObjects
{
    public sealed class EmailAddress
    {
        public string Value { get; }

        private EmailAddress(string value)
        {
            Value = value;
        }

        public static EmailAddress Create(string email)
        {
            if (string.IsNullOrWhiteSpace(email))
            {
                throw new ArgumentException("Email address is required.", nameof(email));
            }

            email = email.Trim();
            if (!email.Contains("@") || email.Length < 5)
            {
                throw new ArgumentException("Email address is invalid.", nameof(email));
            }

            return new EmailAddress(email);
        }

        public override string ToString() => Value;

        public override bool Equals(object? obj) => obj is EmailAddress other && string.Equals(Value, other.Value, StringComparison.OrdinalIgnoreCase);

        public override int GetHashCode() => StringComparer.OrdinalIgnoreCase.GetHashCode(Value);
    }
}

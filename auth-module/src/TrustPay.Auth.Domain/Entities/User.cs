using System;
using TrustPay.Auth.Domain.ValueObjects;

namespace TrustPay.Auth.Domain.Entities
{
    public sealed class User
    {
        public UserId Id { get; private set; }
        public EmailAddress Email { get; private set; }
        public string PasswordHash { get; private set; }
        public DateTime CreatedAtUtc { get; private set; }

        private User()
        {
            Id = default!;
            Email = default!;
            PasswordHash = string.Empty;
            CreatedAtUtc = default;
        }

        private User(UserId id, EmailAddress email, string passwordHash, DateTime createdAtUtc)
        {
            Id = id;
            Email = email;
            PasswordHash = passwordHash;
            CreatedAtUtc = createdAtUtc;
        }

        public static User Create(EmailAddress email, string passwordHash, DateTime createdAtUtc)
        {
            if (string.IsNullOrWhiteSpace(passwordHash))
            {
                throw new ArgumentException("Password hash is required.", nameof(passwordHash));
            }

            return new User(UserId.New(), email, passwordHash, createdAtUtc);
        }

        public bool VerifyPassword(string password, Func<string, bool> verify)
        {
            return verify(password);
        }
    }
}

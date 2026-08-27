using Microsoft.EntityFrameworkCore;
using TrustPay.Auth.Domain.Entities;
using TrustPay.Auth.Domain.ValueObjects;

namespace TrustPay.Auth.Infrastructure.Persistence
{
    public class AuthDbContext : DbContext
    {
        public AuthDbContext(DbContextOptions<AuthDbContext> options)
            : base(options)
        {
        }

        public DbSet<User> Users => Set<User>();
        public DbSet<RefreshToken> RefreshTokens => Set<RefreshToken>();

        protected override void OnModelCreating(ModelBuilder modelBuilder)
        {
            modelBuilder.Entity<User>(entity =>
            {
                entity.HasKey(u => u.Id);
                entity.Property(u => u.Id)
                    .HasConversion(v => v.Value, v => UserId.FromGuid(v));
                entity.OwnsOne(u => u.Email, email =>
                {
                    email.Property(e => e.Value).HasColumnName("Email").IsRequired();
                });
                entity.Property(u => u.PasswordHash).IsRequired();
                entity.Property(u => u.CreatedAtUtc).IsRequired();
            });

            modelBuilder.Entity<RefreshToken>(entity =>
            {
                entity.HasKey(rt => rt.Id);
                entity.Property(rt => rt.Id)
                    .HasConversion(v => v.Value, v => RefreshTokenId.FromGuid(v));
                entity.Property(rt => rt.UserId)
                    .HasConversion(v => v.Value, v => UserId.FromGuid(v));
                entity.Property(rt => rt.TokenHash).IsRequired();
                entity.Property(rt => rt.ExpiresAtUtc).IsRequired();
                entity.Property(rt => rt.IsRevoked).IsRequired();
            });
        }
    }
}

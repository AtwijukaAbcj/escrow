using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using TrustPay.Auth.Application.Interfaces;
using TrustPay.Auth.Domain.Entities;
using TrustPay.Auth.Infrastructure.Persistence;

namespace TrustPay.Auth.Infrastructure.Repositories
{
    public class RefreshTokenRepository : IRefreshTokenRepository
    {
        private readonly AuthDbContext _dbContext;

        public RefreshTokenRepository(AuthDbContext dbContext)
        {
            _dbContext = dbContext;
        }

        public Task AddAsync(RefreshToken refreshToken)
        {
            _dbContext.Set<RefreshToken>().Add(refreshToken);
            return _dbContext.SaveChangesAsync();
        }

        public Task<RefreshToken?> FindByTokenHashAsync(string tokenHash)
        {
            return _dbContext.Set<RefreshToken>().FirstOrDefaultAsync(rt => rt.TokenHash == tokenHash && !rt.IsRevoked);
        }

        public Task SaveChangesAsync()
        {
            return _dbContext.SaveChangesAsync();
        }
    }
}

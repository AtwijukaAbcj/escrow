using System.Threading.Tasks;
using TrustPay.Auth.Domain.Entities;
using TrustPay.Auth.Domain.ValueObjects;

namespace TrustPay.Auth.Application.Interfaces
{
    public interface IRefreshTokenRepository
    {
        Task AddAsync(RefreshToken refreshToken);
        Task<RefreshToken?> FindByTokenHashAsync(string tokenHash);
        Task SaveChangesAsync();
    }
}

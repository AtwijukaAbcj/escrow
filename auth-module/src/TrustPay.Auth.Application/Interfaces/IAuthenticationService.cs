using System.Threading.Tasks;
using TrustPay.Auth.Application.Models;
using TrustPay.Auth.Domain.Entities;

namespace TrustPay.Auth.Application.Interfaces
{
    public interface IAuthenticationService
    {
        Task<User> RegisterAsync(string email, string password);
        Task<AuthenticationResult> AuthenticateAsync(string email, string password);
        Task<AuthenticationResult> RefreshTokenAsync(string refreshToken);
        Task RevokeRefreshTokenAsync(string refreshToken);
    }
}
